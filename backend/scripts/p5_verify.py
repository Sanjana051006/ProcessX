"""P5 exit checks. Needs the backend running on :8000.

    .venv/Scripts/python -m uvicorn backend.main:app --port 8000
    .venv/Scripts/python -m backend.scripts.p5_verify

Drives the whole demo over HTTP and asserts the API contract, including the
§A3 writer discipline: no GET may change the database.
"""

import json
import urllib.error
import urllib.request

from backend import db
from backend.main import app

BASE = "http://localhost:8000"
FAILURES = []


def check(name, condition, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def call(method, path, body=None, expect=200):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            payload, status = json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        payload, status = json.loads(e.read().decode() or "{}"), e.code
    if expect is not None and status != expect:
        raise AssertionError("%s %s -> %s (wanted %s): %s"
                             % (method, path, status, expect, payload))
    return payload


def table_counts():
    conn = db.connect()
    try:
        return {t: conn.execute("SELECT count(*) FROM " + t).fetchone()[0]
                for t in db.TABLES}
    finally:
        conn.close()


# The 11 endpoints frozen in §A9.
LOCKED = [
    ("POST", "/api/runs/reset"),
    ("POST", "/api/runs/inject/{scenario}"),
    ("GET", "/api/stages/health"),
    ("GET", "/api/bottlenecks/ranking"),
    ("GET", "/api/models/metrics"),
    ("POST", "/api/agent/investigate"),
    ("GET", "/api/agent/{inv_id}"),
    ("GET", "/api/agent/{inv_id}/tree"),
    ("GET", "/api/agent/{inv_id}/interventions"),
    ("POST", "/api/interventions/{int_id}/apply"),
    ("GET", "/api/baseline/compare"),
]


def main():
    print("\n== §A9  the locked API surface ==")
    spec = app.openapi()["paths"]
    for method, path in LOCKED:
        check("%-4s %s" % (method, path),
              path in spec and method.lower() in spec[path])
    extra = sorted(set(spec) - {p for _, p in LOCKED} - {"/api/health", "/api/runs"})
    check("no unplanned endpoints", not extra, str(extra) if extra else "11 locked + health + runs")

    print("\n== P5.1  reset and inject ==")
    r = call("POST", "/api/runs/reset")
    check("reset returns the healthy baseline", r["run_id"] == "baseline",
          "cycle %.2f h" % r["kpis"]["mean_cycle_hours"])
    check("reset reloads models instead of refitting", r["models_loaded"] and not r["retrained"])
    check("baseline is now the current run",
          call("GET", "/api/health")["current_run_id"] == "baseline")
    check("only one run exists after reset", len(call("GET", "/api/runs")["runs"]) == 1)

    r = call("POST", "/api/runs/inject/bottleneck_a")
    check("inject creates the bottleneck world", r["run_id"] == "bottleneck_a",
          "cycle %.2f h, SLA breach %.2f%%"
          % (r["kpis"]["mean_cycle_hours"], 100 * r["kpis"]["sla_breach_rate"]))
    check("it is parented to the baseline", r["parent_run_id"] == "baseline")
    check("injecting cycle time is worse than baseline",
          r["kpis"]["mean_cycle_hours"] > 17.0)
    err = call("POST", "/api/runs/inject/bottleneck_b", expect=404)
    check("bottleneck B cannot be injected", "emerges" in err["detail"])

    print("\n== P5.2  read endpoints ==")
    h = call("GET", "/api/stages/health")
    check("5 stages in pipeline order",
          [s["stage"] for s in h["stages"]]
          == ["order_validation", "inventory_allocation", "pick_pack",
              "carrier_handover", "last_mile"])
    check("process-map edges are merged in (§A9)", len(h["edges"]) == 4,
          " -> ".join([h["edges"][0]["from"]] + [e["to"] for e in h["edges"]]))
    ov = next(s for s in h["stages"] if s["stage"] == "order_validation")
    check("order_validation reads red", ov["health"] == "red",
          "%.2fx its %s duration" % (ov["duration_vs_expected"], h["health_reference_run_id"]))
    check("M3 flags it anomalous", ov["anomalous"], "%d windows" % ov["anomalous_windows"])
    check("health is measured against the PARENT run, not the baseline",
          h["health_reference_run_id"] == "baseline")

    rk = call("GET", "/api/bottlenecks/ranking")
    check("M2 ranks order_validation first", rk["stages"][0]["stage"] == "order_validation",
          "%.1f%% contribution" % rk["stages"][0]["contribution_pct"])
    check("last_mile is not first despite the longest duration",
          rk["stages"][0]["stage"] != "last_mile",
          "last_mile at rank %d, %.1f h mean duration"
          % (next(s["rank"] for s in rk["stages"] if s["stage"] == "last_mile"),
             next(s["mean_duration_hours"] for s in rk["stages"] if s["stage"] == "last_mile")))
    check("weights are the §A5 values",
          rk["weights"] == {"queue_wait_share": 0.45, "utilisation": 0.30,
                            "residual_share": 0.25})

    m = call("GET", "/api/models/metrics")
    check("four metric cards", len(m["cards"]) == 4,
          ", ".join("%s %s" % (c["model"], c["display"]) for c in m["cards"]))
    check("all four pass their targets", all(c["pass"] for c in m["cards"]))

    print("\n== §A3  writer discipline: GETs never write ==")
    call("GET", "/api/baseline/compare", expect=409)   # nothing to compare yet
    before = table_counts()
    for path in ("/api/health", "/api/stages/health", "/api/bottlenecks/ranking",
                 "/api/models/metrics", "/api/runs"):
        call("GET", path)
    after = table_counts()
    check("no row count changed across every read endpoint", before == after,
          json.dumps(before))

    print("\n== P5.3  agent endpoints ==")
    inv = call("POST", "/api/agent/investigate", {})
    check("concludes order_validation / staffing_shortage",
          (inv["concluded_stage"], inv["concluded_cause"])
          == ("order_validation", "staffing_shortage"),
          "p=%.2f in %d probes" % (inv["confidence"], inv["probes_used"]))
    check("the finished tree comes back in the response (§A8, no polling)",
          len(inv["nodes"]) == inv["probes_used"] > 0)
    check("every node carries reasoning",
          all(len(n["reasoning"]) > 40 for n in inv["nodes"]))
    inv_id = inv["inv_id"]

    got = call("GET", "/api/agent/" + inv_id)
    check("GET /agent/{inv_id} agrees with the POST",
          got["concluded_stage"] == inv["concluded_stage"]
          and got["status"] == "converged")
    tree = call("GET", "/api/agent/%s/tree" % inv_id)
    check("the persisted tree matches",
          [n["target"] for n in tree["nodes"]] == [n["target"] for n in inv["nodes"]],
          " -> ".join(n["target"] for n in tree["nodes"]))
    check("factor nodes hang off their stage node",
          all(n["parent_node_id"] for n in tree["nodes"] if n["depth"] == 1))

    cands = call("GET", "/api/agent/%s/interventions" % inv_id)["interventions"]
    check("at least two options offered", len(cands) >= 2)
    check("ROI-ranked", [c["roi"] for c in cands] == sorted((c["roi"] for c in cands), reverse=True))
    picked = [c for c in cands if c["selected"]]
    check("the Rs 40k option is selected, the Rs 180k one is not",
          "auto_approve_low_risk" in {c["action"] for c in picked}
          and "add_reviewers_2" not in {c["action"] for c in picked},
          ", ".join("%s Rs%d ROI %.2f" % (c["action"], c["cost"], c["roi"]) for c in picked))
    check("selection fits the budget",
          sum(c["cost"] for c in picked) <= cands[0]["cost"] + 250000)
    check("unknown investigation 404s",
          call("GET", "/api/agent/nope/tree", expect=404)["detail"].startswith("Unknown"))

    print("\n== P5.4  apply, and the cascade ==")
    int_id = picked[0]["int_id"]
    ap = call("POST", "/api/interventions/%s/apply?apply_selected=true" % int_id)
    check("cycle time drops",
          ap["after"]["mean_cycle_hours"] < ap["before"]["mean_cycle_hours"],
          "%.2f h -> %.2f h for Rs %d" % (ap["before"]["mean_cycle_hours"],
                                          ap["after"]["mean_cycle_hours"], ap["total_cost"]))
    check("the whole selected portfolio was applied", len(ap["applied"]) == len(picked))
    check("a child run was created and is now current",
          call("GET", "/api/health")["current_run_id"] == ap["child_run_id"],
          ap["child_run_id"])

    h2 = call("GET", "/api/stages/health")
    pp = next(s for s in h2["stages"] if s["stage"] == "pick_pack")
    ov2 = next(s for s in h2["stages"] if s["stage"] == "order_validation")
    check("order_validation is now green", ov2["health"] == "green",
          "%.2f h wait" % ov2["mean_wait_hours"])
    check("pick_pack has gone RED on its own", pp["health"] == "red",
          "%.2f h wait, %.2fx its pre-fix duration"
          % (pp["mean_wait_hours"], pp["duration_vs_expected"]))
    check("the reference is the pre-fix world, not the healthy one",
          h2["health_reference_run_id"] == "bottleneck_a")

    inv2 = call("POST", "/api/agent/investigate", {})
    check("the re-plan lands on pick_pack / capacity_saturation",
          (inv2["concluded_stage"], inv2["concluded_cause"])
          == ("pick_pack", "capacity_saturation"),
          "p=%.2f" % inv2["confidence"])
    check("it is a different stage than the first investigation",
          inv2["concluded_stage"] != inv["concluded_stage"])
    check("and it recommends a pick_pack action",
          any(i["selected"] and i["stage"] == "pick_pack" for i in inv2["interventions"]),
          ", ".join(i["action"] for i in inv2["interventions"] if i["selected"]))

    print("\n== P5.4  baseline comparison ==")
    cmp = call("GET", "/api/baseline/compare?run_id=bottleneck_a")
    check("agent picked order_validation", cmp["agent"]["chosen_stage"] == "order_validation")
    check("the fixed rule picked last_mile",
          cmp["baseline"]["strict"]["chosen_stage"] == "last_mile",
          "and found no action to buy there"
          if cmp["baseline"]["strict"]["chosen_action"] is None else "")
    check("agent net benefit is positive", cmp["agent"]["net_benefit"] > 0,
          "Rs %s for Rs %s" % (format(int(cmp["agent"]["net_benefit"]), ","),
                               format(int(cmp["agent"]["cost"]), ",")))
    check("agent beats both baseline variants on net benefit",
          all(cmp["agent"]["net_benefit"] > v["net_benefit"]
              for v in cmp["baseline"].values()),
          "; ".join("%s: %s -> Rs %s" % (k, v["chosen_action"],
                                         format(int(v["net_benefit"]), ","))
                    for k, v in cmp["baseline"].items()))

    print("\n" + "=" * 62)
    if FAILURES:
        print("P5 FAILED: " + ", ".join(FAILURES))
        raise SystemExit(1)
    print("P5 ALL CHECKS PASS")


if __name__ == "__main__":
    main()
