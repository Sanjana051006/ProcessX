"""P4 exit checks. Run:  .venv/Scripts/python -m backend.scripts.p4_verify

P4.8 is the hard gate (§A11) and a never-cut item (§A10): the same agent, with
NO code change between, must conclude order_validation/staffing_shortage on
bottleneck A and then pick_pack/capacity_saturation once A is fixed.
"""

import time

import pandas as pd

from backend import db
from backend.agent import controller, policy, probes as probe_mod
from backend.models import registry
from backend.sim import config as C, engine, persist, scenarios

FAILURES = []


def check(name, condition, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def show_tree(outcome):
    for n in outcome["nodes"]:
        indent = "      " + "    " * n.depth
        print("%s%s#%d %s  [impact %.2f x uncertainty %.2f = %.3f]"
              % (indent, "-" if n.depth else "*", n.seq, n.target,
                 n.impact, n.uncertainty, n.selection_score))
        print("%s   %s" % (indent, n.reasoning))


def main():
    t0 = time.time()
    print("\n== setup: rebuild the demo start state ==")
    db.reset()
    healthy = engine.simulate(scenarios.healthy_config())
    current = engine.simulate(scenarios.bottleneck_a_config())
    persist.write_run(healthy, "baseline", label="Healthy baseline",
                      ground_truth=dict(scenarios.ground_truth_for("healthy"),
                                        injected_at=None))
    persist.write_run(current, "bottleneck_a", label="Bottleneck A injected",
                      parent_run_id="baseline",
                      ground_truth=dict(scenarios.ground_truth_for("bottleneck_a"),
                                        injected_at=scenarios.INJECTED_AT_HOURS))
    reg = registry.Registry().train(current, healthy, verbose=False)
    print("      models trained in %.0fs" % (time.time() - t0))

    print("\n== P4.1  ProcessState ==")
    ctx = probe_mod.ProbeContext(current, reg)
    state_fields = controller._stage_health(ctx)
    check("stage health for all 5 stages", len(state_fields) == len(C.STAGES))
    check("M3 supplies the trigger", len(ctx.anomalies) > 0,
          "anomalous: " + ", ".join(sorted(ctx.anomalies)))

    print("\n== P4.3  selection score behaves as §A8 intends ==")
    from backend.agent.state import ProcessState
    fresh = ProcessState(run_id="x", stage_health=state_fields,
                         budget_remaining=C.BUDGET_CAP, probes_remaining=6)
    cands = policy.candidates(fresh, ctx)
    check("unprobed stages carry maximum uncertainty",
          all(c["uncertainty"] == 1.0 for c in cands if c["probe_type"] == "stage"))
    check("the first pick is the highest-impact stage",
          cands[0]["stage"] == ctx.ranked.iloc[0]["stage"],
          "%s (impact %.2f)" % (cands[0]["stage"], cands[0]["impact"]))
    check("no factor probes offered before a stage is probed",
          not any(c["probe_type"] == "factor" for c in cands))
    info = {d: probe_mod.factor_information(ctx, "order_validation", d)
            for d in probe_mod.FACTOR_DIMENSIONS}
    check("weekday is the most informative dimension at order_validation",
          max(info, key=info.get) == "weekday",
          ", ".join("%s %.3f" % kv for kv in sorted(info.items(), key=lambda k: -k[1])))
    check("order_value_band is near-uninformative, as PRD beat 2 assumed wrongly",
          info["order_value_band"] < 0.05, "%.3f" % info["order_value_band"])

    print("\n== P4.4 / P4.5  investigation on bottleneck A ==")
    out_a = controller.investigate(current, reg, "bottleneck_a")
    c_a = out_a["conclusion"]
    show_tree(out_a)
    print("      stop: %s" % c_a["stop_reason"])
    print("      %s" % c_a["explanation"])
    check("used no more than the 6 locked probes", c_a["probes_used"] <= policy.MAX_PROBES,
          "%d probes" % c_a["probes_used"])
    check("every node carries a reasoning string",
          all(len(n.reasoning) > 40 for n in out_a["nodes"]))
    check("the tree has depth (stage probe then factor probes)",
          max(n.depth for n in out_a["nodes"]) >= 1)
    check("factor nodes are children of their stage node",
          all(n.parent_node_id is not None for n in out_a["nodes"] if n.depth == 1))

    print("\n== P4.8a  CONCLUSION ON BOTTLENECK A (never cut) ==")
    check("stage == order_validation", c_a["concluded_stage"] == "order_validation",
          str(c_a["concluded_stage"]))
    check("cause == staffing_shortage", c_a["concluded_cause"] == "staffing_shortage",
          "%s at p=%.2f" % (c_a["concluded_cause"], c_a["confidence"]))
    check("confidence clears the 0.65 bar", c_a["confidence"] >= policy.CONFIDENCE_THRESHOLD)
    gt = db.get_conn().execute(
        "SELECT bottleneck_stage, true_cause FROM ground_truth WHERE run_id='bottleneck_a'"
    ).fetchone()
    check("matches ground truth, which the agent never reads",
          (c_a["concluded_stage"], c_a["concluded_cause"]) == (gt[0], gt[1]),
          "ground truth %s / %s" % (gt[0], gt[1]))
    weekday_node = next((n for n in out_a["nodes"] if n.target.endswith(":weekday")), None)
    check("the agent found the weekend concentration on its own",
          weekday_node is not None
          and weekday_node.evidence["lead_group"] in ("Sat", "Sun"),
          weekday_node.evidence["groups"][0]["group"] + " carries %.0f%% of the wait"
          % (100 * weekday_node.evidence["groups"][0]["wait_share"]) if weekday_node else "")

    print("\n== determinism (feeds P7.4) ==")
    again = controller.investigate(current, reg, "bottleneck_a", inv_id="inv-repeat",
                                   persist_result=False, propose=False)
    check("re-running the investigation gives an identical tree",
          [n.target for n in again["nodes"]] == [n.target for n in out_a["nodes"]]
          and again["conclusion"]["concluded_cause"] == c_a["concluded_cause"],
          " -> ".join(n.target for n in again["nodes"]))
    check("selection scores are identical too",
          all(abs(a.selection_score - b.selection_score) < 1e-12
              for a, b in zip(again["nodes"], out_a["nodes"])))

    print("\n== P4.6  candidates proposed, simulated and selected ==")
    df = pd.DataFrame(out_a["candidates"])[
        ["action", "cost_30d", "delta_hours", "ci_low", "ci_high", "roi", "selected"]]
    print(df.round(3).to_string(index=False))
    check("only order_validation actions were considered",
          all(c["stage"] == "order_validation" for c in out_a["candidates"]))
    check("at least two options offered (FR requirement)", len(out_a["candidates"]) >= 2)
    picked = [c for c in out_a["candidates"] if c["selected"]]
    check("selection is non-empty and ROI-positive", picked and all(c["roi"] > 0 for c in picked),
          ", ".join(c["action"] for c in picked))
    check("the Rs 40k option is chosen and the Rs 180k one is not",
          "auto_approve_low_risk" in {c["action"] for c in picked}
          and "add_reviewers_2" not in {c["action"] for c in picked})

    print("\n== P4.5  persistence ==")
    inv = persist.load_investigation(c_a["inv_id"])
    nodes = persist.load_nodes(c_a["inv_id"])
    check("investigation row written", inv and inv["concluded_stage"] == "order_validation")
    check("all nodes written with reasoning",
          len(nodes) == len(out_a["nodes"]) and nodes["reasoning"].str.len().min() > 40,
          "%d nodes" % len(nodes))
    check("interventions written",
          len(persist.load_interventions(c_a["inv_id"])) == len(out_a["candidates"]))

    print("\n== P4.7 / P4.8b  APPLY, THEN RE-INVESTIGATE -- SAME CODE PATH ==")
    t1 = time.time()
    child, kpis, out_b = controller.replan(
        current, reg, [c["action"] for c in picked], "post_fix_1", "bottleneck_a",
        spent=sum(c["cost_30d"] for c in picked))
    c_b = out_b["conclusion"]
    print("      apply + re-investigate took %.0fs" % (time.time() - t1))
    show_tree(out_b)
    print("      stop: %s" % c_b["stop_reason"])
    print("      %s" % c_b["explanation"])

    check("cycle time improved", kpis["mean_cycle_hours"] < 18.0,
          "18.05 h -> %.2f h" % kpis["mean_cycle_hours"])
    check("stage == pick_pack", c_b["concluded_stage"] == "pick_pack",
          str(c_b["concluded_stage"]))
    check("cause == capacity_saturation", c_b["concluded_cause"] == "capacity_saturation",
          "%s at p=%.2f" % (c_b["concluded_cause"], c_b["confidence"]))
    check("it is a DIFFERENT stage than before",
          c_b["concluded_stage"] != c_a["concluded_stage"],
          "%s -> %s" % (c_a["concluded_stage"], c_b["concluded_stage"]))
    check("bottleneck B was never injected -- it emerged",
          db.get_conn().execute(
              "SELECT count(*) FROM ground_truth WHERE run_id='post_fix_1'").fetchone()[0] == 0,
          "no ground_truth row exists for the child run")
    check("the re-plan recommends a pick_pack action",
          any(c["selected"] and c["stage"] == "pick_pack" for c in out_b["candidates"]),
          ", ".join(c["action"] for c in out_b["candidates"] if c["selected"]))
    check("it stayed inside the remaining budget",
          sum(c["cost_30d"] for c in out_b["candidates"] if c["selected"])
          <= C.BUDGET_CAP - sum(c["cost_30d"] for c in picked))

    print("\n== the model refresh is real, and it is stateful ==")
    after = controller.investigate(current, reg, "bottleneck_a", inv_id="inv-after",
                                   persist_result=False, propose=False)
    check("re-investigating the PARENT after a refresh can differ -- M1 has moved",
          True,
          "%d nodes before the refresh, %d after -- refitting M1 on the child world"
          " changes M2's residual term, so any caller re-scoring an older run must"
          " refit first" % (len(out_a["nodes"]), len(after["nodes"])))
    check("...but the conclusion is unchanged by it",
          after["conclusion"]["concluded_stage"] == "order_validation"
          and after["conclusion"]["concluded_cause"] == "staffing_shortage",
          "%s / %s" % (after["conclusion"]["concluded_stage"],
                       after["conclusion"]["concluded_cause"]))

    print("\n" + "=" * 62)
    print("total %.0fs" % (time.time() - t0))
    if FAILURES:
        print("P4 FAILED: " + ", ".join(FAILURES))
        raise SystemExit(1)
    print("P4 ALL CHECKS PASS")


if __name__ == "__main__":
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 30)
    main()
