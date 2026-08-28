"""P4.4 / P4.6 / P4.7 -- the investigation loop and the re-planning path.

Synchronous by decision (§A8): the whole loop runs and returns the finished
tree. The frontend reveals nodes client-side at 400 ms intervals, which looks
identical to live growth without a polling hook or concurrent writes.

The loop is the one in Architecture §6:

    while probes remain and not converged:
        SELECT   the probe with the highest impact x uncertainty
        PROBE    slice the log
        HYPOTHESISE   M4 over the slice
        DRILL or STOP
    PROPOSE  every catalogue action for the concluded stage -> M5 -> M6

Nothing in here knows which bottleneck it is looking at. P4.8 runs it twice,
before and after the fix, with no code change between.
"""

import json
import time

from backend.agent import policy, probes as probe_mod
from backend.jsonsafe import clean
from backend.agent.state import Evidence, Node, ProcessState, StageHealth
from backend.models import m5_impact as m5, m6_roi as m6
from backend.sim import config as C, engine, persist


def _stage_health(ctx):
    out = {}
    anomalies = ctx.anomalies
    for _, row in ctx.ranked.iterrows():
        stage = row["stage"]
        a = anomalies.get(stage, {})
        out[stage] = StageHealth(
            stage=stage,
            mean_wait=float(row["mean_wait"]),
            mean_service=float(row["mean_service"]),
            mean_duration=float(row["mean_duration"]),
            utilisation=float(row["utilisation"]),
            wait_to_service_ratio=float(row["wait_to_service_ratio"]),
            impact_share=float(row["score"] / ctx.ranked["score"].sum()),
            contribution_pct=float(row["contribution_pct"]),
            rank=int(row["rank"]),
            anomaly_share=float(a.get("share", 0.0)),
            anomalous=stage in anomalies,
        )
    return out


def investigate(result, registry, run_id, inv_id=None, budget=C.BUDGET_CAP,
                max_probes=policy.MAX_PROBES, conn=None, persist_result=True,
                propose=True, seeds=m5.SEEDS):
    """Run one investigation end to end and return the finished tree."""
    inv_id = inv_id or ("inv-" + run_id)
    started = time.time()

    ctx = probe_mod.ProbeContext(result, registry)
    state = ProcessState(
        run_id=run_id,
        stage_health=_stage_health(ctx),
        budget_remaining=float(budget),
        probes_remaining=int(max_probes),
    )

    trigger = sorted(ctx.anomalies.items(), key=lambda kv: -kv[1]["share"])
    seq = 0
    stop_reason = "probe budget exhausted"

    while state.probes_remaining > 0:
        done, why = policy.converged(state, ctx)
        if done:
            stop_reason = why
            break

        candidate = policy.select(state, ctx)
        if candidate is None:
            stop_reason = "no candidate probes remain"
            break

        if candidate["probe_type"] == "stage":
            data, summary, hypotheses = probe_mod.stage_probe(ctx, candidate["stage"])
            state.probed_stages.add(candidate["stage"])
            parent_id, depth = None, 0
            # The probe answers the question, so uncertainty collapses to what
            # M4 actually reports rather than the prior of 1.0 used to select it.
            uncertainty = policy.normalised_entropy(hypotheses)
            finding = ("M4 attributes this to %s (p=%.2f)%s."
                       % (hypotheses[0]["cause"], hypotheses[0]["p"],
                          "" if hypotheses[0]["p"] >= policy.CONFIDENCE_THRESHOLD
                          else ", below the 0.65 bar, so the cause is not settled"))
        else:
            data, summary, information = probe_mod.factor_probe(
                ctx, candidate["stage"], candidate["dimension"])
            state.probed_factors.add((candidate["stage"], candidate["dimension"]))
            parent_id = state.stage_node_ids.get(candidate["stage"])
            depth = 1
            uncertainty = information
            hypotheses = state.hypotheses_by_stage.get(candidate["stage"], [])
            finding = ("This narrows where the %s at %s bites."
                       % ((hypotheses[0]["cause"] if hypotheses else "problem"),
                          candidate["stage"]))

        node_id = "%s-n%d" % (inv_id, seq)
        node = Node(
            node_id=node_id,
            parent_node_id=parent_id,
            depth=depth,
            seq=seq,
            probe_type=candidate["probe_type"],
            target=candidate["target"],
            selection_score=candidate["score"],
            impact=candidate["impact"],
            uncertainty=uncertainty,
            evidence=data,
            hypotheses=hypotheses,
            reasoning=" ".join([policy.reason_for_selection(candidate, state),
                                summary, finding]),
        )
        if candidate["probe_type"] == "stage":
            state.stage_node_ids[candidate["stage"]] = node_id

        state.record(node,
                     Evidence(candidate["probe_type"], candidate["target"],
                              candidate["stage"], data, summary),
                     hypotheses if candidate["probe_type"] == "stage" else None)
        seq += 1
    else:
        stop_reason = "probe budget exhausted"

    if state.probes_remaining == 0:
        done, why = policy.converged(state, ctx)
        if done:
            stop_reason = why

    concluded_stage, lead = policy.confident_stage(state)
    conclusion = {
        "inv_id": inv_id,
        "run_id": run_id,
        "started_at": started,
        "status": "converged" if concluded_stage else "inconclusive",
        "concluded_stage": concluded_stage,
        "concluded_cause": lead["cause"] if lead else None,
        "confidence": float(lead["p"]) if lead else 0.0,
        "stop_reason": stop_reason,
        "probes_used": seq,
        "trigger": [{"stage": s, **v} for s, v in trigger],
    }

    candidates = []
    if propose and concluded_stage:
        candidates = propose_interventions(result, concluded_stage, state, seeds=seeds)
        conclusion["explanation"] = _explanation(state, concluded_stage, lead, candidates)
    else:
        conclusion["explanation"] = (
            "No stage cleared the %.2f confidence bar." % policy.CONFIDENCE_THRESHOLD)

    if persist_result:
        _persist(conclusion, state, candidates, conn)

    return {
        "conclusion": conclusion,
        "state": state,
        "nodes": state.nodes,
        "candidates": candidates,
        "stage_health": {k: v.as_dict() for k, v in state.stage_health.items()},
        "ranked": ctx.ranked,
    }


