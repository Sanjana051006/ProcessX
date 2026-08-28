"""Feature builders shared by M1-M4 (Architecture §4.1).

Two feature sets:

* per case-stage  -- M1's training rows.
* per stage-hour  -- M3's anomaly windows and M4's cause windows.

Every column here is derived from the event log and case attributes only.
`ground_truth` is never read (§A5); it is used solely to score the result.
"""

import numpy as np
import pandas as pd

from backend.sim import config as C, costs

# Fixed categorical levels, so the encoded matrix has identical columns for
# every run -- a model trained on one run can score another.
_CAT_LEVELS = {
    "customer_tier": [k for k, _ in C.CUSTOMER_TIERS],
    "region": [k for k, _ in C.REGIONS],
    "item_category": [k for k, _ in C.ITEM_CATEGORIES],
    "stage": list(C.STAGES),
}

# A window counts as strained once cases wait at least as long as they are
# served. Shared with M4 so the training labels and the stage-level context
# features agree on what "strained" means.
STRAIN_RATIO = 1.0

M1_NUMERIC = [
    "order_value", "fraud_risk", "is_new_customer", "needs_review",
    "queue_len_at_arrival", "servers_busy",
    "weekday", "hour", "stage_weekday", "stage_hour", "stage_is_weekend",
]


def _one_hot(df, column):
    levels = _CAT_LEVELS[column]
    out = pd.DataFrame(index=df.index)
    values = df[column].astype(str)
    for level in levels:
        out[column + "=" + level] = (values == level).astype(np.int8)
    return out


