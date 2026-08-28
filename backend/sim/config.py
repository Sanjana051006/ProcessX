"""ProcessX v2 simulator constants and intervention catalogue.

The simulator still treats each activity as a `stage`, but v2 adds a
`macro_stage` grouping so the same M1-M6 stack can reason over the whole
business lifecycle:

    onboarding -> order processing -> claims -> support -> invoice approval
"""

import copy

MASTER_SEED = 42
HORIZON_DAYS = 7

MACRO_STAGES = [
    "customer_onboarding",
    "order_processing",
    "claims_processing",
    "support_resolution",
    "invoice_approval",
]

STAGE_GROUPS = [
    (
        "customer_onboarding",
        [
            "account_creation",
            "document_verification",
            "risk_screening",
            "account_activation",
        ],
    ),
    (
        "order_processing",
        [
            "order_validation",
            "inventory_allocation",
            "pick_pack",
            "carrier_handover",
            "last_mile",
        ],
    ),
    (
        "claims_processing",
        [
            "claim_intake",
            "eligibility_check",
            "evidence_review",
            "settlement_decision",
            "payout_or_replacement",
        ],
    ),
    (
        "support_resolution",
        [
            "ticket_triage",
            "agent_assignment",
            "investigation",
            "customer_response",
            "closure",
        ],
    ),
    (
        "invoice_approval",
        [
            "invoice_capture",
            "three_way_match",
            "exception_review",
            "manager_approval",
            "payment_release",
        ],
    ),
]

STAGES = [stage for _, stages in STAGE_GROUPS for stage in stages]
STAGE_TO_MACRO = {
    stage: macro for macro, stages in STAGE_GROUPS for stage in stages
}

# ---------------------------------------------------------------- arrivals ---
# t = 0 is Monday 00:00. Time is measured in hours throughout.
ARRIVAL_MEAN_PER_HOUR = 11.0
WEEKEND_MULTIPLIER = 1.6
EVENING_PEAK = 1.4

HOUR_PROFILE = [
    0.30, 0.22, 0.18, 0.18, 0.25, 0.45,
    0.70, 0.95, 1.00, 1.00, 1.00, 1.00,
    1.00, 1.00, 1.00, 1.00, 1.00, 1.10,
    EVENING_PEAK, EVENING_PEAK, EVENING_PEAK, EVENING_PEAK,
    0.90, 0.50,
]

ARRIVALS = {
    "mean_per_hour": ARRIVAL_MEAN_PER_HOUR,
    "weekend_multiplier": WEEKEND_MULTIPLIER,
    "evening_peak": EVENING_PEAK,
    "hour_profile": HOUR_PROFILE,
}

# ------------------------------------------------------ case attributes ------
ORDER_VALUE_MEDIAN = 4000.0
ORDER_VALUE_SIGMA = 0.7
FRAUD_RISK_BETA = (1.2, 6.8)
NEW_CUSTOMER_RATE = 0.28
MANUAL_REVIEW_RATE = 0.35

CUSTOMER_TIERS = (("standard", 0.65), ("plus", 0.25), ("premium", 0.10))
REGIONS = (
    ("north", 0.24),
    ("south", 0.26),
    ("east", 0.16),
    ("west", 0.22),
    ("central", 0.12),
)
ITEM_CATEGORIES = (
    ("electronics", 0.22),
    ("apparel", 0.26),
    ("home", 0.18),
    ("grocery", 0.16),
    ("beauty", 0.10),
    ("sports", 0.08),
)
CUSTOMER_SEGMENTS = (
    ("smb", 0.58),
    ("enterprise", 0.18),
    ("marketplace_seller", 0.24),
)
PRIORITIES = (("standard", 0.78), ("expedited", 0.16), ("vip", 0.06))
CLAIM_TYPES = (
    ("damaged", 0.28),
    ("missing_item", 0.24),
    ("late_delivery", 0.30),
    ("billing_dispute", 0.18),
)
SUPPORT_CHANNELS = (("email", 0.46), ("chat", 0.34), ("phone", 0.20))
INVOICE_EXCEPTION_REASONS = (
    ("none", 0.68),
    ("price_mismatch", 0.12),
    ("quantity_mismatch", 0.09),
    ("tax_code", 0.06),
    ("missing_po", 0.05),
)

