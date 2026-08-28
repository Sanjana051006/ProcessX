"""ProcessX API.

Run from the repository root:
    .venv/Scripts/uvicorn backend.main:app --reload --port 8000

Writer discipline: only
reset / inject / investigate / apply write; every read endpoint is read-only.
"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import analytics, db
from backend.api import (
    routes_actions,
    routes_agent,
    routes_chat,
    routes_dashboard,
    routes_read,
    routes_runs,
)
from backend.api.deps import get_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    # Load the persisted models once at startup. Absent is not fatal -- the
    # endpoints that need them say so with a 503 naming the bootstrap command.
    state = get_state()
    state.load_models(required=False)
    # Warm the activity table for the current world off the request path. It
    # costs an M1 residual pass over the whole event log, and every dashboard
    # panel wants it -- paying for it here means the first page load is instant
    # rather than three seconds. Failure is not fatal: a database with no runs
    # yet, or no trained models, simply skips it.
    threading.Thread(target=_warm, args=(state,), daemon=True).start()
    yield


def _warm(state):
    try:
        analytics.stage_table(state)
    except Exception:
        pass


app = FastAPI(title="ProcessX", version="0.6.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_runs.router)
app.include_router(routes_read.router)
app.include_router(routes_agent.router)
app.include_router(routes_actions.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_chat.router)


@app.get("/api/health")
def health():
    """Liveness, plus the facts P0.8 checks and whether models are loaded."""
    conn = db.get_conn()
    state = get_state()
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    present = {r["name"] for r in
               conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    indexes = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'ix_%'")}
    n_runs = conn.execute("SELECT count(*) FROM runs").fetchone()[0] \
        if "runs" in present else 0

    return {
        "status": "ok",
        "journal_mode": journal_mode,
        "db_path": str(db.DB_PATH),
        "tables": sorted(present & set(db.TABLES)),
        "missing_tables": sorted(set(db.TABLES) - present),
        "indexes": sorted(indexes),
        "models_loaded": state.registry is not None,
        "n_runs": n_runs,
        "current_run_id": state.current_run_id() if n_runs else None,
    }
