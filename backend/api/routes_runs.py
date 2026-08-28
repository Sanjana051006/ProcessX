"""P5.1 -- run lifecycle endpoints. These are write paths (§A3)."""

from fastapi import APIRouter, HTTPException

from backend import db
from backend.api.deps import get_state
from backend.models import registry
from backend.sim import engine, persist, scenarios

router = APIRouter(prefix="/api/runs", tags=["runs"])

_LABELS = {
    "healthy": "Healthy baseline",
    "bottleneck_a": "Bottleneck A injected",
}


def _simulate_and_store(scenario, run_id, parent_run_id=None):
    result = engine.simulate(scenarios.scenario_config(scenario))
    truth = dict(scenarios.ground_truth_for(scenario))
    truth["injected_at"] = (scenarios.INJECTED_AT_HOURS
                            if scenario == "bottleneck_a" else None)
    kpis = persist.write_run(result, run_id, label=_LABELS[scenario],
                             parent_run_id=parent_run_id, ground_truth=truth)
    get_state().cache_run(run_id, result)
    return result, kpis


@router.post("/reset")
def reset(retrain: bool = False):
    """Drop everything and regenerate the healthy baseline world.

    Models are reloaded from the artifact rather than refitted: the baseline
    world is a pure function of the master seed, so the persisted models are
    still the right ones, and a 40 s fit inside a demo beat is not acceptable.
    Pass `retrain=true` to force the fit anyway.
    """
    state = get_state()
    db.reset()
    state.clear_runs()
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
        "label": _LABELS["healthy"],
        "kpis": kpis,
        "models_loaded": state.registry is not None,
        "retrained": retrain,
    }


@router.post("/inject/{scenario}")
def inject(scenario: str):
    """Inject a scenario as a new run, which becomes the current world."""
    if scenario not in ("bottleneck_a", "healthy"):
        raise HTTPException(
            status_code=404,
            detail="Unknown scenario '%s'. Bottleneck B is never injected -- it "
                   "emerges from fixing A (Status §A1)." % scenario)

    state = get_state()
    parent = None
    if db.get_conn().execute(
            "SELECT 1 FROM runs WHERE run_id = 'baseline'").fetchone():
        parent = "baseline"

    run_id = scenario
    _, kpis = _simulate_and_store(scenario, run_id, parent_run_id=parent)
    return {"run_id": run_id, "label": _LABELS[scenario],
            "parent_run_id": parent, "kpis": kpis}


@router.get("")
def list_runs():
    rows = db.get_conn().execute(
        "SELECT run_id, parent_run_id, label, created_at, mean_cycle_hours,"
        " cost_per_case, throughput_per_day FROM runs ORDER BY created_at").fetchall()
    return {"runs": [dict(r) for r in rows],
            "current_run_id": get_state().current_run_id() if rows else None}
