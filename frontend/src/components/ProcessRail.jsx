import { MACRO_COLOR, hours, num, pretty } from "../lib/format.js";
import { HealthDot } from "./ui.jsx";

/**
 * The whole lifecycle on one rail: 5 macro-stages, 24 activities, in order.
 *
 * This is the process map, and it is a rail rather than a node graph because
 * the process genuinely is linear — every case visits every activity exactly
 * once, in this order. Drawing it as a graph would imply branches that do not
 * exist and would make the one thing worth seeing (where the queue is) harder
 * to find, not easier.
 *
 * Each activity's tick is scaled by its share of total delay and coloured by its
 * health band, so the constraint is visible at a glance without reading a label.
 */
export default function ProcessRail({ stages, macroStages, selected, onSelect, activeStage }) {
  const maxContribution = Math.max(...stages.map((s) => s.contribution_pct), 1);

  return (
    <div className="overflow-x-auto pb-1">
      <div className="flex min-w-[860px] gap-3">
        {macroStages.map((macro) => {
          const own = stages.filter((s) => s.macro_stage === macro.macro_stage);
          const color = MACRO_COLOR[macro.macro_stage];
          return (
            <div
              key={macro.macro_stage}
              className="flex-1 min-w-0"
              style={{ flexGrow: Math.max(own.length, 1) }}
            >
              <div className="mb-2 flex items-baseline gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                  style={{ background: color }}
                />
                <span className="truncate font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-mid">
                  {macro.label}
                </span>
                <span className="ml-auto shrink-0 font-mono text-[9.5px] tabular-nums text-ink-faint">
                  {hours(macro.mean_duration_hours)}
                </span>
              </div>

              <div className="flex gap-[3px]">
                {own.map((s) => {
                  const height = 10 + (s.contribution_pct / maxContribution) * 36;
                  const isSelected = selected === s.stage;
                  const isActive = activeStage === s.stage;
                  return (
                    <button
                      key={s.stage}
                      type="button"
                      onClick={() => onSelect?.(s.stage)}
                      title={`${s.label} — rank ${s.rank}, ${num(s.contribution_pct, 1)}% of delay, utilisation ${num(s.utilisation)}`}
                      className="group relative flex-1 min-w-0"
                    >
                      <span
                        className={`block w-full rounded-sm transition-all duration-200
                                    ${isSelected || isActive ? "ring-2 ring-ink ring-offset-2 ring-offset-paper" : ""}`}
                        style={{
                          height: `${height}px`,
                          background:
                            s.health === "red"
                              ? "rgb(var(--red))"
                              : s.health === "amber"
                                ? "rgb(var(--amber))"
                                : color,
                          opacity: isSelected || isActive ? 1 : 0.55,
                        }}
                      />
                      {s.anomalous && (
                        <span className="absolute -top-1.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-red" />
                      )}
                    </button>
                  );
                })}
              </div>

              {/* The rail itself — one continuous line under every macro-stage,
                  with the arrow only between them. */}
              <div className="relative mt-2 h-px bg-ink/18" />
            </div>
          );
        })}
      </div>

      {selected && (
        <SelectedActivity stage={stages.find((s) => s.stage === selected)} />
      )}
    </div>
  );
}

function SelectedActivity({ stage }) {
  if (!stage) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-ink/12 bg-paper-sink/40 px-4 py-3 min-w-[860px]">
      <span className="flex items-center gap-2">
        <span className="font-mono text-[10px] tabular-nums text-ink-faint">
          #{stage.rank}
        </span>
        <span className="text-[14px] font-semibold">{pretty(stage.stage)}</span>
      </span>
      <HealthDot band={stage.health} />
      <Fact label="Wait" value={hours(stage.mean_wait_hours)} />
      <Fact label="Service" value={hours(stage.mean_service_hours)} />
      <Fact
        label="Wait / service"
        value={num(stage.wait_to_service_ratio)}
        tone={stage.wait_to_service_ratio > 1 ? "text-red" : undefined}
      />
      <Fact label="Utilisation" value={num(stage.utilisation)} />
      <Fact label="Roster" value={`${stage.servers} / ${stage.weekend_servers} wknd`} />
      <Fact label="Share of delay" value={`${num(stage.contribution_pct, 1)}%`} />
    </div>
  );
}

function Fact({ label, value, tone }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-faint">
        {label}
      </span>
      <span className={`font-mono text-[12px] tabular-nums font-medium ${tone ?? "text-ink"}`}>
        {value}
      </span>
    </span>
  );
}
