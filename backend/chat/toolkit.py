"""The tools the ProcessX agent can call.

Two families:

* **Database** — a schema description and one guarded read-only SELECT, for the
  long tail of questions nobody wrote an endpoint for.
* **Simulation and models** — first-class access to the same analysis the
  dashboard renders: KPIs, the activity table, M2's ranking, M3's anomalies, the
  agent's investigation tree, M4's verdict, M5's counterfactuals, M6's ROI
  selection, and a case's journey through all 24 activities.

Answer quality comes from the shape of these tools, not from prompting around
weak ones. Each returns compact JSON with units in the key names, so the model
never has to guess whether a number is hours, rupees or a ratio, and each
carries a short `note` when there is a rule the model would otherwise get wrong.
"""

import json

from backend import analytics
from backend.chat.tools import ToolRegistry, ToolResult
from backend.models import m5_impact as m5, m6_roi as m6
from backend.sim import config as C, persist

# Tool results are fed straight back into the prompt, so they are capped. This
# is generous enough for the 24-activity table and tight enough that three tool
# rounds do not blow the context window.
MAX_RESULT_CHARS = 14_000

_NO_ARGS = {"type": "object", "properties": {}}


def _json(payload, note=None):
    if note:
        payload = {**payload, "note": note}
    text = json.dumps(payload, default=str, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '..."TRUNCATED":true}'
    return ToolResult(ok=True, content=text, data=payload)


def _round(value, digits=3):
    return None if value is None else round(float(value), digits)


def build_registry(state):
    """Wire every tool against the live app state (models + current run)."""
    reg = ToolRegistry()

    # ------------------------------------------------------------ database --

    def describe_schema(_args):
        return ToolResult(ok=True, content=analytics.schema_text() + "\n\n" + json.dumps(
            analytics.stage_reference(), separators=(",", ":")))

    reg.register(
        "describe_schema",
        "The ProcessX SQLite schema: all 8 tables with their columns, the join rules, "
        "how timestamps work, and the full list of 24 activities grouped by their 5 "
        "macro-stages. Call this before writing SQL for the first time in a "
        "conversation.",
        _NO_ARGS, describe_schema, category="database")

    def query_database(args):
        sql = args.get("sql") or args.get("query") or ""
        limit = args.get("limit", 100)
        try:
            executed, rows = analytics.run_select(sql, limit=limit)
        except ValueError as exc:
            return ToolResult(ok=False, content="",
                              error="%s. The connection is read-only: one SELECT (or "
                                    "WITH ... SELECT) per call." % exc)
        return _json({"sql": executed, "row_count": len(rows), "rows": rows},
                     note=("No rows. Check the run_id filter — most tables are keyed by "
                           "run_id and an unfiltered or wrong value returns nothing."
                           if not rows else None))

    reg.register(
        "query_database",
        "Run one read-only SQL SELECT against the ProcessX database and get the rows "
        "back. Use it for aggregate questions the other tools do not cover — counts, "
        "group-bys, distributions across cases or activities, slicing by customer "
        "segment or weekday. Always filter by run_id. Timestamps are float hours from "
        "t=0 (Monday 00:00). Only SELECT and WITH are permitted; one statement per call.",
        {
            "type": "object",
            "properties": {
                "sql": {"type": "string",
                        "description": "A single SELECT or WITH...SELECT statement, no trailing semicolon."},
                "limit": {"type": "integer",
                          "description": "Row cap, 1-500. Applied automatically when the query has no LIMIT of its own. Default 100."},
            },
            "required": ["sql"],
        }, query_database, category="database")

    # ------------------------------------------------------------- context --

    def list_runs(_args):
        runs = analytics.list_runs()
        current = state.current_run_id() if runs else None
        return _json({
            "current_run_id": current,
            "runs": [{**r, "is_current": r["run_id"] == current} for r in runs],
            "scenarios_available_to_inject": analytics.scenario_catalogue(),
        }, note="A run is one simulated world. 'baseline' is the healthy lifecycle; a "
                "scenario run has a fault injected; a run whose id contains '+' is a "
                "child world after an intervention was applied.")

    reg.register(
        "list_runs",
        "List every simulated world in the database with its headline KPIs, which one "
        "is current, and the fault scenarios that can be injected. Call this first when "
        "the user's question mentions a scenario, a comparison, or 'before and after'.",
        _NO_ARGS, list_runs, category="simulation")

    def get_process_map(_args):
        return _json(analytics.process_map(),
                     note="The lifecycle is a fixed linear pipeline: every business case "
                          "visits all 24 activities in this order, exactly once.")

    reg.register(
        "get_process_map",
        "The static shape of the process: the 5 macro-stages, the 24 activities inside "
        "them in order, each activity's roster and mean service time, and the frozen "
        "simulator constants (seed, horizon, holding cost, SLA threshold, budget cap).",
        _NO_ARGS, get_process_map, category="simulation")

    # ------------------------------------------------------------ analysis --

    def get_run_overview(args):
        ov = analytics.overview(state, args.get("run_id"))
        return _json(ov, note="`kpis` are for this world; `parent_kpis` are the world it "
                              "came from, which is what a before/after comparison uses.")

    reg.register(
        "get_run_overview",
        "Headline analytics for a world: case count, mean and p90 cycle time, cost per "
        "case, throughput, SLA breach rate, the worst-ranked activity, which activities "
        "are flagged anomalous, and the parent world's KPIs for comparison. Start here "
        "for any 'how is the process doing' question.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_run_overview, category="analysis")

    def get_stage_health(args):
        table = analytics.stage_table(state, args.get("run_id"))
        stages = table["stages"]
        macro = args.get("macro_stage")
        if macro:
            stages = [s for s in stages if s["macro_stage"] == macro]
        stage = args.get("stage")
        if stage:
            stages = [s for s in stages if s["stage"] == stage]
        compact = [
            {"stage": s["stage"], "macro_stage": s["macro_stage"], "rank": s["rank"],
             "mean_wait_hours": _round(s["mean_wait_hours"]),
             "mean_service_hours": _round(s["mean_service_hours"]),
             "mean_duration_hours": _round(s["mean_duration_hours"]),
             "wait_to_service_ratio": _round(s["wait_to_service_ratio"], 2),
             "utilisation": _round(s["utilisation"], 3),
             "contribution_pct": _round(s["contribution_pct"], 1),
             "servers": s["servers"], "weekend_servers": s["weekend_servers"],
             "anomalous": s["anomalous"], "anomaly_share": _round(s["anomaly_share"], 3),
             "health": s["health"]}
            for s in stages
        ]
        return _json({"run_id": table["run_id"], "n": len(compact), "stages": compact},
                     note="wait_to_service_ratio above 1.0 means cases wait longer than "
                          "they are served — that is the strain threshold M4 uses. "
                          "`health` compares this world against its PARENT world, not "
                          "against the healthy baseline.")

    reg.register(
        "get_stage_health",
        "Per-activity operational metrics: mean wait, mean service, wait-to-service "
        "ratio, utilisation, bottleneck rank, share of total delay, roster size, "
        "anomaly flag and health band. Filter to one activity or one macro-stage, or "
        "get all 24. This is the activity table the dashboard renders.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."},
            "stage": {"type": "string", "description": "One activity, e.g. 'evidence_review'."},
            "macro_stage": {"type": "string", "enum": list(C.MACRO_STAGES),
                            "description": "Restrict to one lifecycle macro-stage."}}},
        get_stage_health, category="analysis")

    def get_macro_breakdown(args):
        return _json(analytics.macro_table(state, args.get("run_id")),
                     note="mean_duration_hours is what ONE case spends passing through "
                          "the whole macro-stage — the sum of its activities, not their "
                          "average, because every case visits each activity once.")

    reg.register(
        "get_macro_breakdown",
        "The lifecycle rolled up to its 5 macro-stages: hours a case spends in each, "
        "how much of that is queueing, average utilisation, and each one's share of "
        "total cycle time. Use this when the question is about the lifecycle shape "
        "rather than a single activity.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_macro_breakdown, category="analysis")

    def get_bottleneck_ranking(args):
        table = analytics.stage_table(state, args.get("run_id"))
        limit = int(args.get("limit", 8))
        ranked = sorted(table["stages"], key=lambda s: s["rank"])[:max(1, min(limit, 24))]
        return _json({
            "run_id": table["run_id"],
            "weights": {"queue_wait_share": 0.45, "utilisation": 0.30, "residual_share": 0.25},
            "ranking": [
                {"rank": s["rank"], "stage": s["stage"], "macro_stage": s["macro_stage"],
                 "score": _round(s["score"], 4),
                 "contribution_pct": _round(s["contribution_pct"], 1),
                 "queue_wait_share": _round(s["queue_wait_share"], 4),
                 "utilisation": _round(s["utilisation"], 3),
                 "mean_wait_hours": _round(s["mean_wait_hours"]),
                 "mean_duration_hours": _round(s["mean_duration_hours"])}
                for s in ranked],
        }, note="M2's score is 0.45 x queue-wait share + 0.30 x utilisation + 0.25 x "
                "share of delay M1 could not explain. contribution_pct is that score as "
                "a percentage of all 24 activities' scores.")

    reg.register(
        "get_bottleneck_ranking",
        "M2's ranked bottleneck list: which activities are holding the process up, "
        "scored on queue-wait share, utilisation and unexplained residual. Use this for "
        "'what is the bottleneck', 'what is slowest', or 'where should we look'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."},
            "limit": {"type": "integer", "description": "How many activities, 1-24. Default 8."}}},
        get_bottleneck_ranking, category="analysis")

    def get_anomalies(args):
        step = analytics.anomaly_report(state, args.get("run_id"))
        return _json({
            "run_id": step["run_id"],
            "flagged": step["anomalies"],
            "detection_lead_hours": next(
                (m["value"] for m in step["metrics"] if m["label"] == "Lead time"), None),
            "injected_at_hours": step["injected_at"],
            "timeline_stage": step["timeline_stage"],
        }, note="M3 fits one IsolationForest per activity on the HEALTHY baseline's "
                "weekday windows. A window counts only if it is both statistically "
                "unusual and worse than the healthy 95th percentile, and an activity "
                "only trips after two sustained flags.")

    reg.register(
        "get_anomalies",
        "M3's anomaly detection: which activities are tripping, how many of their "
        "hourly windows are flagged, and how long after the fault started the first "
        "sustained flag appeared. Use this for 'is anything wrong', 'when did it "
        "start', or 'how quickly was it caught'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_anomalies, category="analysis")

    def get_model_metrics(_args):
        reg_models = state.models()
        return _json({"cards": reg_models.cards},
                     note="Scored against the ground_truth table, which no model trains "
                          "on. M2 and M4 are scored across three fault scenarios in "
                          "three different macro-stages, not just the demo one.")

    reg.register(
        "get_model_metrics",
        "The four model scorecards: M1 process-time prediction, M2 bottleneck "
        "detection, M3 anomaly detection lead time, M4 delay-cause accuracy — with the "
        "metric, the value and how it was measured. Use this for 'how accurate is the "
        "model' or 'how well does it work'.",
        _NO_ARGS, get_model_metrics, category="models")

    # ---------------------------------------------------------- the agent ---

    def get_investigation(args):
        run_id = state.resolve(args.get("run_id"))
        outcome = analytics.investigation(state, run_id)
        agent_step = analytics.agent_panel(outcome)
        m4_step = analytics.cause_panel(state.models(), outcome)
        conclusion = {k: v for k, v in outcome["conclusion"].items() if k != "trigger"}
        return _json({
            "run_id": run_id,
            "inv_id": conclusion["inv_id"],
            "conclusion": conclusion,
            "cause_hypotheses": m4_step["hypotheses"],
            "stop_reason": agent_step["stop_reason"],
            "probes": [
                {"seq": n["seq"], "probe_type": n["probe_type"], "target": n["target"],
                 "depth": n["depth"], "impact": _round(n["impact"], 3),
                 "uncertainty": _round(n["uncertainty"], 3),
                 "reasoning": n["reasoning"],
                 "hypotheses": n["hypotheses"]}
                for n in agent_step["nodes"]],
        }, note="Each probe node carries its own reasoning string: why the agent chose "
                "that probe, what the slice showed, and what it changed. Quote those "
                "when explaining how the conclusion was reached.")

    reg.register(
        "get_investigation",
        "Run (or read back) the agent's investigation of a world: the probes it chose "
        "and why, the evidence each returned, M4's ranked cause hypotheses, the "
        "conclusion with its confidence, and the reason it stopped. Use this for 'what "
        "is causing this', 'why is it slow', or 'how did the agent decide'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_investigation, category="agent")

    def get_interventions(args):
        run_id = state.resolve(args.get("run_id"))
        outcome = analytics.investigation(state, run_id)
        m5_step, m6_step = analytics.impact_panel(outcome), analytics.roi_panel(outcome)
        by_action = {c["action"]: c for c in m5_step["candidates"]}
        rows = []
        for c in m6_step["candidates"]:
            impact = by_action.get(c["action"], {})
            rows.append({
                "action": c["action"], "label": c["label"], "stage": c["stage"],
                "cost_rupees": _round(c["cost"], 0),
                "cost_type": impact.get("cost_type"),
                "delta_cycle_hours": _round(c["delta_hours"]),
                "ci_low_hours": _round(impact.get("ci_low")),
                "ci_high_hours": _round(impact.get("ci_high")),
                "delta_sla_rate": _round(impact.get("delta_sla_rate"), 4),
                "benefit_30d_rupees": _round(c["benefit_30d"], 0),
                "roi": _round(c["roi"], 3),
                "selected": c["selected"],
            })
        return _json({
            "run_id": run_id, "inv_id": outcome["conclusion"]["inv_id"],
            "budget_cap_rupees": m6_step["budget_cap"],
            "committed_rupees": _round(m6_step["spend"], 0),
            "total_benefit_30d_rupees": _round(m6_step["benefit"], 0),
            "candidates": rows,
        }, note="delta_cycle_hours is POSITIVE when the action improves things (cycle "
                "time went down). Benefit = hours saved x %d cases/day x %d days x Rs %d "
                "holding cost, plus SLA penalties avoided. ROI = (benefit - cost) / cost. "
                "Selection is greedy on ROI-per-rupee under the shared cap, and an "
                "ROI-negative action is never chosen even if budget remains."
                % (C.CASES_PER_DAY, C.ROI_HORIZON_DAYS, C.HOLDING_COST_PER_HOUR))

    reg.register(
        "get_interventions",
        "M5 and M6 together: every catalogue action for the diagnosed activity, its "
        "simulated effect on cycle time with a 95% confidence interval, its cost, its "
        "30-day benefit, its ROI, and whether M6 selected it under the budget. Use this "
        "for 'what should we do', 'what would it cost', or 'is it worth it'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_interventions, category="agent")

    def get_intervention_catalogue(args):
        return _json({"actions": analytics.intervention_catalogue(args.get("stage"))},
                     note="These are every action the system can price, across all "
                          "activities. M5/M6 only evaluate the ones on the activity the "
                          "agent concluded against; use simulate_intervention to price "
                          "any other combination.")

    reg.register(
        "get_intervention_catalogue",
        "The full catalogue of interventions the simulator can apply: name, what it "
        "does, which activity it targets, its cost and whether that cost is one-time or "
        "monthly. Optionally filtered to one activity.",
        {"type": "object", "properties": {
            "stage": {"type": "string", "description": "Restrict to one activity."}}},
        get_intervention_catalogue, category="agent")

    def simulate_intervention(args):
        actions = args.get("actions") or ([args["action"]] if args.get("action") else [])
        if not actions:
            return ToolResult(ok=False, content="",
                              error="Pass `actions` as a list of one or more catalogue "
                                    "action names. Call get_intervention_catalogue for "
                                    "the valid names.")
        unknown = [a for a in actions if a not in C.CATALOGUE]
        if unknown:
            return ToolResult(ok=False, content="",
                              error="Unknown action(s): %s. Valid names come from "
                                    "get_intervention_catalogue." % ", ".join(unknown))
        result = state.run_result(args.get("run_id"))
        impact = m5.evaluate_bundle(result["config"], actions)
        scored = m6.score(impact)
        return _json({
            "actions": actions,
            "labels": [C.CATALOGUE[a]["label"] for a in actions],
            "cost_rupees": _round(scored["cost_30d"], 0),
            "delta_cycle_hours": _round(scored["delta_hours"]),
            "ci_low_hours": _round(scored["ci_low"]),
            "ci_high_hours": _round(scored["ci_high"]),
            "delta_p90_hours": _round(scored.get("delta_p90_hours")),
            "delta_sla_rate": _round(scored.get("delta_sla_rate"), 4),
            "delta_cost_per_case": _round(scored.get("delta_cost_per_case"), 2),
            "benefit_30d_rupees": _round(scored["benefit_30d"], 0),
            "roi": _round(scored["roi"], 3),
            "per_seed_delta_hours": [_round(x) for x in scored.get("per_seed_delta", [])],
        }, note="Bundles are SIMULATED together, never summed: two capacity changes on "
                "one activity interact, and the second fix has a smaller marginal effect "
                "than it would alone. Positive delta means improvement.")

    reg.register(
        "simulate_intervention",
        "Counterfactually simulate any combination of catalogue actions on a world and "
        "price it: cycle-time delta with a 95% interval over three paired seeds, p90 "
        "delta, SLA movement, 30-day benefit and ROI. Use this when the user asks 'what "
        "if we did X', or asks about an action M6 did not evaluate. Takes a few seconds "
        "— it re-runs the whole simulation.",
        {"type": "object", "properties": {
            "actions": {"type": "array", "items": {"type": "string"},
                        "description": "One or more catalogue action names, applied together."},
            "run_id": {"type": "string", "description": "Defaults to the current run."}},
         "required": ["actions"]},
        simulate_intervention, category="agent")

    # ------------------------------------------------------------- a case ---

    def get_case_journey(args):
        journey = analytics.case_journey(state, args.get("run_id"), args.get("case_id"))
        return _json({
            "run_id": journey["run_id"], "case_id": journey["case_id"],
            "attributes": journey["attributes"],
            "cycle_hours": _round(journey["cycle_hours"]),
            "queue_hours": _round(journey["queue_hours"]),
            "service_hours": _round(journey["service_hours"]),
            "cost_rupees": _round(journey["cost"], 0),
            "sla_breach": journey["sla_breach"],
            "cycle_percentile": _round(journey["cycle_percentile"], 3),
            "population_mean_cycle_hours": _round(journey["population_mean_cycle_hours"]),
            "macro_rollup": [
                {k: (_round(v) if isinstance(v, float) else v) for k, v in m.items()}
                for m in journey["macro_rollup"]],
            "steps": [
                {"order": s["order"], "stage": s["stage"], "macro_stage": s["macro_stage"],
                 "queue_wait_hours": _round(s["queue_wait_hours"]),
                 "service_hours": _round(s["service_hours"]),
                 "duration_hours": _round(s["duration_hours"]),
                 "m1_predicted_hours": _round(s["predicted_hours"]),
                 "m1_residual_hours": _round(s["residual_hours"]),
                 "stage_percentile": _round(s["stage_percentile"], 3),
                 "queue_len_at_arrival": s["queue_len_at_arrival"]}
                for s in journey["steps"]],
        }, note="stage_percentile is where this step's duration sits in the whole "
                "population for that activity — 0.98 means slower than 98% of visits. "
                "m1_residual_hours is actual minus M1's prediction: positive means "
                "slower than the model can explain.")

    reg.register(
        "get_case_journey",
        "Follow one business case through all 24 activities: its attributes, the wait "
        "and service time at every step, M1's prediction and residual for each, where "
        "each step sits in the population, the macro-stage rollup and the total cycle "
        "time. Omit case_id to get the representative case the simulation panel shows.",
        {"type": "object", "properties": {
            "case_id": {"type": "integer", "description": "Omit for the representative (p75 cycle time) case."},
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        get_case_journey, category="simulation")

    def find_cases(args):
        index = analytics.case_index(
            state, args.get("run_id"), limit=int(args.get("limit", 15)),
            sort=args.get("sort", "cycle_desc"))
        return _json({
            "run_id": index["run_id"], "n_cases_total": index["n_cases"],
            "cases": [{k: (_round(v) if isinstance(v, float) else v) for k, v in c.items()}
                      for c in index["cases"]],
        }, note="Sorted by cycle time by default. Pass a case_id from here to "
                "get_case_journey to see where its time went.")

    reg.register(
        "find_cases",
        "List business cases in a world with their cycle time, queue time, cost, SLA "
        "status and attributes — slowest first by default. Use this to find an example "
        "case worth looking at, or to answer 'which cases are worst'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."},
            "limit": {"type": "integer", "description": "How many cases, 1-60. Default 15."},
            "sort": {"type": "string", "enum": ["cycle_desc", "cycle_asc", "case_id"],
                     "description": "Ordering. Default cycle_desc (slowest first)."}}},
        find_cases, category="simulation")

    # ---------------------------------------------------------- comparison --

    def compare_runs(args):
        a, b = args.get("run_id_a"), args.get("run_id_b")
        if not a or not b:
            return ToolResult(ok=False, content="",
                              error="Pass both run_id_a and run_id_b. Call list_runs for "
                                    "the ids that exist.")
        ka = analytics.run_kpis(state, a)
        kb = analytics.run_kpis(state, b)
        table_a = {s["stage"]: s for s in analytics.stage_table(state, a)["stages"]}
        table_b = {s["stage"]: s for s in analytics.stage_table(state, b)["stages"]}
        moves = sorted(
            ({"stage": s,
              "duration_a_hours": _round(table_a[s]["mean_duration_hours"]),
              "duration_b_hours": _round(table_b[s]["mean_duration_hours"]),
              "delta_hours": _round(table_b[s]["mean_duration_hours"]
                                    - table_a[s]["mean_duration_hours"]),
              "rank_a": table_a[s]["rank"], "rank_b": table_b[s]["rank"]}
             for s in table_a if s in table_b),
            key=lambda r: -abs(r["delta_hours"] or 0))[:6]
        return _json({
            "run_id_a": a, "run_id_b": b,
            "kpis_a": {k: _round(v) if isinstance(v, float) else v for k, v in ka.items()},
            "kpis_b": {k: _round(v) if isinstance(v, float) else v for k, v in kb.items()},
            "delta_b_minus_a": {
                "mean_cycle_hours": _round(kb["mean_cycle_hours"] - ka["mean_cycle_hours"]),
                "p90_cycle_hours": _round(kb["p90_cycle_hours"] - ka["p90_cycle_hours"]),
                "cost_per_case": _round(kb["cost_per_case"] - ka["cost_per_case"], 2),
                "sla_breach_rate": _round(kb["sla_breach_rate"] - ka["sla_breach_rate"], 4),
            },
            "biggest_activity_moves": moves,
        }, note="Both worlds replay the same master seed and the same arrival stream, so "
                "any difference between them is the change itself and not sampling noise.")

    reg.register(
        "compare_runs",
        "Compare two simulated worlds head to head: both KPI sets, the deltas between "
        "them, and the activities that moved most. Use this for 'before and after', "
        "'healthy versus the fault', or 'did the fix work'.",
        {"type": "object", "properties": {
            "run_id_a": {"type": "string", "description": "The baseline side of the comparison."},
            "run_id_b": {"type": "string", "description": "The side being compared against it."}},
         "required": ["run_id_a", "run_id_b"]},
        compare_runs, category="analysis")

    def compare_to_baseline_rule(args):
        run_id = state.resolve(args.get("run_id"))
        from backend import db as _db
        rows = _db.get_conn().execute(
            "SELECT * FROM baseline_decisions WHERE run_id LIKE ?", (run_id + "::%",)
        ).fetchall()
        if not rows:
            return ToolResult(
                ok=False, content="",
                error="No fixed-rule decision recorded for run '%s' yet. It is written "
                      "on the investigate write path — call get_investigation first, "
                      "then retry." % run_id)
        inv = _db.get_conn().execute(
            "SELECT * FROM investigations WHERE run_id = ? ORDER BY started_at DESC LIMIT 1",
            (run_id,)).fetchone()
        picked = persist.load_interventions(inv["inv_id"]) if inv else None
        chosen = picked[picked["selected"] == 1] if picked is not None else None
        agent_cost = float(chosen["cost"].sum()) if chosen is not None else 0.0
        agent_benefit = float(chosen["benefit_30d"].sum()) if chosen is not None else 0.0
        return _json({
            "run_id": run_id,
            "agent": {
                "chosen_stage": inv["concluded_stage"] if inv else None,
                "cause": inv["concluded_cause"] if inv else None,
                "confidence": _round(inv["confidence"], 3) if inv else None,
                "actions": list(chosen["action"]) if chosen is not None else [],
                "cost_rupees": _round(agent_cost, 0),
                "benefit_30d_rupees": _round(agent_benefit, 0),
                "net_benefit_rupees": _round(agent_benefit - agent_cost, 0),
            },
            "fixed_rule": {
                r["run_id"].split("::", 1)[1]: {
                    "chosen_stage": r["chosen_stage"], "chosen_action": r["chosen_action"],
                    "cost_rupees": _round(r["cost"], 0), "roi": _round(r["roi"], 3)}
                for r in rows},
        }, note="The fixed rule is 'pick the activity with the highest mean duration, "
                "then the cheapest action available there'. `fallthrough` skips "
                "activities with no available action and is the stronger of the two "
                "variants. It is the comparator the agent has to beat.")

    reg.register(
        "compare_to_baseline_rule",
        "Compare the agent's decision against the fixed heuristic rule on the same "
        "world — which activity each picked, which action, what it costs and what it "
        "returns. Use this for 'is the agent better than a simple rule' or 'why not "
        "just use the slowest activity'.",
        {"type": "object", "properties": {
            "run_id": {"type": "string", "description": "Defaults to the current run."}}},
        compare_to_baseline_rule, category="agent")

    return reg
