import { useMemo, useState } from "react";
import { MACRO_COLOR, hours, num } from "../lib/format.js";
import { HealthDot } from "./ui.jsx";

const COLUMNS = [
  { key: "rank", label: "#", align: "right", width: "w-10", format: (r) => r.rank },
  { key: "label", label: "Activity", align: "left", format: (r) => r.label },
  { key: "macro_label", label: "Macro-stage", align: "left", hideBelow: "lg" },
  { key: "mean_wait_hours", label: "Wait", align: "right", format: (r) => hours(r.mean_wait_hours) },
  { key: "mean_service_hours", label: "Service", align: "right", hideBelow: "sm", format: (r) => hours(r.mean_service_hours) },
  { key: "wait_to_service_ratio", label: "W/S", align: "right", format: (r) => num(r.wait_to_service_ratio) },
  { key: "utilisation", label: "Util.", align: "right", format: (r) => num(r.utilisation) },
  { key: "contribution_pct", label: "Delay share", align: "right", format: (r) => `${num(r.contribution_pct, 1)}%` },
  { key: "health", label: "Health", align: "left" },
];

/**
 * The 24-activity table.
 *
 * Sortable on every numeric column, because the useful reading changes with the
 * question — ranked by score to find the constraint, by utilisation to find
 * what is running hot, by wait-to-service to find where the queue is
 * disproportionate to the work.
 *
 * The delay-share column carries an inline bar behind the number. A separate
 * chart for one column would be a second thing to look at; a bar in the cell is
 * the same information with no extra eye travel.
 */
export default function StageTable({ stages, selected, onSelect, filter }) {
  const [sort, setSort] = useState({ key: "rank", dir: 1 });

  const rows = useMemo(() => {
    const filtered = filter
      ? stages.filter((s) => s.macro_stage === filter)
      : stages;
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
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === "rank" ? 1 : -1 }));
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-ink/12">
      <table className="w-full min-w-[720px] border-collapse text-[13px]">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`sticky top-0 z-10 border-b border-ink/14 bg-paper-sink/70 px-3 py-2.5
                            font-mono text-label uppercase text-ink-light backdrop-blur
                            ${c.align === "right" ? "text-right" : "text-left"}
                            ${c.width ?? ""}
                            ${c.hideBelow === "sm" ? "hidden sm:table-cell" : ""}
                            ${c.hideBelow === "lg" ? "hidden lg:table-cell" : ""}`}
              >
                <button
                  type="button"
                  onClick={() => toggle(c.key)}
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
                className={`cursor-pointer border-b border-ink/8 transition-colors last:border-b-0
                            ${isSelected ? "bg-ink/6" : "hover:bg-paper-sink/40"}`}
              >
                <td className="px-3 py-2 text-right font-mono text-[11px] tabular-nums text-ink-faint">
                  {r.rank}
                </td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-2">
                    <span
                      className="h-3 w-[3px] shrink-0 rounded-sm"
                      style={{ background: MACRO_COLOR[r.macro_stage] }}
                    />
                    <span className={isSelected ? "font-semibold" : ""}>{r.label}</span>
                    {r.anomalous && (
                      <span
                        className="h-1.5 w-1.5 rounded-full bg-red"
                        title={`Flagged in ${Math.round(r.anomaly_share * 100)}% of its windows`}
                      />
                    )}
                  </span>
                </td>
                <td className="hidden px-3 py-2 text-[12px] text-ink-light lg:table-cell">
                  {r.macro_label}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {hours(r.mean_wait_hours)}
                </td>
                <td className="hidden px-3 py-2 text-right font-mono tabular-nums text-ink-mid sm:table-cell">
                  {hours(r.mean_service_hours)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono tabular-nums ${
                    r.wait_to_service_ratio > 1 ? "font-semibold text-red" : "text-ink-mid"
                  }`}
                >
                  {num(r.wait_to_service_ratio)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  <span
                    className={
                      r.utilisation > 0.8
                        ? "font-semibold text-red"
                        : r.utilisation > 0.6
                          ? "text-band-amber"
                          : "text-ink-mid"
                    }
                  >
                    {num(r.utilisation)}
                  </span>
                </td>
                <td className="relative px-3 py-2 text-right font-mono tabular-nums">
                  <span
                    className="absolute inset-y-1 right-2 rounded-sm bg-ink/8"
                    style={{ width: `${(r.contribution_pct / maxShare) * 64}%` }}
                    aria-hidden
                  />
                  <span className="relative">{num(r.contribution_pct, 1)}%</span>
                </td>
                <td className="px-3 py-2">
                  <HealthDot band={r.health} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
