# Status — ProcessX

Living implementation tracker. See [PRD.md](PRD.md) for scope and [Architecture.md](Architecture.md) for design.

**Legend:** `todo` · `doing` · `done` · `cut`

**Update protocol**
- Flip a step to `doing` when work starts, `done` when it is *verified working* — not when the code is merely written.
- Every completed step gets a Notes entry: what was built, the file path, and any deviation from plan.
- Nothing in §A changes once building starts. If something in §A must change, log it in the Decision log with a reason.

---

# §A — FROZEN DECISIONS

**Locked 2026-08-28, before implementation. Do not renegotiate mid-build.**

## A1. Scope

| Item | Locked value |
|------|--------------|
| Company | **NovaCart** (fictional e-commerce fulfilment; never labelled Amazon) |
| Stages | `order_validation` → `inventory_allocation` → `pick_pack` → `carrier_handover` → `last_mile` |
| Bottleneck A | `order_validation`, staffing shortage — weekend manual-review capacity drops 3 → 1 |
| Bottleneck B | `pick_pack`, capacity saturation — emerges from fixing A (throughput cascade), not planted |
| Simulation horizon | **30 days, ~8,000 cases** (cut from 60d/20k) |
| Master seed | **42** everywhere |
| Demo length | 3 minutes, 5 beats (PRD §8) |

## A2. Tech stack

| Layer | Locked |
|-------|--------|
| Frontend | React 19 + Vite. **No router, no state library, no chart library.** |
| Charts | **CSS bars only** — `div` with percentage width. Recharts cut. |
| Backend | FastAPI + uvicorn, Python 3.11 |
| ML | scikit-learn, pandas, numpy |
| Simulator | Plain Python event loop. No SimPy. |
| Datastore | SQLite, single file `backend/processx.db` |
| Ports | backend `:8000`, frontend `:5173` |

`pip install fastapi uvicorn pandas numpy scikit-learn`
`npm create vite@latest frontend -- --template react`

## A3. Database settings — LOCKED

Full contents of `backend/db.py` connection setup. Apply exactly; do not tune later.

```python
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
```

**Locked DB rules**

| Rule | Value |
|------|-------|
| Connection model | One module-level connection, reused. No per-request connections. |
| Writer discipline | Only the simulate / agent / apply paths write. Read endpoints never write. |
| Bulk inserts | `executemany` inside one explicit `BEGIN` / `COMMIT`. Never row-by-row. |
| Migrations | None. `CREATE TABLE IF NOT EXISTS` at startup + `POST /api/runs/reset` drops and recreates. |
| Analytics | pandas in memory via `pd.read_sql`. No analytical SQL. |
| Git | `processx.db`, `processx.db-wal`, `processx.db-shm` all gitignored. |

**Locked indexes** (created at startup with the tables):
```sql
CREATE INDEX IF NOT EXISTS ix_event_run_stage ON event_log(run_id, stage);
CREATE INDEX IF NOT EXISTS ix_event_case      ON event_log(run_id, case_id);
CREATE INDEX IF NOT EXISTS ix_cases_run       ON cases(run_id);
CREATE INDEX IF NOT EXISTS ix_nodes_inv       ON investigation_nodes(inv_id, seq);
CREATE INDEX IF NOT EXISTS ix_int_inv         ON interventions(inv_id);
```

**Locked tables:** `event_log`, `cases`, `ground_truth`, `runs`, `investigations`, `investigation_nodes`, `interventions`, `baseline_decisions`.
`kpi_history` is **cut** — before/after metrics are read from the `runs` table.

## A4. Simulator constants — LOCKED

| Stage | Servers | Mean service | Note |
|-------|---------|--------------|------|
| `order_validation` | 3 manual reviewers (weekday) | 25 min | ~35% of orders need manual review; rest auto-pass instantly |
| `inventory_allocation` | 6 | 8 min | |
| `pick_pack` | 5 | 22 min | Sized for utilisation ≈ **0.82** pre-fix — this is what makes B latent |
| `carrier_handover` | 4 | 6 min | |
| `last_mile` | 40 | 14 h | **Naturally the longest stage** — this is what the fixed-rule baseline wrongly picks |

- Arrivals: non-homogeneous Poisson, ~11/hour mean, weekend multiplier 1.6, evening peak 1.4.
- Service distribution: lognormal.
- **Rework loops: CUT.** No `visit_no`, no revisit logic. Queues and capacity alone produce both bottlenecks.
- Counterfactual: `simulate(config, overrides, seed)` — same seed reproduces identical arrivals, so Δ is attributable to the intervention.

## A5. Models — LOCKED

| ID | Spec |
|----|------|
| M1 | `GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.1, random_state=42)`. Time-based train/test split. Exposes residuals. |
| M2 | Deterministic score: `0.45 × queue_wait_share + 0.30 × utilisation + 0.25 × M1_residual_share`. Ranked, with % contribution. |
| M3 | `IsolationForest(n_estimators=100, contamination=0.05, random_state=42)`, **fit on healthy baseline windows only**. Hourly stage features. Agent trigger. |
| M4 | `GradientBoostingClassifier(n_estimators=150, max_depth=3, random_state=42)`. **3 classes** (cut from 5): `staffing_shortage`, `capacity_saturation`, `normal`. `vendor_wait` and `rework_loop` cut. |
| M5 | Counterfactual `simulate()` wrapper. **3 seed replicates** (42, 43, 44) → mean Δ + CI. Cut from 5. |
| M6 | Greedy ROI-per-rupee under a budget cap. No OR-Tools. |

