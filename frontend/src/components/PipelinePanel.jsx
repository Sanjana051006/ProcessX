import AnomalyStrip from "./charts/AnomalyStrip.jsx";
import PredScatter from "./charts/PredScatter.jsx";
import RankBars from "./charts/RankBars.jsx";
import Waterfall from "./charts/Waterfall.jsx";
import { MACRO_COLOR, clamp, hours, money, num, pct, pretty } from "../lib/format.js";

/**
 * The body of one pipeline panel.
 *
 * Each of the nine steps gets its own visualisation, because each is answering a
 * different shape of question — a ranking is a bar list, a prediction is a
 * scatter against the diagonal, a counterfactual is an interval, a budget
 * decision is a table with a spend line. One generic chart reused nine times
 * would be less code and a far worse panel.
 *
 * **Every panel here is built to fit a fixed box and never to scroll.** The
 * simulation page is a locked-viewport layout: it has exactly one content area
 * and whatever a panel renders has to live inside it. Three rules make that
 * hold, and breaking any of them puts a scrollbar back:
 *
 * 1. Root is `grid h-full min-h-0` and every descendant that owns space carries
 *    `min-h-0` — without it a grid child refuses to shrink below its content.
 * 2. Lists are capped by a count that fits the shortest supported viewport, and
 *    prose is `clamp-*`. Content is dropped, never scrolled.
 * 3. The SVG charts scale to their box through a viewBox, so they shrink with
 *    the window instead of pushing it.
 */
export default function PipelinePanel({ step, journey, activeIndex, setActiveIndex, onSelectStage }) {
  switch (step.key) {
    case "world":
      return <WorldPanel journey={journey} activeIndex={activeIndex} setActiveIndex={setActiveIndex} />;
    case "m1":
      return <M1Panel step={step} />;
    case "m2":
      return <M2Panel step={step} onSelectStage={onSelectStage} />;
    case "m3":
      return <M3Panel step={step} />;
    case "agent":
      return <AgentPanel step={step} />;
    case "m4":
      return <M4Panel step={step} />;
    case "m5":
      return <M5Panel step={step} />;
    case "m6":
      return <M6Panel step={step} />;
    case "outcome":
      return <OutcomePanel step={step} />;
    default:
      return null;
  }
}

/* -- shared shells --------------------------------------------------------- */

/**
 * Two panes side by side. The ratio is per-panel because the chart is the
 * subject in some and the list is in others.
 *
 * Both tracks are `minmax(0, ...)` on purpose. A grid track sized `auto` (or a
 * bare `1fr`) is floored at its items' min-content width, so one long label
 * inside a pane would widen the track and push the panel off the screen instead
 * of being truncated. Never drop the `minmax(0, ...)` wrapper here.
 */
function Split({ ratio = "1.2fr_1fr", children }) {
  return (
    <div
      className="grid h-full min-h-0 gap-3"
      style={{ gridTemplateColumns: `minmax(0,${ratio.split("_")[0]}) minmax(0,${ratio.split("_")[1]})` }}
    >
      {children}
    </div>
  );
}

/** One pane: a label, then a body that fills what is left and clips. */
function Pane({ label, note, children, className = "", bodyClass = "" }) {
  return (
    <section className={`flex min-h-0 min-w-0 flex-col rounded-xl border border-line/8 bg-surface-2 p-3 ${className}`}>
      {label && <p className="eyebrow mb-2 shrink-0">{label}</p>}
      <div className={`min-h-0 min-w-0 flex-1 overflow-hidden ${bodyClass}`}>{children}</div>
      {note && (
        <p className="clamp-2 mt-2 shrink-0 border-t border-line/8 pt-2 text-[10.5px] leading-snug text-ink-4">
          {note}
        </p>
      )}
    </section>
  );
}

/* -- 0. the world --------------------------------------------------------- */

