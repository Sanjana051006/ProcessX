"""Backend-only ProcessX v2 demo.

Run from the repository root:

    .venv\\Scripts\\python -m backend.scripts.v2_demo

The script trains on the full lifecycle dataset, then narrates one business
case flowing through onboarding, order processing, claims, support, and invoice
approval.
"""

from backend import db
from backend.agent import controller
from backend.models import registry
from backend.sim import config as C, costs, engine, persist, scenarios


def _fmt_hours(value):
    return "%.2f h" % float(value)


def _money(value):
    return "Rs %s" % format(int(round(float(value))), ",")


def _print_cards(cards):
    print("\nMODEL CARDS")
    for card in cards:
        status = "PASS" if card["pass"] else "CHECK"
        print(
            "  %-3s %-26s %-28s %s"
            % (card["model"], card["name"], card["display"], status)
        )


def _write(result, run_id, scenario, parent=None):
    return persist.write_run(
        result,
        run_id,
        label=scenarios.label_for(scenario),
        parent_run_id=parent,
        ground_truth={
            **scenarios.ground_truth_for(scenario),
            "injected_at": scenarios.injected_at(scenario),
        },
    )


def _single_case_flow(result):
    events = costs.derive(result["events"])
    summary = costs.case_summary(events)
    target_cycle = summary["cycle_hours"].quantile(0.75)
    picked = summary.assign(distance=(summary["cycle_hours"] - target_cycle).abs()).sort_values(
        "distance"
    ).iloc[0]
    case_id = int(picked["case_id"])
    case = result["cases"][result["cases"]["case_id"] == case_id].iloc[0]
    journey = events[events["case_id"] == case_id].copy()
    journey["duration"] = journey["stage_duration"]

    print("\nSINGLE BUSINESS CASE FLOW")
    print(
        "  business_case_id=%d | segment=%s | priority=%s | claim=%s | support=%s | invoice_exception=%s"
        % (
            case_id,
            case["customer_segment"],
            case["priority"],
            case["claim_type"],
            case["support_channel"],
            "yes" if int(case["invoice_exception"]) else "no",
        )
    )
    print("  lifecycle cycle time: %s" % _fmt_hours(picked["cycle_hours"]))

    for macro, stages in C.STAGE_GROUPS:
        sub = journey[journey["stage"].isin(stages)]
        total = float(sub["duration"].sum())
        wait = float(sub["queue_wait"].sum())
        slowest = sub.sort_values("duration", ascending=False).iloc[0]
        print(
            "  %-22s %6s total | %6s wait | slowest %-24s %s"
            % (
                macro,
                _fmt_hours(total),
                _fmt_hours(wait),
                slowest["stage"],
                _fmt_hours(slowest["duration"]),
            )
        )


def _rankings(result, reg):
    ranked = reg.ranking(result)
    print("\nM2 ACTIVITY BOTTLENECK RANKING")
    for _, row in ranked.head(8).iterrows():
        print(
            "  #%d %-24s %-22s contribution %5.1f%% | wait %s | util %.2f"
            % (
                int(row["rank"]),
                row["stage"],
                C.macro_stage_for(row["stage"]),
                float(row["contribution_pct"]),
                _fmt_hours(row["mean_wait"]),
                float(row["utilisation"]),
            )
        )

    macro = ranked.assign(macro_stage=ranked["stage"].map(C.STAGE_TO_MACRO))
    macro = macro.groupby("macro_stage", sort=False)["score"].sum().sort_values(ascending=False)
    total = float(macro.sum())
    times = costs.macro_stage_summary(
        costs.derive(result["events"]), result["horizon_hours"], result["config"])
    print("\nM2 MACRO-STAGE RANKING")
    for i, (name, score) in enumerate(macro.items(), start=1):
        row = times.loc[name]
        print("  #%d %-22s contribution %5.1f%% | elapsed %8s | queued %8s"
              % (i, name, 100 * score / total,
                 _fmt_hours(row["mean_duration"]), _fmt_hours(row["mean_wait"])))


