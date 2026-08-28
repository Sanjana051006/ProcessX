"""Analysis layer shared by the dashboard endpoints and the chat agent's tools.

Everything the UI shows and everything the agent can answer with is computed
here, once, from the same code — so a number in a chart and the same number in
a chat reply cannot disagree.

Read-only throughout, with one exception that is a write by design: the
pipeline run persists its investigation under a stable `inv_id` so the chat
agent can read the tree the dashboard is showing.
"""

import re
import sqlite3

import numpy as np

from backend import db
from backend.agent import controller, policy
from backend.jsonsafe import clean, finite
from backend.models import features
from backend.sim import config as C, costs, engine, scenarios

# Health bands, shared with routes_read: green < 1.1x expected, amber to 1.5x,
# red beyond it.
AMBER, RED = 1.1, 1.5

# The pipeline is expensive (M5 re-simulates the world once per seed per
# candidate) and perfectly deterministic on seed 42, so it is computed once per
# (run, case) and held for the life of the process.
_PIPELINE_CACHE = {}
# The investigation is the expensive half (M5 re-simulates the world once per
# seed per candidate). Cached separately so the chat agent can ask about the
# conclusion without paying for the whole nine-panel payload.
_INVESTIGATION_CACHE = {}
# The activity table costs an M1 residual pass plus an M3 scoring pass over the
# whole event log (~3 s). Every panel on the dashboard and half the chat tools
# want it, and it is a pure function of the run, so it is memoised on run_id and
# dropped by the same invalidation the other caches use.
_TABLE_CACHE = {}

MACRO_LABELS = {
    "customer_onboarding": "Customer onboarding",
    "order_processing": "Order processing",
    "claims_processing": "Claims processing",
    "support_resolution": "Support resolution",
    "invoice_approval": "Invoice approval",
}

CAUSE_LABELS = {
    "capacity_saturation": "Capacity saturation",
    "staffing_shortage": "Staffing shortage",
    "normal": "Nothing wrong",
}


def pretty(name):
    """`evidence_review` -> `Evidence review`."""
    return str(name).replace("_", " ").capitalize()


def health_band(ratio):
    if ratio is None:
        return "grey"
    if ratio > RED:
        return "red"
    if ratio > AMBER:
        return "amber"
    return "green"


# ------------------------------------------------------------------ runs ----