**Key M4 feature — do not drop:** `wait_to_service_ratio`. It is what separates A (high ratio, normal service) from B (moderate ratio, degraded service).

**Ground truth never enters any feature set.** `ground_truth` is read only when computing metric cards.

## A6. Intervention catalogue — LOCKED (5 actions)

| Stage | Action | Cost (₹) | Effect |
|-------|--------|----------|--------|
| `order_validation` | `auto_approve_low_risk` (< ₹8k, risk < 0.2) | 40,000 one-time | −60% manual review volume |
| `order_validation` | `add_reviewers_2` | 180,000 / month | +2 reviewer capacity |
| `order_validation` | `weekend_shift_reallocation` | 25,000 / month | Moves existing capacity into the weekend peak |
| `pick_pack` | `add_evening_shift` | 150,000 / month | +40% capacity, 6h/day |
| `pick_pack` | `batch_route_optimisation` | 60,000 one-time | −15% service time |

`secondary_carrier` and `add_packing_station` **cut** — 3 options at A and 2 at B exceeds the "at least two" requirement.

## A7. ROI constants — LOCKED

```
holding_cost_per_hour = 12        # ₹ per case-hour of cycle time
sla_threshold_hours   = 48
sla_penalty_per_case  = 250       # ₹ per breached case
cases_per_day         = 270       # 8000 / 30
horizon_days          = 30

benefit_30d = delta_cycle_hours * cases_per_day * horizon_days * holding_cost_per_hour
            + sla_penalty_avoided
roi         = (benefit_30d - cost_30d) / cost_30d
```

**Required outcome (verified at P3.6):** `auto_approve_low_risk` ROI ≈ 7.5 beats `add_reviewers_2` ROI ≈ 1.3, despite saving less absolute time. If the ordering does not hold, adjust `holding_cost_per_hour` — not the story.

## A8. Agent constants — LOCKED

| Constant | Value |
|----------|-------|
| `max_probes` | 6 |
| `confidence_threshold` | 0.65 (top hypothesis probability to converge) |
| Selection score | `m2_impact_share × normalised_entropy(m4_proba)` |
| Factor probe dimensions | `weekday`, `order_value_band`, `is_new_customer`, `resource_id` |
| Budget cap | ₹250,000 for the 30-day horizon |
| Execution model | **Synchronous.** `POST /api/agent/investigate` runs the full loop and returns the complete tree. |

**Locked: no polling.** The frontend receives the finished tree and reveals nodes client-side at 400ms intervals. This looks identical to live growth, removes the polling hook, and eliminates concurrent-write pressure on SQLite entirely.

## A9. API surface — LOCKED (11 endpoints)

| Method | Path |
|--------|------|
| POST | `/api/runs/reset` |
| POST | `/api/runs/inject/{scenario}` |
| GET | `/api/stages/health` — includes process-map data (map endpoint merged in) |
| GET | `/api/bottlenecks/ranking` |
| GET | `/api/models/metrics` |
| POST | `/api/agent/investigate` |
| GET | `/api/agent/{inv_id}` |
| GET | `/api/agent/{inv_id}/tree` |
| GET | `/api/agent/{inv_id}/interventions` |
| POST | `/api/interventions/{int_id}/apply` |
| GET | `/api/baseline/compare` |

## A10. Cut list — final

| Cut | Saved | Why it is safe |
|-----|-------|----------------|
| Rework loops in the simulator | 0:20 | Queues + capacity produce both bottlenecks on their own |
| M4: 5 classes → 3 | 0:20 | Fewer classes also *raises* the accuracy metric card |
| Sim: 60d/20k → 30d/8k cases | 0:20 | Ample for the models; every counterfactual run gets faster too |
| M5 replicates: 5 → 3 | 0:10 | CI still meaningful |
| Catalogue: 7 → 5 actions | 0:10 | Requirement is "at least two" |
| Recharts → CSS bars | 0:15 | Horizontal bars are all we need; one less thing to break |
| Polling → synchronous + client-side reveal | 0:20 | Smoother demo, no lock risk |
| `kpi_history` table → read from `runs` | 0:05 | One less table and write path |
| Sparklines in Stage Health | 0:10 | Plain table reads fine |
| **Total saved** | **~2:10** | Budget 9:45 → **7:35** |

**Never cut, at any cost:** P1.10 (cascade verified), P3.6 (ROI ordering), P4.8 (agent correct on both scenarios with no code change). Those three *are* the demo.

## A11. Checkpoint gates — the anti-panic mechanism

Wall-clock from hour 0. At each gate, if the state is not reached, take the stated action **immediately** — do not push on hoping to catch up.

