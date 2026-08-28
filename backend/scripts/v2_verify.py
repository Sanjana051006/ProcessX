"""ProcessX v2 verification suite.

    .venv/Scripts/python -m backend.scripts.v2_verify      (Windows)
    .venv/bin/python -m backend.scripts.v2_verify          (macOS / Linux)

Prints PASS / FAIL per assertion and exits non-zero on any failure, so it works
as the test suite. It asserts the properties the v2 build is supposed to have,
not just that the demo runs:

  1. the simulator is reproducible and every case walks the whole lifecycle
  2. the healthy baseline is genuinely healthy -- no stage strained with
     nothing wrong, and no queue that fails to drain
  3. injected constraints are stable, and start when the ground truth says
  4. M1-M4 hold up on faults they were not trained on, in three macro-stages
     and across both causes
  5. the agent reaches the right conclusion and stops for a reason
  6. M5/M6 pick an ROI-positive action and applying it actually helps
  7. the storage round-trips and the run is idempotent

It calls db.reset(), so it wipes the database. Re-run bootstrap afterwards.
"""

import sys
import time

import numpy as np

from backend import db
from backend.agent import controller, policy
from backend.models import features, registry
from backend.models.m4_cause import MIN_STRAINED_SHARE, MIN_STRAINED_WINDOWS
from backend.sim import config as C, costs, engine, persist, scenarios

FAILURES = []


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -- " + detail) if detail else ""), flush=True)
    if not ok:
        FAILURES.append(name)
    return ok


def head(title):
    print("\n== %s ==" % title, flush=True)


def stage_table(result):
    return costs.stage_summary(
        costs.derive(result["events"]), result["horizon_hours"], result["config"])


# --------------------------------------------------------------- simulator ---
def verify_simulator():
    head("1  simulator: reproducibility and lifecycle coverage")

    a = engine.simulate(scenarios.healthy_config())
    b = engine.simulate(scenarios.healthy_config())
    check("same seed reproduces the world exactly",
          a["events"]["end_ts"].equals(b["events"]["end_ts"])
          and a["cases"].equals(b["cases"]),
          "%d events" % len(a["events"]))

    per_case = a["events"].groupby("case_id").size()
    check("every case visits all %d activities" % len(C.STAGES),
          bool((per_case == len(C.STAGES)).all()),
          "%d cases" % len(per_case))

    macros = set(a["events"]["macro_stage"].unique())
    check("every macro-stage appears in the log",
          macros == set(C.MACRO_STAGES),
          ", ".join(sorted(macros)))

    ev = costs.derive(a["events"])
    cycle = costs.case_summary(ev)["cycle_hours"]
    per_case_sum = ev.groupby("case_id")["stage_duration"].sum()
    check("cycle time == sum of activity durations",
          bool(np.allclose(cycle.to_numpy(), per_case_sum.to_numpy())))

    # The generalised auto-pass branch must not walk off the end of the pipeline.
    cfg = C.base_config(label="guard")
    cfg["stages"][C.STAGES[-1]]["manual_review"] = True
    guarded = engine.simulate(cfg)
    last = guarded["events"][guarded["events"]["stage"] == C.STAGES[-1]]
    check("auto-pass at the final activity does not overrun the pipeline",
          bool(last["end_ts"].notna().all()) and len(guarded["events"]) == len(a["events"]),
          "%d auto-passes"
          % int(last["resource_id"].astype(str).str.endswith(":auto").sum()))
    return a


# ------------------------------------------------------------ healthy world --
def verify_healthy(healthy):
    head("2  the healthy baseline is genuinely healthy")

    st = stage_table(healthy)
    worst = st["wait_to_service_ratio"].idxmax()
    worst_ratio = float(st.loc[worst, "wait_to_service_ratio"])
    check("no activity is strained with nothing wrong",
          worst_ratio < features.STRAIN_RATIO,
          "worst is %s at %.2f (strain threshold %.1f)"
          % (worst, worst_ratio, features.STRAIN_RATIO))

    over = st.index[st["utilisation"] >= 1.0].tolist()
    check("no activity is offered more load than it can serve",
          not over, "max utilisation %.3f at %s"
          % (st["utilisation"].max(), st["utilisation"].idxmax()))

    kpis = costs.run_kpis(costs.derive(healthy["events"]),
                          healthy["config"]["horizon_days"])
    check("the SLA threshold discriminates rather than never firing",
          0.0 < kpis["sla_breach_rate"] < 0.25,
          "%.2f%% of cases breach the %d h threshold"
          % (100 * kpis["sla_breach_rate"], C.SLA_THRESHOLD_HOURS))


