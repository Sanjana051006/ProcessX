import { useState } from "react";
import { MACRO_COLOR, hours, pct } from "../../lib/format.js";

/**
 * A case's 24 activities as a cumulative time waterfall.
 *
 * Each row is one activity, split into the part the case spent queueing and the
 * part it spent being worked on — the distinction the entire product turns on,
 * since only the queue half is addressable by capacity. The bar starts at the
 * elapsed time when the case reached that activity, so the chart reads
 * left-to-right as the case's actual passage through the week.
 *
 * `activeIndex` drives the step-through: the panel highlights one activity and
 * dims the rest, so pressing Forward walks the case down the lifecycle.
 */
export default function Waterfall({ steps, activeIndex, onSelect, total }) {
  const [hover, setHover] = useState(null);
  const span = total ?? steps[steps.length - 1]?.elapsed_hours ?? 1;

  return (
    <ol className="space-y-[3px]">
      {steps.map((s, i) => {
        const start = s.elapsed_hours - s.duration_hours;
        const left = (start / span) * 100;
        const waitW = (s.queue_wait_hours / span) * 100;
        const svcW = (s.service_hours / span) * 100;
        const isActive = activeIndex === i;
        const dim = activeIndex != null && !isActive;
        const color = MACRO_COLOR[s.macro_stage];

        return (
          <li key={s.stage}>
            <button
              type="button"
              onClick={() => onSelect?.(i)}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              className={`group grid w-full grid-cols-[132px_1fr_66px] items-center gap-2 rounded
                          px-1.5 py-[3px] text-left transition-all
                          ${isActive ? "bg-ink/7" : "hover:bg-ink/4"}
                          ${dim ? "opacity-45" : ""}`}
            >
              <span className="flex items-center gap-1.5 min-w-0">
                <span
                  className="h-2.5 w-[3px] shrink-0 rounded-sm"
                  style={{ background: color }}
                />
                <span
                  className={`truncate text-[11.5px] ${
                    isActive ? "font-semibold text-ink" : "text-ink-mid"
                  }`}
                >
                  {s.label}
                </span>
              </span>

              <span className="relative block h-[13px]">
                {/* The rail the case travels along. */}
                <span className="absolute inset-y-[5px] left-0 right-0 rounded-full bg-ink/6" />
                <span
                  className="absolute inset-y-0 flex overflow-hidden rounded-[3px] animate-sweep origin-left"
                  style={{
                    left: `${left}%`,
                    width: `${Math.max(waitW + svcW, 0.5)}%`,
                    animationDelay: `${i * 18}ms`,
                  }}
                >
                  {/* Queue: hatched, because it is time nobody is working. */}
                  <span
                    className="h-full"
                    style={{
                      width: `${(waitW / (waitW + svcW || 1)) * 100}%`,
                      background: `repeating-linear-gradient(115deg, ${color} 0 2px, transparent 2px 4.5px)`,
                      backgroundColor: `color-mix(in srgb, ${color} 16%, transparent)`,
                    }}
                  />
                  {/* Service: solid. */}
                  <span
                    className="h-full"
                    style={{
                      width: `${(svcW / (waitW + svcW || 1)) * 100}%`,
                      background: color,
                    }}
                  />
                </span>
              </span>

              <span className="text-right font-mono text-[10.5px] tabular-nums text-ink-mid">
                {hours(s.duration_hours)}
              </span>
            </button>

            {(isActive || hover === i) && (
              <div className="ml-[138px] mb-1 mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] tabular-nums text-ink-faint">
                <span>queued {hours(s.queue_wait_hours)}</span>
                <span>worked {hours(s.service_hours)}</span>
                <span>queue depth {s.queue_len_at_arrival}</span>
                {s.predicted_hours != null && (
                  <span>
                    M1 said {hours(s.predicted_hours)} ({s.residual_hours > 0 ? "+" : ""}
                    {hours(s.residual_hours)})
                  </span>
                )}
                <span
                  className={s.stage_percentile > 0.9 ? "text-red" : ""}
                  title="Where this step sits in the population for this activity"
                >
                  p{Math.round(s.stage_percentile * 100)}
                </span>
              </div>
            )}
          </li>
        );
      })}

      <li className="flex items-center gap-4 pt-2 font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span
            className="h-2.5 w-4 rounded-[2px]"
            style={{
              background:
                "repeating-linear-gradient(115deg, rgb(var(--ink-light)) 0 2px, transparent 2px 4.5px)",
            }}
          />
          queueing
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-[2px] bg-ink-light" /> being worked
        </span>
        <span className="ml-auto normal-case tracking-normal">
          {pct(
            steps.reduce((a, s) => a + s.queue_wait_hours, 0) / (span || 1),
          )}{" "}
          of this case's lifecycle was spent waiting
        </span>
      </li>
    </ol>
  );
}
