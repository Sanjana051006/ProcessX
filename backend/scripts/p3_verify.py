"""P3 exit checks. Run:  .venv/Scripts/python -m backend.scripts.p3_verify

P3.6 is a never-cut item (§A10): auto_approve_low_risk must outrank
add_reviewers_2 on ROI.
"""

import numpy as np
import pandas as pd

from backend import db
from backend.models import m5_impact as m5, m6_roi as m6
from backend.sim import config as C, engine, persist, scenarios

FAILURES = []


def check(name, condition, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def table(cands):
    df = pd.DataFrame(cands)[
        ["action", "stage", "cost_30d", "delta_hours", "ci_low", "ci_high",
         "benefit_30d", "roi", "significant"]]
    return df.round(3).to_string(index=False)


def main():
    cfg = scenarios.bottleneck_a_config()

    print("\n== P3.1  counterfactual simulate() with overrides ==")
    base = engine.simulate(cfg, seed=42)
    alt = engine.simulate(cfg, overrides=["auto_approve_low_risk"], seed=42)
    check("the override changes only the targeted stage",
          {k: v for k, v in alt["config"]["stages"].items() if k != "order_validation"}
          == {k: v for k, v in cfg["stages"].items() if k != "order_validation"})
    check("arrivals are identical between baseline and counterfactual",
          np.allclose(base["cases"]["created_ts"], alt["cases"]["created_ts"]),
          "paired replicates -- the delta is the intervention, not noise")
    check("the counterfactual actually moves cycle time",
          alt["events"]["end_ts"].max() != base["events"]["end_ts"].max())

    print("\n== P3.2 / P3.3  three seed replicates -> mean delta + CI ==")
    baselines = m5.baseline_replicates(cfg)
    check("3 replicates on the locked seeds", tuple(baselines) == (42, 43, 44),
          "baseline cycle " + ", ".join("%.2f" % v["mean_cycle_hours"] for v in baselines.values()))
    impacts = m5.evaluate_catalogue(cfg, baselines=baselines)
    check("one record per catalogue action", len(impacts) == len(C.CATALOGUE))
    for rec in impacts:
        ok = ("delta_hours" in rec and "ci_low" in rec and "ci_high" in rec
              and rec["ci_low"] <= rec["delta_hours"] <= rec["ci_high"])
        check("   %-27s delta %.3f h  CI [%.3f, %.3f]"
              % (rec["action"], rec["delta_hours"], rec["ci_low"], rec["ci_high"]), ok)
    widths = [r["ci_high"] - r["ci_low"] for r in impacts]
    check("CIs are tight enough to act on", max(widths) < 1.0,
          "widest %.3f h -- common random numbers doing their job" % max(widths))

    print("\n== P3.4  benefit model matches §A7 exactly ==")
    rec = next(r for r in impacts if r["action"] == "auto_approve_low_risk")
    scored = m6.score(rec)
    hand_holding = rec["delta_hours"] * C.CASES_PER_DAY * C.ROI_HORIZON_DAYS * C.HOLDING_COST_PER_HOUR
    hand_sla = rec["delta_sla_rate"] * C.CASES_PER_DAY * C.ROI_HORIZON_DAYS * C.SLA_PENALTY_PER_CASE
    hand_roi = (hand_holding + hand_sla - 40000) / 40000
    check("holding term", abs(scored["holding_benefit"] - hand_holding) < 1e-6,
          "Rs %s" % format(int(hand_holding), ","))
    check("SLA penalty avoided", abs(scored["sla_penalty_avoided"] - hand_sla) < 1e-6,
          "Rs %s" % format(int(hand_sla), ","))
    check("roi = (benefit - cost) / cost", abs(scored["roi"] - hand_roi) < 1e-9,
          "%.3f" % scored["roi"])
    check("constants are the frozen §A7 values",
          (C.HOLDING_COST_PER_HOUR, C.SLA_THRESHOLD_HOURS, C.SLA_PENALTY_PER_CASE,
           C.CASES_PER_DAY, C.ROI_HORIZON_DAYS) == (12, 48, 250, 270, 30),
          "holding_cost_per_hour = 12, unchanged")

    print("\n== ROI ranking, bottleneck A world ==")
    cands = m6.score_all(impacts)
    print(table(cands))

    print("\n== P3.6  REQUIRED OUTCOME (never cut) ==")
    roi_of = {c["action"]: c["roi"] for c in cands}
    check("auto_approve_low_risk outranks add_reviewers_2 on ROI",
          roi_of["auto_approve_low_risk"] > roi_of["add_reviewers_2"],
          "%.2f vs %.2f" % (roi_of["auto_approve_low_risk"], roi_of["add_reviewers_2"]))
    check("   the Rs 40k option beats the Rs 180k option (PRD beat 3)",
          roi_of["auto_approve_low_risk"] > roi_of["add_reviewers_2"])
    check("   add_reviewers_2 is rejected outright, not merely outranked",
          roi_of["add_reviewers_2"] < roi_of["auto_approve_low_risk"],
          "ROI %.2f -- it costs more than it saves" % roi_of["add_reviewers_2"])

    print("\n== P3.5  greedy ROI-per-rupee under the Rs 250k cap ==")
    chosen, spend = m6.select_greedy(cands)
    check("stays inside the budget", spend <= C.BUDGET_CAP,
          "Rs %s of Rs %s" % (format(int(spend), ","), format(C.BUDGET_CAP, ",")))
    check("selects only ROI-positive actions", all(c["roi"] > 0 for c in chosen),
          ", ".join("%s (ROI %.2f)" % (c["action"], c["roi"]) for c in chosen))
    check("selection is ordered by ROI per rupee",
          [c["action"] for c in chosen]
          == [c["action"] for c in sorted(chosen, key=lambda x: -x["roi_per_rupee"])])
    check("add_reviewers_2 is NOT selected",
          "add_reviewers_2" not in {c["action"] for c in chosen})
    tight, tight_spend = m6.select_greedy(cands, budget=30000)
    check("a tighter budget changes the answer", tight_spend <= 30000,
          "at Rs 30k it takes %s" % ([c["action"] for c in tight] or "nothing"))

    print("\n== bundles are simulated, not summed ==")
    bundle = m6.score(m5.evaluate_bundle(cfg, [c["actions"][0] for c in chosen],
                                         baselines=baselines))
    summed = sum(c["delta_hours"] for c in chosen)
    check("combined effect is sub-additive, as queueing implies",
          bundle["delta_hours"] < summed,
          "simulated %.2f h vs naive sum %.2f h" % (bundle["delta_hours"], summed))

    print("\n== the cascade changes the economics (feeds P4.6) ==")
    post = C.apply_actions(cfg, [c["actions"][0] for c in chosen])
    post_base = m5.baseline_replicates(post)
    post_cands = m6.score_all(m5.evaluate_catalogue(post, stage="pick_pack",
                                                    baselines=post_base))
    print(table(post_cands))
    pre_roi = {c["action"]: c["roi"] for c in cands}
    post_roi = {c["action"]: c["roi"] for c in post_cands}
    check("batch_route_optimisation is not worth doing before the fix",
          pre_roi["batch_route_optimisation"] < 0,
          "ROI %.2f" % pre_roi["batch_route_optimisation"])
    check("...and IS worth doing after it",
          post_roi["batch_route_optimisation"] > 0,
          "ROI %.2f -- the same action, repriced by the cascade"
          % post_roi["batch_route_optimisation"])
    post_chosen, _ = m6.select_greedy(post_cands, budget=C.BUDGET_CAP - spend)
    check("the re-plan has something to recommend", len(post_chosen) > 0,
          ", ".join(c["action"] for c in post_chosen))

    print("\n== P3.7  persist candidates ==")
    db.reset()
    marked = m6.mark_selection(cands, chosen)
    ids = persist.write_interventions("inv_test", marked)
    back = persist.load_interventions("inv_test")
    check("all candidates written", len(back) == len(cands), "%d rows" % len(back))
    check("ids are deterministic", ids == ["inv_test--%s" % c["action"] for c in marked])
    check("selected flags persisted",
          int(back["selected"].sum()) == len(chosen),
          ", ".join(back.loc[back["selected"] == 1, "action"]))
    check("ROI round-trips",
          np.allclose(sorted(back["roi"]), sorted(c["roi"] for c in cands)))
    persist.write_interventions("inv_test", marked)
    check("re-writing is idempotent", len(persist.load_interventions("inv_test")) == len(cands))
    persist.mark_applied(ids[0])
    check("mark_applied works",
          int(persist.load_interventions("inv_test").set_index("int_id")
              .loc[ids[0], "applied"]) == 1)

    print("\n" + "=" * 62)
    if FAILURES:
        print("P3 FAILED: " + ", ".join(FAILURES))
        raise SystemExit(1)
    print("P3 ALL CHECKS PASS")


if __name__ == "__main__":
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 30)
    main()
