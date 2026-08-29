import { useState } from "react";
import { Link } from "react-router-dom";
import {
  getMacro,
  getModelMetrics,
  getOverview,
  getPipeline,
  getScenarios,
  getStages,
  injectScenario,
  resetRuns,
} from "../api.js";
import ActivityRail from "../components/ActivityRail.jsx";
import EventFeed from "../components/EventFeed.jsx";
import StageTable from "../components/StageTable.jsx";
import AnomalyStrip from "../components/charts/AnomalyStrip.jsx";
import RankBars from "../components/charts/RankBars.jsx";
import ShareBar from "../components/charts/ShareBar.jsx";
import {
  Bento,
  Button,
  ErrorNote,
  Eyebrow,
  LiveDot,
  Metric,
  Segmented,
  Skeleton,
  StatTile,
  Tile,
} from "../components/ui.jsx";
import { hours, int, money, num, pct, pretty } from "../lib/format.js";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";

/**
 * The dashboard.
 *
 * Laid out as a bento grid over a **pinned process rail**. That structure is
 * the whole redesign: previously the rail was one section among several, so
 * selecting an activity in the ranking or the table highlighted it on a rail
 * that had already scrolled out of view and the selection read as a no-op. Here
 * the rail is `sticky` directly under the navbar, so all 24 activities are on
 * screen for every interaction on the page and a selection made anywhere is
 * immediately visible in the context of the whole lifecycle.
 *
 * Everything else is a consequence. Tiles are sized by importance rather than
 * uniformly; the activity table scrolls inside its own tile instead of making
 * the page four screens tall; and the live event feed sits beside the table so
 * the bus is visible without a dedicated page.
 */
