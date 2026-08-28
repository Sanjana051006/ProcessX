"""ProcessX API.

Run from the repository root:
    .venv/Scripts/uvicorn backend.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    yield


app = FastAPI(title="ProcessX", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    """Liveness plus the two facts P0.8 checks: WAL is on and the schema is present."""
    conn = db.get_conn()
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    present = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    indexes = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'ix_%'"
        )
    }
    return {
        "status": "ok",
        "journal_mode": journal_mode,
        "db_path": str(db.DB_PATH),
        "tables": sorted(present & set(db.TABLES)),
        "missing_tables": sorted(set(db.TABLES) - present),
        "indexes": sorted(indexes),
    }
