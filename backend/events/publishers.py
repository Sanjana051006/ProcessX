"""Domain publishers.

Every call site in the app publishes through a named function here rather than
building an envelope inline. Two reasons: a payload shape stays in one place
where the subscribers can be checked against it, and no publish call can ever
raise into the code path it is observing — every function in this module
swallows its own failures.

Nothing here is allowed to be expensive. A publisher summarises data that the
caller already has; it never computes anything, never queries, never simulates.
"""

from backend.events.bus import publish

_CAUSE_WORDS = {
    "capacity_saturation": "capacity saturation",
    "staffing_shortage": "staffing shortage",
    "normal": "nothing wrong",
}


def _pretty(name):
    return str(name).replace("_", " ").capitalize()


def _hours(v):
    try:
        return "%.2f h" % float(v)
    except (TypeError, ValueError):
        return "—"


def _money(v):
    try:
        return "Rs %s" % format(int(round(float(v))), ",")
    except (TypeError, ValueError):
        return "—"


# ------------------------------------------------------------ simulation ----

def run_started(run_id, scenario, label):
    return publish("simulation.run.started", run_id=run_id,
                   summary="Simulating %s" % (label or scenario),
                   payload={"scenario": scenario, "label": label})


def run_completed(run_id, scenario, label, kpis, parent_run_id=None):
    return publish(
        "simulation.run.completed", run_id=run_id,
        summary="%s — %s mean cycle, %s per case" % (
            label or run_id, _hours(kpis.get("mean_cycle_hours")),
            _money(kpis.get("cost_per_case"))),
        payload={
            "scenario": scenario, "label": label, "parent_run_id": parent_run_id,
            "n_cases": kpis.get("n_cases"),
            "mean_cycle_hours": kpis.get("mean_cycle_hours"),
            "p90_cycle_hours": kpis.get("p90_cycle_hours"),
            "cost_per_case": kpis.get("cost_per_case"),
            "sla_breach_rate": kpis.get("sla_breach_rate"),
            "throughput_per_day": kpis.get("throughput_per_day"),
        })


def pipeline_started(run_id, case_id):
    return publish("simulation.pipeline.started", run_id=run_id, case_id=case_id,
                   summary="Running the full chain on case #%s" % case_id,
                   payload={"case_id": case_id})


def pipeline_completed(run_id, case_id, inv_id, elapsed):
    return publish("simulation.pipeline.completed", run_id=run_id, case_id=case_id,
                   inv_id=inv_id,
                   summary="Nine panels ready in %.1f s" % elapsed,
                   payload={"elapsed_s": elapsed, "inv_id": inv_id, "n_steps": 9})


def case_sampled(run_id, journey):
    """The case the panel follows, plus enough of its shape to draw a row."""
    return publish(
        "simulation.case.sampled", run_id=run_id, case_id=journey.get("case_id"),
        summary="Case #%s — %s end to end (p%d)" % (
            journey.get("case_id"), _hours(journey.get("cycle_hours")),
            round(100 * (journey.get("cycle_percentile") or 0))),
        payload={
            "case_id": journey.get("case_id"),
            "cycle_hours": journey.get("cycle_hours"),
            "cycle_percentile": journey.get("cycle_percentile"),
            "n_stages": len(journey.get("steps") or []),
        })


def stage_walk(run_id, journey, limit=24):
    """One `stage.entered` / `stage.completed` pair per activity of the case.

    This is what makes the timeline a *journey* rather than a summary: the
    replay control on the simulation page steps through these, so the operator
    watches the case move rather than reading a table of where it went.
    """
    events = []
    for step in (journey.get("steps") or [])[:limit]:
        events.append(publish(
            "simulation.stage.entered", run_id=run_id,
            case_id=journey.get("case_id"),
            summary="%s — queued %s" % (step.get("label") or _pretty(step.get("stage")),
                                        _hours(step.get("queue_wait_hours"))),
            payload={
                "stage": step.get("stage"), "label": step.get("label"),
                "macro_stage": step.get("macro_stage"),
                "order": step.get("order"),
                "arrival_ts": step.get("arrival_ts"),
                "wait_hours": step.get("queue_wait_hours"),
                "queue_len": step.get("queue_len_at_arrival"),
            }))
        events.append(publish(
            "simulation.stage.completed", run_id=run_id,
            case_id=journey.get("case_id"),
            summary="%s — %s total, %s elapsed" % (
                step.get("label") or _pretty(step.get("stage")),
                _hours(step.get("duration_hours")), _hours(step.get("elapsed_hours"))),
            payload={
                "stage": step.get("stage"), "label": step.get("label"),
                "macro_stage": step.get("macro_stage"),
                "order": step.get("order"),
                "duration_hours": step.get("duration_hours"),
                "service_hours": step.get("service_hours"),
                "wait_hours": step.get("queue_wait_hours"),
                "elapsed_hours": step.get("elapsed_hours"),
                "predicted_hours": step.get("predicted_hours"),
                "residual_hours": step.get("residual_hours"),
            }))
    return events


