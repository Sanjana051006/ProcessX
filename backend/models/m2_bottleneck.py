"""M2 -- bottleneck detection.

Deterministic score per stage:

    0.45 x queue_wait_share + 0.30 x utilisation + 0.25 x M1_residual_share

Ranked, with each stage's percentage contribution. This is the *ranking* layer:
on its own it is only a better baseline. What makes the system an agent is the
probe-selection policy in P4, which uses this score as one of its two terms.
"""

import numpy as np
import pandas as pd

from backend.sim import config as C, costs

WEIGHTS = {"queue_wait_share": 0.45, "utilisation": 0.30, "residual_share": 0.25}


def rank(events, cases, config, horizon_hours, residuals=None):
    """Return the ranked stage table. `residuals` is M1's per-event residual
    array aligned to `events`."""
    ev = costs.derive(events) if "stage_duration" not in events.columns else events.copy()
    st = costs.stage_summary(ev, horizon_hours, config)

    wait_share = st["total_wait"] / st["total_wait"].sum() if st["total_wait"].sum() > 0 \
        else pd.Series(0.0, index=st.index)

    if residuals is not None:
        # Only delay the model could NOT explain counts, so a stage that is slow
        # for reasons already in the features does not double-count. The excess
        # is taken as a RATE against the stage's own duration: last_mile has a
        # 14 h lognormal service whose noise dwarfs every other stage's total
        # delay, and an unnormalised sum would hand it the residual term on
        # variance alone.
        unexplained = pd.Series(np.clip(np.asarray(residuals), 0, None), index=ev.index)
        excess = unexplained.groupby(ev["stage"]).sum().reindex(st.index).fillna(0.0)
        scale = ev.groupby("stage")["stage_duration"].sum().reindex(st.index).fillna(0.0)
        rate = excess / scale.replace(0, np.nan)
        rate = rate.fillna(0.0)
        residual_share = rate / rate.sum() if rate.sum() > 0 \
            else pd.Series(0.0, index=st.index)
    else:
        residual_share = pd.Series(0.0, index=st.index)

    out = pd.DataFrame({
        "stage": st.index,
        "queue_wait_share": wait_share.to_numpy(),
        "utilisation": st["utilisation"].to_numpy(),
        "residual_share": residual_share.to_numpy(),
        "mean_wait": st["mean_wait"].to_numpy(),
        "mean_service": st["mean_service"].to_numpy(),
        "mean_duration": st["mean_duration"].to_numpy(),
        "wait_to_service_ratio": st["wait_to_service_ratio"].to_numpy(),
    })
    out["score"] = (
        WEIGHTS["queue_wait_share"] * out["queue_wait_share"]
        + WEIGHTS["utilisation"] * out["utilisation"]
        + WEIGHTS["residual_share"] * out["residual_share"]
    )
    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    out["contribution_pct"] = 100 * out["score"] / out["score"].sum()
    out["rank"] = np.arange(1, len(out) + 1)
    return out


def top_stage(ranked):
    return ranked.iloc[0]["stage"]


def impact_share(ranked):
    """Normalised score per stage -- the `impact` term of the agent's
    probe-selection rule."""
    return dict(zip(ranked["stage"], ranked["score"] / ranked["score"].sum()))


def precision_at_1(ranked, true_stage):
    return float(top_stage(ranked) == true_stage)


def metric_card(results):
    """`results` is a list of (scenario_name, ranked_df, true_stage)."""
    hits = [precision_at_1(r, t) for _, r, t in results]
    value = float(np.mean(hits)) if hits else 0.0
    detail = "; ".join(
        "%s -> %s (truth %s)" % (name, top_stage(r), t) for name, r, t in results)
    return {
        "model": "M2",
        "name": "Bottleneck detection",
        "metric": "precision@1 vs ground truth",
        "value": value,
        "display": "%.2f over %d scenarios" % (value, len(results)),
        "detail": detail,
        "target": 1.0,
        "pass": value >= 1.0,
    }
