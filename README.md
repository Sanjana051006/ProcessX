# ProcessX

Agentic process intelligence over a simulated **business lifecycle** —
onboarding → order processing → claims → support → invoice approval, 24
activities in five macro-stages. A discrete-event simulator generates the
world; six components (M1–M6) predict process times, rank bottlenecks, detect
anomalies, classify causes, simulate interventions and pick the best one under
a budget; an agent loop drives them and re-plans after a fix.

Docs: [ProcessX v2](docs/ProcessX_v2.md).

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
baseline and the claims-bottleneck world, writes ~89,000 event rows, then
trains M1–M4 and saves them to `backend/models/artifacts/models.joblib`.
Expect output ending like this:

```
     baseline       1847 cases | cycle  18.33 h | Rs  226.9/case | SLA breach 2.76%
     claims_bottleneck  1847 cases | cycle  19.08 h | Rs  238.3/case | SLA breach 3.74%

     metric cards
     M1  Process-time prediction    77.7% better than mean         PASS
     M2  Bottleneck detection       1.00 over 3 scenarios          PASS
     M3  Anomaly detection          8 h worst case                 PASS
     M4  Delay-cause prediction     0.99 over 169 windows          PASS

done in 98.5s. Demo start state is ready.
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

## Running the demo

The whole v2 story runs backend-only, no frontend and no server:

```bash
.venv/Scripts/python -m backend.scripts.v2_demo
```

It resets the database, simulates the healthy and constrained lifecycles,
trains M1–M4, follows one business case through all five macro-stages, ranks
bottlenecks by activity and by macro-stage, runs the agent investigation,
prices the interventions and applies the ROI-positive set. Takes ~40 s and
wipes the database, so re-run `bootstrap` afterwards if you want the demo
start state back.

To watch it over HTTP against a running backend instead:

```bash
bash backend/scripts/demo_curl.sh
```

---

## Verifying the build

```bash
.venv/Scripts/python -m backend.scripts.v2_verify
```

Prints `PASS` / `FAIL` per assertion and exits non-zero on any failure, so it
doubles as the test suite. It checks seven things: the simulator is
reproducible and every case walks all 24 activities; the healthy baseline has
no strained activity and no queue that fails to drain; every injected
constraint is stable and starts when its ground truth says it does; M1–M4 hold
up on faults in three macro-stages across both causes, and report `normal`
where nothing is wrong; the agent reaches the right conclusion and stops for a
stated reason rather than running out of probes; M5/M6 pick an ROI-positive
action that measurably helps; and storage round-trips without leaking ground
truth into the feature tables. Takes ~20 minutes and wipes the database —
re-run `bootstrap` afterwards.

There are three fault scenarios. `claims_bottleneck` is the one the demo
narrates; `support_staffing` and `fulfilment_saturation` exist so the metric
cards are scored on more than one activity and more than one cause. All three
can be injected over the API:

```bash
curl -X POST http://localhost:8000/api/runs/inject/support_staffing
```

---

## Layout

```
backend/
  db.py                  connection, PRAGMAs, schema, reset()
  main.py                FastAPI app, CORS, /api/health
  sim/
    config.py            frozen constants, intervention catalogue, ROI model
    engine.py            discrete-event loop -> event rows
    scenarios.py         healthy baseline, claims-bottleneck injection
    costs.py             derived time and cost columns
    persist.py           bulk writes -- the only module that writes
  baseline.py            the fixed-rule comparator the agent has to beat
  jsonsafe.py            inf/nan -> null, so real ratios can be serialised
  api/
    deps.py              shared app state: models, current run, run cache
    routes_runs.py       reset, inject
    routes_read.py       stages/health (incl. map), ranking, model metrics
    routes_agent.py      investigate, investigation, tree, interventions
    routes_actions.py    apply, baseline/compare
  agent/
    state.py             ProcessState -- health, evidence, hypotheses, budget
    probes.py            stage probe, factor probe, expected information gain
    policy.py            probe selection score and the stopping rule
    controller.py        the investigate loop and the re-planning path
  models/
    features.py          per case-stage and per stage-hour feature builders
    m1_process_time.py   GradientBoostingRegressor + residuals
    m2_bottleneck.py     stage scoring and ranking
    m3_anomaly.py        IsolationForest over hourly windows
    m4_cause.py          3-class cause classifier + its own training corpus
    m5_impact.py         counterfactual simulate() + seed replicates
    m6_roi.py            benefit model + greedy budget selection
    registry.py          train-all, persist, the four metric cards
  scripts/               bootstrap, the backend-only demo, the curl walkthrough
frontend/src/            React 19, no router, no state library, no chart library
docs/                    ProcessX v2 spec
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
`bootstrap` or `v2_demo`.

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
