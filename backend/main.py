"""ProcessX API.

Run from the repository root:
    .venv/Scripts/uvicorn backend.main:app --reload --port 8000

The 11 endpoints are frozen in Status §A9. Writer discipline (§A3): only
reset / inject / investigate / apply write; every read endpoint is read-only.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import db
from backend.api import routes_actions, routes_agent, routes_read, routes_runs
from backend.api.deps import get_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    # Load the persisted models once at startup. Absent is not fatal -- the
    # endpoints that need them say so with a 503 naming the bootstrap command.
    get_state().load_models(required=False)
    yield


app = FastAPI(title="ProcessX", version="0.5.0", lifespan=lifespan)

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
