"""Scratch probe for M1-M3. Not a test."""

import time

import pandas as pd

from backend.models import features
from backend.models.m1_process_time import M1
from backend.models.m2_bottleneck import rank
from backend.models.m3_anomaly import M3
from backend.sim import engine, scenarios

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

t0 = time.time()
healthy = engine.simulate(scenarios.healthy_config())
injected = engine.simulate(scenarios.bottleneck_a_config())
cascade = engine.simulate(scenarios.bottleneck_a_config(), overrides=["auto_approve_low_risk"])
print("sims: %.1fs" % (time.time() - t0))

t0 = time.time()
m1 = M1().fit(injected["events"], injected["cases"])
print("M1 fit: %.1fs" % (time.time() - t0))
print("M1 metrics:", {k: round(v, 4) for k, v in m1.metrics.items()})
print("M1 card:", m1.metric_card())

for name, r in (("bottleneck_a", injected), ("cascade_b", cascade), ("healthy", healthy)):
    res = m1.residuals(r["events"], r["cases"])
    ranked = rank(r["events"], r["cases"], r["config"], r["horizon_hours"], res)
    print("\n-- M2 " + name)
    print(ranked[["rank", "stage", "queue_wait_share", "utilisation", "residual_share",
                  "score", "contribution_pct"]].round(3).to_string(index=False))

t0 = time.time()
res_h = m1.residuals(healthy["events"], healthy["cases"])
w_healthy = features.build_window_features(healthy["events"], healthy["cases"], res_h)
print("\nwindow features: %.1fs, rows=%d" % (time.time() - t0, len(w_healthy)))

m3 = M3().fit(w_healthy)
print("M3 trained on", m3.metrics["n_train_windows"], "windows")

for name, r in (("bottleneck_a", injected), ("cascade_b", cascade)):
    res = m1.residuals(r["events"], r["cases"])
    w = features.build_window_features(r["events"], r["cases"], res)
    fl = m3.flag(w)
    print("\n-- M3 " + name)
    print("  anomalous stages:", m3.anomalous_stages(fl))
    for stage in ("order_validation", "pick_pack"):
        lt = m3.detection_lead_time(fl, stage, scenarios.INJECTED_AT_HOURS)
        print("  lead time %-20s %s" % (stage, lt))

print("\n-- window contrast (weekend, strained) --")
for name, r in (("healthy", healthy), ("bottleneck_a", injected), ("cascade_b", cascade)):
    res = m1.residuals(r["events"], r["cases"])
    w = features.build_window_features(r["events"], r["cases"], res)
    sel = w[(w["is_weekend"] == 1) & (w["n_arrivals"] > 0)
            & (w["stage"].isin(["order_validation", "pick_pack"]))]
    print(name)
    print(sel.groupby("stage")[["mean_wait", "mean_service", "wait_to_service_ratio",
                                "utilisation", "resource_deficit", "active_resources",
                                "concentration_by_weekday"]].mean().round(3).to_string())
