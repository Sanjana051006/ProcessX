"""P5.3 -- agent endpoints.

`investigate` is synchronous (§A8): it runs the whole loop and returns the
finished tree. The frontend reveals nodes client-side at 400 ms, which looks
identical to live growth with no polling and no concurrent writes.
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import baseline as baseline_mod, db
from backend.jsonsafe import clean
from backend.agent import controller
from backend.api.deps import get_state
from backend.sim import config as C, persist

router = APIRouter(prefix="/api/agent", tags=["agent"])


class InvestigateRequest(BaseModel):
    run_id: str | None = None
    budget: float | None = None


def _record_baseline(result, run_id, conn=None):
    """Score the fixed rule on the same world, for /api/baseline/compare.

    Done here rather than in the GET because §A3 forbids read endpoints from
    writing, and this is already a write path.
    """
    decision = baseline_mod.evaluate(result)
    conn = conn or db.get_conn()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM baseline_decisions WHERE run_id = ?", (run_id,))
        for variant in ("strict", "fallthrough"):
            row = baseline_mod.summarise(decision, variant)
            conn.execute(
                "INSERT INTO baseline_decisions (run_id, chosen_stage, chosen_action,"
                " cost, roi) VALUES (?,?,?,?,?)",
                ("%s::%s" % (run_id, variant), row["chosen_stage"],
                 row["chosen_action"], row["cost"], row["roi"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return decision


@router.post("/investigate")
def investigate(body: InvestigateRequest = InvestigateRequest()):
    state = get_state()
    reg = state.models()
    row = state.run_row(body.run_id)
    run_id = row["run_id"]
    result = state.run_result(run_id)

    outcome = controller.investigate(
        result, reg, run_id, budget=body.budget or C.BUDGET_CAP)
    _record_baseline(result, run_id)
    return controller.to_json(outcome)


@router.get("/{inv_id}")
def get_investigation(inv_id: str):
    """Status, conclusion and confidence."""
    inv = persist.load_investigation(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Unknown investigation: " + inv_id)
    nodes = persist.load_nodes(inv_id)
    inv["n_nodes"] = int(len(nodes))
    inv["probes_used"] = int(len(nodes))
    return clean(inv)


@router.get("/{inv_id}/tree")
def get_tree(inv_id: str):
    """The investigation tree. Every node carries its own reasoning string."""
    if persist.load_investigation(inv_id) is None:
        raise HTTPException(status_code=404, detail="Unknown investigation: " + inv_id)
    nodes = persist.load_nodes(inv_id)
    # Rows persisted before a value was sanitised can still hold Infinity;
    # clean() here means an old database never 500s the tree.
    return clean({
        "inv_id": inv_id,
        "nodes": [
            {
                "node_id": r["node_id"],
                "parent_node_id": r["parent_node_id"],
                "depth": int(r["depth"]),
                "seq": int(r["seq"]),
                "probe_type": r["probe_type"],
                "target": r["target"],
                "selection_score": float(r["selection_score"]),
                "impact": float(r["impact"]),
                "uncertainty": float(r["uncertainty"]),
                "evidence": json.loads(r["evidence_json"]),
                "hypotheses": json.loads(r["hypotheses_json"]),
                "reasoning": r["reasoning"],
            }
            for _, r in nodes.iterrows()
        ],
    })


@router.get("/{inv_id}/interventions")
def get_interventions(inv_id: str):
    """Candidates with Δ, CI, cost and ROI, ROI-ranked."""
    if persist.load_investigation(inv_id) is None:
        raise HTTPException(status_code=404, detail="Unknown investigation: " + inv_id)
    df = persist.load_interventions(inv_id)
    return clean({
        "inv_id": inv_id,
        "budget_cap": C.BUDGET_CAP,
        "interventions": [
            {
                "int_id": r["int_id"],
                "stage": r["stage"],
                "action": r["action"],
                "label": C.CATALOGUE.get(r["action"], {}).get("label", r["action"]),
                "cost": float(r["cost"]),
                "cost_type": C.CATALOGUE.get(r["action"], {}).get("cost_type"),
                "predicted_delta_hours": float(r["predicted_delta_hours"]),
                "ci_low": float(r["ci_low"]),
                "ci_high": float(r["ci_high"]),
                "benefit_30d": float(r["benefit_30d"]),
                "roi": float(r["roi"]),
                "selected": int(r["selected"]),
                "applied": int(r["applied"]),
            }
            for _, r in df.iterrows()
        ],
    })
