import { useEffect, useRef } from "react";
import { MODULE_COLOR, stamp } from "../lib/format.js";
import { LiveDot } from "./ui.jsx";

/**
 * The event bus, made visible.
 *
 * Every row is one message that was published to the bus and delivered to this
 * browser over SSE — nothing here is polled, computed or faked. That is the
 * whole claim of the pub/sub layer, so the feed shows the producer (the module
 * badge), the event type and the summary the publisher wrote, in the order the
 * bus delivered them.
 *
 * Two modes:
 *
 * - `flow` (default) is a scrolling log that pins to the newest row. It is
 *   **height-capped by `maxHeight`**, and that cap is not optional on a page
 *   that scrolls: a live feed is unbounded (a single pipeline run publishes
 *   ~70 events, a session hundreds), so an uncapped tile grows without limit
 *   and stretches its whole bento row. It is capped to the same height as the
 *   activity table beside it and scrolls inside itself, exactly like the table.
 * - `strip` shows only the last few rows with no scrollbar at all. It goes on
 *   the simulation page, which is a fixed-viewport layout where nothing is
 *   allowed to scroll.
 */
export default function EventFeed({
  events,
  connected,
  variant = "flow",
  maxHeight,
  limit,
  onSelect,
  selectedId,
  emptyLabel = "Waiting for the first event",
}) {
  const boxRef = useRef(null);
  const pinned = useRef(true);

  const rows = limit ? events.slice(-limit) : events;

  // Follow the stream only while the reader is already at the bottom. Yanking
  // someone back down while they are reading an earlier event is the one thing
  // a live log must not do.
  //
  // This sets `scrollTop` on the feed's own box rather than calling
  // `scrollIntoView` on a sentinel. `scrollIntoView` scrolls EVERY ancestor
  // scrolling container, the document included, so on the dashboard it dragged
  // the whole page down to wherever this tile sits — landing anyone arriving
  // from another route in the middle of the page with the hero scrolled past.
  // Writing scrollTop moves this box and nothing else.
  useEffect(() => {
    if (variant !== "flow" || !pinned.current) return;
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows.length, variant]);

  function onScroll() {
    const el = boxRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }

  if (!rows.length) {
    return (
      <div className="grid h-full min-h-[80px] place-items-center rounded-xl border border-dashed border-line/12 px-4 text-center">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-4">
          <LiveDot on={connected} className="mr-2 align-middle" />
          {emptyLabel}
        </p>
      </div>
    );
  }

  return (
    <div
      ref={boxRef}
      onScroll={onScroll}
      // A visible scrollbar, unlike most scroll regions in this UI: it is the
      // only cue that there is more history above, and the table beside it
      // shows one for the same reason.
      style={variant === "flow" && maxHeight ? { maxHeight } : undefined}
      className={
        variant === "flow"
          ? "min-h-0 flex-1 overflow-y-auto"
          // Bottom-anchored: a feed that clips must clip the OLDEST rows, so
          // `justify-end` pushes the overflow off the top and the newest event
          // is always the one you can see.
          : "flex min-h-0 flex-1 flex-col justify-end overflow-hidden"
      }
    >
      <ol className="space-y-px">
        {rows.map((e) => (
          <EventRow
            key={e.event_id}
            event={e}
            onSelect={onSelect}
            selected={selectedId === e.event_id}
          />
        ))}
      </ol>
    </div>
  );
}

function EventRow({ event, onSelect, selected }) {
  const color = MODULE_COLOR[event.module] ?? "rgb(var(--ink-4))";
  const Tag = onSelect ? "button" : "div";
  return (
    <li>
      <Tag
        onClick={onSelect ? () => onSelect(event) : undefined}
        className={`animate-slidein flex w-full min-w-0 items-baseline gap-2 rounded-lg px-2 py-[5px] text-left transition-colors ${
          selected ? "bg-accent-wash" : onSelect ? "hover:bg-surface-3" : ""
        }`}
      >
        <span
          className="w-[42px] shrink-0 truncate rounded-[4px] px-1 py-px text-center font-mono text-[8.5px] font-semibold uppercase tracking-[0.08em]"
          style={{ background: `color-mix(in srgb, ${color} 13%, transparent)`, color }}
          title={event.type}
        >
          {event.module}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={`block truncate text-[11.5px] leading-snug ${
              event.severity === "warning"
                ? "text-warn"
                : event.severity === "success"
                  ? "text-ok"
                  : "text-ink-2"
            }`}
          >
            {event.summary}
          </span>
        </span>
        <span className="shrink-0 font-mono text-[8.5px] tabular-nums text-ink-4">
          {stamp(event.ts)}
        </span>
      </Tag>
    </li>
  );
}

/**
 * The bus header: connection state, backend and a live count. Small enough to
 * sit in a tile's action slot or a card's top-right corner.
 */
export function BusBadge({ connected, backend, count }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line/10 bg-surface px-2.5 py-1 shadow-xs">
      <LiveDot on={connected} />
      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-3">
        {connected ? "Live" : "Offline"}
      </span>
      {backend && (
        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">
          · {backend}
        </span>
      )}
      {count != null && (
        <span className="font-mono text-[9px] tabular-nums text-ink-4">· {count}</span>
      )}
    </span>
  );
}