export default function Dashboard({ bus }) {
  const { runId, runs, setRunId, refresh } = useRun();
  const [selected, setSelected] = useState(null);
  const [macroFilter, setMacroFilter] = useState("all");
  const [busy, setBusy] = useState(false);

  const overview = useAsync(() => getOverview(runId), [runId], { skip: !runId });
  const stages = useAsync(() => getStages(runId), [runId], { skip: !runId });
  const macro = useAsync(() => getMacro(runId), [runId], { skip: !runId });
  const metrics = useAsync(() => getModelMetrics(), []);
  const scenarios = useAsync(() => getScenarios(), []);
  // The anomaly strip needs M3's timeline, which comes with the pipeline. It is
  // the one expensive fetch on this page, so it is fired alongside the rest
  // rather than blocking them — the tile fills in when it lands.
  const pipeline = useAsync(() => getPipeline(runId), [runId], { skip: !runId });

  const toggle = (s) => setSelected((cur) => (cur === s ? null : s));

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
  const ranked = stages.data
    ? [...stages.data.stages].sort((a, b) => a.rank - b.rank)
    : [];

  return (
    <Shell>
      {/* ------------------------------------------------------------ hero -- */}
      <header className="pb-5">
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
          <div className="min-w-0">
            <Eyebrow>Process intelligence · seed 42 · reproducible</Eyebrow>
            <h1 className="title-xl mt-2.5">
              {ov?.label ?? "Loading the world"}
            </h1>
            <p className="lede mt-2 max-w-xl">
              A discrete-event simulator generates the world. Six components predict,
              rank, detect, diagnose, simulate and price it. An agent drives them, and
              every step lands on a live event bus.
            </p>
          </div>

          <dl className="grid shrink-0 grid-cols-2 gap-x-7 gap-y-3 sm:grid-cols-4">
            <Fact label="World" value={ov?.run_id ?? "—"} sub={ov?.scenario} />
            <Fact
              label="Scale"
              value={ov ? int(k.n_cases) : "—"}
              sub={ov ? `${int(ov.n_events)} events` : ""}
            />
            <Fact
              label="Shape"
              value={ov ? `${ov.n_activities} activities` : "—"}
              sub={ov ? `${ov.n_macro_stages} macro-stages` : ""}
            />
            <Fact
              label="Horizon"
              value={ov ? `${ov.horizon_days} days` : "—"}
              sub={`SLA ${ov?.sla_threshold_hours ?? 30} h`}
            />
          </dl>
        </div>

        {/* World switcher and the fault injector. */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="eyebrow mr-1">World</span>
          <Segmented
            items={runs.map((r) => ({ value: r.run_id, label: r.run_id, title: r.label }))}
            value={runId}
            onChange={setRunId}
          />
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            <span className="eyebrow">Inject a fault</span>
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
      </header>

      {/* ------------------------------------------------------ the rail --- */}
      {/* Pinned. Everything below scrolls past it; it never leaves the screen,
          which is what makes a selection made anywhere on this page legible. */}
      <div
        className="sticky z-30 -mx-1 px-1 pb-3 pt-1"
        style={{ top: "calc(var(--nav-space) - 6px)" }}
      >
        <div className="glass card overflow-hidden p-3 shadow-card sm:p-4">
          {stages.data && macro.data ? (
            <ActivityRail
              stages={stages.data.stages}
              macroStages={macro.data.macro_stages}
              selected={selected}
              onSelect={toggle}
            />
          ) : (
            <Skeleton className="h-[104px]" />
          )}
        </div>
      </div>

      {/* ----------------------------------------------------------- bento -- */}
      <Bento>
        {/* Row 1 — the four numbers the week is judged on. */}
        {!ov ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="col-span-1 sm:col-span-3 lg:col-span-3">
              <Skeleton className="h-[132px]" />
            </div>
          ))
        ) : (
          <>
            <StatTile
              label="Mean cycle time"
              value={num(k.mean_cycle_hours)}
              unit="hours"
              delta={pk ? k.mean_cycle_hours - pk.mean_cycle_hours : null}
              deltaLabel={
                pk
                  ? `${num(Math.abs(k.mean_cycle_hours - pk.mean_cycle_hours))} h vs ${ov.parent_run_id}`
                  : "no parent world"
              }
              invert
            />
            <StatTile
              label="Cost per case"
              value={money(k.cost_per_case)}
              delta={pk ? k.cost_per_case - pk.cost_per_case : null}
              deltaLabel={pk ? money(Math.abs(k.cost_per_case - pk.cost_per_case)) : "—"}
              invert
              hint="holding + SLA"
            />
            <StatTile
              label="SLA breach rate"
              value={pct(k.sla_breach_rate, 2)}
              delta={pk ? k.sla_breach_rate - pk.sla_breach_rate : null}
              deltaLabel={pk ? pct(Math.abs(k.sla_breach_rate - pk.sla_breach_rate), 2) : "—"}
              invert
              hint={`over ${ov.sla_threshold_hours} h`}
            />
            <StatTile
              label="Worst activity"
              value={pretty(ov.worst_activity.stage)}
              deltaLabel={`${num(ov.worst_activity.contribution_pct, 1)}% of delay`}
              hint={`util ${num(ov.worst_activity.utilisation)}`}
              accent
            />
          </>
        )}

        {/* Row 2 — where the time goes, and the secondary vitals. */}
        <Tile
          span={8}
          spanSm={6}
          title="Where a case spends its lifecycle"
          meta="share of mean cycle time, by macro-stage"
        >
          {macro.data ? (
            <ShareBar rows={macro.data.macro_stages} />
          ) : (
            <Skeleton className="h-[110px]" />
          )}
        </Tile>

        <Tile span={4} spanSm={6} title="Vitals">
          {ov ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-4">
              <Metric label="p90 cycle" value={hours(k.p90_cycle_hours)} hint="the slow tail" />
              <Metric label="Throughput" value={num(k.throughput_per_day, 0)} hint="cases / day" />
              <Metric
                label="Flagged"
                value={String(ov.n_anomalous)}
                tone={ov.n_anomalous ? "text-danger" : undefined}
                hint="activities tripping M3"
              />
              <Metric label="Budget" value={money(ov.budget_cap, true)} hint="cap on the action set" />
            </div>
          ) : (
            <Skeleton className="h-[110px]" />
          )}
        </Tile>

        {/* Row 3 — the constraint. M2 on the left, M3's timeline on the right. */}
        <Tile
          span={5}
          spanSm={6}
          title="M2 · bottleneck ranking"
          meta="0.45 queue-wait + 0.30 utilisation + 0.25 unexplained residual"
          action={<span className="chip">Top 10 of 24</span>}
        >
          {stages.data ? (
            <RankBars rows={ranked.slice(0, 10)} selected={selected} onSelect={toggle} />
          ) : (
            <Skeleton className="h-[300px]" />
          )}
        </Tile>

        <Tile
          span={7}
          spanSm={6}
          title="M3 · anomaly timeline"
          meta={m3?.timeline_stage ? pretty(m3.timeline_stage) : "hourly windows vs the healthy baseline"}
        >
          {m3 ? (
            <div className="flex h-full flex-col">
              <AnomalyStrip
                timeline={m3.timeline}
                injectedAt={m3.injected_at}
                stageLabel={pretty(m3.timeline_stage)}
              />
              <p className="clamp-3 mt-3 border-t border-line/8 pt-3 text-[11.5px] leading-relaxed text-ink-3">
                {m3.narrative}
              </p>
            </div>
          ) : (
            <Skeleton className="h-[220px]" />
          )}
        </Tile>

        {/* Row 4 — the detail table, and the bus beside it. */}
        <Tile
          span={8}
          spanSm={6}
          title="The activity table"
          meta="sortable on every column · click a row to mark it on the rail above"
          action={
            <Segmented
              size="xs"
              value={macroFilter}
              onChange={setMacroFilter}
              items={[
                { value: "all", label: "All" },
                ...(macro.data?.macro_stages ?? []).map((m) => ({
                  value: m.macro_stage,
                  label: m.label.split(" ")[0],
                  title: m.label,
                })),
              ]}
            />
          }
        >
          {stages.data ? (
            <StageTable
              stages={stages.data.stages}
              selected={selected}
              onSelect={toggle}
              filter={macroFilter === "all" ? null : macroFilter}
              maxHeight={380}
            />
          ) : (
            <Skeleton className="h-[380px]" />
          )}
        </Tile>

        <Tile
          span={4}
          spanSm={6}
          title="Live event bus"
          meta={`pub/sub · ${bus?.meta?.backend ?? "memory"} backend`}
          action={
            <span className="inline-flex items-center gap-1.5">
              <LiveDot on={bus?.connected} />
              <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-3">
                {bus?.connected ? "Streaming" : "Offline"}
              </span>
            </span>
          }
          bodyClass="flex flex-col"
        >
          {/* Capped to the activity table's height so the two tiles in this
              row stay the same size and neither can stretch the page. */}
          <EventFeed
            events={bus?.events ?? []}
            connected={bus?.connected}
            maxHeight={380}
            emptyLabel="Inject a fault or open the simulation to publish"
          />
          <p className="mt-2 shrink-0 border-t border-line/8 pt-2 font-mono text-[9px] uppercase leading-relaxed tracking-[0.14em] text-ink-4">
            {(bus?.events ?? []).length} events · publishers: sim, M1–M6, agent, apply,
            analyst
          </p>
        </Tile>

        {/* Row 5 — how well any of it works. */}
        {(metrics.data?.cards ?? []).map((card) => (
          <Tile key={card.model} span={3} spanSm={3}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[12.5px] font-semibold text-ink">
                {card.model}
              </span>
              <span
                className={`font-mono text-[9px] uppercase tracking-[0.14em] ${
                  card.pass ? "text-ok" : "text-warn"
                }`}
              >
                {card.pass ? "Pass" : "Check"}
              </span>
            </div>
            <p className="clamp-2 mt-2 text-[13px] font-medium leading-snug text-ink-2">
              {card.name}
            </p>
            <p className="metric mt-3 text-[19px] font-bold tracking-[-0.02em] text-ink">
              {card.display}
            </p>
            <p className="clamp-3 mt-2 text-[10.5px] leading-snug text-ink-4">{card.detail}</p>
          </Tile>
        ))}
        {!metrics.data &&
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="col-span-1 sm:col-span-3 lg:col-span-3">
              <Skeleton className="h-[168px]" />
            </div>
          ))}

        {/* Row 6 — where to go next. */}
        <Link
          to="/simulation"
          className="card-lift group col-span-1 flex flex-col justify-between gap-6 p-5 sm:col-span-3 lg:col-span-6"
        >
          <div>
            <Eyebrow>Next</Eyebrow>
            <h3 className="title-md mt-2.5 text-[19px]">Walk the simulation</h3>
            <p className="lede mt-2 max-w-sm text-[13.5px]">
              One case through all 24 activities, then nine panels — M1, M2, M3, the
              agent, M4, M5, M6 and the measured outcome — stepped through one at a time,
              with the event stream running beside them.
            </p>
          </div>
          <span className="font-mono text-label uppercase text-accent">
            Open the panel →
          </span>
        </Link>

        <Link
          to="/chat"
          className="card-ink group relative col-span-1 flex flex-col justify-between gap-6 overflow-hidden p-5 transition-transform hover:-translate-y-0.5 sm:col-span-3 lg:col-span-6"
        >
          <div className="relative">
            <p className="eyebrow text-white/45">Ask instead</p>
            <h3 className="mt-2.5 text-[19px] font-semibold tracking-[-0.02em]">
              The ProcessX analyst
            </h3>
            <p className="mt-2 max-w-sm text-[13.5px] leading-[1.6] text-white/65">
              An agent with twenty-one tools over this database, every model in the
              stack, and the event bus itself. Ask where the bottleneck is, what a fix
              costs, or why the agent chose what it chose.
            </p>
          </div>
          <span className="relative font-mono text-label uppercase text-white/80 group-hover:text-white">
            Start a conversation →
          </span>
        </Link>
      </Bento>

      <footer className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line/8 pt-5">
        <span className="eyebrow">ProcessX v2</span>
        <span className="font-mono text-[10px] text-ink-4">
          Master seed 42 · 7-day horizon · 24 activities · 5 macro-stages
        </span>
        <span className="ml-auto font-mono text-[10px] text-ink-4">
          Every number on this page is reproducible from the same seed.
        </span>
      </footer>
    </Shell>
  );
}

function Shell({ children }) {
  return (
    <main
      id="main"
      className="mx-auto min-w-0 max-w-[1440px] px-3 pb-16 sm:px-5"
      style={{ paddingTop: "var(--nav-space)" }}
    >
      {children}
    </main>
  );
}

function Fact({ label, value, sub }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1.5 truncate text-[14px] font-semibold leading-tight tracking-[-0.015em] text-ink">
        {value}
      </dd>
      {sub && <dd className="truncate font-mono text-[9.5px] text-ink-4">{sub}</dd>}
    </div>
  );
}
