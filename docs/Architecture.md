# Architecture — ProcessX

Companion to [PRD.md](PRD.md). Describes how the system is put together and why.

> All constants and settings are **frozen** in [Status.md §A](Status.md). Where this document and §A differ, §A wins.

---

## 1. Stack

| Layer | Choice | Note |
|-------|--------|------|
| Frontend | React 19 + Vite | Single page, no router, no state library |
| Charts | **CSS bars only** | `div` with percentage width — no chart library |
| Backend | FastAPI (Python 3.11) + uvicorn | Sync endpoints; the simulator is CPU-bound |
| ML | scikit-learn, pandas, numpy | No deep learning needed |
| Simulator | Plain Python event loop | No SimPy — fewer moving parts to debug |
| Datastore | **SQLite** (single file, WAL mode) | See §3 |

No Docker, no deployment. `uvicorn` on :8000, `vite` on :5173, CORS wide open for localhost.

## 2. Why the simulator is the centre of the system

The discrete-event simulator is the single highest-leverage asset. It serves three requirements from one piece of code:

1. **Ground truth** — we injected the bottleneck, so we can prove the agent found the real cause.
2. **M5, intervention-impact prediction** — re-run the same world with capacity changed. This is the only way to answer "what if we add a reviewer", which requirement FR-5 demands.
3. **The cascade** — stages are coupled through throughput, so fixing A causes B (FR-6).

A row-wise tabular generator cannot do any of these: bottlenecks emerge from arrival rate vs service capacity over time, which is a queue, not a distribution. Build the simulator first.

### 2.1 Simulator design

```
config = {
  arrival_rate_by_hour, weekday_multiplier,
  stages: [ { name, servers, service_dist, routing_rule } ],
  interventions_applied: []
}
```

Loop, in timestamp order:

1. Generate case arrivals from a non-homogeneous Poisson process (weekend/evening peaks).
2. Each case walks stages 1→5. At each stage: join queue → wait for a free server → service → move on. **No rework loops** (cut — see Status §A10).
3. Emit one event row per (case, stage).
4. Ground-truth labels (`true_cause`, `true_bottleneck_stage`) are emitted to a **separate table** the models never train on directly — they are for evaluation only.

**Counterfactual call:** `simulate(config, overrides, seed)` — same seed, same arrivals, only capacity/routing changed. Δ is then attributable to the intervention, not to noise. This is what makes M5 credible.

**Cascade mechanism:** `pick_pack` is configured with servers sized to *current* (throttled) throughput. When `order_validation` stops throttling, arrival rate at `pick_pack` rises ~40% and its queue grows. No special-casing — it falls out of the queueing model.

## 3. Datastore — SQLite

**Verdict: yes, SQLite is the right call.** Reasons:

- Zero setup, single file, survives restarts — the demo is reproducible after a crash.
- 8k cases × 5 stages ≈ 40k event rows. Trivial for SQLite; `pandas.read_sql` loads it in well under a second.
- The investigation tree and runs are genuinely relational and benefit from persistence.
- One storage system instead of two (no Parquet + SQLite split) — less to go wrong at 2am.

**Connection settings, PRAGMAs, indexes and writer rules are frozen in [Status.md §A3](Status.md).** Copy that block verbatim into `db.py`; do not tune it later. In short: WAL + `synchronous=NORMAL` + `busy_timeout=5000`, one module-level connection, bulk `executemany` inside a single transaction, and only the simulate / agent / apply paths write.

Analytics run in pandas, in memory, not in SQL. SQLite is storage and persistence, not the analytical engine.

### 3.1 Schema

