import { useMemo, useState } from "react";
import { MACRO_COLOR, hours, num } from "../lib/format.js";
import { HealthDot } from "./ui.jsx";

const COLUMNS = [
  { key: "rank", label: "#", align: "right", width: "w-9" },
  { key: "label", label: "Activity", align: "left" },
  { key: "macro_label", label: "Macro-stage", align: "left", hideBelow: "xl" },
  { key: "mean_wait_hours", label: "Wait", align: "right" },
  { key: "mean_service_hours", label: "Service", align: "right", hideBelow: "sm" },
  { key: "wait_to_service_ratio", label: "W/S", align: "right", hideBelow: "md" },
  { key: "utilisation", label: "Util.", align: "right", hideBelow: "md" },
  { key: "contribution_pct", label: "Delay", title: "Share of total delay", align: "right" },
  { key: "health", label: "Health", align: "left" },
];

/**
 * The 24-activity table.
 *
 * Sortable on every column, because the useful reading changes with the
 * question — ranked by score to find the constraint, by utilisation to find
 * what is running hot, by wait-to-service to find where the queue is
 * disproportionate to the work.
 *
 * Two layout rules it must not break, both of them lessons from the version
 * this replaces:
 *
 * 1. It scrolls **inside itself**, with a sticky header. A 24-row table left to
 *    grow made the dashboard several screens tall, which is what pushed the
 *    process rail off-screen and made selecting a row look like it did nothing.
 * 2. It never widens its container. Low-value columns drop out at each
 *    breakpoint rather than forcing a horizontal scrollbar on the page.
 *
 * The delay-share column carries an inline bar behind the number. A separate
 * chart for one column would be a second thing to look at; a bar in the cell is
 * the same information with no extra eye travel.
 */
export default function StageTable({ stages, selected, onSelect, filter, maxHeight = 360 }) {
  const [sort, setSort] = useState({ key: "rank", dir: 1 });

  const rows = useMemo(() => {
    const filtered = filter ? stages.filter((s) => s.macro_stage === filter) : stages;
    const { key, dir } = sort;
    return [...filtered].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (typeof av === "string") return dir * av.localeCompare(bv);
      return dir * ((av ?? -Infinity) - (bv ?? -Infinity));
    });
  }, [stages, sort, filter]);

  const maxShare = Math.max(...stages.map((s) => s.contribution_pct), 1);

  function toggle(key) {
    setSort((s) =>
      s.key === key ? { key, dir: -s.dir } : { key, dir: key === "rank" ? 1 : -1 },
    );
  }

  return (
    <div
      className="min-h-0 overflow-y-auto overflow-x-hidden rounded-xl border border-line/8"
      style={{ maxHeight }}
    >
      <table className="w-full border-collapse text-[12.5px]">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`sticky top-0 z-10 border-b border-line/10 bg-surface-3/95 px-1.5 py-2 sm:px-2.5
                            font-mono text-label uppercase text-ink-3 backdrop-blur
                            ${c.align === "right" ? "text-right" : "text-left"}
                            ${c.width ?? ""}
                            ${c.hideBelow === "sm" ? "hidden sm:table-cell" : ""}
                            ${c.hideBelow === "md" ? "hidden md:table-cell" : ""}
                            ${c.hideBelow === "xl" ? "hidden xl:table-cell" : ""}`}
              >
                <button
                  type="button"
                  onClick={() => toggle(c.key)}
                  title={c.title}
                  className="inline-flex items-center gap-1 hover:text-ink"
                >
                  {c.label}
                  <span className={sort.key === c.key ? "text-ink" : "text-transparent"}>
                    {sort.dir > 0 ? "↑" : "↓"}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSelected = selected === r.stage;
            return (
              <tr
                key={r.stage}
                onClick={() => onSelect?.(r.stage)}
                className={`cursor-pointer border-b border-line/6 transition-colors last:border-b-0
                            ${isSelected ? "bg-accent-wash" : "hover:bg-surface-3/70"}`}
              >
                <td className="px-1.5 py-1.5 sm:px-2.5 text-right font-mono text-[10.5px] tabular-nums text-ink-4">
                  {r.rank}
                </td>
                <td className="max-w-0 px-1.5 py-1.5 sm:px-2.5">
                  <span className="flex items-center gap-2">
                    <span
                      className="h-3 w-[3px] shrink-0 rounded-full"
                      style={{ background: MACRO_COLOR[r.macro_stage] }}
                    />
                    <span className={`truncate ${isSelected ? "font-semibold text-ink" : "text-ink-2"}`}>
                      {r.label}
                    </span>
                    {r.anomalous && (
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-danger"
                        title={`M3 flags this in ${Math.round(r.anomaly_share * 100)}% of its windows`}
                      />
                    )}
                  </span>
                </td>
                <td className="hidden max-w-0 truncate px-1.5 py-1.5 sm:px-2.5 text-[11.5px] text-ink-3 xl:table-cell">
                  {r.macro_label}
                </td>
                <td className="px-1.5 py-1.5 sm:px-2.5 text-right font-mono tabular-nums text-ink-2">
                  {hours(r.mean_wait_hours)}
                </td>
                <td className="hidden px-1.5 py-1.5 sm:px-2.5 text-right font-mono tabular-nums text-ink-3 sm:table-cell">
                  {hours(r.mean_service_hours)}
                </td>
                <td
                  className={`hidden px-1.5 py-1.5 sm:px-2.5 text-right font-mono tabular-nums md:table-cell ${
                    r.wait_to_service_ratio > 1 ? "font-semibold text-danger" : "text-ink-3"
                  }`}
                >
                  {num(r.wait_to_service_ratio)}
                </td>
                <td className="hidden px-1.5 py-1.5 sm:px-2.5 text-right font-mono tabular-nums md:table-cell">
                  <span
                    className={
                      r.utilisation > 0.8
                        ? "font-semibold text-danger"
                        : r.utilisation > 0.6
                          ? "text-warn"
                          : "text-ink-3"
                    }
                  >
                    {num(r.utilisation)}
                  </span>
                </td>
                <td className="relative px-1.5 py-1.5 sm:px-2.5 text-right font-mono tabular-nums text-ink-2">
                  <span
                    className="absolute inset-y-1 right-1.5 rounded-[4px] bg-accent/10"
                    style={{ width: `${(r.contribution_pct / maxShare) * 70}%` }}
                    aria-hidden
                  />
                  <span className="relative">{num(r.contribution_pct, 1)}%</span>
                </td>
                <td className="px-1.5 py-1.5 sm:px-2.5">
                  <HealthDot band={r.health} label={false} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
