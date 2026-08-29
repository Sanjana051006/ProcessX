import { useState } from "react";
import { MACRO_COLOR, hours } from "../../lib/format.js";

const W = 420;
const H = 300;
const PAD = { t: 12, r: 12, b: 30, l: 40 };

/**
 * M1's prediction against what actually happened, one point per activity of the
 * case being followed.
 *
 * The diagonal is the only reference that matters: a point on it was predicted
 * exactly, a point above it took longer than M1 could explain. That gap is the
 * residual M2 weights at 25% of its bottleneck score and M4 reads as a window
 * feature, so this chart is where the residual stops being a term in a formula
 * and becomes a visible distance.
 *
 * Both axes are log-scaled. Activity durations in this lifecycle span three
 * orders of magnitude — `closure` is minutes, `last_mile` is fourteen hours —
 * and on a linear axis the whole onboarding stage collapses into the origin.
 */
export default function PredScatter({ predictions, highlight, onSelect }) {
  const [hover, setHover] = useState(null);
  const pts = (predictions ?? []).filter((p) => p.actual > 0 && p.predicted > 0);
  if (!pts.length) return null;

  const lo = Math.min(...pts.flatMap((p) => [p.actual, p.predicted])) * 0.7;
  const hi = Math.max(...pts.flatMap((p) => [p.actual, p.predicted])) * 1.35;
  const L = (v) => Math.log10(v);
  const xOf = (v) => PAD.l + ((L(v) - L(lo)) / (L(hi) - L(lo))) * (W - PAD.l - PAD.r);
  const yOf = (v) => H - PAD.b - ((L(v) - L(lo)) / (L(hi) - L(lo))) * (H - PAD.t - PAD.b);

  // Decade ticks that actually fall inside the range.
  const ticks = [0.01, 0.1, 1, 10].filter((t) => t >= lo && t <= hi);
  const active = hover ?? pts.findIndex((p) => p.stage === highlight);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="min-h-0 w-full flex-1"
        role="img"
        aria-label="M1 predicted duration against actual duration, per activity"
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={xOf(t)} x2={xOf(t)} y1={PAD.t} y2={H - PAD.b}
                  stroke="rgb(var(--ink))" strokeOpacity="0.07" />
            <line x1={PAD.l} x2={W - PAD.r} y1={yOf(t)} y2={yOf(t)}
                  stroke="rgb(var(--ink))" strokeOpacity="0.07" />
            <text x={xOf(t)} y={H - PAD.b + 12} textAnchor="middle"
                  className="font-mono" fontSize="8" fill="rgb(var(--ink-faint))">
              {t < 1 ? t : `${t}h`}
            </text>
            <text x={PAD.l - 5} y={yOf(t) + 3} textAnchor="end"
                  className="font-mono" fontSize="8" fill="rgb(var(--ink-faint))">
              {t < 1 ? t : `${t}h`}
            </text>
          </g>
        ))}

        {/* Perfect prediction. */}
        <line
          x1={xOf(lo)} y1={yOf(lo)} x2={xOf(hi)} y2={yOf(hi)}
          stroke="rgb(var(--ink))" strokeOpacity="0.42" strokeWidth="1.2" strokeDasharray="4 3"
        />
        <text
          x={xOf(hi) - 6} y={yOf(hi) + 14} textAnchor="end"
          className="font-mono uppercase" fontSize="7.5" letterSpacing="1.3"
          fill="rgb(var(--ink-faint))"
        >
          predicted = actual
        </text>

        {pts.map((p, i) => {
          const isActive = active === i;
          return (
            <g key={p.stage}>
              {/* The residual, drawn as the vertical drop to the diagonal. */}
              {isActive && (
                <line
                  x1={xOf(p.predicted)} y1={yOf(p.actual)}
                  x2={xOf(p.predicted)} y2={yOf(p.predicted)}
                  stroke="rgb(var(--ink))" strokeWidth="1" strokeOpacity="0.5"
                />
              )}
              <circle
                cx={xOf(p.predicted)}
                cy={yOf(p.actual)}
                r={isActive ? 6 : 4.2}
                fill={MACRO_COLOR[p.macro_stage]}
                fillOpacity={active != null && active >= 0 && !isActive ? 0.35 : 0.85}
                stroke="rgb(var(--paper))"
                strokeWidth="1.2"
                onMouseEnter={() => setHover(i)}
                onClick={() => onSelect?.(p.stage)}
                className={onSelect ? "cursor-pointer" : ""}
              />
            </g>
          );
        })}

        <text
          x={(W + PAD.l) / 2} y={H - 3} textAnchor="middle"
          className="font-mono uppercase" fontSize="7.5" letterSpacing="1.6"
          fill="rgb(var(--ink-faint))"
        >
          M1 predicted
        </text>
        <text
          transform={`rotate(-90 10 ${H / 2})`} x="10" y={H / 2} textAnchor="middle"
          className="font-mono uppercase" fontSize="7.5" letterSpacing="1.6"
          fill="rgb(var(--ink-faint))"
        >
          actual
        </text>
      </svg>

      <p className="mt-1 h-4 shrink-0 truncate text-center font-mono text-[10px] tabular-nums text-ink-3">
        {active >= 0 && pts[active] ? (
          <>
            {pts[active].label}: {hours(pts[active].actual)} actual vs{" "}
            {hours(pts[active].predicted)} predicted ·{" "}
            <span className={pts[active].residual > 0 ? "text-red" : "text-band-green"}>
              {pts[active].residual > 0 ? "+" : ""}
              {hours(pts[active].residual)} residual
            </span>
          </>
        ) : (
          <span className="text-ink-faint">Hover a point for its residual</span>
        )}
      </p>
    </div>
  );
}
