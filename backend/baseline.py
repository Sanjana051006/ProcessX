"""The fixed-rule comparator (P7.1).

    Pick the stage with the highest mean duration, then buy the cheapest
    catalogue action for that stage.

This is the rule a competent team writes without any of M1-M6, and it is what
the agent has to beat. Under bottleneck A it picks `last_mile` -- 14 h of mean
duration, a 0.0000 h queue, and nothing wrong with it.

Two variants are computed, because the strict rule can be accused of being a
straw man:

* `strict`      -- the rule as written. `last_mile` has no catalogue action
                   (§A6 cut `secondary_carrier`), so it recommends nothing.
* `fallthrough` -- the charitable repair: skip to the highest-duration stage
                   that does have an action. This is a genuinely stronger
                   opponent and is reported alongside, so the comparison is not
                   won by the catalogue's shape.

Neither variant looks at queueing, utilisation or cause. That is the whole
difference: duration is what a stage *takes*, not what it *costs you*.
"""

from backend.models import m5_impact as m5, m6_roi as m6
from backend.sim import config as C, costs


def _actions_for(stage):
    return [name for name, spec in C.CATALOGUE.items() if spec["stage"] == stage]


def rank_by_duration(events, horizon_hours, config=None):
    """The rule's view of the world: stages ordered by mean duration."""
    summary = costs.stage_summary(events, horizon_hours, config)
    return summary.sort_values("mean_duration", ascending=False)


def decide(events, horizon_hours, config=None):
    """Return both variants of the fixed-rule decision."""
    ordered = rank_by_duration(events, horizon_hours, config)
    stages = list(ordered.index)

    strict_stage = stages[0]
    strict_actions = _actions_for(strict_stage)
    strict_action = min(strict_actions, key=C.action_cost_30d) if strict_actions else None

    fall_stage, fall_action = None, None
    for stage in stages:
        options = _actions_for(stage)
        if options:
            fall_stage = stage
            fall_action = min(options, key=C.action_cost_30d)
            break

    return {
        "ranked_by_duration": [
            {"stage": s, "mean_duration_hours": float(ordered.loc[s, "mean_duration"]),
             "mean_wait_hours": float(ordered.loc[s, "mean_wait"]),
             "has_action": bool(_actions_for(s))}
            for s in stages
        ],
        "strict": {"stage": strict_stage, "action": strict_action},
        "fallthrough": {"stage": fall_stage, "action": fall_action},
    }


def evaluate(result, seeds=m5.SEEDS, baselines=None):
    """Price the fixed rule's choice the same way the agent's is priced."""
    events = costs.derive(result["events"])
    decision = decide(events, result["horizon_hours"], result["config"])
    baselines = baselines or m5.baseline_replicates(result["config"], seeds)

    def price(action):
        if action is None:
            return None
        impact = m5.evaluate_action(result["config"], action, seeds, baselines)
        return m6.score(impact)

    strict = price(decision["strict"]["action"])
    fall = price(decision["fallthrough"]["action"])

    decision["strict"]["scored"] = strict
    decision["fallthrough"]["scored"] = fall
    decision["strict"]["reason"] = (
        "Highest mean duration is %s at %.2f h. No intervention exists for that "
        "stage, so the rule has nothing to buy."
        % (decision["strict"]["stage"],
           decision["ranked_by_duration"][0]["mean_duration_hours"])
        if strict is None else
        "Highest mean duration is %s; cheapest action there is %s."
        % (decision["strict"]["stage"], decision["strict"]["action"]))
    decision["fallthrough"]["reason"] = (
        "Skipping stages with no available action, the longest remaining is %s; "
        "cheapest action there is %s."
        % (decision["fallthrough"]["stage"], decision["fallthrough"]["action"])
        if fall else "No stage has an available action.")
    return decision


def summarise(decision, variant="strict"):
    """Flatten one variant into the row `baseline_decisions` stores."""
    chosen = decision[variant]
    scored = chosen.get("scored")
    return {
        "chosen_stage": chosen["stage"],
        "chosen_action": chosen["action"],
        "cost": float(scored["cost_30d"]) if scored else 0.0,
        "roi": float(scored["roi"]) if scored else 0.0,
        "benefit_30d": float(scored["benefit_30d"]) if scored else 0.0,
        "delta_hours": float(scored["delta_hours"]) if scored else 0.0,
        "net_benefit": float(scored["benefit_30d"] - scored["cost_30d"]) if scored else 0.0,
        "reason": chosen["reason"],
    }
