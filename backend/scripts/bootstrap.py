"""Build the demo start state from nothing.

    .venv/Scripts/python -m backend.scripts.bootstrap      (Windows)
    .venv/bin/python -m backend.scripts.bootstrap          (macOS / Linux)

Drops and recreates the database, simulates the two worlds, trains M1-M4 and
writes the model artifacts. Safe to re-run at any time -- everything is keyed
off the master seed, so a second run reproduces the first exactly.

This is also what P8.3 wants: one command back to the demo start state.
"""

import argparse
import time

from backend import db
from backend.models import registry
from backend.sim import engine, persist, scenarios

RUNS = {
    "baseline": ("Healthy baseline", "healthy", None),
    "bottleneck_a": ("Bottleneck A injected", "bottleneck_a", "baseline"),
}


def bootstrap(train=True, verbose=True):
    t0 = time.time()

    def say(msg):
        if verbose:
            print(msg, flush=True)

    say("1/3  resetting the database ...")
    db.reset()
    say("     %s -> 8 tables, 5 indexes" % db.DB_PATH)

    say("2/3  simulating the worlds (seed %d) ..." % engine.C.MASTER_SEED)
    results, kpis = {}, {}
    for run_id, (label, scenario, parent) in RUNS.items():
        result = engine.simulate(scenarios.scenario_config(scenario))
        truth = dict(scenarios.ground_truth_for(scenario))
        truth["injected_at"] = (
            scenarios.INJECTED_AT_HOURS if scenario == "bottleneck_a" else None)
        kpi = persist.write_run(result, run_id, label=label,
                                parent_run_id=parent, ground_truth=truth)
        results[run_id] = result
        kpis[run_id] = kpi
        say("     %-13s %5d cases | cycle %6.2f h | Rs %6.1f/case | SLA breach %.2f%%"
            % (run_id, kpi["n_cases"], kpi["mean_cycle_hours"],
               kpi["cost_per_case"], 100 * kpi["sla_breach_rate"]))

    if not train:
        say("3/3  skipped model training (--no-train)")
        say("\ndone in %.1fs" % (time.time() - t0))
        return results, []

    say("3/3  training M1-M4 (this is the slow part, ~40s) ...")
    reg, cards, _ = registry.train_all(verbose=False)
    path = reg.save()
    say("     saved %s (%.1f MB)" % (path, path.stat().st_size / 1e6))

    say("\n     metric cards")
    for c in cards:
        say("     %-3s %-26s %-30s %s" % (c["model"], c["name"], c["display"],
                                          "PASS" if c["pass"] else "FAIL"))

    say("\ndone in %.1fs. Demo start state is ready." % (time.time() - t0))
    return results, cards


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-train", action="store_true",
                    help="database and runs only; skip the ~40s model fit")
    args = ap.parse_args()
    bootstrap(train=not args.no_train)
