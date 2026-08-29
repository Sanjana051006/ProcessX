import { MACRO_COLOR, hours, num, pretty } from "../lib/format.js";
import { HealthDot } from "./ui.jsx";

/**
 * The whole lifecycle on one rail: 5 macro-stages, 24 activities, in order.
 *
 * This component exists to solve one specific failure of the previous
 * dashboard. The rail lived in its own section halfway up the page; the
 * ranking and the activity table lived below it. Selecting an activity in
 * either of those highlighted it on the rail — which was scrolled off-screen,
 * so the highlight was invisible and the selection appeared to do nothing.
 *
 * The fix is positional, not visual: this renders inside a `sticky` band that
 * pins under the navbar, so all 24 activities stay on screen no matter how far
 * the page is scrolled. Clicking a row in the table now visibly moves a marker
 * on a rail the reader can actually see.
 *
 * Everything else follows from having to survive at 92px tall in a pinned bar:
 * the ticks are a fixed-height baseline with a proportional bar growing off it,
 * the macro labels collapse to colour swatches under `md`, and the inspector is
 * a single row of facts rather than a card.
 *
 * It is a rail rather than a node graph because the process genuinely is
 * linear — every case visits every activity exactly once, in this order.
 */
export default function ActivityRail({
  stages,
  macroStages,
  selected,
  onSelect,
  activeStage,
  compact = false,
}) {
  const maxContribution = Math.max(...stages.map((s) => s.contribution_pct), 1);
  const chosen = stages.find((s) => s.stage === selected);
  const barMax = compact ? 26 : 38;

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-stretch gap-2 sm:gap-3">
        {macroStages.map((macro) => {
          const own = stages.filter((s) => s.macro_stage === macro.macro_stage);
          const color = MACRO_COLOR[macro.macro_stage];
          return (
            <div
              key={macro.macro_stage}
              className="flex min-w-0 flex-col"
              style={{ flex: `${Math.max(own.length, 1)} 1 0%` }}
            >
              <div className="mb-1.5 flex min-w-0 items-center gap-1.5">
                <span
                  className="h-2 w-2 shrink-0 rounded-[3px]"
                  style={{ background: color }}
                />
                <span className="hidden truncate font-mono text-[9px] uppercase tracking-[0.14em] text-ink-3 md:inline">
                  {macro.label}
                </span>
                <span className="ml-auto hidden shrink-0 font-mono text-[9px] tabular-nums text-ink-4 lg:inline">
                  {hours(macro.mean_duration_hours, 1)}
                </span>
              </div>

              {/* Ticks grow upward off a shared baseline, so the tallest bar is
                  the biggest contributor and the eye finds the constraint
                  without reading a single label. */}
              <div className="flex items-end gap-[2px]" style={{ height: barMax + 8 }}>
                {own.map((s) => {
                  const height = 6 + (s.contribution_pct / maxContribution) * barMax;
                  const isSelected = selected === s.stage;
                  const isActive = activeStage === s.stage;
                  const on = isSelected || isActive;
                  return (
                    <button
                      key={s.stage}
                      type="button"
                      onClick={() => onSelect?.(s.stage)}
                      title={`${s.label} — rank ${s.rank}, ${num(s.contribution_pct, 1)}% of delay, utilisation ${num(s.utilisation)}`}
                      aria-pressed={isSelected}
                      className="group relative flex min-w-0 flex-1 items-end justify-center"
                    >
                      <span
                        className="block w-full rounded-t-[3px] transition-all duration-300"
                        style={{
                          height: `${height}px`,
                          background:
                            s.health === "red"
                              ? "rgb(var(--danger))"
                              : s.health === "amber"
                                ? "rgb(var(--warn))"
                                : color,
                          opacity: on ? 1 : 0.34,
                          transform: on ? "scaleY(1.06)" : "none",
                          transformOrigin: "bottom",
                        }}
                      />
                      {/* The selected marker is a hard ring rather than a
                          colour change: colour is already carrying health. */}
                      {on && (
                        <span
                          className="pointer-events-none absolute inset-x-0 bottom-0 rounded-t-[3px] ring-2 ring-ink ring-offset-1 ring-offset-surface"
                          style={{ height: `${height}px` }}
                          aria-hidden
                        />
                      )}
                      {s.anomalous && (
                        <span
                          className="pointer-events-none absolute left-1/2 top-0 h-1 w-1 -translate-x-1/2 -translate-y-1.5 rounded-full bg-danger"
                          title="M3 flags this activity"
                        />
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="mt-1 h-px w-full bg-line/12" />
            </div>
          );
        })}
      </div>

      {/* The inspector. Always rendered so the rail never changes height when a
          selection appears — a pinned bar that resizes under the reader is
          worse than one that reserves a line it does not always use. */}
      <div className="mt-2 flex h-[26px] min-w-0 items-center">
        {chosen ? (
          <SelectedFacts stage={chosen} onClear={() => onSelect?.(chosen.stage)} />
        ) : (
          <p className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-4">
            24 activities in lifecycle order · bar height is share of total delay ·
            select one anywhere on the page
          </p>
        )}
      </div>
    </div>
  );
}

function SelectedFacts({ stage, onClear }) {
  return (
    <div className="animate-fade flex min-w-0 flex-1 items-center gap-x-4 gap-y-1 overflow-x-auto no-bar">
      <span className="flex shrink-0 items-center gap-2">
        <span className="chip-solid">#{stage.rank}</span>
        <span className="whitespace-nowrap text-[13px] font-semibold text-ink">
          {pretty(stage.stage)}
        </span>
      </span>
      <HealthDot band={stage.health} />
      <Fact label="Wait" value={hours(stage.mean_wait_hours)} />
      <Fact label="Service" value={hours(stage.mean_service_hours)} />
      <Fact
        label="W/S"
        value={num(stage.wait_to_service_ratio)}
        tone={stage.wait_to_service_ratio > 1 ? "text-danger" : undefined}
      />
      <Fact label="Util" value={num(stage.utilisation)} />
      <Fact label="Roster" value={`${stage.servers}/${stage.weekend_servers}`} />
      <Fact label="Delay" value={`${num(stage.contribution_pct, 1)}%`} />
      <button
        onClick={onClear}
        className="ml-auto shrink-0 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4 hover:text-ink"
      >
        Clear
      </button>
    </div>
  );
}

function Fact({ label, value, tone }) {
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">
        {label}
      </span>
      <span className={`font-mono text-[11.5px] font-medium tabular-nums ${tone ?? "text-ink"}`}>
        {value}
      </span>
    </span>
  );
}
