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
 * The layout is a **flex column where every row is `flex-1`**, not a stack of
 * fixed-height rows. Twenty-four fixed rows are about 530px tall, which does not
 * fit the simulation page's locked viewport on a laptop; sharing the container's
 * height between them means the chart is exactly as tall as the box it is given,
 * on any screen, with no scrollbar and no measurement code.
 *
 * For the same reason the hover detail is an overlay rather than an expanding
 * row — a row that grows on hover would resize all 24 of its siblings.
 *
 * `activeIndex` drives the step-through: the panel highlights one activity and
 * dims the rest, so pressing Forward walks the case down the lifecycle.
 */
export default function Waterfall({ steps, activeIndex, onSelect, total }) {
  const [hover, setHover] = useState(null);
  const span = total ?? steps[steps.length - 1]?.elapsed_hours ?? 1;
  const shown = hover ?? activeIndex;
  const detail = shown != null ? steps[shown] : null;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <ol className="flex min-h-0 flex-1 flex-col gap-[1px]">
        {steps.map((s, i) => {
          const start = s.elapsed_hours - s.duration_hours;
          const left = (start / span) * 100;
          const waitW = (s.queue_wait_hours / span) * 100;
          const svcW = (s.service_hours / span) * 100;
          const isActive = activeIndex === i;
          const dim = activeIndex != null && !isActive;
          const color = MACRO_COLOR[s.macro_stage];

          return (
            <li key={s.stage} className="flex min-h-0 flex-1">
              <button
                type="button"
                onClick={() => onSelect?.(i)}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                className={`group grid w-full min-h-0 grid-cols-[110px_1fr_56px] items-center gap-2
                            rounded px-1.5 text-left transition-colors
                            ${isActive ? "bg-accent-wash" : "hover:bg-surface-3"}
                            ${dim ? "opacity-45" : ""}`}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    className="h-2.5 w-[3px] shrink-0 rounded-full"
                    style={{ background: color }}
                  />
                  <span
                    className={`truncate text-[10.5px] leading-none ${
                      isActive ? "font-semibold text-ink" : "text-ink-2"
                    }`}
                  >
                    {s.label}
                  </span>
                </span>

                <span className="relative block h-[9px]">
                  {/* The rail the case travels along. */}
                  <span className="absolute inset-x-0 inset-y-[3px] rounded-full bg-line/6" />
                  <span
                    className="absolute inset-y-0 flex origin-left animate-sweep overflow-hidden rounded-[3px]"
                    style={{
                      left: `${left}%`,
                      width: `${Math.max(waitW + svcW, 0.5)}%`,
                      animationDelay: `${i * 16}ms`,
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

                <span className="text-right font-mono text-[9.5px] leading-none tabular-nums text-ink-3">
                  {hours(s.duration_hours)}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="mt-2 flex shrink-0 items-center gap-3 border-t border-line/8 pt-2 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">
        <span className="flex items-center gap-1.5">
          <span
            className="h-2.5 w-4 rounded-[3px]"
            style={{
              background:
                "repeating-linear-gradient(115deg, rgb(var(--ink-3)) 0 2px, transparent 2px 4.5px)",
            }}
          />
          queueing
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-[3px] bg-ink-3" /> being worked
        </span>
        <span className="ml-auto truncate normal-case tracking-normal">
          {pct(steps.reduce((a, s) => a + s.queue_wait_hours, 0) / (span || 1))} of this case
          was spent waiting
        </span>
      </div>

      {/* The detail overlay. Absolutely positioned so inspecting a row can never
          change the height of the chart underneath it. */}
      {detail && (
        <div className="pointer-events-none absolute inset-x-0 bottom-8 z-10 animate-fade px-1">
          <div className="glass flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line/10 px-2.5 py-1.5 font-mono text-[9.5px] tabular-nums text-ink-3 shadow-card">
            <span className="font-sans text-[11px] font-semibold text-ink">{detail.label}</span>
            <span>queued {hours(detail.queue_wait_hours)}</span>
            <span>worked {hours(detail.service_hours)}</span>
            <span>depth {detail.queue_len_at_arrival}</span>
            {detail.predicted_hours != null && (
              <span>
                M1 {hours(detail.predicted_hours)} ({detail.residual_hours > 0 ? "+" : ""}
                {hours(detail.residual_hours)})
              </span>
            )}
            <span
              className={detail.stage_percentile > 0.9 ? "text-danger" : ""}
              title="Where this step sits in the population for this activity"
            >
              p{Math.round(detail.stage_percentile * 100)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