def list_runs():
    rows = db.get_conn().execute(
        "SELECT run_id, parent_run_id, label, created_at, mean_cycle_hours,"
        " cost_per_case, throughput_per_day FROM runs ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def run_kpis(state, run_id=None):
    result = state.run_result(run_id)
    return costs.run_kpis(result["events"], result["config"]["horizon_days"])


def _reference_durations(state, row):
    """Expected per-stage duration, taken from the run's own PARENT world.

    Same rule routes_read uses: a fix restores healthy throughput rather than
    beating it, so measuring against the healthy baseline would render an
    intervened world uniformly green and hide the movement the operator cares
    about.
    """
    parent_id = row.get("parent_run_id")
    if not parent_id:
        return None, None
    try:
        parent = state.run_result(parent_id)
    except Exception:
        return None, None
    summary = costs.stage_summary(
        costs.derive(parent["events"]), parent["horizon_hours"], parent["config"])
    return summary["mean_duration"].to_dict(), parent_id


def stage_table(state, run_id=None):
    """One row per activity: timing, load, rank, anomaly flag and health band."""
    reg = state.models()
    row = state.run_row(run_id)
    if row["run_id"] in _TABLE_CACHE:
        return _TABLE_CACHE[row["run_id"]]
    result = state.run_result(row["run_id"])

    ranked = reg.ranking(result).set_index("stage")
    flagged = reg.flagged_windows(result)
    anomalies = reg.m3.anomalous_stages(flagged)
    reference, reference_run_id = _reference_durations(state, row)

    stages = []
    for order, stage in enumerate(C.STAGES):
        r = ranked.loc[stage]
        a = anomalies.get(stage, {})
        expected = (reference or {}).get(stage)
        ratio = (float(r["mean_duration"]) / expected) if expected else None
        cfg = result["config"]["stages"][stage]
        stages.append({
            "stage": stage,
            "label": pretty(stage),
            "macro_stage": C.macro_stage_for(stage),
            "macro_label": MACRO_LABELS[C.macro_stage_for(stage)],
            "order": order,
            "mean_wait_hours": float(r["mean_wait"]),
            "mean_service_hours": float(r["mean_service"]),
            "mean_duration_hours": float(r["mean_duration"]),
            "wait_to_service_ratio": finite(r["wait_to_service_ratio"]),
            "utilisation": float(r["utilisation"]),
            "queue_wait_share": float(r["queue_wait_share"]),
            "contribution_pct": float(r["contribution_pct"]),
            "rank": int(r["rank"]),
            "score": float(r["score"]),
            "anomalous": stage in anomalies,
            "anomaly_share": float(a.get("share", 0.0)),
            "anomalous_windows": int(a.get("n_anomalous_windows", 0)),
            "servers": int(cfg["servers"]),
            "weekend_servers": int(cfg.get("weekend_servers", cfg["servers"])),
            "expected_duration_hours": expected,
            "duration_vs_expected": ratio,
            "health": health_band(ratio),
        })
    table = {
        "run_id": row["run_id"],
        "label": row["label"],
        "parent_run_id": row["parent_run_id"],
        "health_reference_run_id": reference_run_id,
        "stages": stages,
    }
    _TABLE_CACHE[row["run_id"]] = table
    return table


def macro_table(state, run_id=None):
    """The five macro-stages: elapsed and queued hours per case, plus share."""
    row = state.run_row(run_id)
    result = state.run_result(row["run_id"])
    summary = costs.macro_stage_summary(
        costs.derive(result["events"]), result["horizon_hours"], result["config"])
    total_duration = float(summary["mean_duration"].sum()) or 1.0
    out = []
    for macro in C.MACRO_STAGES:
        r = summary.loc[macro]
        out.append({
            "macro_stage": macro,
            "label": MACRO_LABELS[macro],
            "activities": [s for m, ss in C.STAGE_GROUPS if m == macro for s in ss],
            "mean_duration_hours": float(r["mean_duration"]),
            "mean_wait_hours": float(r["mean_wait"]),
            "mean_service_hours": float(r["mean_service"]),
            "avg_utilisation": finite(r["avg_utilisation"]),
            "queue_wait_share": float(r["queue_wait_share"]),
            "share_of_cycle": float(r["mean_duration"]) / total_duration,
        })
    return {"run_id": row["run_id"], "macro_stages": out}


def overview(state, run_id=None):
    """The dashboard header: KPIs, the worst activity, and how the world got here."""
    row = state.run_row(run_id)
    result = state.run_result(row["run_id"])
    kpis = costs.run_kpis(result["events"], result["config"]["horizon_days"])
    table = stage_table(state, row["run_id"])
    stages = table["stages"]
    worst = min(stages, key=lambda s: s["rank"])
    anomalous = [s for s in stages if s["anomalous"]]

    parent_kpis = None
    if row["parent_run_id"]:
        try:
            parent = state.run_result(row["parent_run_id"])
            parent_kpis = costs.run_kpis(parent["events"], parent["config"]["horizon_days"])
        except Exception:
            parent_kpis = None

    cfg = result["config"]
    return clean({
        "run_id": row["run_id"],
        "label": row["label"],
        "parent_run_id": row["parent_run_id"],
        "scenario": cfg.get("scenario", "healthy"),
        "horizon_days": cfg["horizon_days"],
        "interventions_applied": list(cfg.get("interventions_applied") or []),
        "kpis": kpis,
        "parent_kpis": parent_kpis,
        "n_events": int(len(result["events"])),
        "n_activities": len(C.STAGES),
        "n_macro_stages": len(C.MACRO_STAGES),
        "worst_activity": worst,
        "anomalous_activities": [s["stage"] for s in anomalous],
        "n_anomalous": len(anomalous),
        "budget_cap": C.BUDGET_CAP,
        "sla_threshold_hours": C.SLA_THRESHOLD_HOURS,
    })


# ----------------------------------------------------------------- cases ----

def _case_summary(result):
    return costs.case_summary(costs.derive(result["events"]))


def case_index(state, run_id=None, limit=60, sort="cycle_desc"):
    """A browsable slice of cases with their lifecycle cycle time."""
    row = state.run_row(run_id)
    result = state.run_result(row["run_id"])
    summary = _case_summary(result).merge(
        result["cases"][["case_id", "customer_segment", "priority", "claim_type",
                         "support_channel", "invoice_exception", "order_value"]],
        on="case_id", how="left")

    if sort == "cycle_asc":
        summary = summary.sort_values("cycle_hours")
    elif sort == "case_id":
        summary = summary.sort_values("case_id")
    else:
        summary = summary.sort_values("cycle_hours", ascending=False)

    rows = [
        {
            "case_id": int(r["case_id"]),
            "cycle_hours": float(r["cycle_hours"]),
            "total_queue_wait_hours": float(r["total_queue_wait"]),
            "case_cost": float(r["case_cost"]),
            "sla_breach": bool(r["sla_breach"]),
            "customer_segment": r["customer_segment"],
            "priority": r["priority"],
            "claim_type": r["claim_type"],
            "support_channel": r["support_channel"],
            "invoice_exception": bool(r["invoice_exception"]),
            "order_value": float(r["order_value"]),
        }
        for _, r in summary.head(int(limit)).iterrows()
    ]
    return {"run_id": row["run_id"], "n_cases": int(len(summary)), "cases": rows}


def representative_case(state, run_id=None):
    """The case the simulation panel opens on.

    The p75 of cycle time, same choice the backend demo narrates: a case that is
    visibly slower than typical without being the pathological tail, so every
    macro-stage has something to show.
    """
    result = state.run_result(run_id)
    summary = _case_summary(result)
    target = summary["cycle_hours"].quantile(0.75)
    picked = summary.assign(d=(summary["cycle_hours"] - target).abs()).nsmallest(1, "d")
    return int(picked.iloc[0]["case_id"])


def case_journey(state, run_id=None, case_id=None):
    """One business case walked through all 24 activities, with M1's prediction
    for every step and where it sat in the population."""
    reg = state.models()
    row = state.run_row(run_id)
    result = state.run_result(row["run_id"])
    case_id = int(case_id) if case_id is not None else representative_case(state, row["run_id"])

    cases = result["cases"]
    match = cases[cases["case_id"] == case_id]
    if match.empty:
        raise KeyError("no case %s in run %s" % (case_id, row["run_id"]))
    case = match.iloc[0]

    events = costs.derive(result["events"])
    # M1 predictions are row-aligned with the meta frame the feature builder
    # returns, so joining on that index gives per-step predicted vs actual.
    X, y, meta = features.build_m1_features(result["events"], cases)
    predicted = reg.m1.model.predict(X[reg.m1.columns].to_numpy())
    meta = meta.assign(predicted=predicted, actual=y.to_numpy())
    mine = meta[meta["case_id"] == case_id]
    pred_by_stage = dict(zip(mine["stage"], mine["predicted"]))

    # Population percentile for each step, so a step can be called slow with a
    # number rather than an adjective.
    ranks = events.groupby("stage")["stage_duration"]

    journey, elapsed = [], 0.0
    mine_events = events[events["case_id"] == case_id].sort_values("arrival_ts")
    for order, (_, e) in enumerate(mine_events.iterrows()):
        stage = e["stage"]
        duration = float(e["stage_duration"])
        population = ranks.get_group(stage)
        pct = float((population < duration).mean())
        pred = float(pred_by_stage.get(stage, np.nan))
        elapsed += duration
        journey.append({
            "order": order,
            "stage": stage,
            "label": pretty(stage),
            "macro_stage": e["macro_stage"],
            "macro_label": MACRO_LABELS[e["macro_stage"]],
            "arrival_ts": float(e["arrival_ts"]),
            "start_ts": float(e["start_ts"]),
            "end_ts": float(e["end_ts"]),
            "queue_wait_hours": float(e["queue_wait"]),
            "service_hours": float(e["service_time"]),
            "duration_hours": duration,
            "elapsed_hours": elapsed,
            "cost": float(e["stage_cost"]),
            "resource_id": e["resource_id"],
            "queue_len_at_arrival": int(e["queue_len_at_arrival"]),
            "servers_busy": int(e["servers_busy"]),
            "predicted_hours": finite(pred),
            "residual_hours": finite(duration - pred),
            "stage_percentile": pct,
            "population_mean_hours": float(population.mean()),
        })

    macro_rollup = []
    for macro, stage_names in C.STAGE_GROUPS:
        steps = [s for s in journey if s["stage"] in stage_names]
        if not steps:
            continue
        slowest = max(steps, key=lambda s: s["duration_hours"])
        macro_rollup.append({
            "macro_stage": macro,
            "label": MACRO_LABELS[macro],
            "duration_hours": sum(s["duration_hours"] for s in steps),
            "wait_hours": sum(s["queue_wait_hours"] for s in steps),
            "service_hours": sum(s["service_hours"] for s in steps),
            "slowest_stage": slowest["stage"],
            "slowest_hours": slowest["duration_hours"],
            "n_activities": len(steps),
        })

    total = sum(s["duration_hours"] for s in journey)
    population_cycle = _case_summary(result)["cycle_hours"]
    return clean({
        "run_id": row["run_id"],
        "case_id": case_id,
        "attributes": {
            "customer_segment": case["customer_segment"],
            "customer_tier": case["customer_tier"],
            "priority": case["priority"],
            "region": case["region"],
            "item_category": case["item_category"],
            "order_value": float(case["order_value"]),
            "fraud_risk": float(case["fraud_risk"]),
            "is_new_customer": bool(case["is_new_customer"]),
            "needs_review": bool(case["needs_review"]),
            "claim_type": case["claim_type"],
            "claim_severity": float(case["claim_severity"]),
            "support_channel": case["support_channel"],
            "invoice_value": float(case["invoice_value"]),
            "invoice_exception": bool(case["invoice_exception"]),
            "invoice_exception_reason": case["invoice_exception_reason"],
        },
        "cycle_hours": total,
        "queue_hours": sum(s["queue_wait_hours"] for s in journey),
        "service_hours": sum(s["service_hours"] for s in journey),
        "cost": sum(s["cost"] for s in journey),
        "sla_threshold_hours": C.SLA_THRESHOLD_HOURS,
        "sla_breach": total > C.SLA_THRESHOLD_HOURS,
        "cycle_percentile": float((population_cycle < total).mean()),
        "population_mean_cycle_hours": float(population_cycle.mean()),
        "steps": journey,
        "macro_rollup": macro_rollup,
    })


# -------------------------------------------------------------- pipeline ----
# The nine panels the simulation view steps through, forwards and backwards.

PIPELINE_KEYS = ["world", "m1", "m2", "m3", "agent", "m4", "m5", "m6", "outcome"]


def _hours(v):
    return "%.2f h" % float(v)


def _money(v):
    return "Rs %s" % format(int(round(float(v))), ",")


def _card_for(reg, model):
    for card in reg.cards or []:
        if card.get("model") == model:
            return card
    return None


def _step_world(state, run_id, journey, ov):
    kpis = ov["kpis"]
    scenario = ov["scenario"]
    truth = db.get_conn().execute(
        "SELECT bottleneck_stage, true_cause, injected_at FROM ground_truth"
        " WHERE run_id = ?", (run_id,)).fetchone()
    return {
        "key": "world",
        "model": "SIM",
        "title": "The world",
        "subtitle": "Discrete-event simulation, master seed 42",
        "headline": "%s cases through %d activities" % (
            format(kpis["n_cases"], ","), len(C.STAGES)),
        "narrative": (
            "A %d-day lifecycle is simulated from a seed-only random stream, so "
            "arrivals, case attributes and per-(case, stage) service shocks are "
            "identical in every run of this world. Case %d is the one this panel "
            "follows: it takes %s end to end against a population mean of %s, "
            "which puts it at the %d%% mark."
            % (ov["horizon_days"], journey["case_id"], _hours(journey["cycle_hours"]),
               _hours(journey["population_mean_cycle_hours"]),
               round(100 * journey["cycle_percentile"]))),
        "metrics": [
            {"label": "Cases", "value": format(kpis["n_cases"], ","), "hint": "business cases simulated"},
            {"label": "Events", "value": format(ov["n_events"], ","), "hint": "one row per case-activity visit"},
            {"label": "Mean cycle", "value": _hours(kpis["mean_cycle_hours"]), "hint": "onboarding to payment release"},
            {"label": "SLA breach", "value": "%.2f%%" % (100 * kpis["sla_breach_rate"]),
             "hint": "cases over %d h" % C.SLA_THRESHOLD_HOURS},
        ],
        "scenario": scenario,
        "ground_truth": (
            {"bottleneck_stage": truth["bottleneck_stage"], "true_cause": truth["true_cause"],
             "injected_at": truth["injected_at"]} if truth else None),
        "journey": journey,
    }


def _step_m1(state, reg, run_id, journey):
    steps = journey["steps"]
    scored = [s for s in steps if s["predicted_hours"] is not None]
    worst = max(scored, key=lambda s: abs(s["residual_hours"])) if scored else None
    card = _card_for(reg, "M1")
    m = reg.m1.metrics
    return {
        "key": "m1",
        "model": "M1",
        "title": "Process-time prediction",
        "subtitle": "GradientBoostingRegressor, absolute-error loss",
        "headline": card["display"] if card else "%.1f%% better than mean" % (
            100 * m["improvement_vs_mean"]),
        "narrative": (
            "M1 predicts how long each activity should take for this case from its "
            "attributes, the queue it arrived into and the hour of the week. What it "
            "cannot explain is the residual — and that residual is the signal M2 and "
            "M4 both read. The largest gap on case %d is %s: %s actual against %s "
            "predicted, %s unexplained."
            % (journey["case_id"], pretty(worst["stage"]), _hours(worst["duration_hours"]),
               _hours(worst["predicted_hours"]), _hours(worst["residual_hours"]))
            if worst else "M1 predicts activity duration for every step of the lifecycle."),
        "metrics": [
            {"label": "MAE", "value": "%.3f h" % m["mae_hours"], "hint": "on the held-out tail of the horizon"},
            {"label": "vs mean", "value": "%.1f%%" % (100 * m["improvement_vs_mean"]),
             "hint": "against a single global mean predictor"},
            {"label": "vs stage mean", "value": "%.1f%%" % (100 * m["improvement_vs_stage_mean"]),
             "hint": "against each activity's own average"},
            {"label": "Train / test", "value": "%s / %s" % (
                format(m["n_train"], ","), format(m["n_test"], ",")),
             "hint": "time split at hour %.0f, never random" % m["split_hour"]},
        ],
        "predictions": [
            {"stage": s["stage"], "label": s["label"], "macro_stage": s["macro_stage"],
             "actual": s["duration_hours"], "predicted": s["predicted_hours"],
             "residual": s["residual_hours"], "percentile": s["stage_percentile"]}
            for s in scored
        ],
        "worst_residual_stage": worst["stage"] if worst else None,
    }


def _step_m2(state, reg, run_id, table):
    stages = sorted(table["stages"], key=lambda s: s["rank"])
    top = stages[0]
    card = _card_for(reg, "M2")
    return {
        "key": "m2",
        "model": "M2",
        "title": "Bottleneck ranking",
        "subtitle": "0.45 queue-wait share + 0.30 utilisation + 0.25 unexplained residual",
        "headline": "#1 %s — %.1f%% of total delay" % (
            pretty(top["stage"]), top["contribution_pct"]),
        "narrative": (
            "Every activity is scored on three things it can be guilty of: holding the "
            "queue, running hot, and taking longer than M1 can explain. %s tops the "
            "ranking with %.1f%% of the lifecycle's queue-wait, utilisation %.2f and a "
            "wait-to-service ratio of %s — cases spend %s waiting for %s of work."
            % (pretty(top["stage"]), 100 * top["queue_wait_share"], top["utilisation"],
               ("%.2f" % top["wait_to_service_ratio"]) if top["wait_to_service_ratio"] else "n/a",
               _hours(top["mean_wait_hours"]), _hours(top["mean_service_hours"]))),
        "metrics": [
            {"label": "Top activity", "value": pretty(top["stage"]), "hint": MACRO_LABELS[top["macro_stage"]]},
            {"label": "Contribution", "value": "%.1f%%" % top["contribution_pct"], "hint": "share of the ranked score"},
            {"label": "Utilisation", "value": "%.2f" % top["utilisation"], "hint": "busy server-hours / offered server-hours"},
            {"label": "Card", "value": card["display"] if card else "—",
             "hint": "top-1 accuracy against ground truth"},
        ],
        "ranking": stages,
        "top_stage": top["stage"],
    }


def _step_m3(state, reg, run_id):
    result = state.run_result(run_id)
    flagged = reg.flagged_windows(result)
    anomalies = reg.m3.anomalous_stages(flagged)
    card = _card_for(reg, "M3")
    ranked = sorted(anomalies.items(), key=lambda kv: -kv[1]["share"])
    lead_stage = ranked[0][0] if ranked else None

    truth = db.get_conn().execute(
        "SELECT bottleneck_stage, injected_at FROM ground_truth WHERE run_id = ?",
        (run_id,)).fetchone()
    lead_time = None
    if truth and truth["bottleneck_stage"] and truth["injected_at"] is not None:
        lead_time = reg.m3.detection_lead_time(
            flagged, truth["bottleneck_stage"], float(truth["injected_at"]))

    timeline = []
    if lead_stage:
        sub = flagged[flagged["stage"] == lead_stage].sort_values("window")
        timeline = [
            {"window": float(r["window"]), "anomaly": int(r["anomaly"]),
             "score": finite(r["anomaly_score"], 0.0), "mean_wait": finite(r["mean_wait"], 0.0),
             "utilisation": finite(r["utilisation"], 0.0), "n_arrivals": int(r["n_arrivals"])}
            for _, r in sub.iterrows()
        ]

    return {
        "key": "m3",
        "model": "M3",
        "title": "Anomaly detection",
        "subtitle": "One IsolationForest per activity, fitted on healthy windows",
        "headline": ("%s — %.0f%% of windows flagged"
                     % (pretty(lead_stage), 100 * anomalies[lead_stage]["share"])
                     if lead_stage else "No activity is tripping"),
        "narrative": (
            "Each activity has its own detector, fitted on the healthy baseline's "
            "weekday hours. A window counts only when it is both statistically unusual "
            "AND worse than the healthy 95th percentile on wait or utilisation, and a "
            "stage only trips after two sustained flags — contamination alone would "
            "flag 5%% of perfectly healthy hours. %s"
            % (("%s is flagged in %.0f%% of its windows (%d hours)%s."
                % (pretty(lead_stage), 100 * anomalies[lead_stage]["share"],
                   anomalies[lead_stage]["n_anomalous_windows"],
                   (", first sustained flag %s after the constraint started"
                    % _hours(lead_time)) if lead_time is not None else ""))
               if lead_stage else
               "Nothing clears the bar here, which is the correct answer for a healthy world.")),
        "metrics": [
            {"label": "Flagged", "value": str(len(anomalies)), "hint": "activities with sustained anomalies"},
            {"label": "Lead time", "value": _hours(lead_time) if lead_time is not None else "—",
             "hint": "injection to first sustained flag"},
            {"label": "Windows", "value": format(int(len(flagged)), ","), "hint": "stage-hour windows scored"},
            {"label": "Card", "value": card["display"] if card else "—", "hint": "worst-case detection lead"},
        ],
        "anomalies": [
            {"stage": s, "label": pretty(s), "macro_stage": C.macro_stage_for(s), **v}
            for s, v in ranked
        ],
        "timeline_stage": lead_stage,
        "timeline": timeline,
        "injected_at": float(truth["injected_at"]) if truth and truth["injected_at"] is not None else None,
    }


def _step_agent(outcome):
    conclusion = outcome["conclusion"]
    nodes = outcome["nodes"]
    stage_probes = [n for n in nodes if n.probe_type == "stage"]
    factor_probes = [n for n in nodes if n.probe_type == "factor"]
    return {
        "key": "agent",
        "model": "AGENT",
        "title": "Agent investigation",
        "subtitle": "Select by impact x uncertainty, probe, hypothesise, drill or stop",
        "headline": ("%s at p=%.2f" % (pretty(conclusion["concluded_stage"]),
                                       conclusion["confidence"])
                     if conclusion["concluded_stage"] else "Inconclusive"),
        "narrative": (
            "The agent does not walk the activity list. It scores every unprobed "
            "activity by impact times uncertainty, spends a probe on the highest, and "
            "re-scores. It used %d of its %d probes and stopped because %s — not "
            "because it ran out."
            % (conclusion["probes_used"], policy.MAX_PROBES, conclusion["stop_reason"])),
        "metrics": [
            {"label": "Probes used", "value": "%d / %d" % (conclusion["probes_used"], policy.MAX_PROBES),
             "hint": "stopped on a stated reason"},
            {"label": "Stage probes", "value": str(len(stage_probes)), "hint": "which activity is at fault"},
            {"label": "Factor probes", "value": str(len(factor_probes)), "hint": "where inside it the delay lands"},
            {"label": "Confidence", "value": "%.2f" % conclusion["confidence"],
             "hint": "bar is %.2f" % policy.CONFIDENCE_THRESHOLD},
        ],
        "stop_reason": conclusion["stop_reason"],
        "status": conclusion["status"],
        "trigger": conclusion["trigger"],
        "nodes": [
            {"node_id": n.node_id, "parent_node_id": n.parent_node_id, "depth": n.depth,
             "seq": n.seq, "probe_type": n.probe_type, "target": n.target,
             "label": pretty(n.target), "selection_score": finite(n.selection_score, 0.0),
             "impact": finite(n.impact, 0.0), "uncertainty": finite(n.uncertainty, 0.0),
             "evidence": n.evidence, "hypotheses": n.hypotheses, "reasoning": n.reasoning}
            for n in nodes
        ],
    }


def _step_m4(reg, outcome):
    conclusion = outcome["conclusion"]
    stage = conclusion["concluded_stage"]
    nodes = [n for n in outcome["nodes"] if n.probe_type == "stage" and n.target == stage]
    hypotheses = nodes[0].hypotheses if nodes else []
    card = _card_for(reg, "M4")
    lead = hypotheses[0] if hypotheses else {"cause": "normal", "p": 1.0}
    return {
        "key": "m4",
        "model": "M4",
        "title": "Delay-cause classification",
        "subtitle": "Three classes: capacity saturation, staffing shortage, normal",
        "headline": "%s (p=%.2f)" % (CAUSE_LABELS.get(lead["cause"], lead["cause"]), lead["p"]),
        "narrative": (
            "M4 reads the strained hours at %s and separates two failure modes that "
            "look identical in a KPI table. Staffing shortage is capacity below the "
            "activity's own normal roster for part of the week; capacity saturation is "
            "a roster that is constant and simply too small. The verdict is weighted by "
            "the delay in each window and taken at the peak of the queue, not across "
            "the hours spent draining it — draining always looks like saturation, "
            "because the full roster is flat out. Trained on its own synthetic fault "
            "corpus, never on this run."
            % pretty(stage) if stage else
            "No activity cleared the confidence bar, so there is nothing to attribute."),
        "metrics": [
            {"label": "Cause", "value": CAUSE_LABELS.get(lead["cause"], lead["cause"]),
             "hint": "at %s" % (pretty(stage) if stage else "—")},
            {"label": "Probability", "value": "%.2f" % lead["p"], "hint": "delay-weighted over peak windows"},
            {"label": "Classes", "value": "3", "hint": "saturation / shortage / normal"},
            {"label": "Card", "value": card["display"] if card else "—", "hint": "accuracy over held-out windows"},
        ],
        "stage": stage,
        "hypotheses": hypotheses,
        "cause_labels": CAUSE_LABELS,
    }


def _step_m5(outcome):
    candidates = outcome["candidates"]
    best = max(candidates, key=lambda c: c["delta_hours"]) if candidates else None
    return {
        "key": "m5",
        "model": "M5",
        "title": "Intervention impact",
        "subtitle": "Paired counterfactual re-simulation, seeds 42 / 43 / 44",
        "headline": ("%s off mean cycle, best case" % _hours(best["delta_hours"])
                     if best else "No candidate actions"),
        "narrative": (
            "There are no past interventions to regress on, so M5 does not predict — it "
            "re-runs the world. Each candidate is simulated three times against three "
            "paired baselines that share an identical arrival stream and identical "
            "per-case service shocks, so the difference is the intervention and nothing "
            "else. That is why a 95%% interval at n=3 is this narrow. %s"
            % (("%s moves mean cycle by %s (95%% CI %s to %s)."
                % (C.CATALOGUE.get(best["action"], {}).get("label", best["action"]),
                   _hours(best["delta_hours"]), _hours(best["ci_low"]), _hours(best["ci_high"])))
               if best else "")),
        "metrics": [
            {"label": "Candidates", "value": str(len(candidates)), "hint": "catalogue actions for this activity"},
            {"label": "Replicates", "value": "3", "hint": "seeds 42, 43, 44 — paired"},
            {"label": "Best delta", "value": _hours(best["delta_hours"]) if best else "—",
             "hint": "hours off the mean lifecycle"},
            {"label": "Sims run", "value": str(3 + 3 * len(candidates)), "hint": "baselines plus counterfactuals"},
        ],
        "candidates": [
            {"action": c["action"],
             "label": C.CATALOGUE.get(c["action"], {}).get("label", c["action"]),
             "stage": c["stage"], "cost": c["cost_30d"],
             "cost_type": C.CATALOGUE.get(c["action"], {}).get("cost_type"),
             "delta_hours": c["delta_hours"], "ci_low": c["ci_low"], "ci_high": c["ci_high"],
             "delta_p90_hours": c.get("delta_p90_hours"),
             "delta_sla_rate": c.get("delta_sla_rate"),
             "per_seed_delta": c.get("per_seed_delta")}
            for c in candidates
        ],
    }


def _step_m6(outcome):
    candidates = outcome["candidates"]
    picked = [c for c in candidates if c.get("selected")]
    spend = sum(c["cost_30d"] for c in picked)
    benefit = sum(c["benefit_30d"] for c in picked)
    return {
        "key": "m6",
        "model": "M6",
        "title": "ROI optimisation",
        "subtitle": "Greedy ROI-per-rupee under one shared budget",
        "headline": ("%d action%s selected — %s for ROI %.2f"
                     % (len(picked), "" if len(picked) == 1 else "s", _money(spend),
                        (benefit - spend) / spend if spend else 0.0)
                     if picked else "Nothing clears its own cost"),
        "narrative": (
            "Benefit is hours saved times %s cases a day over %d days at Rs %d an hour "
            "of holding cost, plus the SLA penalties avoided. An action only becomes "
            "eligible once that beats its own price — leftover budget is not a reason "
            "to buy something that loses money. %s of the Rs %s cap is committed, "
            "returning %s over the horizon."
            % (format(C.CASES_PER_DAY, ","), C.ROI_HORIZON_DAYS, C.HOLDING_COST_PER_HOUR,
               _money(spend), format(C.BUDGET_CAP, ","), _money(benefit))),
        "metrics": [
            {"label": "Selected", "value": str(len(picked)), "hint": "of %d candidates" % len(candidates)},
            {"label": "Spend", "value": _money(spend), "hint": "against a Rs %s cap" % format(C.BUDGET_CAP, ",")},
            {"label": "Benefit 30d", "value": _money(benefit), "hint": "holding cost plus SLA penalties avoided"},
            {"label": "ROI", "value": "%.2f" % ((benefit - spend) / spend if spend else 0.0),
             "hint": "(benefit - cost) / cost"},
        ],
        "budget_cap": C.BUDGET_CAP,
        "spend": spend,
        "benefit": benefit,
        "candidates": [
            {"action": c["action"],
             "label": C.CATALOGUE.get(c["action"], {}).get("label", c["action"]),
             "stage": c["stage"], "cost": c["cost_30d"],
             "delta_hours": c["delta_hours"], "benefit_30d": c["benefit_30d"],
             "holding_benefit": c.get("holding_benefit"),
             "sla_penalty_avoided": c.get("sla_penalty_avoided"),
             "roi": finite(c["roi"]), "payback_ratio": finite(c.get("payback_ratio")),
             "selected": bool(c.get("selected"))}
            for c in candidates
        ],
    }


def _step_outcome(state, run_id, outcome):
    """Apply the selected portfolio in memory and measure it.

    Deliberately NOT persisted: the panel is a preview the operator steps
    through, and stepping through a view should not mutate which world is
    current. The Apply button on the dashboard is the write path.
    """
    result = state.run_result(run_id)
    picked = [c for c in outcome["candidates"] if c.get("selected")]
    before = costs.run_kpis(result["events"], result["config"]["horizon_days"])

    if not picked:
        return {
            "key": "outcome", "model": "APPLY", "title": "Outcome",
            "subtitle": "Re-simulated with the selected portfolio",
            "headline": "Nothing to apply",
            "narrative": "M6 selected no action, so there is no counterfactual to measure.",
            "metrics": [], "before": before, "after": before, "delta": None,
            "actions": [], "ranking_after": [],
        }

    actions = [c["action"] for c in picked]
    child_config = C.apply_actions(result["config"], actions)
    child = engine.simulate(child_config)
    after = costs.run_kpis(child["events"], child["config"]["horizon_days"])
    reg = state.models()
    ranked_after = reg.ranking(child)
    top_after = ranked_after.iloc[0]

    delta = {
        "mean_cycle_hours": before["mean_cycle_hours"] - after["mean_cycle_hours"],
        "p90_cycle_hours": before["p90_cycle_hours"] - after["p90_cycle_hours"],
        "cost_per_case": before["cost_per_case"] - after["cost_per_case"],
        "sla_breach_rate": before["sla_breach_rate"] - after["sla_breach_rate"],
    }
    return {
        "key": "outcome",
        "model": "APPLY",
        "title": "Outcome",
        "subtitle": "Re-simulated with the selected portfolio on the same seed",
        "headline": "%s off mean cycle time" % _hours(delta["mean_cycle_hours"]),
        "narrative": (
            "The chosen action set is applied to the configuration and the whole world "
            "is simulated again on the same master seed, so the only difference is the "
            "intervention. Mean cycle falls from %s to %s and cost per case from %s to "
            "%s. The constraint moves: %s is now the highest-ranked activity at %.1f%% "
            "of total delay, which is the world the agent would re-plan against."
            % (_hours(before["mean_cycle_hours"]), _hours(after["mean_cycle_hours"]),
               _money(before["cost_per_case"]), _money(after["cost_per_case"]),
               pretty(top_after["stage"]), float(top_after["contribution_pct"]))),
        "metrics": [
            {"label": "Mean cycle", "value": _hours(after["mean_cycle_hours"]),
             "hint": "was %s" % _hours(before["mean_cycle_hours"])},
            {"label": "Cost / case", "value": _money(after["cost_per_case"]),
             "hint": "was %s" % _money(before["cost_per_case"])},
            {"label": "SLA breach", "value": "%.2f%%" % (100 * after["sla_breach_rate"]),
             "hint": "was %.2f%%" % (100 * before["sla_breach_rate"])},
            {"label": "New #1", "value": pretty(top_after["stage"]),
             "hint": "%.1f%% of total delay" % float(top_after["contribution_pct"])},
        ],
        "actions": [
            {"action": c["action"],
             "label": C.CATALOGUE.get(c["action"], {}).get("label", c["action"]),
             "stage": c["stage"], "cost": c["cost_30d"], "int_id": None}
            for c in picked
        ],
        "before": before,
        "after": after,
        "delta": delta,
        "ranking_after": [
            {"rank": int(r["rank"]), "stage": r["stage"], "label": pretty(r["stage"]),
             "macro_stage": C.macro_stage_for(r["stage"]),
             "contribution_pct": float(r["contribution_pct"])}
            for _, r in ranked_after.head(8).iterrows()
        ],
    }


def pipeline(state, run_id=None, case_id=None, refresh=False):
    """The nine panels, computed once per (run, case) and cached.

    The investigation inside is persisted under a stable `inv_id` so the chat
    agent and the interventions endpoint can both read exactly the tree the
    simulation panel is showing.
    """
    row = state.run_row(run_id)
    run_id = row["run_id"]
    case_id = int(case_id) if case_id is not None else representative_case(state, run_id)
    key = (run_id, case_id)
    if not refresh and key in _PIPELINE_CACHE:
        return _PIPELINE_CACHE[key]

    reg = state.models()
    result = state.run_result(run_id)
    journey = case_journey(state, run_id, case_id)
    ov = overview(state, run_id)
    table = stage_table(state, run_id)

    outcome = investigation(state, run_id, refresh=refresh)

    steps = [
        _step_world(state, run_id, journey, ov),
        _step_m1(state, reg, run_id, journey),
        _step_m2(state, reg, run_id, table),
        _step_m3(state, reg, run_id),
        _step_agent(outcome),
        _step_m4(reg, outcome),
        _step_m5(outcome),
        _step_m6(outcome),
        _step_outcome(state, run_id, outcome),
    ]
    payload = clean({
        "run_id": run_id,
        "label": row["label"],
        "case_id": case_id,
        "inv_id": outcome["conclusion"]["inv_id"],
        "conclusion": {k: v for k, v in outcome["conclusion"].items() if k != "trigger"},
        "steps": steps,
    })
    _PIPELINE_CACHE[key] = payload
    return payload


# Public names for the four panels the chat tools read directly, so a tool can
# have the agent's tree or M6's selection without building all nine.
def agent_panel(outcome):
    return _step_agent(outcome)


def cause_panel(reg, outcome):
    return _step_m4(reg, outcome)


def impact_panel(outcome):
    return _step_m5(outcome)


def roi_panel(outcome):
    return _step_m6(outcome)


def investigation(state, run_id=None, refresh=False):
    """Run the agent loop on a world, or return the run already computed.

    Persisted under a stable `inv_id` so the dashboard, the interventions
    endpoint and the chat agent all read one tree rather than three.
    """
    run_id = state.resolve(run_id)
    if not refresh and run_id in _INVESTIGATION_CACHE:
        return _INVESTIGATION_CACHE[run_id]
    outcome = controller.investigate(
        state.run_result(run_id), state.models(), run_id,
        inv_id="pipeline-" + run_id, persist_result=True)
    _INVESTIGATION_CACHE[run_id] = outcome
    return outcome


def anomaly_report(state, run_id=None):
    """M3 on its own — the anomaly panel without paying for M5."""
    run_id = state.resolve(run_id)
    return clean({"run_id": run_id, **_step_m3(state, state.models(), run_id)})


def invalidate_pipeline(run_id=None):
    if run_id is None:
        _PIPELINE_CACHE.clear()
        _INVESTIGATION_CACHE.clear()
        _TABLE_CACHE.clear()
        return
    _INVESTIGATION_CACHE.pop(run_id, None)
    _TABLE_CACHE.pop(run_id, None)
    for key in [k for k in _PIPELINE_CACHE if k[0] == run_id]:
        _PIPELINE_CACHE.pop(key, None)


# ------------------------------------------------------- scenario catalogue --

def scenario_catalogue():
    out = []
    for name, (_, stage, cause, onset) in scenarios.SCENARIOS.items():
        out.append({
            "scenario": name,
            "label": scenarios.label_for(name),
            "bottleneck_stage": stage,
            "macro_stage": C.macro_stage_for(stage) if stage else None,
            "true_cause": cause,
            "injected_at_hours": onset,
            "is_demo": name == scenarios.DEMO_SCENARIO,
        })
    return out


def intervention_catalogue(stage=None):
    out = []
    for action, spec in C.CATALOGUE.items():
        if stage and spec["stage"] != stage:
            continue
        out.append({
            "action": action,
            "label": spec["label"],
            "stage": spec["stage"],
            "macro_stage": C.macro_stage_for(spec["stage"]),
            "cost": float(spec["cost"]),
            "cost_type": spec["cost_type"],
            "effect": spec["effect"],
        })
    return sorted(out, key=lambda a: (a["stage"], a["cost"]))


def process_map():
    return {
        "macro_stages": [
            {"macro_stage": macro, "label": MACRO_LABELS[macro],
             "activities": [
                 {"stage": s, "label": pretty(s),
                  "servers": C.STAGE_DEFS[s]["servers"],
                  "weekend_servers": C.STAGE_DEFS[s].get(
                      "weekend_servers", C.STAGE_DEFS[s]["servers"]),
                  "mean_service_min": C.STAGE_DEFS[s]["mean_service_min"]}
                 for s in stage_names]}
            for macro, stage_names in C.STAGE_GROUPS
        ],
        "edges": [{"from": a, "to": b} for a, b in zip(C.STAGES, C.STAGES[1:])],
        "constants": {
            "master_seed": C.MASTER_SEED,
            "horizon_days": C.HORIZON_DAYS,
            "holding_cost_per_hour": C.HOLDING_COST_PER_HOUR,
            "sla_threshold_hours": C.SLA_THRESHOLD_HOURS,
            "sla_penalty_per_case": C.SLA_PENALTY_PER_CASE,
            "cases_per_day": C.CASES_PER_DAY,
            "roi_horizon_days": C.ROI_HORIZON_DAYS,
            "budget_cap": C.BUDGET_CAP,
        },
    }


# --------------------------------------------------------- read-only SQL -----

TABLE_COLUMNS = {
    "event_log": ["id", "run_id", "case_id", "macro_stage", "stage", "arrival_ts",
                  "start_ts", "end_ts", "resource_id", "queue_len_at_arrival",
                  "servers_busy"],
    "cases": ["case_id", "run_id", "order_value", "customer_tier", "customer_segment",
              "priority", "is_new_customer", "fraud_risk", "region", "item_category",
              "claim_type", "claim_severity", "support_channel", "invoice_value",
              "invoice_exception", "invoice_exception_reason", "created_ts", "weekday",
              "hour", "needs_review"],
    "ground_truth": ["run_id", "bottleneck_stage", "true_cause", "injected_at"],
    "runs": ["run_id", "parent_run_id", "label", "config_json", "created_at",
             "mean_cycle_hours", "cost_per_case", "throughput_per_day"],
    "investigations": ["inv_id", "run_id", "started_at", "status", "concluded_stage",
                       "concluded_cause", "confidence"],
    "investigation_nodes": ["node_id", "inv_id", "parent_node_id", "depth", "seq",
                            "probe_type", "target", "selection_score", "impact",
                            "uncertainty", "evidence_json", "hypotheses_json", "reasoning"],
    "interventions": ["int_id", "inv_id", "stage", "action", "cost",
                      "predicted_delta_hours", "ci_low", "ci_high", "benefit_30d",
                      "roi", "selected", "applied"],
    "baseline_decisions": ["run_id", "chosen_stage", "chosen_action", "cost", "roi"],
}

_FORBIDDEN = ("insert", "update", "delete", "drop", "alter", "create", "replace",
              "attach", "detach", "pragma", "vacuum", "reindex", "begin", "commit")


def run_select(sql, limit=200):
    """Run one read-only SELECT and return rows as dicts.

    Three layers, because the caller is a language model: the statement must be
    a single SELECT or WITH, no write keyword may appear anywhere in it, and the
    connection is opened read-only for the duration so a query that somehow got
    past both would still fail at the driver.
    """
    text = " ".join(str(sql).split())
    stripped = text.rstrip(";").strip()
    if not stripped:
        raise ValueError("empty query")
    if ";" in stripped:
        raise ValueError("one statement per call — remove the ';'")
    lowered = stripped.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("only SELECT (or WITH ... SELECT) is allowed")
    for word in _FORBIDDEN:
        if re.search(r"\b%s\b" % word, lowered):
            raise ValueError("'%s' is not allowed — this connection is read-only" % word)

    limit = max(1, min(int(limit), 500))
    if " limit " not in lowered:
        stripped += " LIMIT %d" % limit

    uri = "file:%s?mode=ro" % db.DB_PATH.as_posix()
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(stripped).fetchall()
    finally:
        conn.close()
    return stripped, [dict(r) for r in rows]


def schema_text():
    """The schema as the model should see it: tables, columns and the two rules
    that are not obvious from column names alone."""
    lines = ["ProcessX SQLite schema. 8 tables. Read-only access.", ""]
    for table, cols in TABLE_COLUMNS.items():
        lines.append("%s(%s)" % (table, ", ".join(cols)))
    lines += [
        "",
        "Rules that matter:",
        "- Every table that carries data is keyed by run_id. A query without a "
        "run_id filter mixes worlds together and its answer means nothing.",
        "- cases has the COMPOSITE key (run_id, case_id): every run replays the "
        "same arrival stream, so case_id 1 exists in every run.",
        "- Timestamps are FLOAT HOURS from t=0, which is Monday 00:00. Hour of day "
        "is `arrival_ts %% 24`, weekday is `(arrival_ts / 24) %% 7` with 0 = Monday.",
        "- event_log has one row per (case, activity). Queue wait is "
        "`start_ts - arrival_ts`, service is `end_ts - start_ts`, and a case's cycle "
        "time is `max(end_ts) - min(arrival_ts)` grouped by case_id.",
        "- ground_truth is evaluation only. No model trains on it. Quote it only "
        "when the user asks whether a prediction was right.",
        "- `stage` is one of the 24 activities; `macro_stage` is one of the 5 "
        "lifecycle groups.",
    ]
    return "\n".join(lines)


def stage_reference():
    return {
        "macro_stages": {m: [s for mm, ss in C.STAGE_GROUPS if mm == m for s in ss]
                         for m in C.MACRO_STAGES},
        "activities": list(C.STAGES),
    }
