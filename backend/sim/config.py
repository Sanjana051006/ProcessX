"""Simulator constants and the intervention catalogue.

Everything here is frozen in docs/Status.md §A4 (stages), §A6 (catalogue) and
§A7 (ROI). One deviation from §A4 is logged in Status §C: `last_mile` servers.
"""

import copy

MASTER_SEED = 42
HORIZON_DAYS = 30

STAGES = [
    "order_validation",
    "inventory_allocation",
    "pick_pack",
    "carrier_handover",
    "last_mile",
]

# ---------------------------------------------------------------- arrivals ---
# t = 0 is Monday 00:00. Time is measured in hours throughout.
ARRIVAL_MEAN_PER_HOUR = 11.0
WEEKEND_MULTIPLIER = 1.6
EVENING_PEAK = 1.4

# Relative intensity by hour of day. The daytime plateau is 1.0 and the evening
# block (18:00-21:59) is EVENING_PEAK x that plateau. The full weekday x hour
# grid is renormalised in the engine so the overall mean is
# ARRIVAL_MEAN_PER_HOUR -- that is what puts the 30-day horizon at ~8k cases.
HOUR_PROFILE = [
    0.30, 0.22, 0.18, 0.18, 0.25, 0.45,   # 00-05
    0.70, 0.95, 1.00, 1.00, 1.00, 1.00,   # 06-11
    1.00, 1.00, 1.00, 1.00, 1.00, 1.10,   # 12-17
    EVENING_PEAK, EVENING_PEAK, EVENING_PEAK, EVENING_PEAK,  # 18-21
    0.90, 0.50,                           # 22-23
]

ARRIVALS = {
    "mean_per_hour": ARRIVAL_MEAN_PER_HOUR,
    "weekend_multiplier": WEEKEND_MULTIPLIER,
    "evening_peak": EVENING_PEAK,
    "hour_profile": HOUR_PROFILE,
}

# ------------------------------------------------------ case attributes ------
# Calibrated so that the auto_approve_low_risk predicate (< Rs 8k AND risk < 0.2)
# covers ~60% of cases, which is the -60% manual-review effect frozen in §A6.
ORDER_VALUE_MEDIAN = 4000.0
ORDER_VALUE_SIGMA = 0.7
FRAUD_RISK_BETA = (1.2, 6.8)
NEW_CUSTOMER_RATE = 0.28
CUSTOMER_TIERS = (("standard", 0.65), ("plus", 0.25), ("premium", 0.10))
REGIONS = (("north", 0.24), ("south", 0.26), ("east", 0.16), ("west", 0.22), ("central", 0.12))
ITEM_CATEGORIES = (
    ("electronics", 0.22), ("apparel", 0.26), ("home", 0.18),
    ("grocery", 0.16), ("beauty", 0.10), ("sports", 0.08),
)

# Share of orders the legacy rule flags for manual review. The rule is crude and
# largely uncorrelated with actual risk -- which is exactly why auto-approving
# genuinely low-risk small orders removes most of the volume.
MANUAL_REVIEW_RATE = 0.35

# ---------------------------------------------------------------- stages -----
# servers / mean service per §A4. `weekend_servers` defaults to `servers`.
#
# DEVIATION (Status §C): §A4 lists last_mile with 40 servers. At 11 cases/hour
# and a 14 h mean service the offered load is 11 x 14 = 154 erlangs, so 40
# servers is ~3.9x over capacity and last_mile would be an unbounded queue --
# the opposite of §A4's own note, which requires it to be the longest stage but
# NOT a bottleneck (it is the stage the fixed-rule baseline wrongly picks).
# 360 servers gives mean utilisation 154/360 = 0.43 and ~0.79 at the weekend
# peak: longest duration, negligible queue. Every other stage's §A4 number is
# arithmetically consistent and is used unchanged.
STAGE_DEFS = {
    "order_validation":     {"servers": 3,   "weekend_servers": 3, "mean_service_min": 25,      "sigma": 0.50, "manual_review": True},
    "inventory_allocation": {"servers": 6,                          "mean_service_min": 8,       "sigma": 0.50},
    "pick_pack":            {"servers": 5,                          "mean_service_min": 22,      "sigma": 0.50},
    "carrier_handover":     {"servers": 4,                          "mean_service_min": 6,       "sigma": 0.50},
    "last_mile":            {"servers": 360,                        "mean_service_min": 14 * 60, "sigma": 0.35},
}

