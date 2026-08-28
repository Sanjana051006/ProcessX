"""ProcessX v2 scenario definitions.

The demo scenario is lifecycle-wide: after onboarding and fulfilment, claims
evidence review becomes the constraint. The models still train on the full
event log, not on a hand-picked sample of the claims stage.

Two further fault scenarios exist so the metric cards are scored on more than
the one fault the demo tells a story about. They sit in different macro-stages
and carry different causes, and both of their stages are absent from M4's
training corpus, so they are genuinely held out.
"""

from backend.sim import config as C

# Reviewers on `evidence_review` once the constraint bites. The healthy roster
# is 5, which leaves the stage at utilisation 0.67. Four reviewers put it at
# 0.84 -- heavily loaded and by far the worst stage in the lifecycle, but still
# a queue that drains. Three would put offered load at 1.12, i.e. an unbounded
# queue whose every metric is a function of how long you let it run rather than
# of the constraint itself.
CLAIMS_EVIDENCE_SERVERS = 4

# The hour a constraint starts. A run opens on the healthy roster and switches
# at this instant, so the timestamp is a real event in the data and M3's
# detection lead time is measured against something that happened.
INJECTED_AT_HOURS = 24.0

# t = 0 is Monday 00:00, so the first weekend hour is the start of day 5. A
# weekend-only fault has that as its onset.
FIRST_WEEKEND_HOUR = 5 * 24.0


def _with_onset(stage_cfg, servers, weekend_servers, at_hours):
    """Switch a stage onto a smaller roster at `at_hours`, keeping the roster it
    ran before so the change is an event in the log rather than a global truth."""
    stage_cfg["capacity_onset"] = {
        "at_hours": at_hours,
        "before": {
            "servers": stage_cfg["servers"],
            "weekend_servers": stage_cfg.get("weekend_servers", stage_cfg["servers"]),
        },
    }
    stage_cfg["servers"] = servers
    stage_cfg["weekend_servers"] = weekend_servers
    return stage_cfg


def healthy_config(horizon_days=C.HORIZON_DAYS):
    return C.base_config(label="ProcessX v2 healthy lifecycle", horizon_days=horizon_days)


def claims_bottleneck_config(horizon_days=C.HORIZON_DAYS):
    """The demo world: claims evidence review loses a reviewer at hour 24."""
    cfg = C.base_config(label="ProcessX v2 claims bottleneck", horizon_days=horizon_days)
    _with_onset(cfg["stages"]["evidence_review"],
                CLAIMS_EVIDENCE_SERVERS, CLAIMS_EVIDENCE_SERVERS, INJECTED_AT_HOURS)
    cfg["scenario"] = "claims_bottleneck"
    return cfg


def support_staffing_config(horizon_days=C.HORIZON_DAYS):
    """Evaluation world: support triage is understaffed at the weekend only.

    The roster is intact Monday to Friday and collapses to one agent when the
    weekend arrival peak lands, which is the staffing_shortage signature --
    capacity below the stage's own normal roster for part of the week.
    """
    cfg = C.base_config(label="ProcessX v2 support staffing shortage",
                        horizon_days=horizon_days)
    cfg["stages"]["ticket_triage"]["weekend_servers"] = 1
    cfg["scenario"] = "support_staffing"
    return cfg


def fulfilment_saturation_config(horizon_days=C.HORIZON_DAYS):
    """Evaluation world: inventory allocation is cut to a roster that is simply
    too small, all week, from hour 24. Constant and insufficient, which is the
    capacity_saturation signature."""
    cfg = C.base_config(label="ProcessX v2 fulfilment saturation",
                        horizon_days=horizon_days)
    _with_onset(cfg["stages"]["inventory_allocation"], 2, 2, INJECTED_AT_HOURS)
    cfg["scenario"] = "fulfilment_saturation"
    return cfg


# name -> (builder, bottleneck stage, true cause, onset hour or None)
SCENARIOS = {
    "healthy": (healthy_config, None, "normal", None),
    "claims_bottleneck": (
        claims_bottleneck_config, "evidence_review", "capacity_saturation",
        INJECTED_AT_HOURS),
    "support_staffing": (
        support_staffing_config, "ticket_triage", "staffing_shortage",
        FIRST_WEEKEND_HOUR),
    "fulfilment_saturation": (
        fulfilment_saturation_config, "inventory_allocation", "capacity_saturation",
        INJECTED_AT_HOURS),
}

# The world the demo tells its story about.
DEMO_SCENARIO = "claims_bottleneck"

# Every fault scenario the metric cards are scored on.
EVALUATION_SCENARIOS = [n for n in SCENARIOS if n != "healthy"]

GROUND_TRUTH = {
    name: {"bottleneck_stage": stage, "true_cause": cause}
    for name, (_, stage, cause, _) in SCENARIOS.items()
}


def scenario_config(name, horizon_days=C.HORIZON_DAYS):
    if name not in SCENARIOS:
        raise KeyError("unknown scenario: " + str(name))
    return SCENARIOS[name][0](horizon_days)


def ground_truth_for(name):
    if name not in GROUND_TRUTH:
        raise KeyError("no ground truth for scenario: " + str(name))
    return GROUND_TRUTH[name]


def injected_at(name):
    """The hour the fault starts, or None for a world with no injected fault."""
    if name not in SCENARIOS:
        raise KeyError("unknown scenario: " + str(name))
    return SCENARIOS[name][3]


def label_for(name):
    return scenario_config(name)["label"]
