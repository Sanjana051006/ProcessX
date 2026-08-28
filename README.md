# ProcessX

Agentic process intelligence over a simulated **NovaCart** order-fulfilment
pipeline. A discrete-event simulator generates the world; six components
(M1–M6) predict process times, rank bottlenecks, detect anomalies, classify
causes, simulate interventions and pick the best one under a budget; an agent
loop drives them and re-plans when a second bottleneck appears.

Docs: [PRD](docs/PRD.md) · [Architecture](docs/Architecture.md) ·
[Status](docs/Status.md) — Status §A holds the frozen decisions, §C the
decision log, §D open items.

---

## Prerequisites

| | Version | Check |
|---|---|---|
| Python | **3.11** | `python --version` |
| Node.js | **20.19+** (22 LTS recommended) | `node --version` |

Python 3.11 specifically: the pinned `pandas` / `numpy` / `scikit-learn`
versions are built against it, and the demo has to reproduce identically on
seed 42 across machines.

> If `python` on your PATH is not 3.11, use the full path to a 3.11 interpreter
> in the `venv` step below (e.g. `py -3.11 -m venv .venv` on Windows).

---

## Setup

Four steps from a fresh clone. Takes about three minutes, most of it the
model fit in step 4.

### 1. Clone and enter

```bash
git clone <repo-url> ProcessX && cd ProcessX
```

### 2. Python environment

**Windows** (PowerShell or Git Bash):

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

**macOS / Linux:**

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### 3. Frontend dependencies

```bash
cd frontend && npm install && cd ..
```

### 4. Build the database and train the models

**This step is not optional.** The SQLite file and the trained model
artifacts are both gitignored — they are generated output, not source — so a
fresh clone has neither. This command creates both:

```bash
.venv/Scripts/python -m backend.scripts.bootstrap
```

macOS / Linux: `.venv/bin/python -m backend.scripts.bootstrap`

It drops and recreates the 8 tables and 5 indexes, simulates the healthy
baseline and the bottleneck-A world, writes ~78,000 event rows, then trains
M1–M4 and saves them to `backend/models/artifacts/models.joblib`. Expect
output ending like this:

```
     metric cards
     M1  Process-time prediction    76.2% better than mean         PASS
     M2  Bottleneck detection       1.00 over 2 scenarios          PASS
     M3  Anomaly detection          2 h worst case                 PASS
     M4  Delay-cause prediction     1.00 over 605 windows          PASS

done in 40.4s. Demo start state is ready.
```

If your four numbers match those exactly, your environment reproduces the
reference machine. Add `--no-train` to skip the model fit and get just the
database (~2 s) when you only need data.

**Run every Python command from the repository root**, not from `backend/` —
the modules import as `backend.sim.engine`, `backend.models.registry` and so
on, which needs the root on `sys.path`.

---

## Running it

Two terminals.

**Backend** (port 8000):

```bash
.venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000
```

macOS / Linux: `.venv/bin/python -m uvicorn backend.main:app --reload --port 8000`

**Frontend** (port 5173):

```bash
cd frontend && npm run dev
```

Then open <http://localhost:5173>. The page reads `GET /api/health` across
origins, so it also confirms CORS is working. A healthy setup shows
`journal_mode: wal`, `Tables 8 / 8`, `Indexes 5 / 5`.

Check the backend on its own with:

```bash
curl http://localhost:8000/api/health
```

---

## Verifying a phase

Each implementation phase has a self-checking script. They print `PASS` /
`FAIL` per assertion and exit non-zero on any failure, so they double as the
test suite. Run them from the repository root.

```bash
.venv/Scripts/python -m backend.scripts.p1_verify
```

| Script | Covers | Runtime |
|---|---|---|
| `backend.scripts.p1_verify` | Simulator, reproducibility, **the cascade** | ~6 s |
| `backend.scripts.p2_verify` | M1–M4, the four metric cards, ground-truth separation | ~90 s |
| `backend.scripts.p3_verify` | M5 counterfactuals, M6 ROI, **the ROI ordering** | ~25 s |

`p1_verify` and `p3_verify` call `db.reset()`, so they wipe the database.
Re-run `bootstrap` afterwards to get back to the demo start state.

---

## Layout

```
backend/
  db.py                  connection, PRAGMAs, schema, reset()
  main.py                FastAPI app, CORS, /api/health
  sim/
    config.py            frozen constants, intervention catalogue, ROI model
    engine.py            discrete-event loop -> event rows
    scenarios.py         healthy baseline, bottleneck-A injection
    costs.py             derived time and cost columns
    persist.py           bulk writes -- the only module that writes
  models/
    features.py          per case-stage and per stage-hour feature builders
    m1_process_time.py   GradientBoostingRegressor + residuals
    m2_bottleneck.py     stage scoring and ranking
    m3_anomaly.py        IsolationForest over hourly windows
    m4_cause.py          3-class cause classifier + its own training corpus
    m5_impact.py         counterfactual simulate() + seed replicates
    m6_roi.py            benefit model + greedy budget selection
    registry.py          train-all, persist, the four metric cards
  scripts/               bootstrap + per-phase verification runners
frontend/src/            React 19, no router, no state library, no chart library
docs/                    PRD, Architecture, Status
```

---

## Reproducibility

Everything keys off **master seed 42**. One simulated world takes ~0.3 s, and
arrivals, case attributes and per-(case, stage) service shocks all come from a
seed-only random stream — so a counterfactual differs from its baseline *only*
by the intervention, never by sampling noise. Re-running `bootstrap` on any
machine should reproduce the numbers above exactly.

Generated files, all gitignored: `backend/processx.db` (plus its `-wal` and
`-shm` sidecars), `backend/models/artifacts/`, `frontend/node_modules/`,
`.venv/`.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'backend'`**
You are not in the repository root. `cd` to the directory containing
`backend/` and `frontend/` and re-run.

**`sqlite3.OperationalError: database is locked`, or "device or resource busy"
when deleting the DB**
A `uvicorn` process still holds the file. Stop the backend before running
`bootstrap` or any `*_verify` script.

**`FileNotFoundError: ... models.joblib`**
The models have not been trained on this machine. Run `bootstrap` (without
`--no-train`).

**Frontend shows "Backend unreachable"**
The backend is not running, or is on a different port. It must be on 8000 —
that is what `frontend/src/api.js` targets and what the CORS allow-list in
`backend/main.py` is paired with.

**`npm install` fails on the Node version**
Vite 8 needs Node 20.19+ or 22.12+. Check with `node --version`.

**The four metric numbers differ from the ones above**
Almost always a dependency-version drift. Confirm the venv is active and
matches `requirements.txt` — `pandas` 3.x and `numpy` 2.x are recent majors
and unpinned installs will not reproduce.