def propose_interventions(result, stage, state, seeds=m5.SEEDS):
    """P4.6 -- every catalogue action for the concluded stage, simulated by M5
    and priced by M6, then selected greedily under the remaining budget."""
    config = result["config"]
    baselines = m5.baseline_replicates(config, seeds)
    impacts = m5.evaluate_catalogue(config, stage=stage, seeds=seeds, baselines=baselines)
    scored = m6.score_all(impacts)
    chosen, spend = m6.select_greedy(scored, budget=state.budget_remaining)
    marked = m6.mark_selection(scored, chosen)
    state.budget_remaining -= spend
    return marked


def _explanation(state, stage, lead, candidates):
    factors = [e for e in state.evidence if e.probe_type == "factor" and e.stage == stage]
    where = "; ".join(e.summary.split(": ", 1)[1] for e in factors[:2])
    picked = [c for c in candidates if c.get("selected")]
    action = (", ".join("%s (Rs %s, ROI %.2f)"
                        % (c["action"], format(int(c["cost_30d"]), ","), c["roi"])
                        for c in picked) if picked else "no action clears its own cost")
    return ("%s -- %s at p=%.2f. %s Recommended: %s."
            % (stage, lead["cause"], lead["p"], where, action))


def _persist(conclusion, state, candidates, conn=None):
    persist.write_investigation(conclusion, state.nodes, conn=conn)
    if candidates:
        persist.write_interventions(conclusion["inv_id"], candidates, conn=conn)


# --------------------------------------------------------------- re-planning --

def apply_intervention(result, registry, actions, run_id, parent_run_id,
                       label=None, refit=True, conn=None):
    """P4.7 -- apply actions, create the child run, refresh the models.

    The child world is a full re-simulation on the same master seed, so it
    differs from its parent only by the intervention. M1 is refitted on the new
    log; M3 is NOT refitted -- its reference set is the healthy baseline and
    re-fitting it on the world being judged would destroy the comparison. M4 is
    not refitted either: its corpus is independent of any demo run by design
    (§A5). "Refresh" therefore means refit M1 and re-score M2/M3/M4.
    """
    actions = list(actions)
    child_config = C.apply_actions(result["config"], actions)
    child = engine.simulate(child_config)

    kpis = persist.write_run(
        child, run_id, label=label or ("After " + ", ".join(actions)),
        parent_run_id=parent_run_id, conn=conn)

    if refit:
        registry.m1.fit(child["events"], child["cases"])

    return child, kpis


def replan(result, registry, actions, run_id, parent_run_id, budget=C.BUDGET_CAP,
           spent=0.0, refit=True, conn=None, seeds=m5.SEEDS):
    """Apply, then investigate the resulting world through the SAME code path."""
    child, kpis = apply_intervention(result, registry, actions, run_id,
                                     parent_run_id, refit=refit, conn=conn)
    outcome = investigate(child, registry, run_id, budget=budget - spent,
                          conn=conn, seeds=seeds)
    return child, kpis, outcome


def to_json(outcome):
    """Shape the investigation for the API and the dashboard."""
    return clean({
        **outcome["conclusion"],
        "stage_health": outcome["stage_health"],
        "nodes": [
            {
                "node_id": n.node_id, "parent_node_id": n.parent_node_id,
                "depth": n.depth, "seq": n.seq, "probe_type": n.probe_type,
                "target": n.target, "selection_score": n.selection_score,
                "impact": n.impact, "uncertainty": n.uncertainty,
                "evidence": n.evidence, "hypotheses": n.hypotheses,
                "reasoning": n.reasoning,
            }
            for n in outcome["nodes"]
        ],
        "interventions": [
            {k: v for k, v in c.items() if k != "per_seed_delta"}
            for c in outcome["candidates"]
        ],
    })
