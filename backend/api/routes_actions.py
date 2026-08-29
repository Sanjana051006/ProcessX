"""apply an intervention, and compare the agent against the fixed rule."""

from fastapi import APIRouter, HTTPException

from backend import analytics, db
from backend.agent import controller
from backend.api.deps import get_state
from backend.events import publishers as pub
from backend.jsonsafe import clean
from backend.sim import config as C, costs, persist

router = APIRouter(prefix="/api", tags=["actions"])


@router.post("/interventions/{int_id}/apply")
def apply_intervention(int_id: str, apply_selected: bool = False):
    """Apply an intervention, re-simulate, and make the child run current.

    Deliberately does NOT re-investigate. Beat 4 is worth showing in two moves:
    the numbers change first, then the agent is asked again and lands somewhere
    new. Folding the re-plan in here would collapse both into one response.

    `apply_selected=true` applies the whole portfolio M6 chose, since the agent
    recommends a set under one budget rather than a single action.
    """
    state = get_state()
    reg = state.models()
    conn = db.get_conn()

    row = conn.execute("SELECT * FROM interventions WHERE int_id = ?", (int_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown intervention: " + int_id)
    row = dict(row)

    if apply_selected:
        rows = conn.execute(
            "SELECT * FROM interventions WHERE inv_id = ? AND selected = 1"
            " ORDER BY roi DESC", (row["inv_id"],)).fetchall()
        chosen = [dict(r) for r in rows] or [row]
    else:
        chosen = [row]

    inv = persist.load_investigation(row["inv_id"])
    if inv is None:
        raise HTTPException(status_code=404, detail="Orphaned intervention")
    parent_run_id = inv["run_id"]
    parent = state.run_result(parent_run_id)
    before = costs.run_kpis(parent["events"], parent["config"]["horizon_days"])

    actions = [c["action"] for c in chosen]
    child_run_id = "%s+%s" % (parent_run_id, "+".join(actions))

    child, after = controller.apply_intervention(
        parent, reg, actions, child_run_id, parent_run_id,
        label="After " + ", ".join(actions), conn=conn)
    state.cache_run(child_run_id, child)
    # M1 was refitted on the child world, so every cached panel is now stale.
    analytics.invalidate_pipeline()
    for c in chosen:
        persist.mark_applied(c["int_id"], conn=conn)

    applied = [
        {"int_id": c["int_id"], "action": c["action"], "stage": c["stage"],
         "cost": float(c["cost"]),
         "label": C.CATALOGUE.get(c["action"], {}).get("label", c["action"])}
        for c in chosen
    ]
    total_cost = float(sum(c["cost"] for c in chosen))
    delta = {
        "mean_cycle_hours": before["mean_cycle_hours"] - after["mean_cycle_hours"],
        "cost_per_case": before["cost_per_case"] - after["cost_per_case"],
        "sla_breach_rate": before["sla_breach_rate"] - after["sla_breach_rate"],
    }
    pub.intervention_applied(parent_run_id, child_run_id, applied, total_cost)
    pub.intervention_measured(child_run_id, before, after, delta)

    return clean({
        "applied": applied,
        "total_cost": total_cost,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "before": before,
        "after": after,
        "delta": delta,
        "note": "Models refreshed. POST /api/agent/investigate to re-plan.",
    })


@router.get("/baseline/compare")
def baseline_compare(run_id: str = None):
    """Fixed rule vs agent, on the same world.

    Reads what the investigate path already wrote (read endpoints never
    write), so it 404s until an investigation has run on this world.
    """
    state = get_state()
    row = state.run_row(run_id)
    rid = row["run_id"]
    conn = db.get_conn()

    rows = conn.execute(
        "SELECT * FROM baseline_decisions WHERE run_id LIKE ?", (rid + "::%",)).fetchall()
    if not rows:
        raise HTTPException(
            status_code=409,
            detail="No baseline decision for run '%s' yet. POST /api/agent/investigate"
                   " first -- the comparison is recorded on that write path." % rid)

    variants = {}
    for r in rows:
        variant = r["run_id"].split("::", 1)[1]
        variants[variant] = {
            "chosen_stage": r["chosen_stage"],
            "chosen_action": r["chosen_action"],
            "cost": float(r["cost"]),
            "roi": float(r["roi"]),
        }

    inv = conn.execute(
        "SELECT * FROM investigations WHERE run_id = ? ORDER BY started_at DESC LIMIT 1",
        (rid,)).fetchone()
    if inv is None:
        raise HTTPException(status_code=409, detail="No investigation for run " + rid)

    picked = conn.execute(
        "SELECT * FROM interventions WHERE inv_id = ? AND selected = 1 ORDER BY roi DESC",
        (inv["inv_id"],)).fetchall()
    agent_cost = float(sum(r["cost"] for r in picked))
    agent_benefit = float(sum(r["benefit_30d"] for r in picked))

    for v in variants.values():
        v["net_benefit"] = v["roi"] * v["cost"] if v["chosen_action"] else 0.0

    return clean({
        "run_id": rid,
        "agent": {
            "chosen_stage": inv["concluded_stage"],
            "concluded_cause": inv["concluded_cause"],
            "confidence": float(inv["confidence"]),
            "actions": [
                {"action": r["action"], "cost": float(r["cost"]),
                 "roi": float(r["roi"]), "benefit_30d": float(r["benefit_30d"])}
                for r in picked
            ],
            "cost": agent_cost,
            "benefit_30d": agent_benefit,
            "net_benefit": agent_benefit - agent_cost,
            "roi": (agent_benefit - agent_cost) / agent_cost if agent_cost else 0.0,
        },
        "baseline": variants,
        "rule": "Fixed rule: highest mean stage duration, then the cheapest action there.",
        "note": ("`strict` is the rule as written; `fallthrough` skips stages with no "
                 "available action and is the stronger opponent of the two."),
    })
