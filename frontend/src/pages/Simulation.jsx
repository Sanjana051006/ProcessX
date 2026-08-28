import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getCases, getPipeline } from "../api.js";
import PipelinePanel from "../components/PipelinePanel.jsx";
import StepRail from "../components/StepRail.jsx";
import { Button, ErrorNote, Eyebrow, Skeleton } from "../components/ui.jsx";
import { hours, int, num, pretty } from "../lib/format.js";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";

const AUTOPLAY_MS = 5200;

/**
 * The simulation panel.
 *
 * One case is followed from its raw journey through every component that
 * touches it — M1, M2, M3, the agent, M4, M5, M6 — and out the other side into
 * the measured outcome of acting on what they concluded. Forward and Backward
 * walk that sequence; inside the first panel a second, nested control walks the
 * case's own 24 activities.
 *
 * The whole payload arrives in one request and every panel is rendered from it,
 * so stepping is instant and never re-fetches. The chain is deterministic on
 * seed 42, which is what makes that safe: stepping back and forward twice
 * cannot produce two different answers.
 */
export default function Simulation() {
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
      setIndex((i) => {
        const clamped = Math.max(0, Math.min(last < 0 ? 0 : last, next(i)));
        return clamped;
      });
      setActivity(null);
    },
    [last],
  );

  const forward = useCallback(() => go((i) => i + 1), [go]);
  const backward = useCallback(() => go((i) => i - 1), [go]);

  // Arrow keys drive the stepper, but not while the user is typing in a field —
  // the case picker is a real input and left/right inside it must move the caret.
  useEffect(() => {
    function onKey(e) {
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable) return;
      if (e.key === "ArrowRight") { e.preventDefault(); forward(); setPlaying(false); }
      if (e.key === "ArrowLeft") { e.preventDefault(); backward(); setPlaying(false); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [forward, backward]);

  // Autoplay stops itself at the end rather than looping: the last panel is the
  // conclusion, and returning to the start would undercut it.
  useEffect(() => {
    clearTimeout(timer.current);
    if (!playing) return;
    if (index >= last) { setPlaying(false); return; }
    timer.current = setTimeout(forward, AUTOPLAY_MS);
    return () => clearTimeout(timer.current);
  }, [playing, index, last, forward]);

  if (pipeline.error) {
    return (
      <Shell>
        <ErrorNote error={pipeline.error} retry={pipeline.reload} />
      </Shell>
    );
  }

  const journey = steps[0]?.journey;

  return (
    <Shell>
      {/* ---------------------------------------------------------- head -- */}
      <header className="pb-8 pt-2">
        <div className="flex flex-wrap items-center gap-3">
          <Eyebrow>The simulation panel</Eyebrow>
          <span className="h-px flex-1 bg-ink/14" />
          <span className="tag">{steps.length || 9} panels</span>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr] lg:items-end">
          <div>
            <h1 className="text-headline font-black uppercase">
              One case,
              <br />
              every component.
            </h1>
            <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-ink-mid">
              Follow a single business case from the raw simulation through M1, M2 and
              M3, into the agent's investigation, out through M4's verdict, M5's
              counterfactuals and M6's budget — and finish on what actually happened when
              the chosen actions were applied.
            </p>
          </div>

          <div className="panel p-4">
            <div className="flex items-baseline justify-between gap-2">
              <p className="eyebrow">World</p>
              <div className="flex flex-wrap gap-1">
                {runs.map((r) => (
                  <button
                    key={r.run_id}
                    onClick={() => { setRunId(r.run_id); setCaseId(null); setIndex(0); }}
                    className={`rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.14em] ${
                      r.run_id === runId
                        ? "border-ink bg-ink text-paper"
                        : "border-ink/18 text-ink-mid hover:text-ink"
                    }`}
                  >
                    {r.run_id}
                  </button>
                ))}
              </div>
            </div>

            <label className="mt-4 block">
              <span className="eyebrow">Case</span>
              <select
                value={caseId ?? ""}
                onChange={(e) => {
                  setCaseId(e.target.value ? Number(e.target.value) : null);
                  setIndex(0);
                }}
                className="mt-2 w-full rounded-lg border border-ink/18 bg-paper px-3 py-2
                           font-mono text-[12px] tabular-nums outline-none
                           focus:border-ink"
              >
                <option value="">
                  Representative case{journey ? ` — #${journey.case_id}` : ""}
                </option>
                {(cases.data?.cases ?? []).map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    #{c.case_id} — {num(c.cycle_hours)} h
                    {c.sla_breach ? " · SLA breach" : ""} · {c.customer_segment}
                  </option>
                ))}
              </select>
            </label>
            {journey && (
              <p className="mt-2 font-mono text-[10px] tabular-nums text-ink-faint">
                {hours(journey.cycle_hours)} cycle · p
                {Math.round(journey.cycle_percentile * 100)} of{" "}
                {int(cases.data?.n_cases ?? 0)} cases
              </p>
            )}
          </div>
        </div>
      </header>

      {/* ---------------------------------------------------------- rail -- */}
      <div className="rule-t pt-6">
        {steps.length ? (
          <StepRail steps={steps} index={index} onSelect={(i) => { setIndex(i); setActivity(null); setPlaying(false); }} />
        ) : (
          <Skeleton className="h-[70px]" />
        )}
      </div>

      {/* --------------------------------------------------------- panel -- */}
      {!step ? (
        <div className="mt-6 space-y-3">
          <Skeleton className="h-[140px]" />
          <Skeleton className="h-[360px]" />
          <p className="text-center font-mono text-[10.5px] uppercase tracking-[0.16em] text-ink-faint">
            Running the pipeline — the agent investigates and M5 re-simulates the world
            nine times
          </p>
        </div>
      ) : (
        <article key={step.key} className="mt-6 animate-rise">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)] lg:items-start">
            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="rounded-full bg-ink px-2.5 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.16em] text-paper">
                  {step.model}
                </span>
                <span className="eyebrow">
                  Panel {index + 1} of {steps.length}
                </span>
              </div>
              <h2 className="mt-3 text-[clamp(1.6rem,3vw,2.3rem)] font-extrabold uppercase leading-[0.95] tracking-[-0.03em]">
                {step.title}
              </h2>
              <p className="mt-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-light">
                {step.subtitle}
              </p>
              <p className="metric mt-4 text-[19px] font-bold tracking-[-0.02em] text-red">
                {step.headline}
              </p>
              <p className="mt-3 max-w-2xl text-[14px] leading-[1.7] text-ink-mid">
                {step.narrative}
              </p>
            </div>

            {step.metrics?.length > 0 && (
              <dl className="grid grid-cols-2 gap-3">
                {step.metrics.map((m) => (
                  <div key={m.label} className="panel p-3">
                    <dt className="eyebrow truncate">{m.label}</dt>
                    <dd className="metric mt-1.5 text-[16px] font-bold leading-none tracking-[-0.02em]">
                      {m.value}
                    </dd>
                    {m.hint && (
                      <dd className="mt-1 text-[10px] leading-snug text-ink-faint">
                        {m.hint}
                      </dd>
                    )}
                  </div>
                ))}
              </dl>
            )}
          </div>

          <div className="mt-7">
            <PipelinePanel
              step={step}
              journey={journey}
              activeIndex={activity}
              setActiveIndex={setActivity}
            />
          </div>
        </article>
      )}

      {/* ------------------------------------------------------ controls -- */}
      <div className="sticky bottom-4 z-30 mt-10">
        <div className="mx-auto flex max-w-2xl items-center gap-2 rounded-full border border-ink/14 bg-paper/92 p-2 shadow-capsule backdrop-blur-xl">
          <Button
            variant="outline"
            onClick={() => { backward(); setPlaying(false); }}
            disabled={index === 0}
            className="min-w-[112px]"
          >
            ◀ Back
          </Button>

          <div className="flex flex-1 items-center gap-2 px-1">
            <span className="h-1 flex-1 overflow-hidden rounded-full bg-ink/10">
              <span
                className="block h-full rounded-full bg-ink transition-[width] duration-500"
                style={{ width: `${last > 0 ? (index / last) * 100 : 0}%` }}
              />
            </span>
            <span className="shrink-0 font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-faint tabular-nums">
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
            onClick={() => { forward(); setPlaying(false); }}
            disabled={!steps.length || index >= last}
            className="min-w-[112px]"
          >
            Forward ▶
          </Button>
        </div>
        <p className="mt-2 text-center font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
          ← → arrow keys also step
        </p>
      </div>

      {/* -------------------------------------------------------- outro --- */}
      {index === last && step && (
        <section className="mt-12 animate-rise">
          <div className="rule-t grid gap-4 pt-8 sm:grid-cols-2">
            <div>
              <Eyebrow>The conclusion</Eyebrow>
              <p className="quote mt-4 text-[16px] leading-relaxed">
                “{pretty(pipeline.data.conclusion.concluded_stage)} —{" "}
                {pretty(pipeline.data.conclusion.concluded_cause)} at p=
                {num(pipeline.data.conclusion.confidence)}. The agent spent{" "}
                {pipeline.data.conclusion.probes_used} probes and stopped because it had
                the answer, not because it ran out.”
              </p>
            </div>
            <Link
              to="/chat"
              className="group flex flex-col justify-between gap-4 rounded-xl bg-ink p-6 text-paper transition-transform hover:-translate-y-0.5"
            >
              <div>
                <p className="eyebrow text-paper/45">Go deeper</p>
                <h3 className="mt-2 text-[20px] font-extrabold uppercase tracking-[-0.03em]">
                  Ask the analyst
                </h3>
                <p className="mt-2 text-[13px] leading-relaxed text-paper/70">
                  Every number in these nine panels is a tool call away. Ask why the agent
                  chose that probe, what a different action would cost, or anything you can
                  put into a query.
                </p>
              </div>
              <span className="font-mono text-label uppercase group-hover:text-red-soft">
                Open the analyst →
              </span>
            </Link>
          </div>
        </section>
      )}
    </Shell>
  );
}

function Shell({ children }) {
  return (
    <main
      id="main"
      className="mx-auto max-w-6xl px-4 pb-16"
      style={{ paddingTop: "var(--nav-space)" }}
    >
      {children}
    </main>
  );
}
