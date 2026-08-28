"""Read endpoints. These never write."""

from fastapi import APIRouter

from backend.api.deps import get_state
from backend.jsonsafe import clean
from backend.sim import config as C, costs

router = APIRouter(prefix="/api", tags=["read"])

# Health bands: green < 1.1x expected, amber 1.1-1.5x, red > 1.5x.
_AMBER, _RED = 1.1, 1.5


def _health_band(ratio):
    if ratio is None:
        return "grey"
    if ratio > _RED:
        return "red"
    if ratio > _AMBER:
        return "amber"
    return "green"


def _reference_durations(state, row):
    """The 'expected' the health colours are measured against: the run's OWN
    PARENT, not the healthy baseline.

    A fix restores healthy throughput rather than exceeding it, so against the
    healthy baseline an intervened run renders uniformly green and the operator
    sees no movement. Against the world they were just looking at, a stage
    turns red exactly when it becomes the constraint and green exactly when a
    fix relieves it.

    A run with no parent has nothing to be worse than, so it reads green.
    """
    parent_id = row.get("parent_run_id")
    if not parent_id:
        return None, None
    try:
        parent = state.run_result(parent_id)
    except Exception:
        return None, None
    summary = costs.stage_summary(
        costs.derive(parent["events"]), parent["horizon_hours"], parent["config"])
    return summary["mean_duration"].to_dict(), parent_id


@router.get("/stages/health")
def stages_health(run_id: str = None):
    """Per-stage metrics, anomaly flags and the process-map data (the process map is
    served from this endpoint rather than its own)."""
    state = get_state()
    reg = state.models()
    row = state.run_row(run_id)
    result = state.run_result(row["run_id"])

    events = costs.derive(result["events"])
    ranked = reg.ranking(result).set_index("stage")
    flagged = reg.flag_windows(result) if hasattr(reg, "flag_windows") \
        else reg.m3.flag(reg.windows(result))
    anomalies = reg.m3.anomalous_stages(flagged)
    kpis = costs.run_kpis(events, result["config"]["horizon_days"])
    reference, reference_run_id = _reference_durations(state, row)

    stages = []
    for order, stage in enumerate(C.STAGES):
        r = ranked.loc[stage]
        a = anomalies.get(stage, {})
        expected = (reference or {}).get(stage)
        ratio = (float(r["mean_duration"]) / expected) if expected else None
        cfg = result["config"]["stages"][stage]
        stages.append({
            "stage": stage,
            "macro_stage": C.macro_stage_for(stage),
            "order": order,
            "mean_wait_hours": float(r["mean_wait"]),
            "mean_service_hours": float(r["mean_service"]),
            "mean_duration_hours": float(r["mean_duration"]),
            "wait_to_service_ratio": float(r["wait_to_service_ratio"]),
            "utilisation": float(r["utilisation"]),
            "queue_wait_share": float(r["queue_wait_share"]),
            "contribution_pct": float(r["contribution_pct"]),
            "rank": int(r["rank"]),
            "anomalous": stage in anomalies,
            "anomaly_share": float(a.get("share", 0.0)),
            "anomalous_windows": int(a.get("n_anomalous_windows", 0)),
            "servers": int(cfg["servers"]),
            "weekend_servers": int(cfg.get("weekend_servers", cfg["servers"])),
            "expected_duration_hours": expected,
            "duration_vs_expected": ratio,
            "health": _health_band(ratio),
        })

    return clean({
        "run_id": row["run_id"],
        "label": row["label"],
        "parent_run_id": row["parent_run_id"],
        "health_reference_run_id": reference_run_id,
        "kpis": kpis,
        "stages": stages,
        # Process map: fixed linear pipeline.
        "macro_stages": [
            {
                "macro_stage": macro,
                "activities": stages_in_macro,
                "contribution_pct": float(sum(
                    s["contribution_pct"] for s in stages
                    if s["macro_stage"] == macro
                )),
            }
            for macro, stages_in_macro in C.STAGE_GROUPS
        ],
        "edges": [{"from": a, "to": b} for a, b in zip(C.STAGES, C.STAGES[1:])],
    })


@router.get("/bottlenecks/ranking")
def bottleneck_ranking(run_id: str = None):
    """M2 ranked output with per-stage percentage contribution."""
    state = get_state()
    reg = state.models()
    row = state.run_row(run_id)
    ranked = reg.ranking(state.run_result(row["run_id"]))

    return clean({
        "run_id": row["run_id"],
        "weights": {"queue_wait_share": 0.45, "utilisation": 0.30, "residual_share": 0.25},
        "stages": [
            {
                "rank": int(r["rank"]),
                "stage": r["stage"],
                "macro_stage": C.macro_stage_for(r["stage"]),
                "score": float(r["score"]),
                "contribution_pct": float(r["contribution_pct"]),
                "queue_wait_share": float(r["queue_wait_share"]),
                "utilisation": float(r["utilisation"]),
                "residual_share": float(r["residual_share"]),
                "mean_wait_hours": float(r["mean_wait"]),
                "mean_duration_hours": float(r["mean_duration"]),
            }
            for _, r in ranked.iterrows()
        ],
    })


@router.get("/models/metrics")
def model_metrics():
    """The four metric cards. Computed at training time against `ground_truth`,
    which is the only place that table is ever read."""
    reg = get_state().models()
    return {
        "cards": reg.cards,
        "note": "Scored against ground_truth, which no model trains on.",
    }
