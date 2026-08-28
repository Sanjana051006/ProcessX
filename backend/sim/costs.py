"""Derived time and cost columns (P1.11).

The simulator models *time*; cost is derived from it (Status §C: "Model time,
derive cost" -- generating cost directly would leave M4 with no signature to
classify). Everything below is a pure function of the event log plus the §A7
constants.
"""

import numpy as np
import pandas as pd

from backend.sim import config as C


def derive(events):
    """Add queue_wait, service_time and stage_cost to an event frame."""
    out = events.copy()
    out["queue_wait"] = out["start_ts"] - out["arrival_ts"]
    out["service_time"] = out["end_ts"] - out["start_ts"]
    out["stage_duration"] = out["queue_wait"] + out["service_time"]
    out["stage_cost"] = out["stage_duration"] * C.HOLDING_COST_PER_HOUR
    return out


def case_summary(events):
    """One row per case: cycle time, holding cost, SLA breach and penalty.

    Stages are sequential with no gaps -- a case arrives at stage i+1 exactly
    when it leaves stage i -- so cycle time equals the sum of the per-stage
    durations, and the two definitions agree by construction.
    """
    ev = derive(events) if "stage_duration" not in events.columns else events
    grouped = ev.groupby("case_id", sort=True)
    summary = pd.DataFrame({
        "entry_ts": grouped["arrival_ts"].min(),
        "exit_ts": grouped["end_ts"].max(),
        "holding_cost": grouped["stage_cost"].sum(),
        "total_queue_wait": grouped["queue_wait"].sum(),
    })
    summary["cycle_hours"] = summary["exit_ts"] - summary["entry_ts"]
    summary["sla_breach"] = (summary["cycle_hours"] > C.SLA_THRESHOLD_HOURS).astype(int)
    summary["sla_penalty"] = summary["sla_breach"] * C.SLA_PENALTY_PER_CASE
    summary["case_cost"] = summary["holding_cost"] + summary["sla_penalty"]
    return summary.reset_index()


def run_kpis(events, horizon_days):
    """The three KPI columns the `runs` table carries."""
    summary = case_summary(events)
    return {
        "n_cases": int(len(summary)),
        "mean_cycle_hours": float(summary["cycle_hours"].mean()),
        "p90_cycle_hours": float(summary["cycle_hours"].quantile(0.90)),
        "cost_per_case": float(summary["case_cost"].mean()),
        "throughput_per_day": float(len(summary) / horizon_days),
        "sla_breach_rate": float(summary["sla_breach"].mean()),
    }


def stage_summary(events, horizon_hours=None, config=None):
    """Per-stage aggregates. Utilisation is server-busy-hours over the
    server-hours actually offered, so a stage whose capacity varies by shift is
    still measured against its own schedule -- including one changed by an
    intervention, which is why the run's own config is used when supplied."""
    ev = derive(events) if "stage_duration" not in events.columns else events
    grouped = ev.groupby("stage", sort=False)
    out = pd.DataFrame({
        "n": grouped.size(),
        "mean_wait": grouped["queue_wait"].mean(),
        "p90_wait": grouped["queue_wait"].quantile(0.90),
        "mean_service": grouped["service_time"].mean(),
        "mean_duration": grouped["stage_duration"].mean(),
        "total_wait": grouped["queue_wait"].sum(),
        "busy_hours": grouped["service_time"].sum(),
    })
    out["wait_to_service_ratio"] = out["mean_wait"] / out["mean_service"].replace(0, np.nan)
    if horizon_hours:
        stages_cfg = (config or {}).get("stages", C.STAGE_DEFS)
        out["utilisation"] = [
            offered_utilisation(stages_cfg[stage], busy, horizon_hours)
            for stage, busy in zip(out.index, out["busy_hours"])
        ]
    return out.reindex(C.STAGES)


def offered_utilisation(stage_cfg, busy_hours, horizon_hours):
    """Busy server-hours / offered server-hours over the horizon."""
    weekday_servers = stage_cfg["servers"]
    weekend_servers = stage_cfg.get("weekend_servers", weekday_servers)
    weeks = horizon_hours / (7 * 24)
    offered = (weekday_servers * 5 + weekend_servers * 2) * 24 * weeks
    boost = stage_cfg.get("shift_boost")
    if boost:
        # The boost adds (factor - 1) x base servers for its hours each day.
        extra_per_day = sum(
            round(weekday_servers * boost["factor"]) - weekday_servers
            for _ in boost["hours"]
        )
        offered += extra_per_day * (horizon_hours / 24)
    return float(busy_hours / offered) if offered else float("nan")
