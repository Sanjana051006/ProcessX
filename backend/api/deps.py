"""Shared state for the API layer.

Two things every endpoint needs: the trained models, and the world a request is
talking about.

The "current run" is NOT held in memory -- it is the most recently created row
in `runs`. That keeps the API restart-safe without adding a ninth table, and it is correct by construction: reset, inject and
apply each create the run that should become current.

Run frames are rebuilt by re-simulating from the config stored on the row. At
0.3 s a world that is cheaper than reading 39k rows back out of SQLite, and it
doubles as a continuous reproducibility check -- if a stored config ever failed
to reproduce its own run, every read endpoint would show it.
"""

import json

from fastapi import HTTPException

from backend import db
from backend.models import registry
from backend.sim import engine

_MODELS_MISSING = (
    "Models are not loaded. Run:  python -m backend.scripts.bootstrap")


class AppState:
    def __init__(self):
        self.registry = None
        self._runs = {}

    # ------------------------------------------------------------- models ---
    def load_models(self, required=False):
        """Load the persisted artifact. Never trains inside a request -- a fit
        is ~40 s and would hold a connection open for the whole demo beat."""
        if self.registry is not None:
            return self.registry
        if registry.ARTIFACT_PATH.exists():
            self.registry = registry.Registry.load()
        elif required:
            raise HTTPException(status_code=503, detail=_MODELS_MISSING)
        return self.registry

    def models(self):
        reg = self.load_models(required=True)
        if reg is None:
            raise HTTPException(status_code=503, detail=_MODELS_MISSING)
        return reg

    def set_registry(self, reg):
        self.registry = reg

    def invalidate_models(self):
        """After a reset the models must come back from the artifact: an apply
        earlier in the session refitted M1 on a child world, and that state
        must not leak across a reset."""
        self.registry = None

    # --------------------------------------------------------------- runs ---
    def current_run_id(self):
        row = db.get_conn().execute(
            "SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="No runs exist. POST /api/runs/reset first, or run bootstrap.")
        return row["run_id"]

    def resolve(self, run_id=None):
        return run_id or self.current_run_id()

    def run_row(self, run_id=None):
        run_id = self.resolve(run_id)
        row = db.get_conn().execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown run: " + run_id)
        return dict(row)

    def run_result(self, run_id=None):
        """The simulate() frames for a run, cached per process."""
        run_id = self.resolve(run_id)
        if run_id not in self._runs:
            row = self.run_row(run_id)
            self._runs[run_id] = engine.simulate(json.loads(row["config_json"]))
        return self._runs[run_id]

    def cache_run(self, run_id, result):
        self._runs[run_id] = result

    def clear_runs(self):
        self._runs.clear()


STATE = AppState()


def get_state():
    return STATE
