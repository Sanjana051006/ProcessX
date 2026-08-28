"""P4.2 -- the two probe types and the evidence they return.

A *stage probe* slices the log for one stage and asks M4 what is wrong with it.
A *factor probe* slices that stage's delay along one of the four locked
dimensions (§A8) and reports where it concentrates.

`factor_information` scores a dimension BEFORE it is probed, which is what lets
the policy pick the next probe by expected information gain rather than by
running all four. It uses only evidence the agent already holds.
"""

import numpy as np
import pandas as pd

from backend.jsonsafe import clean, finite
from backend.models import features
from backend.sim import costs

# §A8, in the locked order.
FACTOR_DIMENSIONS = ("weekday", "order_value_band", "is_new_customer", "resource_id")

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ProbeContext:
    """Everything a probe reads, prepared once per investigation."""

    def __init__(self, result, registry, ranked=None, windows=None, flagged=None):
        self.result = result
        self.registry = registry
        self.events = costs.derive(result["events"])
        self.cases = result["cases"]
        self.config = result["config"]
        self.ranked = ranked if ranked is not None else registry.ranking(result)
        self.windows = windows if windows is not None else registry.windows(result)
        self.flagged = flagged if flagged is not None else registry.m3.flag(self.windows)
        self.anomalies = registry.m3.anomalous_stages(self.flagged)

        merged = self.events.merge(
            self.cases[["case_id", "order_value", "is_new_customer"]],
            on="case_id", how="left")
        merged["weekday"] = ((merged["arrival_ts"] // 24) % 7).astype(int)
        merged["order_value_band"] = pd.qcut(
            merged["order_value"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        self.enriched = merged

    def stage_windows(self, stage):
        return self.windows[self.windows["stage"] == stage]


def _group_labels(rows, dimension):
    if dimension == "weekday":
        return rows["weekday"].map(lambda d: _WEEKDAY_NAMES[int(d)])
    if dimension == "order_value_band":
        return rows["order_value_band"].astype(str)
    if dimension == "is_new_customer":
        return rows["is_new_customer"].map({1: "new", 0: "returning"})
    if dimension == "resource_id":
        return rows["resource_id"].astype(str)
    raise KeyError("unknown factor dimension: " + str(dimension))


def _shares(ctx, stage, dimension):
    """Share of the stage's total queue wait falling in each group, alongside
    each group's share of volume -- the comparison is what makes it evidence."""
    rows = ctx.enriched[ctx.enriched["stage"] == stage]
    labels = _group_labels(rows, dimension)
    wait = rows["queue_wait"]
    total = float(wait.sum())
    by_group = wait.groupby(labels, observed=True).agg(["sum", "count", "mean"])
    by_group.columns = ["wait_sum", "n", "mean_wait"]
    by_group["wait_share"] = by_group["wait_sum"] / total if total > 0 else 0.0
    by_group["volume_share"] = by_group["n"] / len(rows) if len(rows) else 0.0
    return by_group.sort_values("wait_share", ascending=False), total


def normalised_entropy(values):
    p = np.asarray([v for v in values if v > 0], dtype=float)
    if len(p) <= 1:
        return 0.0
    p = p / p.sum()
    return float(-(p * np.log(p)).sum() / np.log(len(p)))


def factor_information(ctx, stage, dimension):
    """Expected information gain from probing this dimension, in [0, 1].

    Concentration = 1 - normalised entropy of the delay distribution across the
    dimension's groups. A dimension the delay is spread evenly across tells the
    agent nothing and scores ~0; one where two of seven weekdays carry 84% of
    the wait scores high. Computable from evidence already in hand, which is
    exactly what "choose the probe with the highest expected information gain"
    requires.
    """
    by_group, total = _shares(ctx, stage, dimension)
    if total <= 0 or len(by_group) <= 1:
        return 0.0
    return 1.0 - normalised_entropy(by_group["wait_share"].to_numpy())


def stage_probe(ctx, stage):
    """Slice the log for one stage; ask M4 what regime it is in."""
    row = ctx.ranked.set_index("stage").loc[stage]
    sw = ctx.stage_windows(stage)
    strained = sw[(sw["n_arrivals"] > 0)
                  & (sw["wait_to_service_ratio"] >= features.STRAIN_RATIO)]
    hypotheses, n_windows = ctx.registry.m4.hypotheses(sw)
    anomaly = ctx.anomalies.get(stage, {})

    data = {
        "mean_wait_hours": float(row["mean_wait"]),
        "mean_service_hours": float(row["mean_service"]),
        "wait_to_service_ratio": float(row["wait_to_service_ratio"]),
        "utilisation": float(row["utilisation"]),
        "queue_wait_share": float(row["queue_wait_share"]),
        "impact_share": float(row["score"]),
        "contribution_pct": float(row["contribution_pct"]),
        "rank": int(row["rank"]),
        "strained_windows": int(len(strained)),
        "diagnosed_from_windows": n_windows,
        "anomalous_windows": int(anomaly.get("n_anomalous_windows", 0)),
        "anomaly_share": float(anomaly.get("share", 0.0)),
    }
    summary = (
        "%s: mean wait %.2f h against %.2f h service (ratio %.1f), utilisation %.2f, "
        "%d strained hours, %d flagged anomalous."
        % (stage, data["mean_wait_hours"], data["mean_service_hours"],
           data["wait_to_service_ratio"], data["utilisation"],
           data["strained_windows"], data["anomalous_windows"])
    )
    return clean(data), summary, hypotheses


def factor_probe(ctx, stage, dimension):
    """Slice one stage's delay along one dimension."""
    by_group, total = _shares(ctx, stage, dimension)
    top = by_group.head(3)
    groups = [
        {
            "group": str(idx),
            "wait_share": float(r["wait_share"]),
            "volume_share": float(r["volume_share"]),
            "mean_wait_hours": float(r["mean_wait"]),
            "n": int(r["n"]),
        }
        for idx, r in by_group.iterrows()
    ]
    lead = groups[0] if groups else None
    concentration = factor_information(ctx, stage, dimension)

    data = {
        "dimension": dimension,
        "groups": groups,
        "concentration": concentration,
        "total_wait_hours": total,
    }

    if lead is None:
        return data, "%s/%s: no delay to attribute." % (stage, dimension), concentration

    # The headline: how much MORE of the delay a group carries than its volume
    # would explain. That ratio is the finding, not the raw share.
    lift = finite(lead["wait_share"] / lead["volume_share"]) if lead["volume_share"] else None

    # Report the smallest set of groups carrying most of the delay, not just the
    # single worst. "Sat and Sun carry 84% of the wait on 29% of the volume" is
    # the finding; "Sun carries 49%" understates a two-day pattern.
    head, share, volume = [], 0.0, 0.0
    for g in groups:
        head.append(g)
        share += g["wait_share"]
        volume += g["volume_share"]
        if share >= 0.75 or len(head) >= 3:
            break
    names = " and ".join(g["group"] for g in head)
    lift_head = finite(share / volume) if volume else None

    summary = (
        "%s by %s: %s %s %.1f%% of the queue wait on %.1f%% of the volume "
        "(x%s), mean wait %.2f h."
        % (stage, dimension, names, "carries" if len(head) == 1 else "carry",
           100 * share, 100 * volume,
           "%.1f" % lift_head if lift_head is not None else "n/a",
           lead["mean_wait_hours"])
    )
    data["lead_group"] = lead["group"]
    data["lead_lift"] = lift
    data["top_groups"] = [g["group"] for g in head]
    data["top_wait_share"] = share
    data["top_volume_share"] = volume
    data["top_lift"] = lift_head
    return clean(data), summary, concentration