| Gate | Must be true | If not, do this |
|------|--------------|-----------------|
| **H+1:50** | P1 done — cascade verified on seed 42 | Cut horizon to 14 days, accept a rougher cascade, move on |
| **H+3:30** | M1–M4 metrics printed | Ship whatever accuracy exists. Stop tuning. Move to P3 |
| **H+4:20** | ROI ordering verified (P3.6) | Hard-set the two Δ values from a single sim run and move on |
| **H+5:30** | Agent works end to end in a script (P4.8) | **Hard gate.** Abandon all model tuning permanently. Go straight to P5/P6 |
| **H+6:00** | Whole demo drivable by curl | Cut the ModelMetrics panel from P6 |
| **H+7:10** | Dashboard done | Ship remaining panels as plain `<table>` |
| **H+7:35** | Two clean rehearsals | Stop building. Rehearse only |

Buffer at a 10-hour window: **2h 25m.** At an 8-hour window: 25m.

---

# §B — IMPLEMENTATION PHASES

## Overall progress

| Phase | Title | Budget | Status |
|-------|-------|--------|--------|
| P0 | Project setup + DB | 0:30 | done |
| P1 | Simulator + data foundation | 1:20 | done |
| P2 | Intelligence components M1–M4 | 1:40 | done |
| P3 | Impact simulation M5 + ROI M6 | 0:50 | done |
| P4 | State engine + agent controller | 1:10 | todo |
| P5 | API layer | 0:25 | todo |
| P6 | Dashboard | 1:15 | todo |
| P7 | Baseline + verification | 0:25 | todo |
| P8 | Demo rehearsal | 0:30 | todo |
| | **Total** | **7:35** | |

---

## P0 — Project setup + DB · budget 0:30

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P0.1 | `backend/` and `frontend/` skeletons per Architecture §4, §8 | done | `backend/` with `sim/ models/ agent/ api/` packages. Module files are created in their own phases rather than as empty stubs. |
| P0.2 | venv + `fastapi uvicorn pandas numpy scikit-learn` | done | `.venv` (Python 3.11.15). fastapi 0.141.1, uvicorn 0.52.4, pandas **3.0.5**, numpy **2.4.6**, scikit-learn 1.9.0. Note the new pandas/numpy majors for P1–P2. |
| P0.3 | Vite React app; **no extra frontend deps** | done | Vite 8.2.2 + React 19.2.8. Scaffold demo assets removed; nothing added. |
| P0.4 | `db.py` — connection + PRAGMA block **exactly as §A3** | done | [backend/db.py](../backend/db.py) — `connect()` is the §A3 block verbatim. One module-level connection via `get_conn()`. |
| P0.5 | `db.py` — `CREATE TABLE IF NOT EXISTS` for the 8 tables + 5 indexes; `reset()` | done | All 8 tables + 5 locked indexes. `reset()` drops and recreates; verified idempotent. **Deviation:** `event_log` also carries `queue_len_at_arrival` and `servers_busy` — both are required M1 features (Architecture §4.1) and there are no migrations, so they had to exist up front. |
| P0.6 | `main.py` — FastAPI, CORS for `localhost:5173`, schema init on startup, `/api/health` | done | [backend/main.py](../backend/main.py) — lifespan handler calls `init_schema()`. `/api/health` returns `journal_mode` + present tables/indexes so P0.8 is one request. |
| P0.7 | `.gitignore`: `processx.db*`, `__pycache__`, `node_modules`, `.venv` | done | Includes the `-wal` / `-shm` sidecars. Not yet a git repo. |
| P0.8 | Verify: `PRAGMA journal_mode` returns `wal`; frontend fetches `/api/health` | done | `journal_mode=wal`, `synchronous=1`, `busy_timeout=5000`, `cache_size=-64000`. 8/8 tables, 5/5 indexes. Frontend at :5173 renders them from a live cross-origin fetch; no console errors. |

**Exit:** both servers up, WAL confirmed, all tables + indexes present.

---

## P1 — Simulator + data foundation · budget 1:20

