import { useMemo, useState } from "react";
import { clock, hours, num } from "../../lib/format.js";

const W = 900;
const H = 150;
const PAD = { t: 10, r: 10, b: 22, l: 34 };

/**
 * The anomaly timeline for one activity: mean wait per hourly window as an
 * area, with the flagged windows marked and the moment the fault was injected
 * drawn as a labelled rule.
 *
 * The injection marker is the point of the chart. A wait curve on its own says
 * "it got worse"; the marker is what turns it into "it got worse HERE, and the
 * detector caught it N hours later", which is the claim M3's metric card makes.
 *
 * Rendered as a responsive SVG with a fixed viewBox — the aspect is stable, the
 * type scales with it, and there is no resize observer to get wrong.
 */
export default function AnomalyStrip({ timeline, injectedAt, stageLabel }) {
  const [hover, setHover] = useState(null);

  const { path, area, points, maxWait, xOf, yOf } = useMemo(() => {
    const pts = timeline ?? [];
    if (!pts.length) return { path: "", area: "", points: [], maxWait: 0 };
    const x0 = pts[0].window;
    const x1 = pts[pts.length - 1].window;
    const span = Math.max(x1 - x0, 1);
    const top = Math.max(...pts.map((p) => p.mean_wait), 0.01);

    const xOf = (w) => PAD.l + ((w - x0) / span) * (W - PAD.l - PAD.r);
    const yOf = (v) => H - PAD.b - (v / top) * (H - PAD.t - PAD.b);

    const d = pts.map((p, i) => `${i ? "L" : "M"}${xOf(p.window).toFixed(1)},${yOf(p.mean_wait).toFixed(1)}`).join("");
    return {
      path: d,
      area: `${d}L${xOf(x1).toFixed(1)},${H - PAD.b}L${xOf(x0).toFixed(1)},${H - PAD.b}Z`,
      points: pts,
      maxWait: top,
      xOf,
      yOf,
    };
  }, [timeline]);

  if (!points.length) {
    return (
      <div className="grid h-full min-h-[110px] place-items-center text-[12px] text-ink-4">
        No windows to plot.
      </div>
    );
  }

  const flagged = points.filter((p) => p.anomaly);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="min-h-0 w-full flex-1"
        role="img"
        aria-label={`Mean queue wait per hour at ${stageLabel}, with anomalous windows marked`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="waitfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--red))" stopOpacity="0.22" />
            <stop offset="100%" stopColor="rgb(var(--red))" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Gridlines at the quartiles of the wait axis. */}
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={yOf(maxWait * f)}
              y2={yOf(maxWait * f)}
              stroke="rgb(var(--ink))"
              strokeOpacity={f === 0 ? 0.22 : 0.08}
              strokeWidth="1"
            />
            <text
              x={PAD.l - 6}
              y={yOf(maxWait * f) + 3}
              textAnchor="end"
              className="font-mono"
              fontSize="8.5"
              fill="rgb(var(--ink-faint))"
            >
              {num(maxWait * f, 1)}
            </text>
          </g>
        ))}

        <path d={area} fill="url(#waitfill)" />
        <path d={path} fill="none" stroke="rgb(var(--red))" strokeWidth="1.6" />

        {/* Flagged windows as ticks along the baseline — dense enough that a
            sustained run of them reads as a solid block, which is exactly the
            pattern M3 requires before it trips a stage. */}
        {flagged.map((p) => (
          <rect
            key={p.window}
            x={xOf(p.window) - 1.4}
            y={H - PAD.b - 7}
            width="2.8"
            height="7"
            fill="rgb(var(--red))"
            opacity="0.85"
          />
        ))}

        {injectedAt != null && (
          <g>
            <line
              x1={xOf(injectedAt)}
              x2={xOf(injectedAt)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="rgb(var(--ink))"
              strokeWidth="1.4"
              strokeDasharray="3 3"
            />
            <text
              x={xOf(injectedAt) + 5}
              y={PAD.t + 9}
              className="font-mono uppercase"
              fontSize="8"
              letterSpacing="1.4"
              fill="rgb(var(--ink-mid))"
            >
              constraint starts
            </text>
          </g>
        )}

        {/* One transparent hit column per window, so the hover target is the
            whole vertical slice rather than a 2px line. */}
        {points.map((p, i) => (
          <rect
            key={p.window}
            x={xOf(p.window) - (W - PAD.l - PAD.r) / points.length / 2}
            y={PAD.t}
            width={(W - PAD.l - PAD.r) / points.length}
            height={H - PAD.t - PAD.b}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {hover != null && (
          <line
            x1={xOf(points[hover].window)}
            x2={xOf(points[hover].window)}
            y1={PAD.t}
            y2={H - PAD.b}
            stroke="rgb(var(--ink))"
            strokeOpacity="0.35"
            strokeWidth="1"
          />
        )}

        <text
          x={PAD.l}
          y={H - 6}
          className="font-mono"
          fontSize="8.5"
          fill="rgb(var(--ink-faint))"
        >
          {clock(points[0].window)}
        </text>
        <text
          x={W - PAD.r}
          y={H - 6}
          textAnchor="end"
          className="font-mono"
          fontSize="8.5"
          fill="rgb(var(--ink-faint))"
        >
          {clock(points[points.length - 1].window)}
        </text>
      </svg>

      <div className="mt-1 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">
        <span className="flex items-center gap-1.5">
          <span className="h-[2px] w-4 bg-red" /> mean queue wait (h)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-[3px] bg-red" /> flagged window
        </span>
        {hover != null && (
          <span className="ml-auto text-ink normal-case tracking-normal">
            {clock(points[hover].window)} · wait {hours(points[hover].mean_wait)} · util{" "}
            {num(points[hover].utilisation)} · {points[hover].n_arrivals} arrivals
            {points[hover].anomaly ? " · flagged" : ""}
          </span>
        )}
      </div>
    </div>
  );
}
