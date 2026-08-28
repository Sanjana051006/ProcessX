"""Run lifecycle endpoints. These are write paths."""

from fastapi import APIRouter, HTTPException

from backend import analytics, db
from backend.api.deps import get_state
from backend.models import registry
from backend.sim import engine, persist, scenarios

router = APIRouter(prefix="/api/runs", tags=["runs"])

def _simulate_and_store(scenario, run_id, parent_run_id=None):
    result = engine.simulate(scenarios.scenario_config(scenario))
    truth = dict(scenarios.ground_truth_for(scenario))
    truth["injected_at"] = scenarios.injected_at(scenario)
    kpis = persist.write_run(
        result,
        run_id,
        label=scenarios.label_for(scenario),
        parent_run_id=parent_run_id,
        ground_truth=truth,
    )
    get_state().cache_run(run_id, result)
    return result, kpis


@router.post("/reset")
def reset(retrain: bool = False):
    """Drop everything and regenerate the healthy baseline world."""
    state = get_state()
    db.reset()
    state.clear_runs()
    analytics.invalidate_pipeline()
    state.invalidate_models()

    _, kpis = _simulate_and_store("healthy", "baseline")

    if retrain:
        healthy = state.run_result("baseline")
        reg = registry.Registry().train(healthy, healthy, verbose=False)
        reg.save()
        state.set_registry(reg)
    else:
        state.load_models(required=False)

    return {
        "run_id": "baseline",
        "label": scenarios.label_for("healthy"),
        "kpis": kpis,
        "models_loaded": state.registry is not None,
        "retrained": retrain,
    }


@router.post("/inject/{scenario}")
def inject(scenario: str):
    """Inject a scenario as a new run, which becomes the current world."""
    if scenario not in scenarios.SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail="Unknown scenario '%s'. Known scenarios: %s."
            % (scenario, ", ".join(sorted(scenarios.SCENARIOS))),
        )

    state = get_state()
    parent = None
    if db.get_conn().execute(
        "SELECT 1 FROM runs WHERE run_id = 'baseline'"
    ).fetchone():
        parent = "baseline"

    analytics.invalidate_pipeline(scenario)
    _, kpis = _simulate_and_store(scenario, scenario, parent_run_id=parent)
    return {
        "run_id": scenario,
        "label": scenarios.label_for(scenario),
        "parent_run_id": parent,
        "kpis": kpis,
    }


@router.get("")
def list_runs():
    rows = db.get_conn().execute(
        "SELECT run_id, parent_run_id, label, created_at, mean_cycle_hours,"
        " cost_per_case, throughput_per_day FROM runs ORDER BY created_at"
    ).fetchall()
    return {
        "runs": [dict(r) for r in rows],
        "current_run_id": get_state().current_run_id() if rows else None,
    }
