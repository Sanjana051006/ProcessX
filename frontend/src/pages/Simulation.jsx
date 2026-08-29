import { useCallback, useEffect, useRef, useState } from "react";
import { getCases, getPipeline } from "../api.js";
import EventFeed from "../components/EventFeed.jsx";
import PipelinePanel from "../components/PipelinePanel.jsx";
import StepRail from "../components/StepRail.jsx";
import { Button, ErrorNote, LiveDot, Segmented, Skeleton } from "../components/ui.jsx";
import { hours, int, num } from "../lib/format.js";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";

const AUTOPLAY_MS = 5200;

/**
 * The simulation panel.
 *
 * One case is followed from its raw journey through every component that
 * touches it — M1, M2, M3, the agent, M4, M5, M6 — and out the other side into
 * the measured outcome of acting on what they concluded. Forward and Backward
 * walk that sequence; inside the first panel a nested control walks the case's
 * own 24 activities.
 *
 * **This page never scrolls, in either axis.** It is a `100dvh` grid with five
 * fixed bands — the navbar's reserved space, a control header, the step rail,
 * the panel, and the transport bar — where only the panel band is elastic
 * (`minmax(0,1fr)`) and the whole grid is `overflow-hidden`. Everything inside
 * the panel is built to fit rather than to scroll (see PipelinePanel), so a step
 * is always visible in full without the reader hunting for it. That is the
 * entire layout brief for this page and every other decision here is downstream
 * of it: the header is one line, the metrics are four tiles in a column, and the
 * event feed shows what fits.
 *
 * `100dvh` rather than `100vh`: on mobile the URL bar collapses and `vh` leaves
 * the transport bar under the fold.
 *
 * The whole payload arrives in one request and every panel renders from it, so
 * stepping is instant and never re-fetches. The chain is deterministic on seed
 * 42, which is what makes that safe: stepping back and forward twice cannot
 * produce two different answers.
 */