function WorldPanel({ journey, activeIndex, setActiveIndex }) {
  const a = journey.attributes;
  const steps = journey.steps;
  const active = activeIndex != null ? steps[activeIndex] : null;

  return (
    <Split ratio="1.5fr_1fr">
      <Pane
        label={`Case ${journey.case_id} · all 24 activities, queued vs worked`}
        note="Each bar starts where the case reached that activity. Only the queue half is addressable by capacity — the worked half is the job itself."
      >
        <Waterfall
          steps={steps}
          activeIndex={activeIndex}
          onSelect={(i) => setActiveIndex(i === activeIndex ? null : i)}
          total={journey.cycle_hours}
        />
      </Pane>

      <div className="grid min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3">
        <Pane label="This case">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11.5px]">
            <Attr k="Cycle" v={hours(journey.cycle_hours)} />
            <Attr k="Queued" v={hours(journey.queue_hours)} tone="text-danger" />
            <Attr k="Percentile" v={`p${Math.round(journey.cycle_percentile * 100)}`} />
            <Attr k="Cost" v={money(journey.cost)} />
            <Attr k="Segment" v={pretty(a.customer_segment)} />
            <Attr k="Tier" v={pretty(a.customer_tier)} />
            <Attr k="Priority" v={pretty(a.priority)} />
            <Attr
              k="SLA"
              v={journey.sla_breach ? "Breached" : "Met"}
              tone={journey.sla_breach ? "text-danger" : "text-ok"}
            />
          </dl>
        </Pane>

        <Pane label={active ? `Step ${active.order + 1} · ${active.macro_label}` : "Selected activity"}>
          {active ? (
            <div className="animate-fade">
              <p className="truncate text-[14px] font-semibold text-ink">{active.label}</p>
              <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-[11px] tabular-nums">
                <Attr k="Queued" v={hours(active.queue_wait_hours)} />
                <Attr k="Worked" v={hours(active.service_hours)} />
                <Attr k="Queue depth" v={active.queue_len_at_arrival} />
                <Attr k="Servers busy" v={active.servers_busy} />
                <Attr k="M1 predicted" v={hours(active.predicted_hours)} />
                <Attr
                  k="Residual"
                  v={hours(active.residual_hours)}
                  tone={active.residual_hours > 0 ? "text-danger" : "text-ok"}
                />
              </dl>
            </div>
          ) : (
            <p className="text-[11.5px] leading-relaxed text-ink-4">
              Click any bar to inspect that activity — what the case queued for, what it
              was worked on for, and how far M1's prediction was off.
            </p>
          )}
        </Pane>
      </div>
    </Split>
  );
}

const Attr = ({ k, v, tone }) => (
  <>
    <dt className="truncate text-ink-4">{k}</dt>
    <dd className={`truncate text-right font-medium ${tone ?? "text-ink-2"}`}>{v}</dd>
  </>
);

/* -- 1. M1 ---------------------------------------------------------------- */

