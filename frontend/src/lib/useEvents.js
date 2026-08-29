import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Subscribe to the ProcessX event bus.
 *
 * One `EventSource` per hook instance, held open for the life of the component.
 * The backend back-fills the last `replay` matching events before going live,
 * so a page that mounts mid-run draws a full timeline immediately instead of an
 * empty box that slowly fills — which is the difference between "this looks
 * broken" and "this is live".
 *
 * `EventSource` is used rather than `fetch` + a reader because this stream is a
 * plain GET with no body: the browser then reconnects it for free after a
 * network blip, with the backoff already implemented.
 */
export function useEvents({ runId, topics, types, replay = 60, limit = 400, enabled = true } = {}) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [meta, setMeta] = useState(null);
  // A ref alongside the state so a burst of events (the pipeline publishes ~60
  // in a second) is de-duplicated without waiting for a render.
  const seen = useRef(new Set());

  const reset = useCallback(() => {
    seen.current = new Set();
    setEvents([]);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    seen.current = new Set();
    setEvents([]);

    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    if (topics?.length) params.set("topics", topics.join(","));
    if (types?.length) params.set("types", types.join(","));
    params.set("replay", String(replay));

    const source = new EventSource(`/api/events/stream?${params}`);

    source.addEventListener("ready", (e) => {
      setConnected(true);
      try {
        setMeta(JSON.parse(e.data));
      } catch {
        /* the ready frame is informational; a malformed one is not fatal */
      }
    });

    source.addEventListener("event", (e) => {
      let payload;
      try {
        payload = JSON.parse(e.data);
      } catch {
        return;
      }
      if (seen.current.has(payload.event_id)) return;
      seen.current.add(payload.event_id);
      setEvents((prev) => {
        const next = [...prev, payload];
        return next.length > limit ? next.slice(next.length - limit) : next;
      });
    });

    source.onerror = () => setConnected(false);
    source.onopen = () => setConnected(true);

    return () => {
      source.close();
      setConnected(false);
    };
    // `topics`/`types` are array literals at every call site, so they are
    // joined into a stable string rather than compared by identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, topics?.join(","), types?.join(","), replay, limit, enabled]);

  return { events, connected, meta, reset };
}