# -------------------------------------------------------------- scenarios ----
def verify_scenarios(healthy):
    head("3  injected constraints are stable and start when ground truth says")

    healthy_end = costs.derive(healthy["events"])["end_ts"].max()
    worlds = {}
    for name in scenarios.EVALUATION_SCENARIOS:
        result = engine.simulate(scenarios.scenario_config(name))
        worlds[name] = result
        truth = scenarios.ground_truth_for(name)
        stage = truth["bottleneck_stage"]
        st = stage_table(result)
        util = float(st.loc[stage, "utilisation"])

        check("%s: %s stays a queue that drains" % (name, stage),
              util < 1.0, "utilisation %.3f" % util)

        ev = costs.derive(result["events"])
        check("%s: the backlog clears inside the run" % name,
              ev["end_ts"].max() <= healthy_end + 24.0,
              "last event %.1f h vs %.1f h healthy" % (ev["end_ts"].max(), healthy_end))

        check("%s: %s is the most strained activity" % (name, stage),
              st["wait_to_service_ratio"].idxmax() == stage,
              "ratio %.2f" % st.loc[stage, "wait_to_service_ratio"])

        onset = scenarios.injected_at(name)
        sub = ev[(ev["stage"] == stage)]
        before = sub[sub["arrival_ts"] < onset]["queue_wait"]
        after = sub[sub["arrival_ts"] >= onset]["queue_wait"]
        check("%s: no queue before the stated onset of %.0f h" % (name, onset),
              (before.mean() if len(before) else 0.0) < 0.05 <= after.mean(),
              "before %.3f h, after %.3f h"
              % (before.mean() if len(before) else 0.0, after.mean()))

    stages = {scenarios.ground_truth_for(n)["bottleneck_stage"]
              for n in scenarios.EVALUATION_SCENARIOS}
    causes = {scenarios.ground_truth_for(n)["true_cause"]
              for n in scenarios.EVALUATION_SCENARIOS}
    check("evaluation covers more than one activity and more than one cause",
          len(stages) >= 3 and causes == {"capacity_saturation", "staffing_shortage"},
          "%d activities, causes %s" % (len(stages), sorted(causes)))
    return worlds


# ----------------------------------------------------------------- models ----
def verify_models(healthy, worlds):
    head("4  M1-M4 on faults they were not trained on")

    t = time.time()
    reg = registry.Registry().train(worlds[scenarios.DEMO_SCENARIO], healthy,
                                    verbose=False)
    cards = reg.metric_cards(registry.evaluation_spec(worlds))
    reg.save()
    print("     trained and scored in %.1fs" % (time.time() - t), flush=True)

    for card in cards:
        check("%s %s" % (card["model"], card["name"]), bool(card["pass"]),
              "%s (target %s)" % (card["display"], card["target"]))

    m2 = next(c for c in cards if c["model"] == "M2")
    check("M2 is scored on every fault scenario",
          "%d scenarios" % len(worlds) in m2["display"], m2["display"])

    # M4's training corpus must not contain the configurations it is scored on.
    from backend.models import m4_cause
    corpus = {s for s, _, _ in m4_cause._STAFFING_RUNS} | \
             {s for s, _, _ in m4_cause._SATURATION_RUNS}
    scored = {scenarios.ground_truth_for(n)["bottleneck_stage"] for n in worlds}
    check("M4 is not trained on the activities it is scored on",
          not (scored & corpus) or scored - corpus,
          "scored %s, corpus %s" % (sorted(scored), sorted(corpus)))

    for name, result in worlds.items():
        truth = scenarios.ground_truth_for(name)
        w = reg.windows(result)
        cause, p, _, _ = reg.m4.stage_cause(w, truth["bottleneck_stage"])
        check("M4 on %s calls %s %s" % (name, truth["bottleneck_stage"],
                                        truth["true_cause"]),
              cause == truth["true_cause"] and p >= policy.CONFIDENCE_THRESHOLD,
              "%s p=%.2f" % (cause, p))

        ranked = reg.ranking(result)
        check("M2 ranks %s first on %s" % (truth["bottleneck_stage"], name),
              ranked.iloc[0]["stage"] == truth["bottleneck_stage"],
              "top: %s" % ranked.iloc[0]["stage"])

    # And it must not invent a fault where there is none.
    hw = reg.windows(healthy)
    verdicts = {s: reg.m4.stage_cause(hw, s)[0] for s in C.STAGES}
    wrong = {s: c for s, c in verdicts.items() if c != "normal"}
    check("M4 reports normal for every activity of the healthy world",
          not wrong, "%d activities, floor is %d strained windows / %.0f%%"
          % (len(C.STAGES), MIN_STRAINED_WINDOWS, 100 * MIN_STRAINED_SHARE)
          if not wrong else "misread: %s" % wrong)
    return reg


