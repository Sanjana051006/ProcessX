"""Scratch probe: weekday/weekend split of the cascade. Not a test."""

import numpy as np
import pandas as pd

from backend.sim import config as C, costs, engine, scenarios

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def split(result, stage):
    ev = costs.derive(result["events"])
    ev = ev[ev["stage"] == stage].copy()
    ev["weekend"] = ((ev["arrival_ts"] // 24) % 7 >= 5)
    g = ev.groupby("weekend")
    return pd.DataFrame({
        "n": g.size(),
        "mean_wait": g["queue_wait"].mean().round(3),
        "p90_wait": g["queue_wait"].quantile(0.9).round(3),
    })


def arrivals_per_hour(result, stage, weekend_only=True):
    ev = result["events"]
    ev = ev[ev["stage"] == stage]
    ts = ev["arrival_ts"].to_numpy()
    is_wk = ((ts // 24) % 7) >= 5
    sel = ts[is_wk] if weekend_only else ts
    hours = np.unique(np.floor(sel))
    return len(sel) / max(len(hours), 1)


worlds = {
    "healthy": engine.simulate(scenarios.healthy_config()),
    "pre-fix (A injected)": engine.simulate(scenarios.bottleneck_a_config()),
}
inj = scenarios.bottleneck_a_config()
for a in ("auto_approve_low_risk", "add_reviewers_2"):
    worlds["post-fix " + a] = engine.simulate(inj, overrides=[a])
worlds["post-fix auto+batch"] = engine.simulate(
    inj, overrides=["auto_approve_low_risk", "batch_route_optimisation"])
worlds["post-fix auto+evening"] = engine.simulate(
    inj, overrides=["auto_approve_low_risk", "add_evening_shift"])
worlds["post-fix auto+batch+evening"] = engine.simulate(
    inj, overrides=["auto_approve_low_risk", "batch_route_optimisation", "add_evening_shift"])

rows = []
for name, r in worlds.items():
    ev = costs.derive(r["events"])
    st = costs.stage_summary(ev, r["horizon_hours"], r["config"])
    kpi = costs.run_kpis(ev, r["config"]["horizon_days"])
    rows.append({
        "world": name,
        "ov_wait": round(st.loc["order_validation", "mean_wait"], 3),
        "pp_wait": round(st.loc["pick_pack", "mean_wait"], 3),
        "pp_util": round(st.loc["pick_pack", "utilisation"], 3),
        "pp_wknd_arr/h": round(arrivals_per_hour(r, "pick_pack"), 2),
        "cycle_h": round(kpi["mean_cycle_hours"], 2),
        "p90_h": round(kpi["p90_cycle_hours"], 2),
        "sla%": round(kpi["sla_breach_rate"] * 100, 2),
        "cost/case": round(kpi["cost_per_case"], 1),
    })
print(pd.DataFrame(rows).to_string(index=False))

print("\n-- pick_pack weekday/weekend --")
for name in ("healthy", "pre-fix (A injected)", "post-fix auto_approve_low_risk"):
    print(name)
    print(split(worlds[name], "pick_pack").to_string())

print("\n-- order_validation weekday/weekend --")
for name in ("healthy", "pre-fix (A injected)"):
    print(name)
    print(split(worlds[name], "order_validation").to_string())

base = worlds["pre-fix (A injected)"]["cases"]["needs_review"].sum()
post = worlds["post-fix auto_approve_low_risk"]["cases"]["needs_review"].sum()
print("\nmanual review volume: %d -> %d  (%.1f%% reduction; §A6 target 60%%)"
      % (base, post, 100 * (1 - post / base)))
