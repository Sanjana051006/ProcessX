import { useState } from "react";
import { MACRO_COLOR, pctRaw } from "../../lib/format.js";

/**
 * A ranked horizontal bar list.
 *
 * Bars are laid out in HTML rather than SVG: the labels are real text that
 * wraps, selects and is read by a screen reader, and the bar is one absolutely
 * positioned div. An SVG here would buy nothing and cost all of that.
 *
 * Colour encodes the macro-stage, not the value — the value is already encoded
 * by length, and doubling it up would waste the one channel left for grouping.
 */
export default function RankBars({
  rows,
  valueKey = "contribution_pct",
  format = pctRaw,
  max,
  onSelect,
  selected,
  showRank = true,
}) {
  const [hover, setHover] = useState(null);
  const top = max ?? Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 0.0001);

  return (
    <ol className="space-y-1">
      {rows.map((r, i) => {
        const value = Number(r[valueKey]) || 0;
        const width = Math.max(1.5, (value / top) * 100);
        const isSelected = selected === r.stage;
        const isHover = hover === r.stage;
        return (
          <li key={r.stage}>
            <button
              type="button"
              onClick={() => onSelect?.(r.stage)}
              onMouseEnter={() => setHover(r.stage)}
              onMouseLeave={() => setHover(null)}
              disabled={!onSelect}
              className={`group relative w-full text-left rounded-md px-2 py-1.5 transition-colors
                          ${onSelect ? "cursor-pointer" : "cursor-default"}
                          ${isSelected ? "bg-ink/6" : "hover:bg-ink/4"}`}
              style={{ animationDelay: `${i * 26}ms` }}
            >
              <div className="flex items-baseline gap-2">
                {showRank && (
                  <span className="font-mono text-[10px] tabular-nums text-ink-faint w-5 shrink-0">
                    {String(r.rank ?? i + 1).padStart(2, "0")}
                  </span>
                )}
                <span
                  className={`text-[13px] font-medium truncate ${
                    isSelected ? "text-ink" : "text-ink-mid group-hover:text-ink"
                  }`}
                >
                  {r.label ?? r.stage}
                </span>
                {r.anomalous && (
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-red"
                    title="Flagged anomalous by M3"
                  />
                )}
                <span className="ml-auto font-mono text-[11px] tabular-nums text-ink shrink-0">
                  {format(value)}
                </span>
              </div>
              <div className="mt-1.5 ml-7 h-[7px] rounded-sm bg-ink/7 overflow-hidden">
                <div
                  className="h-full rounded-sm origin-left animate-sweep transition-opacity"
                  style={{
                    width: `${width}%`,
                    background: MACRO_COLOR[r.macro_stage] ?? "rgb(var(--ink))",
                    opacity: isSelected || isHover ? 1 : 0.78,
                    animationDelay: `${i * 26}ms`,
                  }}
                />
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