PRIORITY_SCORE = {"standard": 0.0, "expedited": 0.5, "vip": 1.0}

# ---------------------------------------------------------------- stages -----
# Capacity is sized so the healthy run is stable across all 24 activities.
# The v2 scenario deliberately constrains evidence_review.
STAGE_DEFS = {
    "account_creation": {"servers": 4, "mean_service_min": 5, "sigma": 0.45},
    # 6, not 5: at 5 this stage sits at wait/service 1.5 with nothing wrong,
    # which M4 reads as saturation on the healthy baseline itself.
    "document_verification": {"servers": 6, "mean_service_min": 18, "sigma": 0.55},
    "risk_screening": {"servers": 4, "mean_service_min": 10, "sigma": 0.50},
    "account_activation": {"servers": 3, "mean_service_min": 4, "sigma": 0.45},

    "order_validation": {
        "servers": 3,
        "weekend_servers": 3,
        "mean_service_min": 25,
        "sigma": 0.50,
        "manual_review": True,
    },
    "inventory_allocation": {"servers": 6, "mean_service_min": 8, "sigma": 0.50},
    # 7. At 5 this stage carries a wait/service ratio of 3.3 in a world with
    # nothing injected, which M4 reads as saturation on the healthy baseline
    # itself and the agent then spends probes on.
    "pick_pack": {"servers": 7, "mean_service_min": 22, "sigma": 0.50},
    "carrier_handover": {"servers": 4, "mean_service_min": 6, "sigma": 0.50},
    # Longest elapsed activity, but not the bottleneck: it has enough parallel
    # carrier capacity to avoid a queue.
    "last_mile": {"servers": 360, "mean_service_min": 14 * 60, "sigma": 0.35},

    "claim_intake": {"servers": 4, "mean_service_min": 7, "sigma": 0.45},
    "eligibility_check": {"servers": 4, "mean_service_min": 12, "sigma": 0.50},
    "evidence_review": {"servers": 5, "mean_service_min": 18, "sigma": 0.55},
    "settlement_decision": {"servers": 4, "mean_service_min": 10, "sigma": 0.50},
    "payout_or_replacement": {"servers": 4, "mean_service_min": 8, "sigma": 0.45},

    "ticket_triage": {"servers": 4, "mean_service_min": 5, "sigma": 0.45},
    "agent_assignment": {"servers": 4, "mean_service_min": 4, "sigma": 0.45},
    "investigation": {"servers": 5, "mean_service_min": 15, "sigma": 0.55},
    "customer_response": {"servers": 4, "mean_service_min": 8, "sigma": 0.50},
    "closure": {"servers": 3, "mean_service_min": 3, "sigma": 0.40},

    "invoice_capture": {"servers": 4, "mean_service_min": 5, "sigma": 0.45},
    "three_way_match": {"servers": 5, "mean_service_min": 8, "sigma": 0.50},
    "exception_review": {"servers": 5, "mean_service_min": 16, "sigma": 0.55},
    "manager_approval": {"servers": 4, "mean_service_min": 12, "sigma": 0.50},
    "payment_release": {"servers": 4, "mean_service_min": 4, "sigma": 0.45},
}