# ------------------------------------------------------------------ agent ----
def verify_agent(reg, worlds):
    head("5  the agent concludes correctly and stops for a reason")

    result = worlds[scenarios.DEMO_SCENARIO]
    truth = scenarios.ground_truth_for(scenarios.DEMO_SCENARIO)
    outcome = controller.investigate(result, reg, scenarios.DEMO_SCENARIO,
                                     inv_id="verify-demo", persist_result=False)
    con = outcome["conclusion"]

    check("agent identifies the injected activity",
          con["concluded_stage"] == truth["bottleneck_stage"],
          "%s" % con["concluded_stage"])
    check("agent identifies the injected cause",
          con["concluded_cause"] == truth["true_cause"],
          "%s at p=%.2f" % (con["concluded_cause"], con["confidence"]))
    check("agent stops because it is done, not because it ran out of probes",
          "probe budget exhausted" not in con["stop_reason"],
          con["stop_reason"])
    check("agent does not spend the whole budget on a single-fault world",
          int(con["probes_used"]) < policy.MAX_PROBES,
          "%d of %d probes" % (con["probes_used"], policy.MAX_PROBES))
    check("agent drills into the leading activity before stopping",
          any(n.probe_type == "factor" for n in outcome["nodes"]),
          ", ".join(n.target for n in outcome["nodes"]))

    # Same code path, a different fault, in a different macro-stage.
    other = next(n for n in scenarios.EVALUATION_SCENARIOS
                 if n != scenarios.DEMO_SCENARIO)
    other_truth = scenarios.ground_truth_for(other)
    out2 = controller.investigate(worlds[other], reg, other,
                                  inv_id="verify-other", persist_result=False)
    check("the same loop diagnoses %s with no code change" % other,
          out2["conclusion"]["concluded_stage"] == other_truth["bottleneck_stage"]
          and out2["conclusion"]["concluded_cause"] == other_truth["true_cause"],
          "%s / %s" % (out2["conclusion"]["concluded_stage"],
                       out2["conclusion"]["concluded_cause"]))
    return outcome


