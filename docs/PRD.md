# PRD — ProcessX: Autonomous Business Bottleneck Investigator

**Hackathon:** 24-Hour AIML & Cybersecurity Hackathon — PS 10 (AIML)
**Build window:** 8–10 hours (compressed from the 24h reference plan)
**Goal:** Working prototype with a flawless 3-minute demo. Not a product.

> All technical decisions are **frozen** in [Status.md §A](Status.md). Constants there win over prose here.

---

## 1. Problem

A company's critical business process has become slower and more expensive. Nobody knows which stage is responsible, what is causing it, or which fix is worth the money.

Build an AI system that **investigates** the process, finds the bottleneck, forms causal hypotheses, simulates candidate interventions, and recommends the highest-ROI action — then re-plans when a new bottleneck appears.

## 2. What this is NOT

Explicitly out of scope. These are the failure modes that lose marks:

- Not a process analytics dashboard. Ranking stages by average duration is the **baseline we beat**.
- Not an LLM wrapper. Per hackathon rules, no hosted LLM in the reasoning, prediction, planning or decision path. All intelligence is team-implemented.
- Not a production system. No auth, no multi-user, no real-time streaming, no deployment.

## 3. Scenario

**Company:** NovaCart — a fictional e-commerce fulfilment operation. Modelled on Amazon-style fulfilment, but deliberately **not** named after a real company: all data is synthetic and must never be presented as a real firm's operational data.

**Process — 5 stages** (satisfies "at least five stages"):

| # | Stage | What happens |
|---|-------|--------------|
| 1 | `order_validation` | Payment auth + fraud review (auto-scored; risky orders go to manual review) |
| 2 | `inventory_allocation` | Reserve stock, pick a fulfilment centre |
| 3 | `pick_pack` | Physical picking and packing at a station |
| 4 | `carrier_handover` | Manifest and hand over to the carrier |
| 5 | `last_mile` | Delivery to customer |

### 3.1 The two bottlenecks

The second is **caused by fixing the first** (Theory of Constraints — relieving a constraint moves it downstream). This satisfies "support a second bottleneck appearing *after* the first intervention" causally, rather than by planting two unrelated problems.

- **Bottleneck A — `order_validation`, staffing shortage.**
  Manual fraud review is understaffed during weekend demand peaks.
  Signature: `queue_wait` explodes, `service_time` stays normal.
  Concentrated in high-value orders from new customers on Sat/Sun.

- **Bottleneck B — `pick_pack`, capacity saturation.**
  Latent. Packing stations run near capacity. Once A is fixed, throughput into stage 3 rises ~40% and B becomes the new constraint.
  Signature: `queue_wait` rises *and* `service_time` degrades as stations saturate.

## 4. Functional requirements

Mapped 1:1 to the PS execution requirements.

### FR-1 — Six intelligence components

| ID | Component | Output | Model |
|----|-----------|--------|-------|
| M1 | Process-time prediction | Expected stage duration per case | GradientBoostingRegressor |
| M2 | Bottleneck detection | Ranked stages + % contribution to cycle time | Scoring model over queue / utilisation / M1 residual |
| M3 | Process anomaly detection | Anomaly flag per stage per time window — **agent trigger** | IsolationForest |
| M4 | Delay-cause prediction | Ranked causes with probabilities (3 classes) | GradientBoostingClassifier |
| M5 | Intervention-impact prediction | Δ duration ± CI for (stage, action) | Counterfactual re-run of the simulator, 3 seed replicates |
| M6 | ROI optimisation | Best action under budget | Greedy ROI-per-rupee under a budget cap |

M1–M4 are the four **independently evaluable** outputs required by the rules; each gets its own metric card on the dashboard.

### FR-2 — Event-log data

Synthetic event log, 5 stages, ~8,000 cases over 30 simulated days, master seed 42. Columns:
`case_id, stage, arrival_ts, start_ts, end_ts, resource_id` + case attributes.

Cost is **derived** from time, never generated directly:

```
queue_wait   = start_ts - arrival_ts
service_time = end_ts   - start_ts
stage_cost   = service_time * labour_rate
             + queue_wait   * holding_cost
             + sla_penalty(total_cycle_time)
```

This is what gives the two bottlenecks distinguishable fingerprints for M4 to classify.