Highest-leverage phase. Produces ground truth, the counterfactual engine (M5), and the cascade.

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P1.1 | `sim/config.py` — stage table from §A4, arrival profile, catalogue from §A6, ROI constants from §A7 | done | [backend/sim/config.py](../backend/sim/config.py). Catalogue effects are *config patches*, not hard-coded outcomes — the simulator produces each effect causally. One §A4 deviation, logged in §C: `last_mile` servers. |
| P1.2 | `sim/engine.py` — non-homogeneous Poisson arrivals | done | Exact NHPP: Poisson count per hour bin, uniform placement inside the bin. Weekday×hour shape renormalised to a mean of 11/h, giving **7,801 cases** over 30 days. |
| P1.3 | `sim/engine.py` — per-stage queue, server allocation, lognormal service, event emission | done | Event heap with deterministic tie-breaks. **Time-varying capacity** (weekend headcount, evening shift) needed an hourly capacity tick so a queue wakes when a shift starts. Lognormal parameterised on its mean, so `service_factor` scales the mean exactly. |
| P1.4 | `simulate(config, overrides, seed)` — same seed → identical arrivals | done | Verified. Arrivals, attributes **and per-(case,stage) service shocks** all come from one seed-only RNG stream, so counterfactuals are paired (common random numbers) — this is what will keep the M5 CI tight. Re-running one config is bit-identical. |
| P1.5 | Case attributes: `order_value, customer_tier, is_new_customer, fraud_risk, region, item_category` | done | `order_value` lognormal (median ₹4k), `fraud_risk` Beta(1.2, 6.8) — **calibrated** so the §A6 auto-approve predicate covers 60% of cases. Realised reduction **61.3%** vs the frozen −60%. |
| P1.6 | `sim/scenarios.py` — healthy baseline, 30 days / ~8k cases | done | 7,801 cases; cycle 16.59 h, ₹199.2/case. Note the baseline is **not** uniformly quiet — see the M3 finding in §D. |
| P1.7 | Bottleneck A injection — weekend reviewer capacity 3 → 1 | done | Cycle 16.59 → **18.05 h**, p90 24.2 → 31.0 h, SLA breach 0.05% → 0.77%. Weekend review wait **6.09 h vs 0.70 h on weekdays** — the weekday concentration M4 needs. wait/service = 18.4 with service time unchanged: a wait problem, not a service problem. |
| P1.8 | `pick_pack` sized to utilisation ≈ 0.82 (B stays latent) | done | Realised **0.783** on the §A4 numbers unchanged. Pre-fix pick_pack wait 0.572 h vs order_validation 2.687 h, so it does not rank #1. `last_mile` is the longest stage (14.05 h) with a 0.0000 h queue — exactly the stage the fixed-rule baseline will wrongly pick. |
| P1.9 | Bulk-write `event_log`, `cases`, `ground_truth`, `runs` (single transaction, `executemany`) | done | [backend/sim/persist.py](../backend/sim/persist.py) (module added beyond Architecture §4 to keep `db.py` to connection + schema). One `BEGIN`/`COMMIT`, `executemany`, re-write of a run_id is idempotent. 78,010 event rows for the two runs. |
| P1.10 | **Verify the cascade** — apply A's fix, confirm `pick_pack` queue grows with no special-casing | **done** | **Passes on seed 42 for all three A-fixes.** pick_pack wait 0.572 → 1.69–1.73 h (**×3.0**) and it becomes the #1 ranked stage, while order_validation drops to ~0.08 h. Mechanism confirmed as throughput: weekend arrival rate into pick_pack **12.08/h → 14.93/h (+24%)** with its servers and service time byte-identical. |
| P1.11 | Derived-cost helper: `queue_wait`, `service_time`, `stage_cost`, `sla_penalty` | done | [backend/sim/costs.py](../backend/sim/costs.py) (module added beyond Architecture §4). Verified cycle time == Σ stage durations, and SLA penalty fires only above 48 h. Utilisation is busy-server-hours ÷ *offered* server-hours, read from the run's own config so a capacity intervention is measured against its new schedule. |
| P1.12 | Sanity assertions: no negative waits, every case visits 5 stages, cycle time rises after injection | done | All three, plus no unfinished events, `start_ts ≤ end_ts`, and ground truth absent from the `cases`/`events` frames. Runner: [backend/scripts/p1_verify.py](../backend/scripts/p1_verify.py) — 45 checks, ~6 s. |

**Exit:** P1.10 passes on seed 42. Gate **H+1:50** — **met.** The whole suite runs in ~6 s and one 30-day world simulates in ~0.3 s, so M5's 3-seed counterfactuals will be effectively free.

---

## P2 — Intelligence components M1–M4 · budget 1:40

Train and print metrics in a script. No UI, no API.

### P2.a — M1 process-time prediction
| ID | Step | Status | Notes |
|----|------|--------|-------|
| P2.1 | Per case-stage feature builder (Architecture §4.1) | done | [backend/models/features.py](../backend/models/features.py). Fixed categorical levels so the encoded matrix is identical across runs — a model fitted on one run can score another. Adds stage-arrival weekday/hour alongside the case-creation ones, and `needs_review` (without it nothing explains the 65% of zero-duration `order_validation` events). |
| P2.2 | Fit M1 per §A5; time-based split | done | Hyperparameters exactly as §A5. Split at hour 512 — 27,303 train / 11,702 test, verified strictly temporal (max train ts ≤ min test ts). Fit takes ~15 s. |
| P2.3 | Residuals exposed for M2 / M4 | done | `M1.residuals()` returns actual − predicted per event. Consumed by M2's third term and by M3's `mean_residual` window feature. **Not** used by M4 — see P2.12. |
| P2.4 | Metric: MAE vs mean-predictor, target > 30% better | done | **76.2%** better (MAE 1.216 h vs 5.113 h). Against a much tougher per-stage-mean predictor it is still **37.7%** better (1.216 h vs 1.951 h) — reported alongside, since the global mean is an easy bar when stage durations span 6 min to 14 h. |