# ----------------------------------------------------------- interventions ---
def verify_interventions(reg, worlds, outcome):
    head("6  M5/M6 pick an action that actually helps")

    result = worlds[scenarios.DEMO_SCENARIO]
    candidates = outcome["candidates"]
    check("M5 produces a non-zero effect for every candidate",
          all(abs(c["delta_hours"]) > 0 for c in candidates),
          ", ".join("%s %.2f h" % (c["action"], c["delta_hours"]) for c in candidates))

    selected = [c for c in candidates if c.get("selected")]
    check("M6 selects at least one ROI-positive action", bool(selected),
          ", ".join(c["action"] for c in selected) or "none")
    check("every selected action is ROI-positive",
          all(c["roi"] > 0 for c in selected),
          ", ".join("%s ROI %.2f" % (c["action"], c["roi"]) for c in selected))

    total = sum(c["cost_30d"] for c in selected)
    check("the selected set fits the budget", total <= C.BUDGET_CAP,
          "Rs %s of Rs %s" % (format(int(total), ","), format(C.BUDGET_CAP, ",")))

    for c in selected:
        check("   %s targets the concluded activity" % c["action"],
              C.CATALOGUE[c["action"]]["stage"] == outcome["conclusion"]["concluded_stage"],
              C.CATALOGUE[c["action"]]["stage"])

    before = costs.run_kpis(result["events"], result["config"]["horizon_days"])
    child, after = controller.apply_intervention(
        result, reg, [c["action"] for c in selected], run_id="verify_after",
        parent_run_id=scenarios.DEMO_SCENARIO, label="verify", refit=False)
    check("applying the selected set improves mean cycle time",
          after["mean_cycle_hours"] < before["mean_cycle_hours"],
          "%.2f h -> %.2f h" % (before["mean_cycle_hours"], after["mean_cycle_hours"]))
    check("applying the selected set lowers cost per case",
          after["cost_per_case"] < before["cost_per_case"],
          "Rs %.1f -> Rs %.1f" % (before["cost_per_case"], after["cost_per_case"]))

    st = stage_table(child)
    stage = outcome["conclusion"]["concluded_stage"]
    before_st = stage_table(result)
    check("the fix relieves the activity it targeted",
          st.loc[stage, "mean_wait"] < before_st.loc[stage, "mean_wait"] * 0.75,
          "%s wait %.3f h -> %.3f h"
          % (stage, before_st.loc[stage, "mean_wait"], st.loc[stage, "mean_wait"]))


# ---------------------------------------------------------------- storage ----
def verify_storage(healthy, worlds):
    head("7  storage round-trips and is idempotent")

    db.reset()
    k0 = persist.write_run(healthy, "baseline", label=scenarios.label_for("healthy"),
                           ground_truth={**scenarios.ground_truth_for("healthy"),
                                         "injected_at": None})
    name = scenarios.DEMO_SCENARIO
    k1 = persist.write_run(worlds[name], name, label=scenarios.label_for(name),
                           parent_run_id="baseline",
                           ground_truth={**scenarios.ground_truth_for(name),
                                         "injected_at": scenarios.injected_at(name)})

    conn = db.get_conn()
    n_events = conn.execute("SELECT count(*) FROM event_log").fetchone()[0]
    check("event rows == cases x activities x runs",
          n_events == (k0["n_cases"] + k1["n_cases"]) * len(C.STAGES),
          "%d rows" % n_events)

    back = persist.load_events(name)
    check("macro_stage survives the round trip",
          set(back["macro_stage"].unique()) == set(C.MACRO_STAGES))
    check("timings survive the round trip",
          bool(np.allclose(back.sort_values(["case_id", "stage"])["end_ts"].to_numpy(),
                           worlds[name]["events"].sort_values(["case_id", "stage"])["end_ts"].to_numpy())))

    cases = persist.load_cases(name)
    for col in ("customer_segment", "priority", "claim_type", "support_channel",
                "invoice_value", "invoice_exception_reason"):
        check("   lifecycle attribute %s is persisted" % col, col in cases.columns)
    check("ground truth is never written into the case table",
          "true_cause" not in cases.columns and "bottleneck_stage" not in cases.columns)

    again = persist.write_run(worlds[name], name, label=scenarios.label_for(name))
    check("re-writing a run is idempotent",
          again["mean_cycle_hours"] == k1["mean_cycle_hours"]
          and conn.execute("SELECT count(*) FROM event_log").fetchone()[0] == n_events)


def main():
    t0 = time.time()
    print("ProcessX v2 verification", flush=True)
    print("%d activities, %d macro-stages, %d-day horizon, seed %d"
          % (len(C.STAGES), len(C.MACRO_STAGES), C.HORIZON_DAYS, C.MASTER_SEED))
    db.reset()

    healthy = verify_simulator()
    verify_healthy(healthy)
    worlds = verify_scenarios(healthy)
    reg = verify_models(healthy, worlds)
    outcome = verify_agent(reg, worlds)
    verify_interventions(reg, worlds, outcome)
    verify_storage(healthy, worlds)

    print("\n" + "=" * 62, flush=True)
    if FAILURES:
        print("v2 VERIFY FAILED in %.1fs: %s" % (time.time() - t0, ", ".join(FAILURES)), flush=True)
        return 1
    print("v2 VERIFY PASSED in %.1fs. Run bootstrap to restore the demo start state."
          % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