### FR-3 — Investigating agent

The agent chooses which **stage or factor** to investigate next by
`expected_impact (M2) × uncertainty (M4 entropy)` — not by score order.
It drills from stage → factor (weekday, order-value band, customer type, resource) and records every node it visits.

### FR-4 — Intervention options

Minimum two per bottleneck, with different costs and effects. See §6.

### FR-5 — Simulate before recommending

Every candidate action is run through the counterfactual simulator before M6 selects one.

### FR-6 — Re-planning

After applying the winning action, the log is regenerated under the new configuration, M3 re-fires on the cascade, and the agent starts a fresh investigation with **no code changes**.

## 5. Dashboard requirements

Single page. Eight required panels:

| Panel | Content |
|-------|---------|
| Process map | 5 stage boxes, coloured by health, with flow volumes |
| Stage health | Per-stage cycle time, wait, utilisation, anomaly flag |
| Bottleneck ranking | M2 output, ranked, with % contribution |
| Delay causes | M4 probabilities for the investigated stage |
| Investigation tree | The agent's actual path, node by node, with evidence |
| Intervention simulation | Candidate actions, predicted Δ, cost, CI |
| Expected improvement | Cycle time before / after |
| ROI | ROI per action + agent-vs-baseline comparison |

Every AI decision must be explainable on screen (hackathon rule).

## 6. Intervention catalogue

| Stage | Action | Cost (₹) | Expected effect |
|-------|--------|----------|-----------------|
| `order_validation` | `auto_approve_low_risk` (order < ₹8k, risk < 0.2) | 40,000 one-time | Removes ~60% of manual review volume |
| `order_validation` | `add_reviewers_2` | 180,000 / month | +2 review capacity |
| `order_validation` | `weekend_shift_reallocation` | 25,000 / month | Moves existing capacity into the peak |
| `pick_pack` | `add_evening_shift` | 150,000 / month | +40% capacity, 6h/day |
| `pick_pack` | `batch_route_optimisation` | 60,000 one-time | −15% service time |

**ROI** = `(benefit_30d − cost_30d) / cost_30d`, where

```
benefit_30d = delta_cycle_hours_per_case
            * cases_per_day * 30
            * holding_cost_per_hour
            + sla_penalty_avoided
```

Intended result: `auto_approve_low_risk` (₹40k) beats `add_reviewers_2` (₹180k/mo) on ROI despite a smaller absolute time saving. That contrast is the point of the PS.

## 7. Baseline (for comparison)

**Fixed rule:** "intervene on the stage with the highest mean duration."

Under bottleneck A that rule picks `last_mile` — naturally the longest stage, and not the problem. The agent picks `order_validation`. One bar chart: baseline ROI vs agent ROI.

## 8. Success criteria

The prototype is done when this 3-minute demo runs end to end without a stumble:

| # | Beat | Time |
|---|------|------|
| 1 | Dashboard green. Inject bottleneck A. M3 fires. | 20s |
| 2 | Agent investigates; tree grows; lands on "order_validation — staffing shortage, weekends, orders > ₹15k, p≈0.7" | 45s |
| 3 | Three interventions simulated with costs. Agent picks the ₹40k option, not the ₹180k one. | 45s |
| 4 | Apply → cycle time drops → **bottleneck B surfaces on its own** at `pick_pack`; agent re-plans, no code changes | 45s |
| 5 | Baseline-vs-agent ROI bar | 25s |

Beat 4 is the winning moment. Everything else is built to reach it.

## 9. Non-goals / explicit cuts

To protect the 8–10 hour window:

- No migrations tool — `CREATE TABLE IF NOT EXISTS` at startup plus a reset endpoint.
- No OR-Tools — greedy ROI-per-rupee under a budget cap is sufficient and defensible.
- No graph layout engine — the process map is 5 fixed boxes.
- No DataDoom — case attributes are sampled inline. It has no queues, no counterfactual re-run, no cascade.
- No chart library — CSS bars only.
- No polling or websockets — the agent runs synchronously; the tree is revealed client-side.
- No rework loops in the simulator — queues and capacity produce both bottlenecks.
- No auth, no routing library, no state management library.
- No test suite beyond a handful of sanity assertions on the simulator.

Full cut list with time saved: [Status.md §A10](Status.md).
