"""Diagnose M4: compare training-corpus signatures against the demo scenarios."""

import pandas as pd

from backend.models import features
from backend.models import m4_cause as M
from backend.sim import engine, scenarios

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

X, y, use = M.build_training_corpus()
X["label"] = y
act = X[use]

cols = features.M4_FEATURES
print("== training corpus, mean feature by label (strained windows only) ==")
strained = act[act["wait_to_service_ratio"] >= M.STRAIN_RATIO]
print(strained.groupby("label")[cols].mean().round(3).to_string())
print("\ncounts:", strained["label"].value_counts().to_dict())

print("\n== training saturation windows, by stage ==")
sat = strained[strained["label"] == "capacity_saturation"]
print(sat.groupby("stage")[cols].mean().round(3).to_string())

print("\n== training staffing windows, by stage ==")
sta = strained[strained["label"] == "staffing_shortage"]
print(sta.groupby("stage")[cols].mean().round(3).to_string())

print("\n== demo scenarios (strained windows at the ground-truth stage) ==")
inj = engine.simulate(scenarios.bottleneck_a_config())
cas = engine.simulate(scenarios.bottleneck_a_config(), overrides=["auto_approve_low_risk"])
for name, r, stage in (("bottleneck_a", inj, "order_validation"),
                       ("cascade_b", cas, "pick_pack")):
    w = features.build_window_features(r["events"], r["cases"])
    sub = w[(w["stage"] == stage) & (w["n_arrivals"] > 0)
            & (w["wait_to_service_ratio"] >= M.STRAIN_RATIO)]
    print("%-14s n=%d" % (name, len(sub)))
    print(sub[cols].mean().round(3).to_frame().T.to_string(index=False))
