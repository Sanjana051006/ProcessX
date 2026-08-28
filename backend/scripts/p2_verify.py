"""P2 exit checks. Run:  .venv/Scripts/python -m backend.scripts.p2_verify

Trains M1-M4, prints the four metric cards, and asserts the things that are
easy to get quietly wrong: that the split is temporal, that M3's reference set
really is healthy weekday windows, that M4 never saw the demo scenarios, and
that ground truth never reaches a feature matrix.
"""

import numpy as np
import pandas as pd

from backend.models import features, registry
from backend.models import m4_cause as m4mod
from backend.models.m4_cause import M4, normalised_entropy
from backend.sim import config as C, engine, scenarios

FAILURES = []


def check(name, condition, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def main():
    print("\n== training M1-M4 ==")
    reg, cards, (healthy, current, cascade) = registry.train_all(verbose=True)

    print("\n== the four metric cards (P2.16) ==")
    for c in cards:
        print("  %-3s %-26s %-34s %s" % (c["model"], c["name"], c["display"],
                                         "PASS" if c["pass"] else "FAIL"))
        print("      target %-6s | %s" % (c["target"], c["detail"]))

    print("\n== P2.4  M1 ==")
    m = reg.m1.metrics
    check("beats the mean-predictor by > 30%", m["improvement_vs_mean"] > 0.30,
          "%.1f%%" % (100 * m["improvement_vs_mean"]))
    check("also beats a per-stage mean-predictor", m["improvement_vs_stage_mean"] > 0.0,
          "%.1f%% (MAE %.3f h vs %.3f h)" % (100 * m["improvement_vs_stage_mean"],
                                             m["mae_hours"], m["mae_stage_mean_predictor"]))
    X, y, meta = features.build_m1_features(current["events"], current["cases"])
    train, test, cutoff = features.time_split(meta)
    check("split is temporal, not random",
          meta.loc[train, "arrival_ts"].max() <= meta.loc[test, "arrival_ts"].min(),
          "cutoff at hour %.0f, %d train / %d test" % (cutoff, train.sum(), test.sum()))
    check("no ground-truth column reached M1 features",
          not any(k in " ".join(X.columns) for k in ("true_cause", "bottleneck_stage")))

    print("\n== P2.7  M2 ==")
    for name, result, truth in (("bottleneck_a", current, "order_validation"),
                                ("cascade_b", cascade, "pick_pack")):
        ranked = reg.ranking(result)
        check("precision@1 on " + name, ranked.iloc[0]["stage"] == truth,
              "top=%s (%.1f%% contribution), 2nd=%s" % (
                  ranked.iloc[0]["stage"], ranked.iloc[0]["contribution_pct"],
                  ranked.iloc[1]["stage"]))
        check("   last_mile is not ranked #1 on " + name,
              ranked.iloc[0]["stage"] != "last_mile",
              "last_mile sits at rank %d despite the longest mean duration (%.1f h)"
              % (int(ranked.loc[ranked["stage"] == "last_mile", "rank"].iloc[0]),
                 ranked.loc[ranked["stage"] == "last_mile", "mean_duration"].iloc[0]))

    print("\n== P2.9 / P2.11  M3 ==")
    hw = reg.windows(healthy)
    check("fitted on healthy WEEKDAY windows only",
          reg.m3.metrics["n_train_windows"] == int(
              ((hw["is_weekend"] == 0) & (hw["n_arrivals"] > 0)).sum()),
          "%d windows" % reg.m3.metrics["n_train_windows"])
    check("one model per stage", len(reg.m3.models) == len(C.STAGES))
    flagged = reg.flagged_windows(current)
    lead = reg.m3.detection_lead_time(flagged, "order_validation",
                                      scenarios.INJECTED_AT_HOURS)
    check("detects the injection within 6 simulated hours",
          lead is not None and lead < 6.0, "%s h" % lead)
    check("the injected stage is the most-flagged stage",
          max(reg.m3.anomalous_stages(flagged).items(),
              key=lambda kv: kv[1]["share"])[0] == "order_validation")
    cas_flagged = reg.flagged_windows(cascade)
    cas_lead = reg.m3.detection_lead_time(cas_flagged, "pick_pack",
                                          scenarios.INJECTED_AT_HOURS)
    print("      (not scored) cascade B at pick_pack detected at +%s h -- B is not"
          " injected, so this measures how long it takes to MANIFEST" % cas_lead)

    print("\n== P2.15  M4 ==")
    card = cards[3]
    check("window accuracy > 0.80", card["value"] > 0.80, "%.2f" % card["value"])
    for name, result, stage, truth in (
            ("bottleneck_a", current, "order_validation", "staffing_shortage"),
            ("cascade_b", cascade, "pick_pack", "capacity_saturation")):
        w = reg.windows(result)
        cause, p, ranked, n = reg.m4.stage_cause(w, stage)
        check("%s/%s -> %s" % (name, stage, truth), cause == truth,
              "p=%.3f over %d peak windows" % (p, n))
        check("   confident enough for the agent to converge (>0.65)", p > 0.65,
              "p=%.3f, entropy=%.3f" % (p, normalised_entropy(ranked)))

    print("\n== P2.13  M4 never saw the demo scenarios ==")
    demo_ov = scenarios.bottleneck_a_config()["stages"]["order_validation"]
    check("demo bottleneck A config absent from the training corpus",
          not any(s == "order_validation" and wk == demo_ov["weekend_servers"]
                  for s, wk, _ in m4mod._STAFFING_RUNS),
          "corpus staffing runs: " + ", ".join("%s->%d" % (s, k) for s, k, _ in m4mod._STAFFING_RUNS))
    check("training seeds disjoint from the master seed",
          C.MASTER_SEED not in [s for _, _, s in m4mod._STAFFING_RUNS]
          + [s for _, _, s in m4mod._SATURATION_RUNS] + m4mod._NORMAL_SEEDS)
    check("no ground-truth column reached M4 features",
          not any(k in " ".join(features.M4_FEATURES)
                  for k in ("true_cause", "bottleneck_stage", "label")))

    print("\n== M4 generalises to faults it was not trained on ==")
    # Stage/level combinations absent from the corpus, on unseen seeds.
    held_out = [
        ("staffing_shortage", "carrier_handover", {"weekend_servers": 2}, 901),
        ("staffing_shortage", "order_validation", {"weekend_servers": 1}, 902),
        ("capacity_saturation", "pick_pack", {"servers": 5, "weekend_servers": 5}, 903),
        ("capacity_saturation", "inventory_allocation", {"servers": 4, "weekend_servers": 4}, 904),
    ]
    for truth, stage, patch, seed in held_out:
        cfg = m4mod._comfortable_config("holdout", 14)
        cfg["stages"][stage].update(patch)
        result = engine.simulate(cfg, seed=seed)
        w = features.build_window_features(result["events"], result["cases"])
        cause, p, _, n = reg.m4.stage_cause(w, stage)
        check("held-out %s at %s (seed %d)" % (truth, stage, seed), cause == truth,
              "-> %s p=%.2f over %d windows" % (cause, p, n))

    print("\n== P2.16  registry persistence ==")
    path = reg.save()
    reloaded = registry.Registry.load(path)
    w = reloaded.windows(current)
    cause, p, _, _ = reloaded.m4.stage_cause(w, "order_validation")
    check("models round-trip through joblib", cause == "staffing_shortage",
          "reloaded from %s (%.1f MB)" % (path.name, path.stat().st_size / 1e6))
    check("cards persisted", len(reloaded.cards) == 4)
    print("      fit times: " + ", ".join("%s %.1fs" % (k, v) for k, v in reg.timings.items()))

    print("\n" + "=" * 62)
    if FAILURES:
        print("P2 FAILED: " + ", ".join(FAILURES))
        raise SystemExit(1)
    print("P2 ALL CHECKS PASS")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