def build_m1_features(events, cases):
    """P2.1 -- one row per (case, stage). Target is stage duration in hours."""
    ev = costs.derive(events) if "stage_duration" not in events.columns else events.copy()
    keep = ["case_id", "order_value", "customer_tier", "is_new_customer", "fraud_risk",
            "region", "item_category", "weekday", "hour", "needs_review"]
    df = ev.merge(cases[keep], on="case_id", how="left")

    df["stage_weekday"] = ((df["arrival_ts"] // 24) % 7).astype(np.int64)
    df["stage_hour"] = (df["arrival_ts"] % 24).astype(np.int64)
    df["stage_is_weekend"] = (df["stage_weekday"] >= 5).astype(np.int8)

    X = pd.concat(
        [df[M1_NUMERIC].astype(float)] + [_one_hot(df, c) for c in
                                          ("customer_tier", "region", "item_category", "stage")],
        axis=1,
    )
    y = df["stage_duration"].astype(float)
    meta = df[["case_id", "stage", "arrival_ts", "queue_wait", "service_time"]].copy()
    return X, y, meta


def time_split(meta, train_frac=0.7):
    """§A5 -- time-based split, never random: the test set is the tail of the
    horizon, so the model is always predicting forward."""
    cutoff = meta["arrival_ts"].quantile(train_frac)
    train = (meta["arrival_ts"] <= cutoff).to_numpy()
    return train, ~train, float(cutoff)


# --------------------------------------------------------- window features ---

def _occupancy(stage_events, n_windows):
    """Busy server-hours and the set of distinct resources active, per hour
    window. Purely observational -- read off the event log, not the roster."""
    busy = np.zeros(n_windows)
    active = [set() for _ in range(n_windows)]
    starts = stage_events["start_ts"].to_numpy()
    ends = stage_events["end_ts"].to_numpy()
    res = stage_events["resource_id"].to_numpy()
    for s, e, r in zip(starts, ends, res):
        if not (e > s):
            continue
        w0 = int(s)
        w1 = min(int(e), n_windows - 1)
        for w in range(max(w0, 0), w1 + 1):
            lo = s if s > w else w
            hi = e if e < w + 1 else w + 1
            if hi > lo:
                busy[w] += hi - lo
                active[w].add(r)
    return busy, np.fromiter((len(a) for a in active), dtype=np.int64, count=n_windows)


def _concentration(values, weights):
    """Largest share of total delay falling in any one group. 1/k means the
    delay is spread evenly; high means it is concentrated."""
    total = weights.sum()
    if total <= 0:
        return 0.0
    shares = pd.Series(weights).groupby(pd.Series(values).to_numpy()).sum() / total
    return float(shares.max())


def build_window_features(events, cases, residuals=None, n_windows=None):
    """P2.8 / P2.12 -- one row per (stage, hour window).

    Utilisation is mean concurrent servers over the stage's FULL observed
    roster, so a stage running 1 of its 3 reviewers reads as low utilisation
    with a long queue (staffing shortage) while a stage running 5 of 5 reads as
    saturated (capacity saturation). That contrast, together with
    wait_to_service_ratio, is what M4 keys on.
    """
    ev = costs.derive(events) if "stage_duration" not in events.columns else events.copy()
    ev = ev.merge(cases[["case_id", "order_value"]], on="case_id", how="left")
    if residuals is not None:
        ev = ev.join(pd.Series(np.asarray(residuals), index=ev.index, name="m1_residual"))
    else:
        ev["m1_residual"] = np.nan

    if n_windows is None:
        n_windows = int(np.ceil(ev["arrival_ts"].max())) + 1
    ev["window"] = ev["arrival_ts"].astype(int).clip(0, n_windows - 1)
    ev["end_window"] = ev["end_ts"].astype(int).clip(0, n_windows - 1)

    value_band = pd.qcut(ev["order_value"], 4, labels=False, duplicates="drop")

    frames = []
    for stage in C.STAGES:
        sub = ev[ev["stage"] == stage]
        if sub.empty:
            continue
        busy, active = _occupancy(sub, n_windows)
        roster = int(active.max()) if active.size else 1
        roster = max(roster, 1)

        grp = sub.groupby("window", sort=True)
        agg = pd.DataFrame({
            "n_arrivals": grp.size(),
            "mean_wait": grp["queue_wait"].mean(),
            "p90_wait": grp["queue_wait"].quantile(0.90),
            "wait_variance": grp["queue_wait"].var(),
            "mean_service": grp["service_time"].mean(),
            "mean_residual": grp["m1_residual"].mean(),
        }).reindex(range(n_windows))

        throughput = sub.groupby("end_window", sort=True).size().reindex(range(n_windows), fill_value=0)

        agg["stage"] = stage
        agg["window"] = np.arange(n_windows)
        agg["throughput"] = throughput.to_numpy()
        agg["busy_hours"] = busy
        agg["active_resources"] = active
        agg["roster"] = roster
        agg["utilisation"] = busy / roster
        agg["resource_deficit"] = 1.0 - active / roster
        agg["weekday"] = (agg["window"] // 24) % 7
        agg["hour"] = agg["window"] % 24
        agg["is_weekend"] = (agg["weekday"] >= 5).astype(np.int8)

        # Needed here, not after the concat, because the stage-level context
        # features below are defined over this stage's strained windows.
        agg["wait_to_service_ratio"] = (
            agg["mean_wait"] / agg["mean_service"].replace(0, np.nan)
        ).fillna(0.0).clip(upper=200.0)

        # Stage-level shape of the delay, repeated onto every window of the stage.
        agg["concentration_by_weekday"] = _concentration(
            ((sub["arrival_ts"] // 24) % 7).to_numpy(), sub["queue_wait"].to_numpy())
        agg["concentration_by_value_band"] = _concentration(
            value_band.loc[sub.index].to_numpy(), sub["queue_wait"].to_numpy())

        # Stage-level regime context: how hard the roster was working in the
        # stage's WORST hours.
        #
        # A cause is a property of the regime, not of a single hour. While a
        # weekend backlog drains on Monday the stage runs its full roster flat
        # out, and that hour read alone is indistinguishable from saturation.
        # Asking "when this stage was at its worst, was everyone working?"
        # separates the two cleanly: a shortage queues up while capacity sits
        # idle, saturation queues up with capacity maxed. Note this deliberately
        # replaces a raw idle-capacity feature, which conflates "roster has a
        # hole in it" with "nobody is busy right now" and does not survive the
        # move from a training world to the demo world.
        busy_windows = agg[agg["n_arrivals"] > 0]
        if len(busy_windows) >= 10:
            worst = busy_windows.nlargest(max(len(busy_windows) // 10, 1), "mean_wait")
            agg["stage_util_at_peak_wait"] = float(worst["utilisation"].mean())
        else:
            agg["stage_util_at_peak_wait"] = float(agg["utilisation"].mean())

        # The smoking gun for a staffing shortage: does this stage EVER queue up
        # while part of its roster sits idle? Under saturation that is
        # impossible -- every strained hour runs flat out -- so the low end of
        # utilisation across strained hours separates the two cleanly.
        #
        # This is needed on top of the peak-wait feature because the fault and
        # the worst delay are separated in time: the weekend shortage builds the
        # backlog, but the deepest queues are on Monday while it drains at full
        # roster. Peak hours alone therefore read as saturation.
        strained_windows = busy_windows[busy_windows["wait_to_service_ratio"] >= STRAIN_RATIO]
        agg["stage_min_util_strained"] = (
            float(strained_windows["utilisation"].quantile(0.10))
            if len(strained_windows) >= 5 else 1.0)

        frames.append(agg)

    out = pd.concat(frames, ignore_index=True)
    out["n_arrivals"] = out["n_arrivals"].fillna(0)
    for col in ("mean_wait", "p90_wait", "wait_variance", "mean_residual"):
        out[col] = out[col].fillna(0.0)
    out["mean_service"] = out["mean_service"].fillna(0.0)
    out["wait_to_service_ratio"] = out["wait_to_service_ratio"].fillna(0.0)

    # Scale-free shape features. M4 has to recognise the same *pattern* at a
    # 6-minute stage and a 14-hour one, and generalise from the stages in its
    # training corpus to ones it has never seen -- so it is given ratios, not
    # magnitudes. Absolute values (mean_wait, throughput, active_resources)
    # would let it memorise "pick_pack with 4 servers" instead.
    mean_wait = out["mean_wait"].replace(0, np.nan)
    out["p90_to_mean_wait"] = (out["p90_wait"] / mean_wait).fillna(1.0).clip(upper=20.0)
    out["wait_cv"] = (np.sqrt(out["wait_variance"]) / mean_wait).fillna(0.0).clip(upper=20.0)
    out["clearance_ratio"] = (
        out["throughput"] / out["n_arrivals"].replace(0, np.nan)).fillna(1.0).clip(upper=10.0)
    out["residual_ratio"] = (
        out["mean_residual"] / out["mean_service"].replace(0, np.nan)).fillna(0.0)
    return out


# Columns M3 scores on (Architecture §4.1).
M3_FEATURES = [
    "mean_wait", "p90_wait", "mean_service", "throughput", "utilisation", "mean_residual",
]

# M4's set (§A5 -- wait_to_service_ratio must stay). Every column is scale-free,
# for the reason given above. `mean_residual` is deliberately excluded: M4's
# training corpus is generated without a per-run M1 fit, so a residual feature
# would be identically zero in training and non-zero at inference.
M4_FEATURES = [
    "utilisation", "wait_to_service_ratio",
    "p90_to_mean_wait", "wait_cv", "clearance_ratio",
    "concentration_by_weekday", "concentration_by_value_band",
    "stage_util_at_peak_wait", "stage_min_util_strained",
]
