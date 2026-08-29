import { useState } from "react";
import { MACRO_COLOR, hours, pct } from "../../lib/format.js";

/**
 * One stacked bar showing how a whole is divided — here, how the mean cycle
 * time splits across the five macro-stages.
 *
 * A single bar rather than five, because the question it answers is "what share
 * of the lifecycle is this", and a share reads best against the whole it is a
 * share of. Segments under 4% still get a hit target and a legend row even when
 * their label will not fit inside them.
 */
export default function ShareBar({ rows, valueKey = "share_of_cycle", total }) {
  const [active, setActive] = useState(null);
  const sum = (total ?? rows.reduce((a, r) => a + (Number(r[valueKey]) || 0), 0)) || 1;

  return (
    <div>
      <div className="flex h-12 w-full overflow-hidden rounded-xl border border-line/8 shadow-xs">
        {rows.map((r) => {
          const share = (Number(r[valueKey]) || 0) / sum;
          const isActive = active === r.macro_stage;
          return (
            <button
              key={r.macro_stage}
              type="button"
              onMouseEnter={() => setActive(r.macro_stage)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(r.macro_stage)}
              onBlur={() => setActive(null)}
              title={`${r.label} — ${pct(share)} of mean cycle time`}
              className="relative h-full min-w-[3px] transition-[filter,opacity] duration-200
                         focus:outline-none focus-visible:z-10"
              style={{
                flex: `${Math.max(share, 0.008)} 1 0`,
                background: MACRO_COLOR[r.macro_stage],
                opacity: active && !isActive ? 0.42 : 1,
              }}
            >
              {share > 0.11 && (
                <span className="absolute inset-0 grid place-items-center font-mono text-[10px] text-paper tabular-nums">
                  {pct(share, 0)}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-5">
        {rows.map((r) => {
          const isActive = active === r.macro_stage;
          return (
            <li
              key={r.macro_stage}
              className={`flex items-start gap-2 transition-opacity ${
                active && !isActive ? "opacity-45" : ""
              }`}
            >
              <span
                className="mt-[5px] h-2 w-2 shrink-0 rounded-[2px]"
                style={{ background: MACRO_COLOR[r.macro_stage] }}
              />
              <span className="min-w-0">
                <span className="block truncate text-[11.5px] font-medium leading-tight text-ink-mid">
                  {r.label}
                </span>
                <span className="block font-mono text-[10.5px] tabular-nums text-ink-faint">
                  {hours(r.mean_duration_hours)}
                  {r.mean_wait_hours != null && (
                    <> · {hours(r.mean_wait_hours)} queued</>
                  )}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