export default function Simulation({ bus }) {
  const { runId, runs, setRunId } = useRun();
  const [caseId, setCaseId] = useState(null);
  const [index, setIndex] = useState(0);
  const [activity, setActivity] = useState(null);
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);

  const cases = useAsync(() => getCases(runId, 24, "cycle_desc"), [runId], { skip: !runId });
  const pipeline = useAsync(() => getPipeline(runId, caseId), [runId, caseId], { skip: !runId });

  const steps = pipeline.data?.steps ?? [];
  const step = steps[index];
  const last = steps.length - 1;

  const go = useCallback(
    (next) => {
      setIndex((i) => Math.max(0, Math.min(last < 0 ? 0 : last, next(i))));
      setActivity(null);
    },
    [last],
  );

  const forward = useCallback(() => go((i) => i + 1), [go]);
  const backward = useCallback(() => go((i) => i - 1), [go]);

  // Arrow keys drive the stepper, but not while the user is typing in a field —
  // the case picker is a real control and left/right inside it must move the
  // selection rather than the panel.
  useEffect(() => {
    function onKey(e) {
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable)
        return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        forward();
        setPlaying(false);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        backward();
        setPlaying(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [forward, backward]);

  // Autoplay stops itself at the end rather than looping: the last panel is the
  // conclusion, and returning to the start would undercut it.
  useEffect(() => {
    clearTimeout(timer.current);
    if (!playing) return undefined;
    if (index >= last) {
      setPlaying(false);
      return undefined;
    }
    timer.current = setTimeout(forward, AUTOPLAY_MS);
    return () => clearTimeout(timer.current);
  }, [playing, index, last, forward]);

  const journey = steps[0]?.journey;

  return (
    <div
      className="grid overflow-hidden"
      style={{ height: "100dvh", gridTemplateRows: "var(--nav-space) auto auto minmax(0,1fr) auto" }}
    >
      {/* The band the floating navbar occupies. Nothing renders here — it is
          reserved space, which is what keeps the panel out from under it. */}
      <div aria-hidden />

      {/* ------------------------------------------------------ header row -- */}
      <header className="mx-auto flex w-full max-w-[1440px] min-w-0 flex-wrap items-center gap-x-4 gap-y-2 px-3 pb-2 sm:px-5">
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="title-md whitespace-nowrap text-[17px]">One case, every component</h1>
          {journey && (
            <p className="truncate font-mono text-[10px] tabular-nums text-ink-4">
              #{journey.case_id} · {hours(journey.cycle_hours)} · p
              {Math.round(journey.cycle_percentile * 100)} of {int(cases.data?.n_cases ?? 0)}
            </p>
          )}
        </div>

        <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
          <Segmented
            size="xs"
            items={runs.map((r) => ({ value: r.run_id, label: r.run_id, title: r.label }))}
            value={runId}
            onChange={(id) => {
              setRunId(id);
              setCaseId(null);
              setIndex(0);
            }}
          />
          <label className="flex min-w-0 items-center gap-2">
            <span className="eyebrow shrink-0">Case</span>
            <select
              value={caseId ?? ""}
              onChange={(e) => {
                setCaseId(e.target.value ? Number(e.target.value) : null);
                setIndex(0);
              }}
              className="max-w-[240px] truncate rounded-full border border-line/10 bg-surface px-3 py-1.5
                         font-mono text-[10.5px] tabular-nums text-ink-2 shadow-xs outline-none
                         focus:border-accent"
            >
              <option value="">
                Representative{journey ? ` — #${journey.case_id}` : ""}
              </option>
              {(cases.data?.cases ?? []).map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  #{c.case_id} — {num(c.cycle_hours)} h{c.sla_breach ? " · breach" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {/* -------------------------------------------------------- step rail -- */}
      <div className="mx-auto w-full max-w-[1440px] min-w-0 px-3 pb-2 sm:px-5">
        <div className="card px-3 py-2">
          {steps.length ? (
            <StepRail
              steps={steps}
              index={index}
              onSelect={(i) => {
                setIndex(i);
                setActivity(null);
                setPlaying(false);
              }}
            />
          ) : (
            <Skeleton className="h-[46px]" />
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------ panel -- */}
      <main
        id="main"
        className="mx-auto min-h-0 w-full max-w-[1440px] min-w-0 overflow-hidden px-3 pb-2 sm:px-5"
      >
        {pipeline.error ? (
          <ErrorNote error={pipeline.error} retry={pipeline.reload} />
        ) : !step ? (
          <div className="card grid h-full min-h-0 place-items-center p-6">
            <div className="max-w-md text-center">
              <LiveDot on className="mb-3 inline-flex" />
              <p className="title-md">Running the pipeline</p>
              <p className="lede mt-2 text-[13px]">
                The agent investigates and M5 re-simulates the world nine times. Every
                step it takes is publishing to the event bus as it happens.
              </p>
              <div className="mt-4 space-y-2">
                <Skeleton className="h-3" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="h-3 w-3/5" />
              </div>
            </div>
          </div>
        ) : (
          <article
            key={step.key}
            className="grid h-full min-h-0 animate-fade gap-3 xl:grid-cols-[minmax(0,1fr)_296px]"
          >
            {/* The panel itself: a heading band, then the visualisation. */}
            <section className="card flex min-h-0 min-w-0 flex-col p-4">
              <header className="mb-3 flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="chip-accent">{step.model}</span>
                <h2 className="title-md truncate text-[17px]">{step.title}</h2>
                <span className="truncate font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-4">
                  {step.subtitle}
                </span>
                <span className="ml-auto shrink-0 font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-4">
                  Panel {index + 1} / {steps.length}
                </span>
              </header>

              <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
                <PipelinePanel
                  step={step}
                  journey={journey}
                  activeIndex={activity}
                  setActiveIndex={setActivity}
                />
              </div>
            </section>

            {/* The side column: the headline claim, its four numbers, and the
                bus. Hidden below `xl` — on a narrow window the panel is the
                thing worth the space, and the metrics are all restated inside
                it anyway. */}
            <aside className="hidden min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3 xl:grid">
              <section className="card-accent p-4">
                <p className="eyebrow">The claim</p>
                <p className="metric clamp-2 mt-2 text-[17px] font-bold leading-tight tracking-[-0.02em] text-ink">
                  {step.headline}
                </p>
                <p className="clamp-6 mt-2.5 text-[11.5px] leading-relaxed text-ink-2">
                  {step.narrative}
                </p>
                {step.metrics?.length > 0 && (
                  <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-line/8 pt-3">
                    {step.metrics.slice(0, 4).map((m) => (
                      <div key={m.label} className="min-w-0">
                        <dt className="eyebrow truncate">{m.label}</dt>
                        <dd className="metric mt-1 truncate text-[14px] font-bold leading-none tracking-[-0.02em] text-ink">
                          {m.value}
                        </dd>
                        {m.hint && (
                          <dd className="clamp-2 mt-0.5 text-[9.5px] leading-snug text-ink-4">
                            {m.hint}
                          </dd>
                        )}
                      </div>
                    ))}
                  </dl>
                )}
              </section>

              <section className="card flex min-h-0 flex-col p-4">
                <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
                  <p className="eyebrow">Live event bus</p>
                  <span className="inline-flex items-center gap-1.5">
                    <LiveDot on={bus?.connected} />
                    <span className="font-mono text-[9px] tabular-nums text-ink-4">
                      {(bus?.events ?? []).length}
                    </span>
                  </span>
                </div>
                {/* `strip`: shows what fits and nothing more. Nothing on this
                    page is allowed a scrollbar, this feed included. */}
                <EventFeed
                  events={bus?.events ?? []}
                  connected={bus?.connected}
                  variant="strip"
                  limit={10}
                  emptyLabel="No events yet"
                />
              </section>
            </aside>
          </article>
        )}
      </main>

      {/* -------------------------------------------------------- transport -- */}
      <div className="mx-auto w-full max-w-[1440px] min-w-0 px-3 pb-3 sm:px-5">
        <div className="glass card mx-auto flex max-w-2xl items-center gap-2 rounded-full p-1.5 shadow-card">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              backward();
              setPlaying(false);
            }}
            disabled={index === 0}
            className="min-w-[96px]"
          >
            ◀ Back
          </Button>

          <div className="flex flex-1 items-center gap-2 px-1">
            <span className="h-1 flex-1 overflow-hidden rounded-full bg-line/10">
              <span
                className="block h-full rounded-full bg-accent transition-[width] duration-500"
                style={{ width: `${last > 0 ? (index / last) * 100 : 0}%` }}
              />
            </span>
            <span className="shrink-0 font-mono text-[9.5px] uppercase tracking-[0.14em] tabular-nums text-ink-4">
              {String(index + 1).padStart(2, "0")}/{String(steps.length || 9).padStart(2, "0")}
            </span>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPlaying((p) => !p)}
            disabled={!steps.length || index >= last}
            title="Step through automatically"
          >
            {playing ? "❚❚" : "▶"}
          </Button>

          <Button
            variant="accent"
            size="sm"
            onClick={() => {
              forward();
              setPlaying(false);
            }}
            disabled={!steps.length || index >= last}
            className="min-w-[96px]"
          >
            Forward ▶
          </Button>
        </div>
      </div>
    </div>
  );
}
