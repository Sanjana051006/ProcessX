"""P4.3 -- probe selection and the stopping rule (§A8).

This module is the difference between the agent and the baseline. Ranking
stages is what M2 already does; choosing which question to ask next, by
expected information gain, is what makes this an agent.

    selection score = m2_impact_share x normalised_entropy(m4_proba)

Reading the entropy term (Status §D, found at P2.15)
----------------------------------------------------
M4 is decisive on this simulator -- once a stage has been probed its entropy is
0.000. Taken literally as "entropy of M4's posterior for this candidate", the
score would be zero for *every* candidate before any probe existed to compute
it from, and the agent would choose arbitrarily.

The term means the agent's CURRENT uncertainty about a candidate:

* a stage it has not probed carries maximum uncertainty (1.0), so its score
  reduces to impact -- look at the biggest problem first;
* probing collapses that uncertainty to M4's actual entropy, so the agent does
  not ask the same question twice;
* a factor dimension's uncertainty is how concentrated the delay is along it,
  estimated from evidence already held.

No constant floor is used anywhere; the term is always a real quantity.
"""

import numpy as np

from backend.agent import probes as probe_mod
from backend.sim import config as C

MAX_PROBES = 6                  # §A8
CONFIDENCE_THRESHOLD = 0.65     # §A8

# Stop drilling once the best remaining probe would explain less than this
# fraction of the leading stage's impact. Expressed as a fraction rather than
# an absolute so it does not need retuning when the ranking changes scale.
INFORMATION_FLOOR_FRACTION = 0.25


def normalised_entropy(hypotheses):
    """Uncertainty of a ranked hypothesis list, scaled to [0, 1]."""
    p = np.asarray([h["p"] for h in hypotheses], dtype=float)
    p = p[p > 0]
    if len(p) <= 1:
        return 0.0
    return float(-(p * np.log(p)).sum() / np.log(len(p)))


def candidates(state, ctx):
    """Every question the agent could ask next, scored.

    Stage candidates it has not probed, plus factor candidates for stages it
    has -- the drill-down only becomes available once there is something to
    drill into.
    """
    out = []
    impact = dict(zip(ctx.ranked["stage"], ctx.ranked["score"] / ctx.ranked["score"].sum()))

    for stage in ctx.ranked["stage"]:
        if stage in state.probed_stages:
            continue
        out.append({
            "probe_type": "stage",
            "stage": stage,
            "target": stage,
            "dimension": None,
            "impact": impact.get(stage, 0.0),
            "uncertainty": 1.0,          # never probed -> maximum uncertainty
            "score": impact.get(stage, 0.0) * 1.0,
        })

    for stage in state.probed_stages:
        for dim in probe_mod.FACTOR_DIMENSIONS:
            if (stage, dim) in state.probed_factors:
                continue
            information = probe_mod.factor_information(ctx, stage, dim)
            out.append({
                "probe_type": "factor",
                "stage": stage,
                "target": "%s:%s" % (stage, dim),
                "dimension": dim,
                "impact": impact.get(stage, 0.0),
                "uncertainty": information,
                "score": impact.get(stage, 0.0) * information,
            })

    # Deterministic ordering: score first, then a stable key, so two identical
    # runs produce identical trees (P7.4).
    return sorted(out, key=lambda c: (-c["score"], c["probe_type"], c["target"]))


def select(state, ctx):
    ranked = candidates(state, ctx)
    return ranked[0] if ranked else None


def confident_stage(state):
    """The highest-impact stage whose leading cause clears the §A8 threshold."""
    return state.top_hypothesis(threshold=CONFIDENCE_THRESHOLD)


def converged(state, ctx):
    """Stop when the cause is known AND nothing worth asking is left.

    §A8 sets the probability bar at 0.65. On its own that bar would stop the
    agent after a single probe, with a cause but no account of when or where it
    bites -- and the intervention choice depends on that account (a weekend
    shift reallocation only makes sense for a weekend-concentrated fault). So
    the agent also keeps going while a remaining probe would still be
    informative, and stops when the best one falls below the floor.
    """
    stage, lead = confident_stage(state)
    if stage is None:
        return False, None
    remaining = candidates(state, ctx)
    if not remaining:
        return True, "no probes left to run"
    best = remaining[0]
    # The floor is a fraction of the LEADING stage's impact, not of the
    # candidate's own. Scoring each candidate against itself would clear every
    # stage probe by construction and march the agent through all five stages.
    lead_impact = state.stage_health[stage].impact_share if stage in state.stage_health else 0.0
    floor = INFORMATION_FLOOR_FRACTION * lead_impact
    if best["score"] < floor or best["score"] <= 1e-9:
        return True, ("%s identified as %s at p=%.2f; the best remaining probe (%s) "
                      "scores %.3f against a floor of %.3f, so it would not change "
                      "the answer" % (stage, lead["cause"], lead["p"], best["target"],
                                      best["score"], floor))
    return False, None


def reason_for_selection(candidate, state):
    """The 'why this probe' half of a node's reasoning string."""
    if candidate["probe_type"] == "stage":
        return ("Selected %s: highest impact share (%.2f of the total bottleneck "
                "score) among stages not yet examined, and its cause is unknown."
                % (candidate["stage"], candidate["impact"]))
    return ("Selected %s at %s: the stage delay is more concentrated along this "
            "dimension than any other left (information %.2f), so it is the "
            "question that narrows the explanation most."
            % (candidate["dimension"], candidate["stage"], candidate["uncertainty"]))


def budget_note(state):
    return "Rs %s of the Rs %s budget still uncommitted." % (
        format(int(state.budget_remaining), ","), format(C.BUDGET_CAP, ","))
