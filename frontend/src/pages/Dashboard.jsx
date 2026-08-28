import { useState } from "react";
import { Link } from "react-router-dom";
import {
  getMacro,
  getModelMetrics,
  getOverview,
  getScenarios,
  getStages,
  injectScenario,
  resetRuns,
} from "../api.js";
import AnomalyStrip from "../components/charts/AnomalyStrip.jsx";
import RankBars from "../components/charts/RankBars.jsx";
import ShareBar from "../components/charts/ShareBar.jsx";
import ProcessRail from "../components/ProcessRail.jsx";
import StageTable from "../components/StageTable.jsx";
import {
  Button,
  ErrorNote,
  Eyebrow,
  Metric,
  Section,
  Skeleton,
  StatCard,
} from "../components/ui.jsx";
import { hours, int, money, num, pct, pretty } from "../lib/format.js";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";
import { getPipeline } from "../api.js";

export default function Dashboard() {
  const { runId, runs, setRunId, refresh } = useRun();
  const [selected, setSelected] = useState(null);
  const [macroFilter, setMacroFilter] = useState(null);
  const [busy, setBusy] = useState(false);

  const overview = useAsync(() => getOverview(runId), [runId], { skip: !runId });
  const stages = useAsync(() => getStages(runId), [runId], { skip: !runId });
  const macro = useAsync(() => getMacro(runId), [runId], { skip: !runId });
  const metrics = useAsync(() => getModelMetrics(), []);
  const scenarios = useAsync(() => getScenarios(), []);
  // The anomaly strip needs M3's timeline, which comes with the pipeline. It is
  // the one expensive fetch on this page, so it is fired alongside the rest
  // rather than blocking them — the panel fills in when it lands.
  const pipeline = useAsync(() => getPipeline(runId), [runId], { skip: !runId });

  async function inject(scenario) {
    setBusy(true);
    try {
      await injectScenario(scenario);
      const next = await refresh(scenario);
      if (next) setRunId(next);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await resetRuns(false);
      await refresh("baseline");
      setRunId("baseline");
    } finally {
      setBusy(false);
    }
  }

  if (overview.error) {
    return (
      <Shell>
        <ErrorNote error={overview.error} retry={overview.reload} />
      </Shell>
    );
  }

  const ov = overview.data;
  const k = ov?.kpis;
  const pk = ov?.parent_kpis;
  const m3 = pipeline.data?.steps?.[3];

  return (
    <Shell>
      {/* ---------------------------------------------------------- hero -- */}
      <header className="pb-10 pt-2">
        <div className="flex flex-wrap items-center gap-3">
          <Eyebrow>Act I · The world</Eyebrow>
          <span className="h-px flex-1 bg-ink/14" />
          <span className="tag">Seed 42 · reproducible</span>
        </div>

        <h1 className="mt-6 text-display font-black uppercase">
          Process
          <br />
          intelligence.
        </h1>

        <div className="mt-6 grid gap-8 lg:grid-cols-[1.15fr_1fr]">
          <p className="quote max-w-xl text-[17px] leading-relaxed">
            “A discrete-event simulator generates the world. Six components predict,
            rank, detect, diagnose, simulate and price. An agent drives them — and
            re-plans after the fix.”
          </p>

          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 self-end sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
            <Fact label="01 / World" value={ov?.label ?? "—"} sub={ov?.run_id} />
            <Fact
              label="02 / Scale"
              value={ov ? int(k.n_cases) : "—"}
              sub={ov ? `${int(ov.n_events)} events` : ""}
            />
            <Fact
              label="03 / Shape"
              value={ov ? `${ov.n_activities} activities` : "—"}
              sub={ov ? `${ov.n_macro_stages} macro-stages` : ""}
            />
            <Fact
              label="04 / Horizon"
              value={ov ? `${ov.horizon_days} days` : "—"}
              sub={`SLA ${ov?.sla_threshold_hours ?? 30} h`}
            />
          </dl>
        </div>
      </header>

      {/* ------------------------------------------------------ scenarios -- */}
      <div className="rule-t flex flex-wrap items-center gap-2 py-4">
        <span className="eyebrow mr-1">World</span>
        {runs.map((r) => (
          <button
            key={r.run_id}
            onClick={() => setRunId(r.run_id)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.16em]
                        transition-colors ${
                          r.run_id === runId
                            ? "border-ink bg-ink text-paper"
                            : "border-ink/18 text-ink-mid hover:border-ink/40 hover:text-ink"
                        }`}
          >
            {r.run_id}
          </button>
        ))}

        <span className="ml-auto flex flex-wrap items-center gap-2">
          <span className="eyebrow">Inject</span>
          {(scenarios.data?.scenarios ?? [])
            .filter((s) => s.scenario !== "healthy")
            .map((s) => (
              <Button
                key={s.scenario}
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => inject(s.scenario)}
                title={`${pretty(s.bottleneck_stage)} — ${pretty(s.true_cause)}`}
              >
                {s.scenario}
              </Button>
            ))}
          <Button variant="ghost" size="sm" disabled={busy} onClick={reset}>
            Reset
          </Button>
        </span>
      </div>

      {/* ------------------------------------------------------------ KPI -- */}
      <Section eyebrow="Act II · The numbers" index={2} title="Where the week landed"
               lede="Every figure is measured against the world this one came from, not against an abstract target. A delta here is the intervention or the fault — never sampling noise.">
        {!ov ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[132px]" />)}
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Mean cycle time"
                value={num(k.mean_cycle_hours)}
                unit="hours"
                delta={pk ? k.mean_cycle_hours - pk.mean_cycle_hours : null}
                deltaLabel={pk ? `${num(Math.abs(k.mean_cycle_hours - pk.mean_cycle_hours))} h vs ${ov.parent_run_id}` : "no parent world"}
                invert
              />
              <StatCard
                label="Cost per case"
                value={money(k.cost_per_case)}
                delta={pk ? k.cost_per_case - pk.cost_per_case : null}
                deltaLabel={pk ? `${money(Math.abs(k.cost_per_case - pk.cost_per_case))}` : "—"}
                invert
                hint="holding + SLA penalty"
              />
              <StatCard
                label="SLA breach rate"
                value={pct(k.sla_breach_rate, 2)}
                delta={pk ? k.sla_breach_rate - pk.sla_breach_rate : null}
                deltaLabel={pk ? `${pct(Math.abs(k.sla_breach_rate - pk.sla_breach_rate), 2)}` : "—"}
                invert
                hint={`over ${ov.sla_threshold_hours} h`}
              />
              <StatCard
                label="Worst activity"
                value={pretty(ov.worst_activity.stage)}
                deltaLabel={`${num(ov.worst_activity.contribution_pct, 1)}% of delay`}
                hint={`util ${num(ov.worst_activity.utilisation)}`}
                accent={ov.worst_activity.health === "red"}
              />
            </div>

            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="panel p-4 sm:col-span-2">
                <p className="eyebrow mb-3">Where a case spends its lifecycle</p>
                {macro.data ? (
                  <ShareBar rows={macro.data.macro_stages} />
                ) : (
                  <Skeleton className="h-[110px]" />
                )}
              </div>
              <div className="panel grid grid-cols-2 gap-4 p-4">
                <Metric label="p90 cycle" value={hours(k.p90_cycle_hours)}
                        hint="the slow tail, not the average" />
                <Metric label="Throughput" value={`${num(k.throughput_per_day, 0)}`}
                        hint="cases per day" />
                <Metric label="Flagged" value={`${ov.n_anomalous}`}
                        tone={ov.n_anomalous ? "text-red" : undefined}
                        hint="activities tripping M3" />
                <Metric label="Budget" value={money(ov.budget_cap, true)}
                        hint="cap on the action set" />
              </div>
            </div>
          </>
        )}
      </Section>

      {/* ------------------------------------------------------ the rail --- */}
      <Section
        eyebrow="Act III · The map"
        index={3}
        title="Twenty-four activities, in order"
        lede="Every business case walks all of them, exactly once. Bar height is the activity's share of total delay; colour is its health against the world before this one."
        className="mt-14"
      >
        {stages.data && macro.data ? (
          <ProcessRail
            stages={stages.data.stages}
            macroStages={macro.data.macro_stages}
            selected={selected}
            onSelect={(s) => setSelected(s === selected ? null : s)}
          />
        ) : (
          <Skeleton className="h-[130px]" />
        )}
      </Section>

      {/* ------------------------------------------------- ranking + M3 ---- */}
      <Section
        eyebrow="Act IV · The constraint"
        index={4}
        title="What is holding it up"
        lede="M2 scores every activity on three things it can be guilty of — holding the queue, running hot, and taking longer than M1 can explain. M3 watches the same activities hour by hour against the healthy baseline."
        className="mt-14"
      >
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
          <div className="panel p-4">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <p className="eyebrow">M2 · bottleneck ranking</p>
              <p className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-faint">
                top 10 of 24
              </p>
            </div>
            {stages.data ? (
              <RankBars
                rows={[...stages.data.stages].sort((a, b) => a.rank - b.rank).slice(0, 10)}
                selected={selected}
                onSelect={(s) => setSelected(s === selected ? null : s)}
              />
            ) : (
              <Skeleton className="h-[320px]" />
            )}
            <p className="mt-3 border-t border-ink/10 pt-3 text-[11.5px] leading-relaxed text-ink-faint">
              Score = 0.45 × queue-wait share + 0.30 × utilisation + 0.25 × share of
              delay M1 could not explain.
            </p>
          </div>

          <div className="panel flex flex-col p-4">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <p className="eyebrow">M3 · anomaly timeline</p>
              {m3?.timeline_stage && (
                <p className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-mid">
                  {pretty(m3.timeline_stage)}
                </p>
              )}
            </div>
            {m3 ? (
              <>
                <AnomalyStrip
                  timeline={m3.timeline}
                  injectedAt={m3.injected_at}
                  stageLabel={pretty(m3.timeline_stage)}
                />
                <p className="mt-3 border-t border-ink/10 pt-3 text-[11.5px] leading-relaxed text-ink-faint">
                  {m3.narrative}
                </p>
              </>
            ) : (
              <Skeleton className="h-[220px]" />
            )}
          </div>
        </div>
      </Section>

      {/* ---------------------------------------------------- the table ---- */}
      <Section
        eyebrow="Act V · The detail"
        index={5}
        title="The activity table"
        lede="Sortable on every column — by rank to find the constraint, by utilisation to find what is running hot, by wait-over-service to find where the queue is out of proportion to the work."
        className="mt-14"
        action={
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setMacroFilter(null)}
              className={`rounded-full border px-3 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.16em] ${
                !macroFilter ? "border-ink bg-ink text-paper" : "border-ink/18 text-ink-mid hover:text-ink"
              }`}
            >
              All
            </button>
            {(macro.data?.macro_stages ?? []).map((m) => (
              <button
                key={m.macro_stage}
                onClick={() => setMacroFilter(m.macro_stage === macroFilter ? null : m.macro_stage)}
                className={`rounded-full border px-3 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.16em] ${
                  macroFilter === m.macro_stage
                    ? "border-ink bg-ink text-paper"
                    : "border-ink/18 text-ink-mid hover:text-ink"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        }
      >
        {stages.data ? (
          <StageTable
            stages={stages.data.stages}
            selected={selected}
            onSelect={(s) => setSelected(s === selected ? null : s)}
            filter={macroFilter}
          />
        ) : (
          <Skeleton className="h-[500px]" />
        )}
      </Section>

      {/* ------------------------------------------------- model scorecards */}
      <Section
        eyebrow="Act VI · The evidence"
        index={6}
        title="How well any of this works"
        lede="Scored against the ground-truth table, which no model trains on, across three fault scenarios in three different macro-stages."
        className="mt-14"
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(metrics.data?.cards ?? []).map((card) => (
            <div key={card.model} className="panel p-4">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-[13px] font-semibold">{card.model}</span>
                <span
                  className={`font-mono text-[9.5px] uppercase tracking-[0.16em] ${
                    card.pass ? "text-band-green" : "text-band-amber"
                  }`}
                >
                  {card.pass ? "Pass" : "Check"}
                </span>
              </div>
              <p className="mt-2 text-[13.5px] font-medium leading-snug">{card.name}</p>
              <p className="metric mt-3 text-[19px] font-extrabold tracking-[-0.02em]">
                {card.display}
              </p>
              <p className="mt-2 text-[11px] leading-snug text-ink-faint">{card.detail}</p>
            </div>
          ))}
          {!metrics.data && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[168px]" />)}
        </div>
      </Section>

      {/* ------------------------------------------------------- handoff --- */}
      <section className="mt-16 grid gap-3 sm:grid-cols-2">
        <Link
          to="/simulation"
          className="panel group flex flex-col justify-between gap-6 p-6 transition-colors hover:border-ink/30 hover:bg-paper-sink/50"
        >
          <div>
            <Eyebrow>Next</Eyebrow>
            <h3 className="mt-3 text-[22px] font-extrabold uppercase tracking-[-0.03em]">
              Walk the simulation
            </h3>
            <p className="mt-2 max-w-sm text-[13.5px] leading-relaxed text-ink-mid">
              One case through all 24 activities, then the nine panels — M1, M2, M3, the
              agent, M4, M5, M6 and the measured outcome — stepped through one at a time.
            </p>
          </div>
          <span className="font-mono text-label uppercase text-ink group-hover:text-red">
            Open the panel →
          </span>
        </Link>

        <Link
          to="/chat"
          className="group relative flex flex-col justify-between gap-6 overflow-hidden rounded-xl bg-ink p-6 text-paper transition-transform hover:-translate-y-0.5"
        >
          <div className="grain absolute inset-0 opacity-30" aria-hidden />
          <div className="relative">
            <p className="eyebrow text-paper/45">Ask instead</p>
            <h3 className="mt-3 text-[22px] font-extrabold uppercase tracking-[-0.03em]">
              The ProcessX analyst
            </h3>
            <p className="mt-2 max-w-sm text-[13.5px] leading-relaxed text-paper/70">
              An agent with eighteen tools over this database and every model in the
              stack. Ask it where the bottleneck is, what a fix would cost, or anything
              you can express as a query.
            </p>
          </div>
          <span className="relative font-mono text-label uppercase text-paper group-hover:text-red-soft">
            Start a conversation →
          </span>
        </Link>
      </section>
    </Shell>
  );
}

function Shell({ children }) {
  return (
    <main
      id="main"
      className="mx-auto max-w-6xl px-4 pb-24"
      style={{ paddingTop: "var(--nav-space)" }}
    >
      {children}
      <footer className="rule-t mt-20 flex flex-wrap items-center gap-x-6 gap-y-2 pt-5">
        <span className="eyebrow">ProcessX v2</span>
        <span className="font-mono text-[10px] text-ink-faint">
          Master seed 42 · 7-day horizon · 24 activities · 5 macro-stages
        </span>
        <span className="ml-auto font-mono text-[10px] text-ink-faint">
          Every number on this page is reproducible from the same seed.
        </span>
      </footer>
    </main>
  );
}

function Fact({ label, value, sub }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-2 text-[15px] font-semibold leading-tight tracking-[-0.02em]">
        {value}
      </dd>
      {sub && <dd className="font-mono text-[10px] text-ink-faint">{sub}</dd>}
    </div>
  );
}
