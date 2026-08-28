# ProcessX v2

Backend-only demo plan for a full business lifecycle. The demo follows one
business case through every macro-stage, while the models train and score on
the full synthetic population.

## Demo Positioning

ProcessX v2 expands the original fulfilment-only demo into lifecycle process
intelligence.

The primary narrative is:

```text
customer_onboarding
  -> order_processing
  -> claims_processing
  -> support_resolution
  -> invoice_approval
```

Every simulated business case travels through the entire chain. The terminal
demo highlights one representative case, but M1-M6 are trained and evaluated on
all generated events.

## Activity Map

| Macro-stage | Activities |
|---|---|
| `customer_onboarding` | `account_creation`, `document_verification`, `risk_screening`, `account_activation` |
| `order_processing` | `order_validation`, `inventory_allocation`, `pick_pack`, `carrier_handover`, `last_mile` |
| `claims_processing` | `claim_intake`, `eligibility_check`, `evidence_review`, `settlement_decision`, `payout_or_replacement` |
| `support_resolution` | `ticket_triage`, `agent_assignment`, `investigation`, `customer_response`, `closure` |
| `invoice_approval` | `invoice_capture`, `three_way_match`, `exception_review`, `manager_approval`, `payment_release` |

In the code, each activity is still represented as `stage`. The new
`macro_stage` field groups those activities for lifecycle reporting.

## Demo Scenario

The v2 disruption is a claims-processing constraint:

```text
evidence_review capacity drops from 5 reviewers to 4, at hour 24 of the run
```

Two properties of that sentence are load-bearing.

**Four reviewers, not three.** Three puts the offered load at 1.12, i.e. an
unbounded queue: the wait, the utilisation and every metric derived from them
become a function of how long the run is allowed to go on rather than of the
constraint. Four holds utilisation at 0.84 -- by far the worst stage in the
lifecycle, and still a queue that drains inside the horizon.

**At hour 24, not from the start.** The run opens on the healthy roster and
switches at a real instant, so `INJECTED_AT_HOURS` names something that happens
in the data and M3's detection lead time is measured against it.

This creates a lifecycle-visible delay after fulfilment, not inside the original
order-processing segment. The point of the demo is to show that the same
process intelligence stack can discover the bottleneck wherever it appears in
the business lifecycle.

Expected demo conclusion:

```text
bottleneck stage: evidence_review
macro-stage: claims_processing
cause: capacity_saturation
```

## Model Responsibilities

| Model | v2 behavior |
|---|---|
| M1 process-time prediction | Predicts activity duration for every lifecycle activity using case, timing, macro-stage, and stage features. |
| M2 bottleneck detection | Ranks all activities, then the demo also summarizes impact by macro-stage. |
| M3 process anomaly detection | Fits one detector per activity on healthy lifecycle windows and flags degraded windows. |
| M4 delay-cause prediction | Classifies strained activity windows as `staffing_shortage`, `capacity_saturation`, or `normal`. |
| M5 intervention impact prediction | Re-simulates the same lifecycle with intervention patches and paired seeds. |
| M6 ROI optimization | Selects the best ROI-positive intervention set under the shared lifecycle budget. |

## Demo Data

The synthetic data contains:

- One row per business case in `cases`.
- One row per case-activity visit in `event_log`.
- `macro_stage` on every event.
- Lifecycle attributes including customer segment, priority, claim type,
  claim severity, support channel, invoice value, invoice exception, and the
  original order attributes.

Target scale:

```text
7 simulated operating days
1,847 business cases
24 lifecycle activities
44,328 event rows per run
```

Every other activity is sized so the healthy baseline is genuinely healthy:
no stage sits above a wait/service ratio of 1.0 with nothing wrong. The worst
is `evidence_review` at 0.53.

## Evaluation Scenarios

The demo narrates one fault, but scoring the models on one fault says very
little. Two further scenarios exist purely to score M1-M6. They sit in
different macro-stages, carry a different cause, and their activities are
absent from M4's training corpus, so they are genuinely held out.

| Scenario | Activity | Macro-stage | Cause | Onset |
|---|---|---|---|---|
| `claims_bottleneck` | `evidence_review` | `claims_processing` | `capacity_saturation` | hour 24 |
| `support_staffing` | `ticket_triage` | `support_resolution` | `staffing_shortage` | first weekend hour |
| `fulfilment_saturation` | `inventory_allocation` | `order_processing` | `capacity_saturation` | hour 24 |

All three are injectable through `POST /api/runs/inject/{scenario}`, and the
agent diagnoses each of them through the same loop with no code change.

## Backend-Only Demo Flow

Run:

```powershell
.venv\Scripts\python -m backend.scripts.v2_demo
```

The script performs the whole demo without a frontend:

1. Reset the SQLite database.
2. Simulate and persist the healthy lifecycle baseline.
3. Simulate and persist the claims bottleneck scenario.
4. Train M1-M4 on the full lifecycle data.
5. Print the model metric cards.
6. Print a single representative business case journey through all
   macro-stages.
7. Print M2 activity and macro-stage bottleneck rankings.
8. Run the agent investigation.
9. Print the investigation tree and M4 cause.
10. Print M5/M6 intervention candidates and selected ROI-positive actions.
11. Apply the selected action set and print the before/after lifecycle KPIs.

## Verification

```powershell
.venv\Scripts\python -m backend.scripts.v2_verify
```

Asserts the properties above rather than just that the demo runs: seed
reproducibility and full lifecycle coverage, a healthy baseline with no
strained activity and no queue that fails to drain, injected constraints that
are stable and start when their ground truth says, M1-M4 on held-out faults in
three macro-stages across both causes, `normal` everywhere in the healthy
world, an agent that stops for a stated reason inside its probe budget, an
ROI-positive action that measurably helps, and storage that round-trips
without leaking ground truth into the feature tables.

## Success Criteria

- The generated event log includes all five macro-stages.
- The representative case visibly passes through every macro-stage.
- M2 ranks `evidence_review` at or near the top under the v2 disruption.
- M4 attributes the bottleneck to `capacity_saturation`, and reports `normal`
  for every stage that has nothing wrong with it.
- M5 produces non-zero intervention deltas.
- M6 selects at least one ROI-positive claims intervention under the budget.
- The post-intervention run improves mean cycle time.

Observed on seed 42:

| | healthy | claims bottleneck | after intervention |
|---|---|---|---|
| mean cycle | 18.33 h | 19.08 h | 18.15 h |
| cost per case | Rs 227 | Rs 238 | Rs 224 |
| SLA breach (30 h) | 2.76% | 3.74% | — |
| `evidence_review` utilisation | 0.67 | 0.84 | — |
| `evidence_review` wait/service | 0.53 | 3.12 | — |

Model cards: M1 77.7% better than mean, M2 1.00 over 3 scenarios, M3 8 h
detection lead, M4 0.99 over 169 windows.