function M1Panel({ step }) {
  const rows = [...(step.predictions ?? [])].sort(
    (a, b) => Math.abs(b.residual) - Math.abs(a.residual),
  );
  const scale = Math.max(...rows.map((x) => Math.abs(x.residual)), 0.01);

  return (
    <Split ratio="1fr_1.15fr">
      <Pane label="Predicted against actual, this case">
        <PredScatter predictions={step.predictions} highlight={step.worst_residual_stage} />
      </Pane>

      <Pane
        label="Largest residuals — where M1 was most wrong"
        note="Positive means the activity took longer than the model could account for from the case's attributes, the queue it arrived into and the hour of the week. That unexplained share is 25% of M2's bottleneck score."
      >
        <ol className="space-y-[3px]">
          {rows.slice(0, 8).map((r) => {
            const width = clamp(Math.abs(r.residual) / scale) * 50;
            const over = r.residual > 0;
            return (
              <li key={r.stage} className="grid grid-cols-[1fr_auto] items-center gap-2">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="h-3 w-[3px] shrink-0 rounded-full"
                    style={{ background: MACRO_COLOR[r.macro_stage] }}
                  />
                  <span className="truncate text-[11.5px] text-ink-2">{r.label}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {/* A centred divergent bar: right of the axis is slower than
                      predicted, left is faster. The sign is the whole point. */}
                  <span className="relative block h-2 w-[92px] rounded-full bg-line/8">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-line/25" />
                    <span
                      className="absolute inset-y-0 rounded-full"
                      style={{
                        left: over ? "50%" : `${50 - width}%`,
                        width: `${width}%`,
                        background: over ? "rgb(var(--danger))" : "rgb(var(--ok))",
                      }}
                    />
                  </span>
                  <span
                    className={`w-[62px] text-right font-mono text-[10.5px] tabular-nums ${
                      over ? "text-danger" : "text-ok"
                    }`}
                  >
                    {over ? "+" : "−"}
                    {hours(Math.abs(r.residual))}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      </Pane>
    </Split>
  );
}

/* -- 2. M2 ---------------------------------------------------------------- */

function M2Panel({ step, onSelectStage }) {
  const top = step.ranking.slice(0, 9);
  return (
    <Split ratio="1.1fr_1fr">
      <Pane label="Ranked by share of total delay">
        <RankBars rows={top} onSelect={onSelectStage} selected={step.top_stage} />
      </Pane>

      <Pane label="The three things an activity can be guilty of">
        <div className="space-y-2.5">
          {top.slice(0, 5).map((s) => (
            <div key={s.stage}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="truncate text-[11.5px] font-medium text-ink-2">{s.label}</span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-4">
                  {num(s.score, 3)}
                </span>
              </div>
              <div className="flex h-2.5 gap-px overflow-hidden rounded-full">
                <Component share={s.queue_wait_share * 0.45} color="rgb(var(--danger))" title="queue-wait share × 0.45" />
                <Component share={s.utilisation * 0.3} color="rgb(var(--warn))" title="utilisation × 0.30" />
                <Component
                  share={Math.max(s.score - s.queue_wait_share * 0.45 - s.utilisation * 0.3, 0)}
                  color="rgb(var(--info))"
                  title="unexplained residual × 0.25"
                />
                <span className="flex-1 bg-line/8" />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-line/8 pt-2 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-4">
          <Legend color="rgb(var(--danger))">queue ×0.45</Legend>
          <Legend color="rgb(var(--warn))">util ×0.30</Legend>
          <Legend color="rgb(var(--info))">residual ×0.25</Legend>
        </div>
      </Pane>
    </Split>
  );
}

const Component = ({ share, color, title }) => (
  <span title={title} style={{ flex: `${Math.max(share, 0.001)} 0 0`, background: color }} />
);

const Legend = ({ color, children }) => (
  <span className="flex items-center gap-1.5">
    <span className="h-2 w-3 rounded-[3px]" style={{ background: color }} />
    {children}
  </span>
);

/* -- 3. M3 ---------------------------------------------------------------- */

function M3Panel({ step }) {
  return (
    <Split ratio="1.4fr_1fr">
      <Pane
        label={step.timeline_stage ? `${pretty(step.timeline_stage)} — hour by hour` : "Timeline"}
      >
        <AnomalyStrip
          timeline={step.timeline}
          injectedAt={step.injected_at}
          stageLabel={pretty(step.timeline_stage)}
        />
      </Pane>

      <Pane
        label="Activities tripping, by share of flagged windows"
        note="The detector runs at 5% contamination, so a few percent on a quiet activity is the noise floor. What separates a real constraint is the run of consecutive flagged hours — two sustained flags before an activity trips at all."
      >
        <ol className="space-y-[3px]">
          {step.anomalies.slice(0, 9).map((a) => (
            <li key={a.stage} className="grid grid-cols-[1fr_auto] items-center gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="h-3 w-[3px] shrink-0 rounded-full"
                  style={{ background: MACRO_COLOR[a.macro_stage] }}
                />
                <span className="truncate text-[11.5px] text-ink-2">{a.label}</span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="block h-2 w-[88px] overflow-hidden rounded-full bg-line/8">
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${clamp(a.share / 0.25) * 100}%`,
                      background: a.share > 0.12 ? "rgb(var(--danger))" : "rgb(var(--ink-3))",
                    }}
                  />
                </span>
                <span className="w-9 text-right font-mono text-[10.5px] tabular-nums text-ink-2">
                  {pct(a.share, 0)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </Pane>
    </Split>
  );
}

/* -- 4. the agent --------------------------------------------------------- */

function AgentPanel({ step }) {
  return (
    <Split ratio="1fr_1.5fr">
      <div className="grid min-h-0 grid-cols-1 grid-rows-[minmax(0,1fr)_auto] gap-3">
        <Pane label="What triggered the investigation">
          <ol className="space-y-1">
            {step.trigger.slice(0, 6).map((t) => (
              <li key={t.stage} className="flex items-baseline justify-between gap-2 text-[11.5px]">
                <span className="truncate text-ink-2">{pretty(t.stage)}</span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-4">
                  {pct(t.share, 0)} · {t.n_anomalous_windows} h
                </span>
              </li>
            ))}
          </ol>
        </Pane>
        <Pane label="Stop reason" className="shrink-0">
          <p className="clamp-4 text-[11.5px] leading-relaxed text-ink-2">{step.stop_reason}</p>
        </Pane>
      </div>

      <Pane label="The probe tree — every node carries its own reasoning">
        <ol className="space-y-2">
          {step.nodes.slice(0, 4).map((n) => (
            <li key={n.node_id} className="relative" style={{ marginLeft: n.depth * 16 }}>
              {n.depth > 0 && (
                <span className="absolute -left-[10px] top-4 h-px w-2.5 bg-line/25" aria-hidden />
              )}
              <div className="rounded-lg border border-line/10 bg-surface p-2.5 shadow-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="chip-solid">{n.probe_type}</span>
                  <span className="truncate text-[12.5px] font-semibold text-ink">{n.label}</span>
                  <span className="ml-auto shrink-0 font-mono text-[9.5px] tabular-nums text-ink-4">
                    impact {num(n.impact, 2)} × uncert {num(n.uncertainty, 2)}
                  </span>
                </div>
                <p className="clamp-3 mt-1.5 text-[11.5px] leading-relaxed text-ink-3">
                  {n.reasoning}
                </p>
                {n.hypotheses?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {n.hypotheses.map((h) => (
                      <span
                        key={h.cause}
                        className={h.p > 0.6 ? "chip border-danger/30 bg-danger/[0.06] text-danger" : "chip"}
                      >
                        {pretty(h.cause)} {num(h.p, 2)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Pane>
    </Split>
  );
}

/* -- 5. M4 ---------------------------------------------------------------- */

const CAUSE_NOTE = {
  capacity_saturation:
    "A roster that is constant and simply too small: the activity is flat out all week and the queue never clears.",
  staffing_shortage:
    "Capacity below the activity's own normal roster for part of the week — the roster is fine on Tuesday and gone on Saturday.",
  normal:
    "Nothing is wrong with this activity. Reporting normal where nothing is wrong is half of what the classifier is for.",
};

function M4Panel({ step }) {
  return (
    <Split ratio="1fr_1fr">
      <Pane label={`Cause distribution at ${step.stage ? pretty(step.stage) : "—"}`}>
        <ol className="space-y-3">
          {step.hypotheses.map((h) => (
            <li key={h.cause}>
              <div className="mb-1.5 flex items-baseline justify-between gap-2">
                <span className="truncate text-[12.5px] font-medium text-ink-2">
                  {step.cause_labels?.[h.cause] ?? pretty(h.cause)}
                </span>
                <span className="shrink-0 font-mono text-[11.5px] font-semibold tabular-nums text-ink">
                  {num(h.p, 3)}
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-line/8">
                <div
                  className="h-full origin-left animate-sweep rounded-full"
                  style={{
                    width: `${clamp(h.p) * 100}%`,
                    background: h.p > 0.6 ? "rgb(var(--danger))" : "rgb(var(--ink-3))",
                  }}
                />
              </div>
            </li>
          ))}
        </ol>
      </Pane>

      <Pane label="The two failure modes it separates">
        <div className="space-y-2">
          {["capacity_saturation", "staffing_shortage", "normal"].map((c) => {
            const isVerdict = step.hypotheses?.[0]?.cause === c;
            return (
              <div
                key={c}
                className={`rounded-lg border p-2.5 transition-colors ${
                  isVerdict ? "border-danger/30 bg-danger/[0.04]" : "border-line/10"
                }`}
              >
                <p className="flex items-center gap-2 text-[12px] font-semibold text-ink">
                  {step.cause_labels?.[c] ?? pretty(c)}
                  {isVerdict && <span className="chip border-danger/30 text-danger">verdict</span>}
                </p>
                <p className="clamp-2 mt-1 text-[11px] leading-relaxed text-ink-3">
                  {CAUSE_NOTE[c]}
                </p>
              </div>
            );
          })}
        </div>
      </Pane>
    </Split>
  );
}

/* -- 6. M5 ---------------------------------------------------------------- */

function M5Panel({ step }) {
  const scale = Math.max(...step.candidates.map((c) => Math.abs(c.ci_high)), 0.1);
  return (
    <Pane
      label="Paired counterfactual re-simulation — seeds 42 / 43 / 44"
      note="Each candidate is simulated three times against three paired baselines that share an identical arrival stream and identical per-case service shocks. The interval is this narrow at n=3 because the pairing removes sampling noise, not because the sample is large."
      className="h-full"
    >
      <div className="grid h-full min-h-0 auto-rows-min grid-cols-1 gap-2.5">
        {step.candidates.slice(0, 4).map((c) => (
          <div key={c.action} className="rounded-lg border border-line/10 bg-surface p-3 shadow-xs">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-[13px] font-semibold text-ink">{c.label}</p>
                <p className="truncate font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-4">
                  {pretty(c.stage)} · {money(c.cost)} {c.cost_type?.replace("_", "-")}
                </p>
              </div>
              <p className="metric shrink-0 text-[18px] font-bold tracking-[-0.02em] text-ok">
                −{hours(c.delta_hours)}
              </p>
            </div>

            {/* The interval, drawn. A number ± a number is easy to skim past; a
                bar that visibly does not cross zero is not. */}
            <div className="relative mt-2 h-5">
              <span className="absolute inset-x-0 top-1/2 h-px bg-line/12" />
              <span className="absolute inset-y-0 left-0 w-px bg-line/35" />
              <span
                className="absolute top-1/2 h-[8px] -translate-y-1/2 rounded-full bg-ok/25"
                style={{
                  left: `${clamp(c.ci_low / scale) * 100}%`,
                  width: `${clamp((c.ci_high - c.ci_low) / scale) * 100}%`,
                }}
              />
              <span
                className="absolute top-1/2 h-[13px] w-[3px] -translate-y-1/2 rounded-full bg-ok"
                style={{ left: `${clamp(c.delta_hours / scale) * 100}%` }}
              />
            </div>
            <p className="truncate font-mono text-[10px] tabular-nums text-ink-4">
              95% CI {hours(c.ci_low)} to {hours(c.ci_high)} · p90 −{hours(c.delta_p90_hours)} ·
              SLA {pct(c.delta_sla_rate, 2)} better
            </p>
          </div>
        ))}
      </div>
    </Pane>
  );
}

/* -- 7. M6 ---------------------------------------------------------------- */

function M6Panel({ step }) {
  const spendShare = clamp(step.spend / step.budget_cap);
  return (
    <div className="grid h-full min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3">
      <Pane label="Budget committed" className="shrink-0">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <p className="font-mono text-[11px] tabular-nums text-ink-2">
            {money(step.spend)} of {money(step.budget_cap)}
          </p>
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-4">
            {pct(1 - spendShare, 0)} deliberately unspent
          </p>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-line/8">
          <div
            className="h-full origin-left animate-sweep rounded-full bg-accent"
            style={{ width: `${spendShare * 100}%` }}
          />
        </div>
      </Pane>

      <Pane
        label="Every candidate, priced"
        note="Benefit = hours saved × 270 cases a day × 30 days × ₹12 an hour of holding cost, plus SLA penalties avoided. Selection is greedy on ROI-per-rupee; an ROI-negative action is never bought just because budget remains."
      >
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr>
              {["", "Action", "Δ cycle", "Cost", "Benefit 30d", "ROI"].map((h, i) => (
                <th
                  key={h + i}
                  className={`border-b border-line/10 pb-1.5 font-mono text-label uppercase text-ink-3 ${
                    i > 1 ? "text-right" : "text-left"
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {step.candidates.slice(0, 6).map((c) => (
              <tr
                key={c.action}
                className={`border-b border-line/6 last:border-b-0 ${c.selected ? "bg-ok/[0.05]" : ""}`}
              >
                <td className="py-1.5 pr-2">
                  <span
                    className={`grid h-4 w-4 place-items-center rounded-[5px] border text-[9px] ${
                      c.selected
                        ? "border-ok bg-ok text-white"
                        : "border-line/25 text-transparent"
                    }`}
                    title={c.selected ? "Selected by M6" : "Not selected"}
                  >
                    ✓
                  </span>
                </td>
                <td className="max-w-0 py-1.5 pr-2">
                  <span className="block truncate font-medium text-ink-2">{c.label}</span>
                  <span className="block truncate font-mono text-[9.5px] text-ink-4">
                    {pretty(c.stage)}
                  </span>
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-ok">
                  −{hours(c.delta_hours)}
                </td>
                <td className="py-1.5 pl-2 text-right font-mono tabular-nums text-ink-2">
                  {money(c.cost, true)}
                </td>
                <td className="py-1.5 pl-2 text-right font-mono tabular-nums text-ink-2">
                  {money(c.benefit_30d, true)}
                </td>
                <td
                  className={`py-1.5 pl-2 text-right font-mono font-semibold tabular-nums ${
                    c.roi > 0 ? "text-ok" : "text-danger"
                  }`}
                >
                  {num(c.roi)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Pane>
    </div>
  );
}

/* -- 8. outcome ----------------------------------------------------------- */

function OutcomePanel({ step }) {
  if (!step.delta) {
    return (
      <Pane label="Outcome" className="h-full">
        <p className="text-[13px] leading-relaxed text-ink-2">{step.narrative}</p>
      </Pane>
    );
  }
  const rows = [
    ["Mean cycle", step.before.mean_cycle_hours, step.after.mean_cycle_hours, hours, true],
    ["p90 cycle", step.before.p90_cycle_hours, step.after.p90_cycle_hours, hours, true],
    ["Cost per case", step.before.cost_per_case, step.after.cost_per_case, money, true],
    ["SLA breach", step.before.sla_breach_rate, step.after.sla_breach_rate, (v) => pct(v, 2), true],
    ["Throughput / day", step.before.throughput_per_day, step.after.throughput_per_day, (v) => num(v, 0), false],
  ];

  return (
    <Split ratio="1.15fr_1fr">
      <Pane label="Before and after, same seed">
        <ol className="space-y-2">
          {rows.map(([label, before, after, fmt, lowerIsBetter]) => {
            const improved = lowerIsBetter ? after < before : after > before;
            const change = before === 0 ? 0 : (after - before) / Math.abs(before);
            return (
              <li key={label} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-2">
                <span className="truncate text-[11.5px] text-ink-3">{label}</span>
                <span className="font-mono text-[11px] tabular-nums text-ink-4 line-through decoration-line/25">
                  {fmt(before)}
                </span>
                <span className="font-mono text-[9.5px] text-ink-4">→</span>
                <span
                  className={`w-[104px] text-right font-mono text-[12.5px] font-semibold tabular-nums ${
                    improved ? "text-ok" : "text-danger"
                  }`}
                >
                  {fmt(after)}
                  <span className="ml-1 text-[9px] font-normal opacity-70">
                    {change > 0 ? "+" : ""}
                    {(change * 100).toFixed(1)}%
                  </span>
                </span>
              </li>
            );
          })}
        </ol>

        <div className="mt-3 border-t border-line/8 pt-2.5">
          <p className="eyebrow mb-1.5">Applied</p>
          <ul className="space-y-1">
            {step.actions.slice(0, 3).map((a) => (
              <li key={a.action} className="flex items-baseline justify-between gap-2 text-[11.5px]">
                <span className="truncate text-ink-2">{a.label}</span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-4">
                  {money(a.cost, true)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </Pane>

      <Pane
        label="Where the constraint moved to"
        note="Relieving one constraint promotes the next. This is the world the agent would re-plan against — the same loop, no code change, a different answer."
      >
        <RankBars rows={step.ranking_after.slice(0, 7)} showRank />
      </Pane>
    </Split>
  );
}
