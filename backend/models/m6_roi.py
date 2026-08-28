"""M6 -- benefit model and greedy budget selection.

    benefit_30d = delta_cycle_hours x cases_per_day x horizon_days
                  x holding_cost_per_hour
                + sla_penalty_avoided
    roi         = (benefit_30d - cost_30d) / cost_30d

Selection is greedy ROI-per-rupee under the budget cap. No OR-Tools -- with a
single budget and a handful of candidates per activity, greedy is optimal in
practice and can be explained in a sentence, which matters more here than the
last 1%.
"""

from backend.sim import config as C

CASE_MONTH = C.CASES_PER_DAY * C.ROI_HORIZON_DAYS   # cases in the ROI horizon


def benefit(delta_hours, delta_sla_rate=0.0):
    """Rupees saved over the 30-day horizon, split into its two terms."""
    holding = delta_hours * CASE_MONTH * C.HOLDING_COST_PER_HOUR
    sla_avoided = delta_sla_rate * CASE_MONTH * C.SLA_PENALTY_PER_CASE
    return holding + sla_avoided, holding, sla_avoided


def roi(benefit_30d, cost_30d):
    if cost_30d <= 0:
        return float("inf")
    return (benefit_30d - cost_30d) / cost_30d


def score(impact):
    """Attach the benefit model to one M5 impact record."""
    total, holding, sla_avoided = benefit(impact["delta_hours"], impact["delta_sla_rate"])
    cost = impact["cost"]
    out = dict(impact)
    out.update({
        "benefit_30d": total,
        "holding_benefit": holding,
        "sla_penalty_avoided": sla_avoided,
        "cost_30d": cost,
        "roi": roi(total, cost),
        # ROI per rupee committed -- the greedy ordering key. Equal to
        # benefit/cost - 1, so ranking on it and on ROI agree; it is named
        # separately because the selection rule is stated in those terms.
        "roi_per_rupee": (total - cost) / cost if cost > 0 else float("inf"),
        "payback_ratio": total / cost if cost > 0 else float("inf"),
    })
    return out


def score_all(impacts):
    return sorted((score(i) for i in impacts), key=lambda c: -c["roi"])


def select_greedy(candidates, budget=C.BUDGET_CAP):
    """take the best ROI-per-rupee that still fits, until nothing does.

    Only ROI-positive actions are eligible: an action that costs more than it
    saves does not become worth doing just because there is budget left.
    """
    chosen, spend = [], 0.0
    for cand in sorted(candidates, key=lambda c: -c["roi_per_rupee"]):
        if cand["roi"] <= 0:
            continue
        if spend + cand["cost_30d"] > budget:
            continue
        chosen.append(cand)
        spend += cand["cost_30d"]
    return chosen, spend


def mark_selection(candidates, chosen):
    """Return the full candidate list with a `selected` flag, ROI-ranked."""
    picked = {c["action"] for c in chosen}
    out = []
    for c in sorted(candidates, key=lambda c: -c["roi"]):
        row = dict(c)
        row["selected"] = int(row["action"] in picked)
        out.append(row)
    return out


def explain(candidate):
    """One sentence, for the intervention card and the investigation node."""
    return (
        "%s at %s: %.2f h off mean cycle time (95%% CI %.2f-%.2f), "
        "worth Rs %s against Rs %s cost -- ROI %.2f."
        % (C.CATALOGUE.get(candidate["action"], {}).get("label", candidate["action"]),
           candidate["stage"], candidate["delta_hours"],
           candidate["ci_low"], candidate["ci_high"],
           format(int(candidate["benefit_30d"]), ","),
           format(int(candidate["cost_30d"]), ","), candidate["roi"])
    )