# ----------------------------------------------------- intervention catalogue
CATALOGUE = {
    "auto_verify_low_risk_documents": {
        "stage": "document_verification",
        "cost": 55_000,
        "cost_type": "one_time",
        "label": "Auto-verify low-risk onboarding documents",
        "effect": {"service_factor": 0.82},
    },
    "add_kyc_reviewer_shift": {
        "stage": "document_verification",
        "cost": 110_000,
        "cost_type": "monthly",
        "label": "Add KYC reviewer shift",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "auto_approve_low_risk": {
        "stage": "order_validation",
        "cost": 40_000,
        "cost_type": "one_time",
        "label": "Auto-approve low-risk orders (< Rs 8k, risk < 0.2)",
        "effect": {"auto_approve": {"max_value": 8000.0, "max_risk": 0.2}},
    },
    "add_reviewers_2": {
        "stage": "order_validation",
        "cost": 180_000,
        "cost_type": "monthly",
        "label": "Hire 2 more manual reviewers",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "weekend_shift_reallocation": {
        "stage": "order_validation",
        "cost": 25_000,
        "cost_type": "monthly",
        "label": "Move reviewer capacity into the weekend peak",
        "effect": {"servers_delta": -1, "weekend_servers_delta": 2},
    },
    "add_evening_shift": {
        "stage": "pick_pack",
        "cost": 150_000,
        "cost_type": "monthly",
        "label": "Add a 6-hour evening pick/pack shift",
        "effect": {"shift_boost": {"hours": [16, 17, 18, 19, 20, 21], "factor": 1.4}},
    },
    "batch_route_optimisation": {
        "stage": "pick_pack",
        "cost": 60_000,
        "cost_type": "one_time",
        "label": "Batch/route optimisation for pick/pack",
        "effect": {"service_factor": 0.85},
    },
    "claims_evidence_precheck": {
        "stage": "evidence_review",
        "cost": 45_000,
        "cost_type": "one_time",
        "label": "Pre-check claim evidence packets before reviewer queue",
        "effect": {"service_factor": 0.78},
    },
    "add_claims_reviewers_2": {
        "stage": "evidence_review",
        "cost": 120_000,
        "cost_type": "monthly",
        "label": "Add 2 claims evidence reviewers",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "claim_fast_track_low_value": {
        "stage": "settlement_decision",
        "cost": 50_000,
        "cost_type": "one_time",
        "label": "Fast-track low-value claim settlement decisions",
        "effect": {"service_factor": 0.80},
    },
    "priority_auto_routing": {
        "stage": "ticket_triage",
        "cost": 35_000,
        "cost_type": "one_time",
        "label": "Auto-route priority support tickets",
        "effect": {"service_factor": 0.75},
    },
    "add_l2_agent_coverage": {
        "stage": "investigation",
        "cost": 95_000,
        "cost_type": "monthly",
        "label": "Add L2 support investigation coverage",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "auto_match_clean_invoices": {
        "stage": "three_way_match",
        "cost": 70_000,
        "cost_type": "one_time",
        "label": "Auto-match clean invoices",
        "effect": {"service_factor": 0.78},
    },
    "approval_delegate_pool": {
        "stage": "manager_approval",
        "cost": 80_000,
        "cost_type": "monthly",
        "label": "Add delegated month-end approval pool",
        "effect": {"servers_delta": 2, "weekend_servers_delta": 2},
    },
    "auto_approve_low_value_invoices": {
        "stage": "exception_review",
        "cost": 65_000,
        "cost_type": "one_time",
        "label": "Auto-approve low-value invoice exceptions",
        "effect": {"service_factor": 0.80},
    },
}

# ------------------------------------------------------------ ROI constants --
HOLDING_COST_PER_HOUR = 12
# 30 h, against a lifecycle whose mean is 18.3 h and p90 is 24.8 h. The 72 h
# this started at was above the WORST case in either world (max 56 h), so the
# penalty never fired: cost_per_case, sla_breach_rate and the SLA half of every
# ROI were all identically zero. At 30 h the healthy world breaches 2.8% and
# the constrained one 3.7%, so the term carries information.
SLA_THRESHOLD_HOURS = 30
SLA_PENALTY_PER_CASE = 250
CASES_PER_DAY = 270
ROI_HORIZON_DAYS = 30
BUDGET_CAP = 250_000


def macro_stage_for(stage):
    return STAGE_TO_MACRO[stage]


def base_config(label="baseline", horizon_days=HORIZON_DAYS):
    """A fresh, healthy ProcessX v2 lifecycle configuration."""
    return {
        "version": "ProcessX v2",
        "label": label,
        "horizon_days": horizon_days,
        "arrivals": copy.deepcopy(ARRIVALS),
        "macro_stages": copy.deepcopy(MACRO_STAGES),
        "stage_groups": copy.deepcopy(STAGE_GROUPS),
        "stages": copy.deepcopy(STAGE_DEFS),
        "interventions_applied": [],
    }


def apply_action(config, action_name):
    """Return a copy of `config` with one catalogue action applied."""
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