```sql
-- Generated event log
event_log(
  id INTEGER PK, run_id TEXT, case_id INTEGER, stage TEXT,
  arrival_ts REAL, start_ts REAL, end_ts REAL, resource_id TEXT
)

-- Per-case attributes (joined into features)
cases(
  case_id INTEGER PK, run_id TEXT, order_value REAL, customer_tier TEXT,
  is_new_customer INTEGER, fraud_risk REAL, region TEXT, item_category TEXT,
  created_ts REAL, weekday INTEGER, hour INTEGER
)

-- Evaluation only. Models never train on this.
ground_truth(run_id TEXT, bottleneck_stage TEXT, true_cause TEXT, injected_at REAL)

-- One row per world-state (baseline, post-intervention-1, ...)
runs(
  run_id TEXT PK, parent_run_id TEXT, label TEXT, config_json TEXT,
  created_at REAL, mean_cycle_hours REAL, cost_per_case REAL, throughput_per_day REAL
)

-- Agent investigations
investigations(inv_id TEXT PK, run_id TEXT, started_at REAL, status TEXT,
               concluded_stage TEXT, concluded_cause TEXT, confidence REAL)

investigation_nodes(
  node_id TEXT PK, inv_id TEXT, parent_node_id TEXT, depth INTEGER, seq INTEGER,
  probe_type TEXT,        -- 'stage' | 'factor'
  target TEXT,            -- e.g. 'order_validation' or 'weekday=Sat'
  selection_score REAL, impact REAL, uncertainty REAL,
  evidence_json TEXT, hypotheses_json TEXT, reasoning TEXT
)

-- Candidate actions and their simulated outcomes
interventions(
  int_id TEXT PK, inv_id TEXT, stage TEXT, action TEXT, cost REAL,
  predicted_delta_hours REAL, ci_low REAL, ci_high REAL,
  benefit_30d REAL, roi REAL, selected INTEGER, applied INTEGER
)

-- Fixed-rule comparison
baseline_decisions(run_id TEXT, chosen_stage TEXT, chosen_action TEXT, cost REAL, roi REAL)
```

`kpi_history` is **cut**. Before/after metrics come from `runs.mean_cycle_hours` / `runs.cost_per_case`, which every run already records. Indexes are listed in [Status.md §A3](Status.md).

## 4. Backend layout

```
backend/
  main.py                  FastAPI app, CORS, startup schema init
  db.py                    connection, PRAGMAs, CREATE TABLE IF NOT EXISTS, reset()
  sim/
    config.py              stage definitions, arrival profile, intervention catalogue
    engine.py              discrete-event loop -> event rows
    scenarios.py           bottleneck A / B injection, cascade coupling
  models/
    m1_process_time.py     GradientBoostingRegressor + residual computation
    m2_bottleneck.py       stage scoring + ranking
    m3_anomaly.py          IsolationForest over windowed stage features
    m4_cause.py            GradientBoostingClassifier over cause labels
    m5_impact.py           counterfactual simulate() wrapper + CI from seed replicates
    m6_roi.py              benefit model + greedy budget selection
    registry.py            train-all / load-all, metric cards
  agent/
    state.py               ProcessState dataclass
    controller.py          the investigation loop
    probes.py              stage probe, factor probe, evidence extraction
    policy.py              probe selection score, stopping rule
  baseline.py              fixed-rule comparator
  api/routes_*.py          endpoint modules
```

### 4.1 Feature sets

- **M1 (per case-stage):** `order_value, customer_tier, is_new_customer, fraud_risk, region, item_category, weekday, hour, stage, queue_len_at_arrival, servers_busy`
- **M3 (per stage per hour window):** `mean_wait, p90_wait, mean_service, throughput, utilisation, mean_residual_M1`
- **M4 (per stage per window):** M3 features + `wait_to_service_ratio, wait_variance, concentration_by_weekday, concentration_by_value_band`
  Classes (3): `staffing_shortage | capacity_saturation | normal`

`wait_to_service_ratio` is the feature that separates bottleneck A (high ratio, normal service) from B (moderate ratio, degraded service). Keep it.

## 5. State engine

```python
@dataclass
class ProcessState:
    run_id: str
    stage_health: dict[str, StageHealth]      # M1/M2/M3 output per stage
    evidence: list[Evidence]                  # everything probed so far
    open_hypotheses: list[Hypothesis]         # from M4, with p and status
    tested_hypotheses: list[Hypothesis]
    budget_remaining: float
    probes_remaining: int
    actions_taken: list[Intervention]
```

Serialised to `investigations` / `investigation_nodes` after each step. The investigation runs **synchronously**: the endpoint returns the finished tree, and the frontend reveals nodes client-side at 400ms intervals. That looks identical to live growth, removes a polling hook, and eliminates concurrent-write pressure on SQLite.

## 6. Agent controller

The distinction that decides the score: **ranking stages is the baseline; choosing the next probe by expected information gain is the agent.**

```python
def investigate(state, max_probes=6):
    while state.probes_remaining and not converged(state):
        # 1. SELECT — impact x uncertainty, not max score
        target = argmax(
            candidates(state),
            key=lambda c: m2.impact(c) * entropy(m4.predict_proba(c))
        )

        # 2. PROBE — slice the log for that stage or factor
        evidence = probe(state.run_id, target)

        # 3. HYPOTHESISE
        hyps = m4.hypotheses(evidence)          # ranked causes with probabilities
        state.update(target, evidence, hyps)
        persist_node(...)                       # dashboard sees the tree grow

        # 4. DRILL or STOP
        if top_p(hyps) < CONFIDENCE_THRESHOLD:
            enqueue_factor_probes(target)       # weekday, value band, resource, ...
        state.probes_remaining -= 1

    # 5. PROPOSE + SIMULATE every candidate
    for action in catalogue[state.concluded_stage]:
        delta, ci = m5.simulate(state.run_id, action)   # real counterfactual re-run
        roi = m6.roi(delta, action.cost)
        record(action, delta, ci, roi)

    # 6. SELECT under budget
    return m6.select(candidates, state.budget_remaining)
```

