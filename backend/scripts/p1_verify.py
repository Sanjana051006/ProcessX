"""P1 exit checks. Run:  .venv/Scripts/python -m backend.scripts.p1_verify

Covers P1.4 (seed reproducibility), P1.10 (the cascade) and P1.12 (sanity
assertions). Every check either prints PASS or raises.
"""

import numpy as np
import pandas as pd

from backend import db
from backend.sim import config as C, costs, engine, persist, scenarios

FAILURES = []


def check(name, condition, detail=""):
    tag = "PASS" if condition else "FAIL"
    print("  [%s] %s%s" % (tag, name, ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def stage_table(result):
    ev = costs.derive(result["events"])
    return costs.stage_summary(ev, result["horizon_hours"], result["config"])


def m2_like_rank(st):
    """Rank stages the way M2 will (§A5), minus the M1 residual term which does
    not exist yet. Enough to show which stage the ranking points at."""
    wait_share = st["total_wait"] / st["total_wait"].sum()
    score = 0.45 * wait_share + 0.30 * st["utilisation"]
    return score.sort_values(ascending=False)


def main():
    print("\n== P1.5 / P1.6  world generation ==")
    healthy = engine.simulate(scenarios.healthy_config())
    cases, events = healthy["cases"], healthy["events"]
    n = len(cases)
    check("~8k cases over 30 days", 7000 <= n <= 9000, "n = %d" % n)
    check("manual review rate ~35 pct", 0.32 <= cases["needs_review"].mean() <= 0.38,
          "%.3f" % cases["needs_review"].mean())
    for col in ("order_value", "customer_tier", "is_new_customer", "fraud_risk",
                "region", "item_category"):
        check("attribute present: " + col, col in cases.columns)

    print("\n== P1.12  sanity assertions ==")
    ev = costs.derive(events)
    check("no negative queue waits", bool((ev["queue_wait"] >= -1e-9).all()),
          "min = %.2e" % ev["queue_wait"].min())
    check("no negative service times", bool((ev["service_time"] >= -1e-9).all()),
          "min = %.2e" % ev["service_time"].min())
    check("no unfinished events", int(ev["end_ts"].isna().sum()) == 0)
    per_case = ev.groupby("case_id")["stage"].nunique()
    check("every case visits all 5 stages", bool((per_case == 5).all()),
          "min = %d, max = %d" % (per_case.min(), per_case.max()))
    ordered = ev.sort_values(["case_id", "arrival_ts"])
    starts_before_ends = bool((ordered["start_ts"] <= ordered["end_ts"] + 1e-9).all())
    check("start_ts <= end_ts everywhere", starts_before_ends)

    injected = engine.simulate(scenarios.bottleneck_a_config())
    k_healthy = costs.run_kpis(healthy["events"], 30)
    k_injected = costs.run_kpis(injected["events"], 30)
    check("cycle time rises after injection",
          k_injected["mean_cycle_hours"] > k_healthy["mean_cycle_hours"],
          "%.2f h -> %.2f h" % (k_healthy["mean_cycle_hours"], k_injected["mean_cycle_hours"]))

    print("\n== P1.4  same seed -> identical arrivals ==")
    a = engine.simulate(scenarios.healthy_config())
    b = engine.simulate(scenarios.bottleneck_a_config())
    c = engine.simulate(scenarios.bottleneck_a_config(), overrides=["add_reviewers_2"])
    check("arrival stream identical across configs",
          np.allclose(a["cases"]["created_ts"], b["cases"]["created_ts"])
          and np.allclose(a["cases"]["created_ts"], c["cases"]["created_ts"]))
    check("case attributes identical across configs",
          np.allclose(a["cases"]["order_value"], c["cases"]["order_value"])
          and np.allclose(a["cases"]["fraud_risk"], c["cases"]["fraud_risk"]))
    d = engine.simulate(scenarios.bottleneck_a_config())
    check("rerunning one config is bit-identical",
          np.allclose(b["events"]["end_ts"], d["events"]["end_ts"]))
    e = engine.simulate(scenarios.healthy_config(), seed=43)
    check("a different seed gives a different world",
          not np.allclose(a["cases"]["created_ts"][:100], e["cases"]["created_ts"][:100]))

    print("\n== P1.7  bottleneck A is where it was injected ==")
    st_inj = stage_table(injected)
    rank_inj = m2_like_rank(st_inj)
    check("order_validation ranks #1 pre-fix", rank_inj.index[0] == "order_validation",
          "ranking: " + ", ".join(rank_inj.index[:3]))
    ov = st_inj.loc["order_validation"]
    check("bottleneck A is a WAIT problem, not a service problem",
          ov["wait_to_service_ratio"] > 5,
          "wait/service = %.1f, mean_service %.3f h (healthy %.3f h)"
          % (ov["wait_to_service_ratio"], ov["mean_service"],
             stage_table(healthy).loc["order_validation", "mean_service"]))

    print("\n== P1.8  pick_pack sized for utilisation ~0.82, B latent pre-fix ==")
    check("pick_pack utilisation near 0.82",
          0.75 <= st_inj.loc["pick_pack", "utilisation"] <= 0.88,
          "%.3f" % st_inj.loc["pick_pack", "utilisation"])
    check("pick_pack is NOT the top stage pre-fix",
          rank_inj.index[0] != "pick_pack",
          "pick_pack wait %.3f h vs order_validation %.3f h"
          % (st_inj.loc["pick_pack", "mean_wait"], ov["mean_wait"]))
    check("last_mile is the longest stage but carries no queue",
          st_inj["mean_duration"].idxmax() == "last_mile"
          and st_inj.loc["last_mile", "mean_wait"] < 0.05,
          "duration %.2f h, wait %.4f h"
          % (st_inj.loc["last_mile", "mean_duration"], st_inj.loc["last_mile", "mean_wait"]))

    print("\n== P1.10  THE CASCADE -- fixing A raises pick_pack, no special-casing ==")
    inj_cfg = scenarios.bottleneck_a_config()
    for fix in ("auto_approve_low_risk", "add_reviewers_2", "weekend_shift_reallocation"):
        fixed = engine.simulate(inj_cfg, overrides=[fix])
        st_fix = stage_table(fixed)
        rank_fix = m2_like_rank(st_fix)
        pp_before = st_inj.loc["pick_pack", "mean_wait"]
        pp_after = st_fix.loc["pick_pack", "mean_wait"]
        ov_after = st_fix.loc["order_validation", "mean_wait"]
        print("  -- fix: " + fix)
        check("   order_validation relieved", ov_after < ov["mean_wait"] * 0.5,
              "%.3f h -> %.3f h" % (ov["mean_wait"], ov_after))
        check("   pick_pack queue grows", pp_after > pp_before * 1.5,
              "%.3f h -> %.3f h  (x%.1f)" % (pp_before, pp_after, pp_after / pp_before))
        check("   pick_pack becomes the #1 stage", rank_fix.index[0] == "pick_pack",
              "ranking: " + ", ".join(rank_fix.index[:3]))

    print("\n== P1.10b  the cascade mechanism is throughput, not a planted rule ==")
    fixed = engine.simulate(inj_cfg, overrides=["auto_approve_low_risk"])

    def weekend_rate(result, stage):
        ts = result["events"].loc[result["events"]["stage"] == stage, "arrival_ts"].to_numpy()
        wk = ts[((ts // 24) % 7) >= 5]
        return len(wk) / max(len(np.unique(np.floor(wk))), 1)

    before, after = weekend_rate(injected, "pick_pack"), weekend_rate(fixed, "pick_pack")
    check("weekend arrival rate into pick_pack rises",
          after > before * 1.15,
          "%.2f/h -> %.2f/h  (+%.0f%%)" % (before, after, 100 * (after / before - 1)))
    check("pick_pack servers and service time are UNCHANGED by the fix",
          fixed["config"]["stages"]["pick_pack"] == inj_cfg["stages"]["pick_pack"],
          "only order_validation was touched")

    print("\n== P1.11  derived costs ==")
    summary = costs.case_summary(costs.derive(injected["events"]))
    recomputed = costs.derive(injected["events"]).groupby("case_id")["stage_duration"].sum()
    check("cycle time == sum of stage durations",
          np.allclose(summary["cycle_hours"], recomputed.to_numpy(), atol=1e-6))
    check("SLA penalty only above the 48 h threshold",
          bool(((summary["cycle_hours"] > C.SLA_THRESHOLD_HOURS)
                == (summary["sla_penalty"] > 0)).all()))
    k = costs.run_kpis(injected["events"], 30)
    print("     KPIs: " + ", ".join("%s=%.3f" % (a, b) for a, b in k.items()))

    print("\n== P1.6 / P1.9  bulk write ==")
    db.reset()
    kh = persist.write_run(healthy, "baseline", label="Healthy baseline",
                           ground_truth=dict(scenarios.ground_truth_for("healthy"),
                                             injected_at=None))
    ki = persist.write_run(injected, "bottleneck_a", label="Bottleneck A injected",
                           parent_run_id="baseline",
                           ground_truth=dict(scenarios.ground_truth_for("bottleneck_a"),
                                             injected_at=scenarios.INJECTED_AT_HOURS))
    conn = db.get_conn()
    n_ev = conn.execute("SELECT count(*) FROM event_log").fetchone()[0]
    n_cs = conn.execute("SELECT count(*) FROM cases").fetchone()[0]
    n_gt = conn.execute("SELECT count(*) FROM ground_truth").fetchone()[0]
    n_rn = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
    check("event_log rows == cases x 5 x 2 runs", n_ev == len(cases) * 5 * 2, str(n_ev))
    check("cases rows across both runs", n_cs == len(cases) * 2, str(n_cs))
    check("ground_truth has one row per run", n_gt == 2)
    check("runs has both rows", n_rn == 2)

    back = persist.load_events("bottleneck_a")
    check("round-trip preserves timings",
          np.allclose(np.sort(back["end_ts"].to_numpy()),
                      np.sort(injected["events"]["end_ts"].to_numpy())))
    check("re-writing a run is idempotent",
          persist.write_run(injected, "bottleneck_a")["mean_cycle_hours"] == ki["mean_cycle_hours"]
          and conn.execute("SELECT count(*) FROM event_log").fetchone()[0] == n_ev)
    check("ground truth is stored, never fed back into cases/events",
          "true_cause" not in persist.load_cases("bottleneck_a").columns)
    print("     baseline    : cycle %.2f h, cost/case Rs %.1f"
          % (kh["mean_cycle_hours"], kh["cost_per_case"]))
    print("     bottleneck_a: cycle %.2f h, cost/case Rs %.1f"
          % (ki["mean_cycle_hours"], ki["cost_per_case"]))

    print("\n" + "=" * 62)
    if FAILURES:
        print("P1 FAILED: " + ", ".join(FAILURES))
        raise SystemExit(1)
    print("P1 ALL CHECKS PASS")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
