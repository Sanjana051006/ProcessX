import { hours, money, num, pct } from "../lib/format.js";
import { span as colSpan } from "./grid.js";

/* ------------------------------------------------------------------ text -- */

/** The mono micro-label the whole system uses as its section marker. */
export function Eyebrow({ children, className = "", dot }) {
  return (
    <p className={`eyebrow flex items-center gap-2 ${className}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full" style={{ background: dot }} />}
      <span className="truncate">{children}</span>
    </p>
  );
}

/**
 * A page section header. No rules, no act numbers — on a bento layout the tiles
 * already separate the content, and a second divider system on top of them is
 * noise. A section is a label, a title and an optional right-hand control.
 */
export function SectionHead({ eyebrow, title, lede, action, className = "" }) {
  return (
    <header className={`mb-4 flex flex-wrap items-end justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        {title && <h2 className="title-lg mt-2">{title}</h2>}
        {lede && <p className="lede mt-2 max-w-2xl">{lede}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
  );
}

/* ----------------------------------------------------------------- bento -- */

/**
 * The bento grid.
 *
 * Twelve columns with `auto-rows-[minmax(0,auto)]`, and tiles claim spans. The
 * point of a bento over a uniform card grid is that the tiles are not equal:
 * the KPI that matters gets twice the area of the one that does not, and the
 * eye reads size as importance before it reads any label.
 *
 * `min-w-0` on the grid and on every tile is load-bearing — without it a wide
 * table or a long mono string inside one tile blows the whole row out and
 * reintroduces the horizontal scroll this layout exists to remove.
 */
export function Bento({ children, className = "" }) {
  return (
    <div className={`grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-6 lg:grid-cols-12 ${className}`}>
      {children}
    </div>
  );
}

/**
 * One bento cell. `span` / `spanSm` are column counts against the 12/6 track;
 * `tone` picks the surface treatment.
 */
export function Tile({
  span = 4,
  spanSm = 6,
  tone = "default",
  title,
  meta,
  action,
  children,
  className = "",
  bodyClass = "",
  ...rest
}) {
  const tones = {
    default: "card",
    flat: "card-flat",
    ink: "card-ink",
    accent: "card-accent",
  };
  return (
    <section
      className={`${colSpan(span, spanSm)} ${tones[tone] ?? tones.default} flex min-w-0 flex-col overflow-hidden p-4 sm:p-5 ${className}`}
      {...rest}
    >
      {(title || action) && (
        <div className="mb-3 flex shrink-0 items-start justify-between gap-3">
          <div className="min-w-0">
            {title && (
              <p className={`eyebrow ${tone === "ink" ? "text-white/45" : ""}`}>{title}</p>
            )}
            {meta && (
              <p className={`mt-1 font-mono text-[10px] tabular-nums ${tone === "ink" ? "text-white/40" : "text-ink-4"}`}>
                {meta}
              </p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      <div className={`min-h-0 min-w-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------------ data -- */

/**
 * A KPI tile.
 *
 * The delta is the reason the tile exists — a cycle time of 19.08 h means
 * nothing on its own and everything against the 18.33 h it used to be. `invert`
 * flips which direction counts as good, because for cycle time and cost down is
 * better while for throughput up is.
 */
export function StatTile({
  label, value, unit, delta, deltaLabel, invert = false, hint, accent,
  span = 3, spanSm = 3,
}) {
  const dir = delta == null || Math.abs(delta) < 1e-9 ? 0 : delta > 0 ? 1 : -1;
  const good = invert ? dir < 0 : dir > 0;
  const tone = dir === 0 ? "text-ink-4" : good ? "text-ok" : "text-danger";

  return (
    <section
      className={`${colSpan(span, spanSm)} flex min-w-0 flex-col justify-between overflow-hidden p-4 sm:p-5 ${
        accent ? "card-accent" : "card"
      }`}
    >
      <p className="eyebrow truncate">{label}</p>
      <p className="mt-3 flex items-baseline gap-1.5">
        <span className="metric truncate text-[27px] font-bold leading-none tracking-[-0.03em] text-ink sm:text-[30px]">
          {value}
        </span>
        {unit && <span className="shrink-0 text-[12px] font-medium text-ink-3">{unit}</span>}
      </p>
      <div className="mt-2.5 flex min-h-[16px] flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] tabular-nums">
        {dir !== 0 ? (
          <span className={`inline-flex items-center gap-1 ${tone}`}>
            <Arrow up={dir > 0} />
            {deltaLabel}
          </span>
        ) : (
          deltaLabel && <span className="text-ink-4">{deltaLabel}</span>
        )}
        {hint && <span className="truncate text-ink-4">{hint}</span>}
      </div>
    </section>
  );
}

function Arrow({ up }) {
  return (
    <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden>
      <path
        d={up ? "M5 8.5V1.5M5 1.5L1.8 4.7M5 1.5l3.2 3.2" : "M5 1.5v7M5 8.5L1.8 5.3M5 8.5l3.2-3.2"}
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** A small labelled figure, for dense metric rows inside a tile. */
export function Metric({ label, value, hint, tone }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow truncate">{label}</p>
      <p className={`metric mt-1.5 truncate text-[16px] font-bold leading-none tracking-[-0.02em] ${tone ?? "text-ink"}`}>
        {value}
      </p>
      {hint && <p className="clamp-2 mt-1 text-[10.5px] leading-snug text-ink-4">{hint}</p>}
    </div>
  );
}

/* --------------------------------------------------------------- controls -- */

/** Buttons. `solid` is the one primary action on a screen; everything else is
 *  `soft`, `outline` or `ghost`. */
export function Button({
  as: As = "button", variant = "solid", size = "md", className = "", ...props
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-full font-mono uppercase " +
    "tracking-[0.14em] transition-all disabled:opacity-40 disabled:pointer-events-none " +
    "active:scale-[0.98]";
  const sizes = {
    xs: "px-2.5 py-1 text-[9px]",
    sm: "px-3 py-1.5 text-[9.5px]",
    md: "px-4 py-2.5 text-label",
    lg: "px-6 py-3 text-[11px]",
  };
  const variants = {
    solid: "bg-ink text-white hover:bg-ink/88 shadow-soft",
    accent: "bg-accent text-white hover:bg-accent-2 shadow-accent",
    soft: "bg-surface-3 text-ink hover:bg-line/10",
    outline: "border border-line/12 bg-surface text-ink hover:border-line/25 shadow-xs",
    ghost: "text-ink-3 hover:text-ink hover:bg-line/6",
    danger: "bg-danger text-white hover:bg-danger/88",
  };
  return <As className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props} />;
}

/** A segmented control. One selected value out of a short list — the run
 *  switcher, the macro-stage filter, the panel view toggle. */
export function Segmented({ items, value, onChange, className = "", size = "sm" }) {
  return (
    <div className={`segmented no-bar max-w-full overflow-x-auto ${className}`} role="tablist">
      {items.map((it) => {
        const key = it.value ?? it;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={value === key}
            data-active={value === key}
            onClick={() => onChange(key)}
            title={it.title}
            className={`segmented-item ${size === "xs" ? "px-2.5 py-1 text-[9px]" : ""}`}
          >
            {it.label ?? key}
          </button>
        );
      })}
    </div>
  );
}

/** The health band as a dot plus its word — colour is never the only channel. */
export function HealthDot({ band, label }) {
  const map = {
    green: ["bg-ok", "Healthy"],
    amber: ["bg-warn", "Strained"],
    red: ["bg-danger", "Critical"],
    grey: ["bg-ink-4", "No reference"],
  };
  const [bg, word] = map[band] ?? map.grey;
  return (
    <span className="inline-flex items-center gap-1.5" title={word}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${bg}`} />
      {label !== false && (
        <span className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-3">
          {word}
        </span>
      )}
    </span>
  );
}

/** A live indicator: a dot with an expanding ring behind it while connected. */
export function LiveDot({ on = true, className = "" }) {
  return (
    <span className={`relative inline-flex h-2 w-2 shrink-0 ${className}`}>
      {on && (
        <span
          className="absolute inset-0 animate-ping rounded-full bg-ok"
          aria-hidden
        />
      )}
      <span className={`relative h-2 w-2 rounded-full ${on ? "bg-ok" : "bg-ink-4"}`} />
    </span>
  );
}

/* ----------------------------------------------------------------- state -- */

/** A skeleton that holds the exact space its content will take, so nothing on
 *  the page jumps when the fetch lands. */
export function Skeleton({ className = "h-24" }) {
  return <div className={`animate-pulse rounded-xl bg-line/[0.055] ${className}`} />;
}

export function ErrorNote({ error, retry }) {
  return (
    <div className="card border-danger/20 bg-danger/[0.035] p-5">
      <p className="eyebrow text-danger">Could not load</p>
      <p className="mt-2 text-[14px] text-ink-2">{String(error)}</p>
      <p className="mt-3 text-[12.5px] text-ink-3">
        The backend must be running on port 8000:{" "}
        <code className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px]">
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

/** An empty box with a reason. Used wherever a tile has nothing to draw yet but
 *  must still hold its height in the grid. */
export function Empty({ children, className = "" }) {
  return (
    <div
      className={`grid h-full min-h-[80px] place-items-center rounded-xl border border-dashed border-line/12 px-4 text-center ${className}`}
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-4">
        {children}
      </p>
    </div>
  );
}

/** Formatters re-exported so a page imports its numbers and its chrome from one
 *  place rather than two. */
export { hours, money, num, pct };
