"""Dashboard and simulation-panel endpoints. Read-only.

These sit alongside the original read routes rather than replacing them: the
originals are the documented API surface, these are the shapes the UI actually
renders — the activity table with its labels, the macro rollup, a case's journey
and the nine pipeline panels the simulation view steps through.
"""

from fastapi import APIRouter, HTTPException

from backend import analytics
from backend.api.deps import get_state
from backend.jsonsafe import clean

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/overview")
def overview(run_id: str = None):
    """KPI header: cycle time, cost, throughput, SLA, worst activity, anomalies."""
    return analytics.overview(get_state(), run_id)


@router.get("/stages")
def stages(run_id: str = None):
    """The 24-activity table with health bands and bottleneck ranks."""
    return clean(analytics.stage_table(get_state(), run_id))


@router.get("/macro")
def macro(run_id: str = None):
    """The 5 macro-stages rolled up."""
    return clean(analytics.macro_table(get_state(), run_id))


@router.get("/process-map")
def process_map():
    """The static process shape and the frozen simulator constants."""
    return analytics.process_map()


@router.get("/scenarios")
def scenarios():
    """Every injectable fault scenario with its ground truth."""
    return {"scenarios": analytics.scenario_catalogue()}


@router.get("/catalogue")
def catalogue(stage: str = None):
    """Every intervention the simulator can apply."""
    return {"actions": analytics.intervention_catalogue(stage)}


@router.get("/cases")
def cases(run_id: str = None, limit: int = 40, sort: str = "cycle_desc"):
    """Browsable case list for the simulation panel's case picker."""
    return clean(analytics.case_index(get_state(), run_id, limit=limit, sort=sort))


@router.get("/cases/{case_id}/journey")
def case_journey(case_id: int, run_id: str = None):
    """One case through all 24 activities, with M1's prediction at every step."""
    try:
        return analytics.case_journey(get_state(), run_id, case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pipeline")
def pipeline(run_id: str = None, case_id: int = None, refresh: bool = False):
    """The nine panels the simulation view steps through.

    In order: the simulated world, M1, M2, M3, the agent's investigation, M4,
    M5, M6, and the measured outcome of applying what M6 chose. Computed once
    per (run, case) and cached — the whole chain is deterministic on seed 42, so
    a second call is the same answer and should not cost another 8 seconds.
    """
    return analytics.pipeline(get_state(), run_id, case_id, refresh=refresh)
