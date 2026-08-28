"""SQLite storage for ProcessX.

Connection settings, PRAGMAs, indexes and writer rules are frozen in
the connect() body below — do not tune it.

Writer discipline: only the simulate / agent / apply paths write.
Read endpoints never write. Bulk inserts go through executemany() inside one
explicit BEGIN/COMMIT — never row-by-row.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "processx.db"


def connect():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,   # FastAPI serves from a threadpool
        isolation_level=None,      # autocommit; we manage transactions explicitly
    )
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode = WAL;         -- concurrent reads during writes
        PRAGMA synchronous  = NORMAL;      -- safe with WAL, much faster than FULL
        PRAGMA busy_timeout = 5000;        -- wait 5s for a lock instead of erroring
        PRAGMA foreign_keys = ON;
        PRAGMA temp_store   = MEMORY;
        PRAGMA cache_size   = -64000;      -- 64 MB page cache
    """)
    return conn


# One module-level connection, reused. No per-request connections.
_conn = connect()


def get_conn():
    return _conn


# The 8 tables. kpi_history is cut — before/after metrics are read
# from the runs table.
TABLES = [
    "event_log",
    "cases",
    "ground_truth",
    "runs",
    "investigations",
    "investigation_nodes",
    "interventions",
    "baseline_decisions",
]

SCHEMA = """
-- Generated event log. One row per (case, stage).
CREATE TABLE IF NOT EXISTS event_log (
    id                   INTEGER PRIMARY KEY,
    run_id               TEXT,
    case_id              INTEGER,
    macro_stage          TEXT,
    stage                TEXT,
    arrival_ts           REAL,
    start_ts             REAL,
    end_ts               REAL,
    resource_id          TEXT,
    queue_len_at_arrival INTEGER,
    servers_busy         INTEGER
);

-- Per-case attributes, joined into feature sets.
-- The primary key is composite: every run replays the SAME arrival stream from
-- the master seed, so case_id 1 exists in every run and is only unique together
-- with run_id. A bare `case_id INTEGER PK` would collide
-- on the second run.
CREATE TABLE IF NOT EXISTS cases (
    case_id         INTEGER,
    run_id          TEXT,
    order_value     REAL,
    customer_tier   TEXT,
    customer_segment TEXT,
    priority        TEXT,
    is_new_customer INTEGER,
    fraud_risk      REAL,
    region          TEXT,
    item_category   TEXT,
    claim_type      TEXT,
    claim_severity  REAL,
    support_channel TEXT,
    invoice_value   REAL,
    invoice_exception INTEGER,
    invoice_exception_reason TEXT,
    created_ts      REAL,
    weekday         INTEGER,
    hour            INTEGER,
    needs_review    INTEGER,
    PRIMARY KEY (run_id, case_id)
);

-- Evaluation only. Models never train on this.
CREATE TABLE IF NOT EXISTS ground_truth (
    run_id           TEXT,
    bottleneck_stage TEXT,
    true_cause       TEXT,
    injected_at      REAL
);

-- One row per world-state (baseline, post-intervention-1, ...).
CREATE TABLE IF NOT EXISTS runs (
    run_id             TEXT PRIMARY KEY,
    parent_run_id      TEXT,
    label              TEXT,
    config_json        TEXT,
    created_at         REAL,
    mean_cycle_hours   REAL,
    cost_per_case      REAL,
    throughput_per_day REAL
);

-- Agent investigations.
CREATE TABLE IF NOT EXISTS investigations (
    inv_id          TEXT PRIMARY KEY,
    run_id          TEXT,
    started_at      REAL,
    status          TEXT,
    concluded_stage TEXT,
    concluded_cause TEXT,
    confidence      REAL
);

CREATE TABLE IF NOT EXISTS investigation_nodes (
    node_id         TEXT PRIMARY KEY,
    inv_id          TEXT,
    parent_node_id  TEXT,
    depth           INTEGER,
    seq             INTEGER,
    probe_type      TEXT,          -- 'stage' | 'factor'
    target          TEXT,          -- e.g. 'order_validation' or 'weekday=Sat'
    selection_score REAL,
    impact          REAL,
    uncertainty     REAL,
    evidence_json   TEXT,
    hypotheses_json TEXT,
    reasoning       TEXT
);

-- Candidate actions and their simulated outcomes.
CREATE TABLE IF NOT EXISTS interventions (
    int_id                TEXT PRIMARY KEY,
    inv_id                TEXT,
    stage                 TEXT,
    action                TEXT,
    cost                  REAL,
    predicted_delta_hours REAL,
    ci_low                REAL,
    ci_high               REAL,
    benefit_30d           REAL,
    roi                   REAL,
    selected              INTEGER,
    applied               INTEGER
);

-- Fixed-rule comparison.
CREATE TABLE IF NOT EXISTS baseline_decisions (
    run_id        TEXT,
    chosen_stage  TEXT,
    chosen_action TEXT,
    cost          REAL,
    roi           REAL
);

-- Locked indexes.
CREATE INDEX IF NOT EXISTS ix_event_run_stage ON event_log(run_id, stage);
CREATE INDEX IF NOT EXISTS ix_event_case      ON event_log(run_id, case_id);
CREATE INDEX IF NOT EXISTS ix_cases_run       ON cases(run_id);
CREATE INDEX IF NOT EXISTS ix_nodes_inv       ON investigation_nodes(inv_id, seq);
CREATE INDEX IF NOT EXISTS ix_int_inv         ON interventions(inv_id);
"""


def init_schema(conn=None):
    """Create the 8 tables and 5 indexes if absent. Called at app startup."""
    (conn or _conn).executescript(SCHEMA)


def reset(conn=None):
    """Drop and recreate everything. There are no migrations — this is the
    only way the schema changes, and it is what POST /api/runs/reset calls."""
    conn = conn or _conn
    drops = "\n".join(f"DROP TABLE IF EXISTS {t};" for t in TABLES)
    conn.executescript(drops)
    conn.executescript(SCHEMA)