**Convergence:** stop when top hypothesis probability > 0.65, or probes exhausted.
**Every node stores its own `reasoning` string** — that is the explainability requirement.

### 6.1 Re-planning loop

```
apply(action) -> new config
             -> simulate() -> new run_id (parent = previous run)
             -> retrain/refresh M1..M4 on the new log
             -> M3 fires on pick_pack
             -> investigate() again, same code path
```

No branch, no special case for "second bottleneck". That is what makes FR-6 credible.

## 7. API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/runs/reset` | Regenerate baseline world, retrain models |
| POST | `/api/runs/inject/{scenario}` | Inject bottleneck A (or B) |
| GET | `/api/stages/health` | Per-stage metrics + anomaly flags (M1/M3) **and process-map data** |
| GET | `/api/bottlenecks/ranking` | M2 ranked output |
| POST | `/api/agent/investigate` | Run an investigation, returns `inv_id` |
| GET | `/api/agent/{inv_id}` | Status, conclusion, confidence |
| GET | `/api/agent/{inv_id}/tree` | Investigation tree nodes (polled) |
| GET | `/api/agent/{inv_id}/interventions` | Candidates with Δ, CI, cost, ROI |
| POST | `/api/interventions/{int_id}/apply` | Apply, re-simulate, create child run |
| GET | `/api/baseline/compare` | Fixed-rule vs agent |
| GET | `/api/models/metrics` | M1–M4 metric cards |

11 endpoints, frozen in [Status.md §A9](Status.md). No polling — `investigate` is synchronous and returns the full tree.

## 8. Frontend layout

```
frontend/src/
  App.jsx                  layout + control bar
  api.js                   fetch wrappers
  components/
    ProcessMap.jsx         5 fixed boxes, SVG arrows, health colour
    StageHealth.jsx        plain metrics table (no sparklines)
    BottleneckRanking.jsx  CSS bars, % contribution
    DelayCauses.jsx        CSS probability bars
    InvestigationTree.jsx  nested list, client-side reveal at 400ms
    InterventionSim.jsx    candidate cards: Δ, CI, cost, ROI
    ImpactPanel.jsx        before/after cycle time (from runs)
    RoiPanel.jsx           ROI + agent vs baseline bars
    ModelMetrics.jsx       four cards: M1 MAE, M2 precision@1, M3 lead time, M4 accuracy
```

All bars are `div`s with a percentage width. No chart library.

Health colours: green `< 1.1x` expected, amber `1.1–1.5x`, red `> 1.5x`.

## 9. Model evaluation (the four metric cards)

| Model | Metric | Target |
|-------|--------|--------|
| M1 | MAE on held-out stage duration | Beats mean-predictor by > 30% |
| M2 | precision@1 vs `ground_truth.bottleneck_stage` | 1.0 on both scenarios |
| M3 | Detection lead time vs injection timestamp | Fires within 6 simulated hours |
| M4 | Accuracy vs `ground_truth.true_cause` | > 0.8 |

These come from the `ground_truth` table, which no model trains on. That separation is what makes the numbers mean anything — state it out loud in the demo.

## 10. Risks

| Risk | Mitigation |
|------|------------|
| Simulator overruns its time box | Gate at H+1:50 — cut the horizon to 14 days and move on |
| Cascade doesn't reproduce reliably | `pick_pack` servers sized for utilisation ≈ 0.82 pre-fix; verified at P1.10 before any UI work |
| M4 accuracy too low | `wait_to_service_ratio` is the discriminating feature; already reduced to 3 classes |
| ROI ordering doesn't hold | Adjust `holding_cost_per_hour`, not the story (P3.6) |
| SQLite write locks | WAL + `busy_timeout` + single-writer discipline + synchronous agent (§3, Status §A3) |
| Frontend eats the remaining time | Panels built in demo order; any stalling panel ships as a plain `<table>` |
| General slippage | Checkpoint gates in [Status.md §A11](Status.md) — each one names the action to take, so no end-of-build scramble |
