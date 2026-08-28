"""Scenario definitions: the healthy world and the bottleneck-A injection.

Bottleneck B is deliberately *not* defined here. It is latent in the healthy
sizing of pick_pack and emerges only once order_validation stops throttling
weekend throughput (Status §A1, §C). There is no "inject B" code path -- if
there were, the cascade would prove nothing.
"""

from backend.sim import config as C

# The scenario the whole demo runs on. Bottleneck A is a staffing shortage:
# weekend manual-review capacity drops 3 -> 1 (§A1).
BOTTLENECK_A_WEEKEND_SERVERS = 1

GROUND_TRUTH = {
    "healthy": {"bottleneck_stage": None, "true_cause": "normal"},
    "bottleneck_a": {
        "bottleneck_stage": "order_validation",
        "true_cause": "staffing_shortage",
    },
    # Recorded only when a run is produced by fixing A. The label is what the
    # agent must independently rediscover at P4.8.
    "cascade_b": {
        "bottleneck_stage": "pick_pack",
        "true_cause": "capacity_saturation",
    },
}

# When the injection starts biting. Day 5 is the first Saturday (t = 0 is a
# Monday), so this is the first hour at which reduced weekend capacity is real.
INJECTED_AT_HOURS = 5 * 24.0


def healthy_config(horizon_days=C.HORIZON_DAYS):
    """P1.6 -- the healthy baseline. 30 days, ~8k cases."""
    return C.base_config(label="baseline", horizon_days=horizon_days)


def bottleneck_a_config(horizon_days=C.HORIZON_DAYS):
    """P1.7 -- weekend reviewer capacity 3 -> 1.

    Weekend review demand is ~2.6 erlangs, so 3 reviewers absorb it (util 0.86)
    while 1 reviewer cannot -- the queue builds every weekend and drains during
    the week. That recurring signature is what makes weekday concentration a
    discriminating M4 feature.
    """
    cfg = C.base_config(label="bottleneck_a", horizon_days=horizon_days)
    cfg["stages"]["order_validation"]["weekend_servers"] = BOTTLENECK_A_WEEKEND_SERVERS
    cfg["scenario"] = "bottleneck_a"
    return cfg


def scenario_config(name, horizon_days=C.HORIZON_DAYS):
    if name == "healthy":
        return healthy_config(horizon_days)
    if name == "bottleneck_a":
        return bottleneck_a_config(horizon_days)
    raise KeyError("unknown scenario: " + str(name))


def ground_truth_for(scenario):
    return GROUND_TRUTH[scenario]