# ----------------------------------------------------- intervention catalogue -
# §A6, 5 actions. `effect` is a patch applied to the stage's config -- the
# simulator then produces the outcome causally; no effect size is hard-coded.
CATALOGUE = {
    "auto_approve_low_risk": {
        "stage": "order_validation", "cost": 40_000, "cost_type": "one_time",
        "label": "Auto-approve low-risk orders (< Rs 8k, risk < 0.2)",
        "effect": {"auto_approve": {"max_value": 8000.0, "max_risk": 0.2}},
    },
    "add_reviewers_2": {
        "stage": "order_validation", "cost": 180_000, "cost_type": "monthly",
        "label": "Hire 2 more manual reviewers",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "weekend_shift_reallocation": {
        "stage": "order_validation", "cost": 25_000, "cost_type": "monthly",
        "label": "Move existing reviewer capacity into the weekend peak",
        "effect": {"servers_delta": -1, "weekend_servers_delta": 2},
    },
    "add_evening_shift": {
        "stage": "pick_pack", "cost": 150_000, "cost_type": "monthly",
        "label": "Add a 6-hour evening pick/pack shift (+40% capacity)",
        "effect": {"shift_boost": {"hours": [16, 17, 18, 19, 20, 21], "factor": 1.4}},
    },
    "batch_route_optimisation": {
        "stage": "pick_pack", "cost": 60_000, "cost_type": "one_time",
        "label": "Batch/route optimisation (-15% service time)",
        "effect": {"service_factor": 0.85},
    },
}

# ------------------------------------------------------------ ROI (§A7) ------
HOLDING_COST_PER_HOUR = 12      # Rs per case-hour of cycle time
SLA_THRESHOLD_HOURS = 48
SLA_PENALTY_PER_CASE = 250      # Rs per breached case
CASES_PER_DAY = 270             # 8000 / 30
ROI_HORIZON_DAYS = 30
BUDGET_CAP = 250_000            # §A8


def base_config(label="baseline", horizon_days=HORIZON_DAYS):
    """A fresh, healthy world configuration."""
    return {
        "label": label,
        "horizon_days": horizon_days,
        "arrivals": copy.deepcopy(ARRIVALS),
        "stages": copy.deepcopy(STAGE_DEFS),
        "interventions_applied": [],
    }


def apply_action(config, action_name):
    """Return a copy of `config` with one catalogue action applied.

    Effects are config patches, so a counterfactual differs from its parent only
    in capacity/routing -- never in the arrival stream. That is what makes the
    M5 delta attributable to the intervention (§A4).
    """
    if action_name not in CATALOGUE:
        raise KeyError(f"unknown action: {action_name}")
    cfg = copy.deepcopy(config)
    action = CATALOGUE[action_name]
    stage = cfg["stages"][action["stage"]]

    for key, value in action["effect"].items():
        if key == "servers_delta":
            stage["servers"] = max(1, stage["servers"] + value)
        elif key == "weekend_servers_delta":
            current = stage.get("weekend_servers", stage["servers"])
            stage["weekend_servers"] = max(1, current + value)
        elif key == "service_factor":
            stage["service_factor"] = stage.get("service_factor", 1.0) * value
        elif key == "shift_boost":
            stage["shift_boost"] = copy.deepcopy(value)
        elif key == "auto_approve":
            stage["auto_approve"] = copy.deepcopy(value)
        else:
            raise KeyError(f"unknown effect key: {key}")

    cfg["interventions_applied"] = list(cfg["interventions_applied"]) + [action_name]
    return cfg


def apply_actions(config, action_names):
    for name in action_names:
        config = apply_action(config, name)
    return config


def action_cost_30d(action_name):
    """Cost over the 30-day ROI horizon. One-time costs are charged in full."""
    return float(CATALOGUE[action_name]["cost"])
