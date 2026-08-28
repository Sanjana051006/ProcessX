"""M5 -- intervention-impact prediction by counterfactual simulation (§A5).

Not a regression on past interventions -- there are none to learn from. Instead
the world is re-run with capacity or routing changed and the difference is
measured. That is the only honest way to answer "what if we add a reviewer",
which is what FR-5 asks for.

Three seed replicates (42, 43, 44), cut from 5 in §A10. The replicates are
PAIRED: for a given seed the baseline and the counterfactual share an identical
arrival stream, identical case attributes and identical per-(case,stage) service
shocks, because all three come from a seed-only RNG stream (P1.4). The delta is
therefore attributable to the intervention rather than to sampling noise, and
the interval is narrow even at n = 3.
"""

import math

import numpy as np

from backend.sim import config as C, costs, engine

SEEDS = (42, 43, 44)

# Student t, 95%, 2 degrees of freedom. n = 3 is small enough that the normal
# approximation would understate the interval by more than a factor of two.
_T_95_DF2 = 4.302652729911275


def _kpis(result):
    return costs.run_kpis(result["events"], result["config"]["horizon_days"])


def _interval(values):
    """Mean and 95% CI over the seed replicates."""
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if len(arr) < 2:
        return mean, mean, mean
    sd = float(arr.std(ddof=1))
    half = _T_95_DF2 * sd / math.sqrt(len(arr))
    return mean, mean - half, mean + half


def baseline_replicates(config, seeds=SEEDS):
    """KPIs for the unchanged world, one per seed. Cached across actions --
    every candidate is compared against the same three baselines."""
    return {seed: _kpis(engine.simulate(config, seed=seed)) for seed in seeds}


def evaluate_action(config, action, seeds=SEEDS, baselines=None):
    """P3.3 -- returns delta_hours with a CI, plus the SLA movement M6 needs.

    Positive delta = improvement (cycle time went down).
    """
    return evaluate_bundle(config, [action], seeds=seeds, baselines=baselines)


def evaluate_bundle(config, actions, seeds=SEEDS, baselines=None):
    """Same measurement for a set of actions applied together.

    Bundles are simulated, never summed: two capacity changes on one stage
    interact, and a second fix applied after the first has a smaller marginal
    effect. Adding the individual deltas would overstate the pair.
    """
    baselines = baselines or baseline_replicates(config, seeds)
    actions = list(actions)

    d_cycle, d_sla, d_cost, d_p90 = [], [], [], []
    for seed in seeds:
        after = _kpis(engine.simulate(config, overrides=actions, seed=seed))
        before = baselines[seed]
        d_cycle.append(before["mean_cycle_hours"] - after["mean_cycle_hours"])
        d_p90.append(before["p90_cycle_hours"] - after["p90_cycle_hours"])
        d_sla.append(before["sla_breach_rate"] - after["sla_breach_rate"])
        d_cost.append(before["cost_per_case"] - after["cost_per_case"])

    mean, lo, hi = _interval(d_cycle)
    stages = sorted({C.CATALOGUE[a]["stage"] for a in actions})
    return {
        "actions": actions,
        "action": actions[0] if len(actions) == 1 else " + ".join(actions),
        "stage": stages[0] if len(stages) == 1 else "multi",
        "cost": sum(C.action_cost_30d(a) for a in actions),
        "delta_hours": mean,
        "ci_low": lo,
        "ci_high": hi,
        "delta_p90_hours": _interval(d_p90)[0],
        "delta_sla_rate": _interval(d_sla)[0],
        "delta_cost_per_case": _interval(d_cost)[0],
        "per_seed_delta": [float(x) for x in d_cycle],
        "n_replicates": len(seeds),
        "significant": lo > 0,
    }


def evaluate_catalogue(config, stage=None, seeds=SEEDS, baselines=None):
    """Every catalogue action, optionally restricted to one stage. This is what
    the agent calls once it has concluded where the bottleneck is."""
    baselines = baselines or baseline_replicates(config, seeds)
    actions = [a for a, spec in C.CATALOGUE.items()
               if stage is None or spec["stage"] == stage]
    return [evaluate_action(config, a, seeds, baselines) for a in actions]