# ---------------------------------------------------------------- models ----

def m1_predicted(run_id, case_id, step):
    worst = step.get("worst_residual_stage")
    preds = step.get("predictions") or []
    return publish(
        "model.m1.predicted", run_id=run_id, case_id=case_id,
        summary="M1 scored %d activities — largest gap at %s"
                % (len(preds), _pretty(worst) if worst else "none"),
        payload={"n_scored": len(preds), "worst_residual_stage": worst,
                 "headline": step.get("headline")})


def m2_ranked(run_id, step):
    ranking = step.get("ranking") or []
    top = ranking[0] if ranking else {}
    return publish(
        "model.m2.ranked", run_id=run_id,
        summary="M2 ranks %s #1 — %.1f%% of total delay"
                % (_pretty(top.get("stage")), top.get("contribution_pct") or 0.0),
        payload={
            "top_stage": step.get("top_stage"),
            "contribution_pct": top.get("contribution_pct"),
            "utilisation": top.get("utilisation"),
            "queue_wait_share": top.get("queue_wait_share"),
            "top_5": [{"rank": r.get("rank"), "stage": r.get("stage"),
                       "contribution_pct": r.get("contribution_pct")}
                      for r in ranking[:5]],
        })


def m3_anomaly(run_id, step):
    anomalies = step.get("anomalies") or []
    if not anomalies:
        return publish("model.m3.clear", run_id=run_id,
                       summary="M3 flags nothing — the world reads healthy",
                       payload={"n_flagged": 0})
    lead = anomalies[0]
    return publish(
        "model.m3.anomaly_detected", run_id=run_id, severity="warning",
        summary="M3 flags %s in %.0f%% of its windows"
                % (_pretty(lead.get("stage")), 100 * (lead.get("share") or 0)),
        payload={
            "n_flagged": len(anomalies),
            "stage": lead.get("stage"),
            "share": lead.get("share"),
            "n_anomalous_windows": lead.get("n_anomalous_windows"),
            "injected_at": step.get("injected_at"),
            "stages": [a.get("stage") for a in anomalies],
        })


def m4_classified(run_id, step, inv_id=None):
    hypotheses = step.get("hypotheses") or []
    lead = hypotheses[0] if hypotheses else {}
    return publish(
        "model.m4.cause_classified", run_id=run_id, inv_id=inv_id, severity="warning",
        summary="M4 attributes %s to %s (p=%.2f)"
                % (_pretty(step.get("stage")),
                   _CAUSE_WORDS.get(lead.get("cause"), lead.get("cause") or "—"),
                   lead.get("p") or 0.0),
        payload={"stage": step.get("stage"), "cause": lead.get("cause"),
                 "p": lead.get("p"), "hypotheses": hypotheses})


def m5_counterfactuals(run_id, step, inv_id=None):
    candidates = step.get("candidates") or []
    best = max(candidates, key=lambda c: c.get("delta_hours") or 0) if candidates else {}
    return publish(
        "model.m5.counterfactual_completed", run_id=run_id, inv_id=inv_id,
        summary="M5 re-simulated %d candidates — best is %s off mean cycle"
                % (len(candidates), _hours(best.get("delta_hours"))),
        payload={
            "n_candidates": len(candidates), "replicates": 3,
            "best_action": best.get("action"),
            "best_delta_hours": best.get("delta_hours"),
            "ci": [best.get("ci_low"), best.get("ci_high")],
            "candidates": [{"action": c.get("action"), "delta_hours": c.get("delta_hours"),
                            "cost": c.get("cost")} for c in candidates],
        })


def m6_selected(run_id, step, inv_id=None):
    picked = [c for c in (step.get("candidates") or []) if c.get("selected")]
    spend = step.get("spend") or 0.0
    benefit = step.get("benefit") or 0.0
    return publish(
        "model.m6.intervention_selected", run_id=run_id, inv_id=inv_id, severity="success",
        summary=("M6 buys %d action%s for %s, returning %s"
                 % (len(picked), "" if len(picked) == 1 else "s",
                    _money(spend), _money(benefit))
                 if picked else "M6 buys nothing — no action clears its own cost"),
        payload={
            "n_selected": len(picked), "spend": spend, "benefit_30d": benefit,
            "budget_cap": step.get("budget_cap"),
            "roi": (benefit - spend) / spend if spend else 0.0,
            "actions": [{"action": c.get("action"), "label": c.get("label"),
                         "stage": c.get("stage"), "cost": c.get("cost"),
                         "roi": c.get("roi")} for c in picked],
        })


