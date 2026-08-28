import AnomalyStrip from "./charts/AnomalyStrip.jsx";
import PredScatter from "./charts/PredScatter.jsx";
import RankBars from "./charts/RankBars.jsx";
import Waterfall from "./charts/Waterfall.jsx";
import { Button, HealthDot, Metric } from "./ui.jsx";
import { MACRO_COLOR, clamp, hours, int, money, num, pct, pretty } from "../lib/format.js";

/**
 * The body of one pipeline panel.
 *
 * Each of the nine steps gets its own visualisation, because each one is
 * answering a different shape of question — a ranking is a bar list, a
 * prediction is a scatter against the diagonal, a counterfactual is an interval,
 * a budget decision is a table with a spend line. A single generic chart
 * component reused nine times would have been less code and a much worse panel.
 */
export default function PipelinePanel({ step, journey, activeIndex, setActiveIndex, onSelectStage }) {
  switch (step.key) {
    case "world":
      return <WorldPanel step={step} journey={journey} activeIndex={activeIndex} setActiveIndex={setActiveIndex} />;
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

/* -- 0. the world --------------------------------------------------------- */

function WorldPanel({ step, journey, activeIndex, setActiveIndex }) {
  const a = journey.attributes;
  const steps = journey.steps;
  const active = activeIndex != null ? steps[activeIndex] : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="eyebrow">Case {journey.case_id} · all 24 activities</p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={activeIndex == null || activeIndex <= 0}
              onClick={() => setActiveIndex(Math.max(0, (activeIndex ?? 0) - 1))}
              aria-label="Previous activity"
            >
              ◀
            </Button>
            <span className="w-24 text-center font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-mid">
              {activeIndex == null ? "all" : `${activeIndex + 1} / ${steps.length}`}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={activeIndex != null && activeIndex >= steps.length - 1}
              onClick={() => setActiveIndex(activeIndex == null ? 0 : activeIndex + 1)}
              aria-label="Next activity"
            >
              ▶
            </Button>
            {activeIndex != null && (
              <Button variant="ghost" size="sm" onClick={() => setActiveIndex(null)}>
                Clear
              </Button>
            )}
          </div>
        </div>
        <Waterfall
          steps={steps}
          activeIndex={activeIndex}
          onSelect={(i) => setActiveIndex(i === activeIndex ? null : i)}
          total={journey.cycle_hours}
        />
      </div>

      <div className="space-y-3">
        <div className="panel-flat p-4">
          <p className="eyebrow mb-3">This case</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Metric label="Cycle time" value={hours(journey.cycle_hours)}
                    hint={`p${Math.round(journey.cycle_percentile * 100)} of the population`} />
            <Metric label="Of which queued" value={hours(journey.queue_hours)}
                    tone="text-red"
                    hint={pct(journey.queue_hours / journey.cycle_hours)} />
            <Metric label="Cost" value={money(journey.cost)} hint="holding cost" />
            <Metric label="SLA" value={journey.sla_breach ? "Breached" : "Met"}
                    tone={journey.sla_breach ? "text-red" : "text-band-green"}
                    hint={`threshold ${journey.sla_threshold_hours} h`} />
          </div>
        </div>

        <div className="panel-flat p-4">
          <p className="eyebrow mb-3">Attributes</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
            <Attr k="Segment" v={pretty(a.customer_segment)} />
            <Attr k="Tier" v={pretty(a.customer_tier)} />
            <Attr k="Priority" v={pretty(a.priority)} />
            <Attr k="Region" v={pretty(a.region)} />
            <Attr k="Order value" v={money(a.order_value)} />
            <Attr k="Fraud risk" v={num(a.fraud_risk)} />
            <Attr k="Claim type" v={pretty(a.claim_type)} />
            <Attr k="Support channel" v={pretty(a.support_channel)} />
            <Attr k="Invoice" v={money(a.invoice_value)} />
            <Attr k="Exception" v={a.invoice_exception ? pretty(a.invoice_exception_reason) : "None"} />
          </dl>
        </div>

        {active && (
          <div className="panel-flat animate-rise p-4">
            <p className="eyebrow mb-2">
              Step {active.order + 1} · {active.macro_label}
            </p>
            <p className="text-[15px] font-semibold">{active.label}</p>
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[11px] tabular-nums">
              <Row k="Queued" v={hours(active.queue_wait_hours)} />
              <Row k="Worked" v={hours(active.service_hours)} />
              <Row k="Queue depth" v={active.queue_len_at_arrival} />
              <Row k="Servers busy" v={active.servers_busy} />
              <Row k="M1 predicted" v={hours(active.predicted_hours)} />
              <Row k="Residual" v={hours(active.residual_hours)}
                   tone={active.residual_hours > 0 ? "text-red" : "text-band-green"} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const Attr = ({ k, v }) => (
  <>
    <dt className="truncate text-ink-faint">{k}</dt>
    <dd className="truncate text-right font-medium">{v}</dd>
  </>
);

const Row = ({ k, v, tone }) => (
  <>
    <span className="text-ink-faint">{k}</span>
    <span className={`text-right font-medium ${tone ?? ""}`}>{v}</span>
  </>
);

/* -- 1. M1 ---------------------------------------------------------------- */

function M1Panel({ step }) {
  const rows = [...(step.predictions ?? [])].sort(
    (a, b) => Math.abs(b.residual) - Math.abs(a.residual),
  );
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-2">Predicted against actual, this case</p>
        <PredScatter predictions={step.predictions} highlight={step.worst_residual_stage} />
      </div>
      <div className="panel-flat overflow-hidden p-4">
        <p className="eyebrow mb-3">Largest residuals — where M1 was most wrong</p>
        <ol className="space-y-1.5">
          {rows.slice(0, 9).map((r) => {
            const scale = Math.max(...rows.map((x) => Math.abs(x.residual)), 0.01);
            const width = clamp(Math.abs(r.residual) / scale) * 50;
            const over = r.residual > 0;
            return (
              <li key={r.stage} className="grid grid-cols-[1fr_auto] items-center gap-2">
                <span className="flex items-center gap-2 min-w-0">
                  <span className="h-3 w-[3px] shrink-0 rounded-sm"
                        style={{ background: MACRO_COLOR[r.macro_stage] }} />
                  <span className="truncate text-[12.5px]">{r.label}</span>
                </span>
                <span className="flex items-center gap-2">
                  {/* A centred divergent bar: right of the axis is slower than
                      predicted, left is faster. The sign is the whole point. */}
                  <span className="relative block h-2 w-[120px] rounded-sm bg-ink/6">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-ink/25" />
                    <span
                      className="absolute inset-y-0 rounded-sm"
                      style={{
                        left: over ? "50%" : `${50 - width}%`,
                        width: `${width}%`,
                        background: over ? "rgb(var(--red))" : "rgb(var(--green))",
                      }}
                    />
                  </span>
                  <span className={`w-16 text-right font-mono text-[11px] tabular-nums ${
                    over ? "text-red" : "text-band-green"
                  }`}>
                    {over ? "+" : "−"}{hours(Math.abs(r.residual))}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
        <p className="mt-3 border-t border-ink/10 pt-3 text-[11.5px] leading-relaxed text-ink-faint">
          Positive means the activity took longer than the model could account for from
          the case's attributes, the queue it arrived into and the hour of the week.
          That unexplained share is 25% of M2's bottleneck score.
        </p>
      </div>
    </div>
  );
}

/* -- 2. M2 ---------------------------------------------------------------- */

function M2Panel({ step, onSelectStage }) {
  const top = step.ranking.slice(0, 12);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">Ranked by share of total delay</p>
        <RankBars rows={top} onSelect={onSelectStage} selected={step.top_stage} />
      </div>
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">The three things an activity can be guilty of</p>
        <div className="space-y-4">
          {top.slice(0, 5).map((s) => (
            <div key={s.stage}>
              <div className="mb-1.5 flex items-baseline justify-between gap-2">
                <span className="truncate text-[12.5px] font-medium">{s.label}</span>
                <span className="font-mono text-[10.5px] tabular-nums text-ink-faint">
                  score {num(s.score, 3)}
                </span>
              </div>
              <div className="flex h-2.5 gap-px overflow-hidden rounded-sm">
                <Component share={s.queue_wait_share * 0.45} color="rgb(var(--red))" title="queue-wait share × 0.45" />
                <Component share={s.utilisation * 0.3} color="rgb(var(--amber))" title="utilisation × 0.30" />
                <Component share={Math.max(s.score - s.queue_wait_share * 0.45 - s.utilisation * 0.3, 0)}
                           color="rgb(var(--blue))" title="unexplained residual × 0.25" />
                <span className="flex-1 bg-ink/6" />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-ink/10 pt-3 font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-faint">
          <Legend color="rgb(var(--red))">queue wait ×0.45</Legend>
          <Legend color="rgb(var(--amber))">utilisation ×0.30</Legend>
          <Legend color="rgb(var(--blue))">residual ×0.25</Legend>
        </div>
      </div>
    </div>
  );
}

const Component = ({ share, color, title }) => (
  <span title={title} style={{ flex: `${Math.max(share, 0.001)} 0 0`, background: color }} />
);

const Legend = ({ color, children }) => (
  <span className="flex items-center gap-1.5">
    <span className="h-2 w-3 rounded-[2px]" style={{ background: color }} />
    {children}
  </span>
);

/* -- 3. M3 ---------------------------------------------------------------- */

function M3Panel({ step }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">
          {step.timeline_stage ? `${pretty(step.timeline_stage)} — hour by hour` : "Timeline"}
        </p>
        <AnomalyStrip
          timeline={step.timeline}
          injectedAt={step.injected_at}
          stageLabel={pretty(step.timeline_stage)}
        />
      </div>
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">Activities tripping, by share of flagged windows</p>
        <ol className="space-y-1.5">
          {step.anomalies.slice(0, 10).map((a) => (
            <li key={a.stage} className="grid grid-cols-[1fr_auto] items-center gap-2">
              <span className="flex items-center gap-2 min-w-0">
                <span className="h-3 w-[3px] shrink-0 rounded-sm"
                      style={{ background: MACRO_COLOR[a.macro_stage] }} />
                <span className="truncate text-[12.5px]">{a.label}</span>
              </span>
              <span className="flex items-center gap-2">
                <span className="block h-2 w-[110px] rounded-sm bg-ink/6">
                  <span
                    className="block h-full rounded-sm"
                    style={{
                      width: `${clamp(a.share / 0.25) * 100}%`,
                      background: a.share > 0.12 ? "rgb(var(--red))" : "rgb(var(--ink-light))",
                    }}
                  />
                </span>
                <span className="w-12 text-right font-mono text-[11px] tabular-nums">
                  {pct(a.share, 0)}
                </span>
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 border-t border-ink/10 pt-3 text-[11.5px] leading-relaxed text-ink-faint">
          The detector is set to 5% contamination, so a few percent on a quiet activity
          is the noise floor rather than a finding. What separates a real constraint is
          the run of consecutive flagged hours, which is why two sustained flags are
          required before an activity trips at all.
        </p>
      </div>
    </div>
  );
}

/* -- 4. the agent --------------------------------------------------------- */

function AgentPanel({ step }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">What triggered the investigation</p>
        <ol className="space-y-1.5">
          {step.trigger.slice(0, 6).map((t) => (
            <li key={t.stage} className="flex items-baseline justify-between gap-2 text-[12.5px]">
              <span className="truncate">{pretty(t.stage)}</span>
              <span className="font-mono text-[10.5px] tabular-nums text-ink-faint">
                {pct(t.share, 0)} · {t.n_anomalous_windows} h
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-4 rounded-lg border border-ink/12 bg-paper-sink/40 p-3">
          <p className="eyebrow mb-1.5">Stop reason</p>
          <p className="text-[12px] leading-relaxed text-ink-mid">{step.stop_reason}</p>
        </div>
      </div>

      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">The probe tree — every node carries its own reasoning</p>
        <ol className="space-y-2.5">
          {step.nodes.map((n) => (
            <li key={n.node_id} className="relative" style={{ marginLeft: n.depth * 18 }}>
              {n.depth > 0 && (
                <span className="absolute -left-[11px] top-3 h-px w-2.5 bg-ink/25" aria-hidden />
              )}
              <div className="rounded-lg border border-ink/14 bg-paper p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-paper bg-ink rounded-full px-2 py-0.5">
                    {n.probe_type}
                  </span>
                  <span className="text-[13px] font-semibold">{n.label}</span>
                  <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-faint">
                    impact {num(n.impact, 2)} × uncertainty {num(n.uncertainty, 2)}
                  </span>
                </div>
                <p className="mt-2 text-[12.5px] leading-relaxed text-ink-mid">{n.reasoning}</p>
                {n.hypotheses?.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {n.hypotheses.map((h) => (
                      <span
                        key={h.cause}
                        className={`tag ${h.p > 0.6 ? "border-red/40 bg-red/8 text-red" : ""}`}
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
      </div>
    </div>
  );
}

/* -- 5. M4 ---------------------------------------------------------------- */

function M4Panel({ step }) {
  const CAUSE_NOTE = {
    capacity_saturation:
      "A roster that is constant and simply too small: the activity is flat out all week and the queue never clears.",
    staffing_shortage:
      "Capacity below the activity's own normal roster for part of the week — the roster is fine on Tuesday and gone on Saturday.",
    normal: "Nothing is wrong with this activity. Reporting normal where nothing is wrong is half of what the classifier is for.",
  };
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-4">
          Cause distribution at {step.stage ? pretty(step.stage) : "—"}
        </p>
        <ol className="space-y-3">
          {step.hypotheses.map((h) => (
            <li key={h.cause}>
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[13px] font-medium">
                  {step.cause_labels?.[h.cause] ?? pretty(h.cause)}
                </span>
                <span className="font-mono text-[12px] tabular-nums font-semibold">
                  {num(h.p, 3)}
                </span>
              </div>
              <div className="h-3 rounded-sm bg-ink/7">
                <div
                  className="h-full origin-left animate-sweep rounded-sm"
                  style={{
                    width: `${clamp(h.p) * 100}%`,
                    background: h.p > 0.6 ? "rgb(var(--red))" : "rgb(var(--ink-light))",
                  }}
                />
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">The two failure modes it separates</p>
        <div className="space-y-3">
          {["capacity_saturation", "staffing_shortage", "normal"].map((c) => {
            const isVerdict = step.hypotheses?.[0]?.cause === c;
            return (
              <div
                key={c}
                className={`rounded-lg border p-3 transition-colors ${
                  isVerdict ? "border-red/35 bg-red/[0.05]" : "border-ink/12"
                }`}
              >
                <p className="flex items-center gap-2 text-[12.5px] font-semibold">
                  {step.cause_labels?.[c] ?? pretty(c)}
                  {isVerdict && (
                    <span className="tag border-red/40 text-red">verdict</span>
                  )}
                </p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-ink-mid">
                  {CAUSE_NOTE[c]}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* -- 6. M5 ---------------------------------------------------------------- */

function M5Panel({ step }) {
  const scale = Math.max(...step.candidates.map((c) => Math.abs(c.ci_high)), 0.1);
  return (
    <div className="space-y-3">
      {step.candidates.map((c) => (
        <div key={c.action} className="panel-flat p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[14px] font-semibold">{c.label}</p>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint">
                {c.action} · {pretty(c.stage)} · {money(c.cost)} {c.cost_type?.replace("_", "-")}
              </p>
            </div>
            <p className="metric text-[20px] font-extrabold tracking-[-0.02em] text-band-green">
              −{hours(c.delta_hours)}
            </p>
          </div>

          {/* The interval, drawn. A number ±  a number is easy to skim past; a
              bar that visibly does not cross zero is not. */}
          <div className="mt-3">
            <div className="relative h-7">
              <span className="absolute inset-x-0 top-1/2 h-px bg-ink/12" />
              <span className="absolute left-0 inset-y-0 w-px bg-ink/35" />
              <span className="absolute left-0 top-0 font-mono text-[8.5px] uppercase tracking-[0.14em] text-ink-faint">
                0
              </span>
              <span
                className="absolute top-1/2 h-[9px] -translate-y-1/2 rounded-sm bg-band-green/25"
                style={{
                  left: `${clamp(c.ci_low / scale) * 100}%`,
                  width: `${clamp((c.ci_high - c.ci_low) / scale) * 100}%`,
                }}
              />
              <span
                className="absolute top-1/2 h-[15px] w-[3px] -translate-y-1/2 rounded-sm bg-band-green"
                style={{ left: `${clamp(c.delta_hours / scale) * 100}%` }}
              />
            </div>
            <p className="font-mono text-[10.5px] tabular-nums text-ink-faint">
              95% CI {hours(c.ci_low)} to {hours(c.ci_high)} · p90 −{hours(c.delta_p90_hours)} ·
              SLA {pct(c.delta_sla_rate, 2)} better
              {c.per_seed_delta && (
                <> · seeds {c.per_seed_delta.map((d) => num(d)).join(" / ")}</>
              )}
            </p>
          </div>
        </div>
      ))}
      <p className="text-[11.5px] leading-relaxed text-ink-faint">
        Each candidate is simulated three times against three paired baselines that share
        an identical arrival stream and identical per-case service shocks. The interval is
        this narrow at n=3 because the pairing removes sampling noise, not because the
        sample is large.
      </p>
    </div>
  );
}

/* -- 7. M6 ---------------------------------------------------------------- */

function M6Panel({ step }) {
  const spendShare = clamp(step.spend / step.budget_cap);
  return (
    <div className="space-y-4">
      <div className="panel-flat p-4">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <p className="eyebrow">Budget committed</p>
          <p className="font-mono text-[11px] tabular-nums">
            {money(step.spend)} of {money(step.budget_cap)}
          </p>
        </div>
        <div className="h-3.5 overflow-hidden rounded-sm bg-ink/7">
          <div
            className="h-full origin-left animate-sweep rounded-sm bg-ink"
            style={{ width: `${spendShare * 100}%` }}
          />
        </div>
        <p className="mt-2 text-[11.5px] text-ink-faint">
          {pct(1 - spendShare, 0)} of the cap is deliberately left unspent — nothing else
          on the table returns more than it costs.
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-ink/12">
        <table className="w-full min-w-[620px] border-collapse text-[13px]">
          <thead>
            <tr>
              {["", "Action", "Δ cycle", "Cost", "Benefit 30d", "ROI"].map((h, i) => (
                <th
                  key={h + i}
                  className={`border-b border-ink/14 bg-paper-sink/60 px-3 py-2.5 font-mono text-label uppercase text-ink-light ${
                    i > 1 ? "text-right" : "text-left"
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {step.candidates.map((c) => (
              <tr
                key={c.action}
                className={`border-b border-ink/8 last:border-b-0 ${
                  c.selected ? "bg-band-green/[0.06]" : ""
                }`}
              >
                <td className="px-3 py-2.5">
                  <span
                    className={`grid h-4 w-4 place-items-center rounded-sm border text-[9px] ${
                      c.selected
                        ? "border-band-green bg-band-green text-paper"
                        : "border-ink/25 text-transparent"
                    }`}
                    title={c.selected ? "Selected by M6" : "Not selected"}
                  >
                    ✓
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className="block font-medium">{c.label}</span>
                  <span className="font-mono text-[10px] text-ink-faint">
                    {pretty(c.stage)}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-band-green">
                  −{hours(c.delta_hours)}
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                  {money(c.cost, true)}
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                  {money(c.benefit_30d, true)}
                </td>
                <td
                  className={`px-3 py-2.5 text-right font-mono tabular-nums font-semibold ${
                    c.roi > 0 ? "text-band-green" : "text-red"
                  }`}
                >
                  {num(c.roi)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11.5px] leading-relaxed text-ink-faint">
        Benefit = hours saved × 270 cases a day × 30 days × ₹12 an hour of holding cost,
        plus the SLA penalties avoided. Selection is greedy on ROI-per-rupee, and an
        ROI-negative action is never bought just because budget remains.
      </p>
    </div>
  );
}

/* -- 8. outcome ----------------------------------------------------------- */

function OutcomePanel({ step }) {
  if (!step.delta) {
    return <p className="text-[14px] text-ink-mid">{step.narrative}</p>;
  }
  const rows = [
    ["Mean cycle", step.before.mean_cycle_hours, step.after.mean_cycle_hours, hours, true],
    ["p90 cycle", step.before.p90_cycle_hours, step.after.p90_cycle_hours, hours, true],
    ["Cost per case", step.before.cost_per_case, step.after.cost_per_case, money, true],
    ["SLA breach", step.before.sla_breach_rate, step.after.sla_breach_rate, (v) => pct(v, 2), true],
    ["Throughput / day", step.before.throughput_per_day, step.after.throughput_per_day, (v) => num(v, 0), false],
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <div className="panel-flat p-4">
        <p className="eyebrow mb-4">Before and after, same seed</p>
        <ol className="space-y-3">
          {rows.map(([label, before, after, fmt, lowerIsBetter]) => {
            const improved = lowerIsBetter ? after < before : after > before;
            const change = before === 0 ? 0 : (after - before) / Math.abs(before);
            return (
              <li key={label} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3">
                <span className="truncate text-[12.5px] text-ink-mid">{label}</span>
                <span className="font-mono text-[12px] tabular-nums text-ink-faint line-through decoration-ink/25">
                  {fmt(before)}
                </span>
                <span className="font-mono text-[10px] text-ink-faint">→</span>
                <span
                  className={`w-24 text-right font-mono text-[13px] tabular-nums font-semibold ${
                    improved ? "text-band-green" : "text-red"
                  }`}
                >
                  {fmt(after)}
                  <span className="ml-1.5 text-[9.5px] font-normal opacity-70">
                    {change > 0 ? "+" : ""}
                    {(change * 100).toFixed(1)}%
                  </span>
                </span>
              </li>
            );
          })}
        </ol>

        <div className="mt-4 border-t border-ink/10 pt-3">
          <p className="eyebrow mb-2">Applied</p>
          <ul className="space-y-1">
            {step.actions.map((a) => (
              <li key={a.action} className="flex items-baseline justify-between gap-2 text-[12.5px]">
                <span className="truncate">{a.label}</span>
                <span className="font-mono text-[10.5px] tabular-nums text-ink-faint">
                  {money(a.cost, true)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="panel-flat p-4">
        <p className="eyebrow mb-3">Where the constraint moved to</p>
        <RankBars rows={step.ranking_after} showRank />
        <p className="mt-3 border-t border-ink/10 pt-3 text-[11.5px] leading-relaxed text-ink-faint">
          Relieving one constraint promotes the next. This is the world the agent would
          re-plan against — the same loop, no code change, a different answer.
        </p>
      </div>
    </div>
  );
}