def _investigation(result, reg):
    outcome = controller.investigate(
        result,
        reg,
        scenarios.DEMO_SCENARIO,
        inv_id="v2-demo-claims",
        persist_result=True,
    )
    conclusion = outcome["conclusion"]
    print("\nAGENT INVESTIGATION")
    print(
        "  conclusion: %s / %s at p=%.2f"
        % (
            conclusion["concluded_stage"],
            conclusion["concluded_cause"],
            float(conclusion["confidence"]),
        )
    )
    print("  stop: %s" % conclusion["stop_reason"])
    print("  probes used: %d" % int(conclusion["probes_used"]))

    for node in outcome["nodes"]:
        print("  - %s -> %s" % (node.target, node.reasoning))

    print("\nM5/M6 INTERVENTIONS")
    for candidate in outcome["candidates"]:
        mark = "[x]" if candidate.get("selected") else "[ ]"
        print(
            "  %s %-28s cost %-10s delta %-8s CI [%s, %s] ROI %.2f"
            % (
                mark,
                candidate["action"],
                _money(candidate["cost_30d"]),
                _fmt_hours(candidate["delta_hours"]),
                _fmt_hours(candidate["ci_low"]),
                _fmt_hours(candidate["ci_high"]),
                float(candidate["roi"]),
            )
        )
    return outcome


def _apply_selected(result, reg, outcome):
    picked = [c for c in outcome["candidates"] if c.get("selected")]
    if not picked:
        print("\nPOST-INTERVENTION")
        print("  No ROI-positive intervention was selected.")
        return

    actions = [c["action"] for c in picked]
    before = costs.run_kpis(result["events"], result["config"]["horizon_days"])
    child, after = controller.apply_intervention(
        result,
        reg,
        actions,
        run_id="v2_after_selected",
        parent_run_id=scenarios.DEMO_SCENARIO,
        label="ProcessX v2 after selected claims intervention",
        refit=False,
    )
    ranked_after = reg.ranking(child)

    print("\nPOST-INTERVENTION")
    print("  applied: %s" % ", ".join(actions))
    print(
        "  mean cycle: %s -> %s (delta %s)"
        % (
            _fmt_hours(before["mean_cycle_hours"]),
            _fmt_hours(after["mean_cycle_hours"]),
            _fmt_hours(before["mean_cycle_hours"] - after["mean_cycle_hours"]),
        )
    )
    print(
        "  cost per case: %s -> %s"
        % (_money(before["cost_per_case"]), _money(after["cost_per_case"]))
    )
    top = ranked_after.iloc[0]
    print(
        "  next highest-ranked activity: %s (%s), contribution %.1f%%"
        % (top["stage"], C.macro_stage_for(top["stage"]), float(top["contribution_pct"]))
    )


def main():
    print("ProcessX v2 backend demo")
    print("Full lifecycle: %s" % " -> ".join(C.MACRO_STAGES))

    print("\n1/5 reset and simulate lifecycle worlds")
    db.reset()
    healthy = engine.simulate(scenarios.healthy_config())
    current = engine.simulate(scenarios.scenario_config(scenarios.DEMO_SCENARIO))

    healthy_kpis = _write(healthy, "baseline", "healthy")
    current_kpis = _write(current, scenarios.DEMO_SCENARIO, scenarios.DEMO_SCENARIO,
                          parent="baseline")
    print(
        "  baseline:          %d cases | %d events | cycle %s"
        % (healthy_kpis["n_cases"], len(healthy["events"]),
           _fmt_hours(healthy_kpis["mean_cycle_hours"]))
    )
    print(
        "  claims bottleneck: %d cases | %d events | cycle %s"
        % (current_kpis["n_cases"], len(current["events"]),
           _fmt_hours(current_kpis["mean_cycle_hours"]))
    )
    print("  training data covers %d activities across %d macro-stages"
          % (len(C.STAGES), len(C.MACRO_STAGES)))

    print("\n2/5 train M1-M4 on the full lifecycle data")
    reg = registry.Registry().train(current, healthy, verbose=False)

    # Scored on every fault scenario, not just the one the demo narrates. The
    # other two sit in different macro-stages and carry a different cause, and
    # their stages are absent from M4's training corpus.
    worlds = {scenarios.DEMO_SCENARIO: current}
    for name in scenarios.EVALUATION_SCENARIOS:
        if name != scenarios.DEMO_SCENARIO:
            worlds[name] = engine.simulate(scenarios.scenario_config(name))
    cards = reg.metric_cards(registry.evaluation_spec(worlds))
    reg.save()
    _print_cards(cards)
    print("  scored on: %s" % ", ".join(worlds))

    print("\n3/5 show one case moving through the full process")
    _single_case_flow(current)

    print("\n4/5 detect and diagnose the bottleneck")
    _rankings(current, reg)
    outcome = _investigation(current, reg)

    print("\n5/5 apply selected intervention and rescore")
    _apply_selected(current, reg, outcome)

    print("\nDemo complete. The frontend is not required for this flow.")


if __name__ == "__main__":
    main()