# ----------------------------------------------------------------- agent ----

def investigation_started(run_id, inv_id, trigger, budget):
    lead = trigger[0] if trigger else {}
    return publish(
        "agent.investigation.started", run_id=run_id, inv_id=inv_id,
        summary=("Agent opens on %s" % _pretty(lead.get("stage"))
                 if lead else "Agent opens with no anomaly to chase"),
        payload={"inv_id": inv_id, "budget": budget,
                 "trigger": [t.get("stage") for t in trigger][:5]})


def probe_selected(run_id, inv_id, node):
    return publish(
        "agent.probe.selected", run_id=run_id, inv_id=inv_id,
        summary="Probe %d: %s %s (impact %.2f x uncertainty %.2f)"
                % (node.seq + 1, node.probe_type, _pretty(node.target),
                   node.impact or 0.0, node.uncertainty or 0.0),
        payload={
            "node_id": node.node_id, "seq": node.seq, "depth": node.depth,
            "probe_type": node.probe_type, "target": node.target,
            "impact": node.impact, "uncertainty": node.uncertainty,
            "selection_score": node.selection_score,
        })


def evidence_recorded(run_id, inv_id, node):
    lead = (node.hypotheses or [{}])[0]
    return publish(
        "agent.evidence.recorded", run_id=run_id, inv_id=inv_id,
        summary=(node.reasoning or "")[:220],
        payload={
            "node_id": node.node_id, "seq": node.seq, "target": node.target,
            "probe_type": node.probe_type,
            "cause": lead.get("cause"), "p": lead.get("p"),
            "hypotheses": node.hypotheses,
        })


def investigation_concluded(run_id, inv_id, conclusion):
    stage = conclusion.get("concluded_stage")
    return publish(
        "agent.investigation.concluded", run_id=run_id, inv_id=inv_id,
        severity="success" if stage else "warning",
        summary=("%s — %s at p=%.2f, after %d probes"
                 % (_pretty(stage),
                    _CAUSE_WORDS.get(conclusion.get("concluded_cause"),
                                     conclusion.get("concluded_cause") or "—"),
                    conclusion.get("confidence") or 0.0,
                    conclusion.get("probes_used") or 0)
                 if stage else "Inconclusive — nothing cleared the confidence bar"),
        payload={
            "inv_id": inv_id,
            "status": conclusion.get("status"),
            "concluded_stage": stage,
            "concluded_cause": conclusion.get("concluded_cause"),
            "confidence": conclusion.get("confidence"),
            "probes_used": conclusion.get("probes_used"),
            "stop_reason": conclusion.get("stop_reason"),
            "explanation": conclusion.get("explanation"),
        })


# ---------------------------------------------------------- interventions ----

def intervention_applied(parent_run_id, child_run_id, applied, total_cost):
    return publish(
        "intervention.applied", run_id=child_run_id, severity="success",
        summary="Applied %s for %s" % (
            ", ".join(a.get("label") or a.get("action") for a in applied),
            _money(total_cost)),
        payload={"parent_run_id": parent_run_id, "child_run_id": child_run_id,
                 "actions": applied, "total_cost": total_cost})


def intervention_measured(run_id, before, after, delta):
    return publish(
        "intervention.measured", run_id=run_id, severity="success",
        summary="Mean cycle %s → %s (%s off)" % (
            _hours(before.get("mean_cycle_hours")), _hours(after.get("mean_cycle_hours")),
            _hours(delta.get("mean_cycle_hours"))),
        payload={"before": before, "after": after, "delta": delta})


# ------------------------------------------------------------------ chat ----

def chat_turn_started(session_id, run_id, message):
    return publish("chat.turn.started", run_id=run_id,
                   summary=message[:160],
                   payload={"session_id": session_id, "message": message[:600]})


def chat_tool_called(session_id, run_id, tool, ok, elapsed, summary=""):
    return publish("chat.tool.called", run_id=run_id,
                   severity="info" if ok else "warning",
                   summary="%s %s(%s)" % ("✓" if ok else "✗", tool, summary[:80]),
                   payload={"session_id": session_id, "tool": tool, "ok": ok,
                            "elapsed_s": elapsed})


def chat_turn_completed(session_id, run_id, meta, answer):
    tools = (meta or {}).get("tools_used") or []
    return publish("chat.turn.completed", run_id=run_id,
                   summary="Answered in %.1f s using %d tool%s"
                           % ((meta or {}).get("elapsed") or 0.0, len(tools),
                              "" if len(tools) == 1 else "s"),
                   payload={"session_id": session_id, "tools_used": tools,
                            "elapsed_s": (meta or {}).get("elapsed"),
                            "ttft_s": (meta or {}).get("ttft"),
                            "preview": (answer or "")[:400]})