### P2.b — M2 bottleneck detection
| ID | Step | Status | Notes |
|----|------|--------|-------|
| P2.5 | Stage score per §A5 weights | done | Weights exactly as §A5. **Deviation in one definition:** the residual term is an excess *rate* (positive residual ÷ that stage's own total duration), not a raw sum. Unnormalised, `last_mile`'s 14 h lognormal noise dwarfed every other stage's entire delay and handed it 74% of the residual term on variance alone. |
| P2.6 | Ranked output with % contribution | done | Ranked frame with per-stage `contribution_pct`. `impact_share()` exposes the normalised score as the agent's impact term (§A8). |
| P2.7 | Metric: precision@1 vs `ground_truth`, both scenarios | done | **1.00.** bottleneck_a → `order_validation` (42.6% contribution); cascade_b → `pick_pack` (55.4%). `last_mile` sits at **rank 4** in both despite having the longest mean duration (14.0 h) — the contrast P7.2 depends on. |

### P2.c — M3 anomaly detection
| ID | Step | Status | Notes |
|----|------|--------|-------|
| P2.8 | Hourly windowed stage features | done | Exact occupancy by interval overlap, not an approximation. Utilisation = mean concurrent servers ÷ the stage's own observed roster, so 1-of-3 reviewers reads as *low* utilisation with a long queue. 3,615 windows per 30-day run, ~0.3 s. |
| P2.9 | IsolationForest fit on healthy windows only | done | One model per stage (so `last_mile`'s 14 h service does not swamp `carrier_handover`'s 6 min), hyperparameters per §A5, on **2,606 healthy weekday windows** — the restriction from the P1.10 finding in §D. Added a **direction gate**: a window must also be worse than the healthy p95 on wait or utilisation. Without it a stage that was just *fixed* trips the trigger, because a forest flags *different*, not *worse*. |
| P2.10 | Anomaly flag per stage per window — the agent trigger | done | `flag()` per window; `anomalous_stages()` returns the trigger list. Requires 2 consecutive flagged windows — `contamination=0.05` guarantees ~5% of healthy windows trip, so a single flag is noise. |
| P2.11 | Metric: detection lead time, target < 6 simulated hours | done | **2.0 h** on the bottleneck-A injection, and `order_validation` is the most-flagged stage. The cascade is reported but **not scored**: B is not injected, so its +24 h figure measures how long the fault takes to *manifest*, not how long M3 takes to notice it. |

### P2.d — M4 delay-cause prediction
| ID | Step | Status | Notes |
|----|------|--------|-------|
| P2.12 | Features incl. `wait_to_service_ratio`, concentration by weekday / value band | done | All present. **M4's set is deliberately scale-free** (ratios, not magnitudes) so one classifier recognises the same pattern at a 6-minute stage and a 14-hour one. `mean_residual` is excluded from M4: its corpus is built without a per-run M1 fit, so a residual feature would be identically zero in training and non-zero at inference. |
| P2.13 | Fit 3-class classifier per §A5 | done | Hyperparameters per §A5, with balanced sample weights (faults are ~5% of windows; predicting `normal` everywhere otherwise scores 0.95). **Trained on its own corpus of 15 simulated worlds** with faults injected and labelled by construction, on seeds 301–503. Both demo scenarios are held out, so `ground_truth` is only ever read to score. |
| P2.14 | `predict_proba` → ranked hypotheses | done | A stage verdict aggregates window probabilities over the **deepest-queue 20%** of its strained windows, weighted by delay. Averaging over all of them gave the right answer at p ≈ 0.35 — below the agent's 0.65 bar — because the long tail of hours spent *draining* a backlog runs at full roster and genuinely looks like saturation. |
| P2.15 | Metric: accuracy vs `ground_truth.true_cause`, target > 0.8 | done | **1.00** over 605 windows; both stage verdicts at p = 1.000. Plus a generalisation test on 4 stage/severity combinations absent from the corpus, on unseen seeds — 4/4 correct, though one (inventory_allocation saturation) had only 4 strained windows and p = 0.37, so that one is weak evidence. See the caveat in §D. |
| P2.16 | `models/registry.py` — train-all, persist, 4 metric cards | done | [backend/models/registry.py](../backend/models/registry.py). Owns fit order (M1 before M3/M4, which consume its residuals) and is **the only place `ground_truth` is read**. Persists to `models/artifacts/models.joblib` (5.6 MB), round-trip verified. Full train ~36 s (M1 15.6, M3 2.1, M4 18.4). Runner: [backend/scripts/p2_verify.py](../backend/scripts/p2_verify.py). |

**Exit:** four metrics hitting targets on both scenarios. Gate **H+3:30** — **met.**

| Model | Metric | Target | Result |
|-------|--------|--------|--------|
| M1 | MAE vs mean-predictor | > 30% | **76.2%** (37.7% vs per-stage mean) |
| M2 | precision@1, both scenarios | 1.0 | **1.00** |
| M3 | detection lead time | < 6 h | **2.0 h** |
| M4 | accuracy vs `true_cause` | > 0.8 | **1.00** |

---

## P3 — Impact simulation M5 + ROI M6 · budget 0:50

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P3.1 | `m5_impact.py` — `simulate()` with intervention overrides | done | [backend/models/m5_impact.py](../backend/models/m5_impact.py). Verified the override touches only the targeted stage and leaves the arrival stream identical, so the Δ is the intervention rather than sampling noise. |
| P3.2 | 3 seed replicates (42/43/44) → mean Δ + CI | done | Replicates are **paired** — baseline and counterfactual share arrivals, attributes and per-(case,stage) service shocks (P1.4). Student-t at 2 df, not the normal approximation, which would understate the interval by ~2× at n = 3. Widest CI across all five actions is **0.725 h**. |
| P3.3 | Returns `(delta_hours, ci_low, ci_high)` per (stage, action) | done | Plus Δp90, ΔSLA-rate and Δcost/case. Also `evaluate_bundle()`: combinations are **simulated, not summed** — the chosen pair measures 1.70 h against a naive sum of 3.21 h, because two fixes to the same queue interact. |
| P3.4 | `m6_roi.py` — benefit model from §A7 | done | [backend/models/m6_roi.py](../backend/models/m6_roi.py). Both terms hand-checked against the §A7 formula to 1e-6. **`holding_cost_per_hour` stays at the locked 12** — §A7 permits adjusting it only if the ordering fails, and it does not. |
| P3.5 | Greedy ROI-per-rupee under the ₹250k cap | done | Selects `weekend_shift_reallocation` + `auto_approve_low_risk` for **₹65k of ₹250k**. ROI-negative actions are ineligible — spare budget is not a reason to buy something that costs more than it saves. At a ₹30k cap it correctly falls back to the reallocation alone. |
| P3.6 | **Verify:** `auto_approve_low_risk` outranks `add_reviewers_2` on ROI | **done** | **Holds: ROI 3.42 vs −0.06** on the locked constants. The ₹180k option is not merely outranked, it is rejected outright — it costs more than it saves. See §D for why §A7's indicative 7.5 / 1.3 pair is not simultaneously reachable. |
| P3.7 | Persist candidates to `interventions` | done | `persist.write_interventions()` — one `BEGIN`/`COMMIT`, `executemany`, idempotent on re-write. `int_id` is derived from (inv_id, action) rather than a uuid, so P7.4's two identical end-to-end runs stay identical. |

**Exit:** P3.6 holds. Gate **H+4:20** — **met.** Runner: [backend/scripts/p3_verify.py](../backend/scripts/p3_verify.py), 34 checks, ~25 s.

ROI ranking in the bottleneck-A world (holding cost ₹12/case-hour, unchanged):

| Action | Cost | Δ cycle | 95% CI | ROI | |
|--------|------|---------|--------|-----|---|
| `weekend_shift_reallocation` | ₹25k | 1.525 h | 1.18–1.87 | **5.46** | selected |
| `auto_approve_low_risk` | ₹40k | 1.682 h | 1.34–2.03 | **3.42** | selected |
| `add_reviewers_2` | ₹180k | 1.598 h | 1.24–1.96 | −0.06 | rejected |
| `batch_route_optimisation` | ₹60k | 0.488 h | 0.37–0.60 | −0.14 | rejected *(pre-fix)* |
| `add_evening_shift` | ₹150k | 0.406 h | 0.35–0.47 | −0.71 | rejected |

**The cascade reprices the catalogue.** Re-scored in the post-fix world, `batch_route_optimisation` moves from ROI **−0.14 to +1.08** (Δ 0.49 h → 1.28 h) — the same action at the same price, worth buying only once bottleneck A stops starving `pick_pack`. That is what P4.6's re-plan will recommend, and it is a stronger version of beat 4 than a bare queue chart.

---

## P4 — State engine + agent controller · budget 1:10

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P4.1 | `agent/state.py` — `ProcessState` (Architecture §5) | todo | |
| P4.2 | `agent/probes.py` — stage probe + factor probe over the 4 locked dimensions | todo | |
| P4.3 | `agent/policy.py` — selection score + convergence rule per §A8 | todo | |
| P4.4 | `agent/controller.py` — the investigate loop, synchronous | todo | |
| P4.5 | Persist each node with its `reasoning` string | todo | |
| P4.6 | Candidate proposal → M5 → M6 selection at loop end | todo | |
| P4.7 | Re-planning: `apply()` → child run → refresh models → re-investigate, same code path | todo | |
| P4.8 | **Verify:** concludes `order_validation`/`staffing_shortage` on A, then `pick_pack`/`capacity_saturation` after the fix — no code change between | todo | |

**Exit:** P4.8 passes from a script. Gate **H+5:30 — hard gate.**

---

## P5 — API layer · budget 0:25

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P5.1 | Run endpoints: `reset`, `inject/{scenario}` | todo | |
| P5.2 | Read endpoints: `stages/health` (incl. map), `bottlenecks/ranking`, `models/metrics` | todo | |
| P5.3 | Agent endpoints: `investigate`, `{inv_id}`, `{inv_id}/tree`, `{inv_id}/interventions` | todo | |
| P5.4 | Action endpoints: `interventions/{int_id}/apply`, `baseline/compare` | todo | |
| P5.5 | Verify the whole demo runs from curl | todo | |

**Exit:** P5.5 passes. Gate **H+6:00**.

---

## P6 — Dashboard · budget 1:15

Built in demo order. Any panel that stalls ships as a plain `<table>`. CSS bars only.

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P6.1 | `App.jsx` layout + `api.js` fetch wrappers | todo | |
| P6.2 | `ProcessMap.jsx` — 5 fixed boxes, SVG arrows, health colours | todo | |
| P6.3 | `StageHealth.jsx` — metrics table + anomaly flags (no sparklines) | todo | |
| P6.4 | `BottleneckRanking.jsx` — CSS bars, % contribution | todo | |
| P6.5 | `InvestigationTree.jsx` — nested list, client-side reveal at 400ms | todo | |
| P6.6 | `DelayCauses.jsx` — CSS probability bars | todo | |
| P6.7 | `InterventionSim.jsx` — candidate cards: Δ, CI, cost, ROI | todo | |
| P6.8 | `ImpactPanel.jsx` — before/after cycle time from `runs` | todo | |
| P6.9 | `RoiPanel.jsx` — ROI bars + agent vs baseline | todo | |
| P6.10 | `ModelMetrics.jsx` — four cards (first to cut if behind) | todo | |
| P6.11 | Control bar: Reset / Inject A / Investigate / Apply | todo | |

**Exit:** all eight PRD §5 panels render. P6.5 is the one that must look good. Gate **H+7:10**.

---

## P7 — Baseline + verification · budget 0:25

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P7.1 | `baseline.py` — fixed rule: highest mean stage duration → cheapest action there | todo | |
| P7.2 | Confirm baseline picks `last_mile` while the agent picks `order_validation` | todo | |
| P7.3 | Both ROIs → `baseline_decisions` → comparison panel | todo | |
| P7.4 | Full end-to-end from a clean DB, twice, seed 42 — identical result | todo | |

**Exit:** agent measurably beats baseline, run is reproducible.

---

## P8 — Demo rehearsal · budget 0:30

| ID | Step | Status | Notes |
|----|------|--------|-------|
| P8.1 | Walk the five beats (PRD §8) with a stopwatch | todo | |
| P8.2 | Pre-warm model training so no beat waits on a fit | todo | |
| P8.3 | One-command reset to the demo start state | todo | |
| P8.4 | Prep answers: why no LLM; how the 6 components map to the requirements; how ground truth stays out of training | todo | |
| P8.5 | Second uninterrupted rehearsal | todo | |

**Exit:** two clean consecutive run-throughs inside 3 minutes. Gate **H+7:35**.

---

# §C — Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-28 | Fictional "NovaCart", not Amazon | Synthetic data must not be presented as a real company's operational data |
| 2026-08-28 | Model time, derive cost | Generating cost directly leaves M4 with no signature to classify |
| 2026-08-28 | Bottleneck B caused by fixing A | Satisfies "second bottleneck appearing *after* the first intervention" causally; strongest demo beat |
| 2026-08-28 | Custom discrete-event simulator, not DataDoom | DataDoom has no queues, no counterfactual re-run, no cascade. Not used at all — the optional attribute upgrade is dropped |
| 2026-08-28 | SQLite, WAL, single writer, settings frozen in §A3 | Zero setup, survives restarts, ~40k rows is trivial |
| 2026-08-28 | Greedy ROI selection, not OR-Tools | Saves setup; defensible for single-budget selection |
| 2026-08-28 | Rework loops cut | Queues + capacity produce both bottlenecks; removes `visit_no` throughout |
| 2026-08-28 | M4 reduced to 3 classes | Cutting `vendor_wait`/`rework_loop` also raises the accuracy metric |
| 2026-08-28 | Sim reduced to 30 days / 8k cases | Ample training data; makes every counterfactual re-run faster |
| 2026-08-28 | Recharts cut, CSS bars only | Horizontal bars are the only chart form needed |
| 2026-08-28 | Agent synchronous, no polling | Client-side reveal looks identical, removes lock risk and a hook |
| 2026-08-28 | `kpi_history` table cut | Before/after reads from `runs` |
| 2026-08-28 | `event_log` gains `queue_len_at_arrival`, `servers_busy` | Both are M1 features per Architecture §4.1 and must be captured at event time. No §A value changes — §A3 freezes table *names*, not columns — but with no migration path the columns had to be created in P0 |
| 2026-08-28 | **§A4 changed: `last_mile` servers 40 → 360** | The only §A value altered so far. At 11 cases/h and 14 h mean service the offered load is 154 erlangs, so 40 servers is ~3.9× over capacity and `last_mile` becomes an unbounded queue — the exact opposite of §A4's own note, which needs it to be the longest stage but *not* a bottleneck (it is what the fixed-rule baseline wrongly picks). 360 gives utilisation 0.43 and a 0.0000 h queue. Every other §A4 number is arithmetically consistent and is used unchanged |
| 2026-08-28 | `cases` primary key → composite `(run_id, case_id)` | Architecture §3.1 says `case_id INTEGER PK`, but every run replays the same arrival stream from the master seed, so case_id 1 exists in every run. The original key collides on the second run |
| 2026-08-28 | `cases` gains `needs_review` | Without it nothing can explain why 65% of `order_validation` events take zero time; M1 would have to infer it from its own target |
| 2026-08-28 | Modules `sim/costs.py` and `sim/persist.py` added | Keeps `db.py` to connection + schema and the single-writer discipline in one obvious place. Architecture §4's layout is not frozen in §A |
| 2026-08-28 | M2 residual term is an excess *rate*, not a raw sum | §A5 fixes the weight at 0.25 but not the definition. Unnormalised, `last_mile`'s 14 h lognormal service noise exceeded every other stage's entire delay and took 74% of the term on variance alone |
| 2026-08-28 | M3 gains a direction gate (must also be worse than healthy p95) | An IsolationForest flags *different*, not *worse*. Without the gate, applying the fix made `order_validation` anomalous **because it improved**, and the stage just repaired kept re-triggering the agent |
| 2026-08-28 | M4 trained on its own synthetic fault corpus, not the demo runs | The only way to satisfy §A5's 'ground truth is read only when computing metric cards' while still having labels. 15 worlds, seeds 301–503, both demo configurations held out |
| 2026-08-28 | M4 features are scale-free ratios; `mean_residual` excluded | Magnitudes let the classifier memorise 'pick_pack with 4 servers' instead of the pattern. The residual is excluded because the corpus carries no per-run M1 fit, which would make it zero in training and non-zero at inference |
| 2026-08-28 | `holding_cost_per_hour` **kept at 12** | §A7 authorises changing it only if the ROI ordering fails. The ordering holds (3.42 vs −0.06), so the licence does not apply and the constant stays frozen |
| 2026-08-28 | M5 bundles are simulated, never summed | Two capacity changes on one queue interact; the naive sum overstates the chosen pair by 89% (3.21 h vs a simulated 1.70 h) |
| 2026-08-28 | M6 excludes ROI-negative actions from greedy selection | Leftover budget is not a reason to buy something that costs more than it saves. Without this the ₹250k cap would absorb `add_reviewers_2` after the two cheap fixes |

---

# §D — Open items

None. All decisions frozen as of 2026-08-28. Anything new goes in §C with a reason.

**Watch item (not a decision):** pandas 3.0 and numpy 2.4 are majors newer than the code these docs assume. If a P1/P2 pandas idiom breaks, that is why.

**Open constraint for P2.9 (M3), found at P1.10.** Fixing bottleneck A *restores* healthy throughput — it cannot exceed it — so post-fix `pick_pack` (weekend wait 3.48 h) is statistically indistinguishable from the healthy baseline (3.57 h). An M3 fitted on *all* healthy-run windows therefore treats post-fix pick_pack as normal and never fires, killing the cascade trigger. **Fit M3 on healthy-run weekday windows only** — the normal-operation regime. Bottleneck A then registers (weekend order_validation 6.09 h vs weekday 0.70 h) and so does cascade B (weekend pick_pack 3.48 h vs weekday 0.67 h), from one reference set. This is a modelling choice about the reference regime; no ground-truth label is involved.

**Resolved at P2.9.** The M3 constraint above was implemented as stated: 2,606 healthy weekday windows, detection at 2.0 h, plus a direction gate so an improvement is not mistaken for a fault.

**Open constraint for P4.3 (agent policy), found at P2.15.** §A8 sets the probe-selection score to `m2_impact_share × normalised_entropy(m4_proba)`. M4 is confident enough on this simulator that entropy is **0.000** at both demo stages — which would zero the score for *every* candidate and leave the agent choosing arbitrarily. The fix is to read the term the way it is meant: entropy is the agent's uncertainty about a stage it **has not yet probed**, so an unprobed candidate carries maximum entropy and the score reduces to impact, while probing collapses it. Do not paper over this with a constant floor.

**Caveat to state out loud in P8.** M4 scoring 1.00 reflects a simulator in which the two fault signatures are genuinely disjoint — a shortage queues up while capacity sits idle, saturation queues up with capacity flat out. It is not evidence of real-world difficulty. The honest claim is that the classifier learned the mechanism rather than the stage: it was never shown either demo scenario, and it gets 4/4 held-out stage/severity combinations right (one on thin evidence, p = 0.37 over 4 windows).

**§A7's indicative ROI values are not simultaneously reachable — resolved at P3.6.** §A7 predicts `auto_approve_low_risk` ≈ 7.5 and `add_reviewers_2` ≈ 1.3. With the measured deltas (1.682 h and 1.598 h) the holding cost that yields 7.5 for the first is ₹24.1/case-hour, while the one that yields 1.3 for the second is ₹30.9 — no single value satisfies both, and at ₹24.1 the second lands at 0.81, not 1.3. The pair was written before the simulator existed and assumed the two actions were far apart on time saved; in fact both essentially fully relieve bottleneck A. **The frozen requirement is the ordering, and the ordering holds at the locked ₹12.** Two related notes for the demo script: §A7's parenthetical 'despite saving less absolute time' no longer describes the simulator — `auto_approve_low_risk` saves the *most* time of the three *and* costs a quarter of `add_reviewers_2`; and at ₹12 the ₹180k option comes out mildly negative, which is a sharper line than '1.3' anyway.

**PRD beat 2's wording needs correcting before P8.** The beat quotes the agent concluding "order_validation — staffing shortage, weekends, **orders > ₹15k**, p≈0.7". There is no value concentration to find: the legacy review rule is deliberately uncorrelated with order value (that is *why* auto-approving low-risk orders removes 61% of the volume), and the measured `concentration_by_value_band` is 0.26 against 0.25 for a uniform split. The real, defensible finding is the weekday one — weekend review wait 6.09 h vs 0.70 h on weekdays. P4.2's factor probe will surface exactly that, and the beat should say `weekday=Sat/Sun`, not an order-value band.

**Beat 3 still holds, with one addition.** M6 selects a *pair* — `weekend_shift_reallocation` (₹25k) and `auto_approve_low_risk` (₹40k) — for ₹65k, rather than the single ₹40k action the PRD describes. The frozen contrast ("picks the ₹40k option, not the ₹180k one") is intact, and a budget optimiser returning a portfolio is a better demonstration of M6 than a single pick.

**Related framing point for P8.** 'Latent' for bottleneck B means *masked by the upstream throttle*, not absent: pick_pack carries weekend strain in the healthy world too, and bottleneck A hides it by starving the stage. The demo must therefore compare post-fix against **pre-fix**, never against the healthy baseline. Injecting A visibly *improves* pick_pack (0.572 h vs 1.721 h healthy) — that is the mask, and it is worth showing rather than hiding.
