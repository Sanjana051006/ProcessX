import { hours, money, num, pct } from "../lib/format.js";

/** The mono micro-label the whole system uses as its section marker. */
export function Eyebrow({ children, className = "", index }) {
  return (
    <p className={`eyebrow flex items-center gap-2.5 ${className}`}>
      {index != null && (
        <span className="tabular-nums text-ink">{String(index).padStart(2, "0")}</span>
      )}
      {index != null && <span className="h-px w-6 bg-ink/25" />}
      <span>{children}</span>
    </p>
  );
}

/**
 * A page section. The 2px ink rule at the top is the reference site's device for
 * separating acts, and it does the same job here: it is the only divider in the
 * system, so a rule always means "a new part of the argument starts".
 */
export function Section({ eyebrow, index, title, lede, action, children, className = "", ruled = true }) {
  return (
    <section className={`${ruled ? "rule-t pt-8 sm:pt-10" : ""} ${className}`}>
      {(eyebrow || title) && (
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            {eyebrow && <Eyebrow index={index}>{eyebrow}</Eyebrow>}
            {title && (
              <h2 className="mt-3 text-headline font-extrabold uppercase">{title}</h2>
            )}
            {lede && (
              <p className="mt-2.5 max-w-2xl text-[14px] leading-relaxed text-ink-mid">
                {lede}
              </p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/**
 * A KPI tile.
 *
 * The delta is the reason the tile exists — a cycle time of 19.08 h means
 * nothing on its own and everything against the 18.33 h it used to be. `invert`
 * flips which direction counts as good, because for cycle time and cost down is
 * better while for throughput up is.
 */
export function StatCard({ label, value, unit, delta, deltaLabel, invert = false, hint, accent }) {
  const dir = delta == null || Math.abs(delta) < 1e-9 ? 0 : delta > 0 ? 1 : -1;
  const good = invert ? dir < 0 : dir > 0;
  const tone =
    dir === 0 ? "text-ink-faint" : good ? "text-band-green" : "text-red";

  return (
    <div
      className={`panel relative overflow-hidden p-4 sm:p-5 ${
        accent ? "border-red/30 bg-red/[0.04]" : ""
      }`}
    >
      <p className="eyebrow">{label}</p>
      <p className="mt-3 flex items-baseline gap-1.5">
        <span className="metric text-[26px] font-extrabold leading-none tracking-[-0.03em] sm:text-[30px]">
          {value}
        </span>
        {unit && <span className="text-[12px] font-medium text-ink-light">{unit}</span>}
      </p>
      <p className="mt-2 flex min-h-[16px] items-center gap-1.5 font-mono text-[10.5px] tabular-nums">
        {dir !== 0 && (
          <span className={tone}>
            {dir > 0 ? "▲" : "▼"} {deltaLabel}
          </span>
        )}
        {dir === 0 && deltaLabel && <span className="text-ink-faint">{deltaLabel}</span>}
        {hint && <span className="truncate text-ink-faint">{hint}</span>}
      </p>
    </div>
  );
}

/** A small labelled figure, for dense metric rows inside a panel. */
export function Metric({ label, value, hint, tone }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow truncate">{label}</p>
      <p
        className={`metric mt-1.5 text-[17px] font-bold leading-none tracking-[-0.02em] ${
          tone ?? "text-ink"
        }`}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-1 text-[10.5px] leading-snug text-ink-faint">{hint}</p>
      )}
    </div>
  );
}

/** Primary action: an ink capsule. There is one per screen at most. */
export function Button({ as: As = "button", variant = "solid", size = "md", className = "", ...props }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-full font-mono uppercase " +
    "tracking-[0.16em] transition-all disabled:opacity-40 disabled:pointer-events-none";
  const sizes = {
    sm: "px-3 py-1.5 text-[9.5px]",
    md: "px-4 py-2.5 text-label",
    lg: "px-6 py-3 text-[11px]",
  };
  const variants = {
    solid: "bg-ink text-paper hover:bg-ink/88 active:scale-[0.98]",
    outline: "border border-ink/22 text-ink hover:bg-ink hover:text-paper active:scale-[0.98]",
    ghost: "text-ink-mid hover:text-ink hover:bg-ink/6",
    red: "bg-red text-paper hover:bg-red/88 active:scale-[0.98]",
  };
  return <As className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props} />;
}

/** The health band as a dot plus its word — colour is never the only channel. */
export function HealthDot({ band, label }) {
  const map = {
    green: ["bg-band-green", "Healthy"],
    amber: ["bg-band-amber", "Strained"],
    red: ["bg-red", "Critical"],
    grey: ["bg-ink-faint", "No reference"],
  };
  const [bg, word] = map[band] ?? map.grey;
  return (
    <span className="inline-flex items-center gap-1.5" title={word}>
      <span className={`h-1.5 w-1.5 rounded-full ${bg}`} />
      {label !== false && (
        <span className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-mid">
          {word}
        </span>
      )}
    </span>
  );
}

/** A skeleton that holds the exact space its content will take, so nothing on
 *  the page jumps when the fetch lands. */
export function Skeleton({ className = "h-24" }) {
  return (
    <div className={`animate-pulse rounded-xl bg-ink/[0.055] ${className}`} />
  );
}

export function ErrorNote({ error, retry }) {
  return (
    <div className="panel border-red/30 bg-red/[0.05] p-5">
      <p className="eyebrow text-red">Could not load</p>
      <p className="mt-2 text-[14px] text-ink-mid">{String(error)}</p>
      <p className="mt-3 text-[12.5px] text-ink-faint">
        The backend must be running on port 8000:{" "}
        <code className="rounded bg-paper-sink px-1.5 py-0.5 font-mono text-[11px]">
          .venv/Scripts/python -m uvicorn backend.main:app --port 8000
        </code>
      </p>
      {retry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={retry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/** Formatters re-exported so a page imports its numbers and its chrome from one
 *  place rather than two. */
export { hours, money, num, pct };
