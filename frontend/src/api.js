/**
 * The whole backend surface in one place.
 *
 * Requests go to a relative `/api/...` path, which the Vite dev server proxies
 * to port 8000. Same-origin matters for the chat stream: an SSE response over
 * CORS is workable but fragile, and the proxy removes the question entirely.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function get(path, params) {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
      )
    : "";
  const res = await fetch(`${BASE}${path}${qs}`);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new Error(detail);
  }
  return res.json();
}

async function post(path, body, params) {
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const res = await fetch(`${BASE}${path}${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* as above */
    }
    throw new Error(detail);
  }
  return res.json();
}

/* -- read ----------------------------------------------------------------- */

export const getHealth = () => get("/api/health");
export const getRuns = () => get("/api/runs");
export const getOverview = (run_id) => get("/api/overview", { run_id });
export const getStages = (run_id) => get("/api/stages", { run_id });
export const getMacro = (run_id) => get("/api/macro", { run_id });
export const getProcessMap = () => get("/api/process-map");
export const getScenarios = () => get("/api/scenarios");
export const getCatalogue = (stage) => get("/api/catalogue", { stage });
export const getModelMetrics = () => get("/api/models/metrics");
export const getCases = (run_id, limit = 40, sort = "cycle_desc") =>
  get("/api/cases", { run_id, limit, sort });
export const getCaseJourney = (case_id, run_id) =>
  get(`/api/cases/${case_id}/journey`, { run_id });
export const getPipeline = (run_id, case_id, refresh) =>
  get("/api/pipeline", { run_id, case_id, refresh: refresh ? "true" : undefined });

/* -- write ---------------------------------------------------------------- */

export const resetRuns = (retrain = false) =>
  post("/api/runs/reset", undefined, { retrain: String(retrain) });
export const injectScenario = (scenario) =>
  post(`/api/runs/inject/${scenario}`);
export const applyIntervention = (int_id, applySelected = true) =>
  post(`/api/interventions/${int_id}/apply`, undefined, {
    apply_selected: String(applySelected),
  });

/* -- chat ----------------------------------------------------------------- */

export const getChatHealth = () => get("/api/chat/health");
export const getSuggestions = () => get("/api/chat/suggestions");
export const clearChatSession = (id) =>
  fetch(`${BASE}/api/chat/session/${id}`, { method: "DELETE" });

/**
 * Stream one chat turn.
 *
 * `EventSource` cannot POST, so the stream is read off `fetch` and the SSE
 * frames are parsed by hand. Frames are separated by a blank line and can split
 * across network chunks, so the tail of the buffer is held back until it
 * completes rather than being parsed as a short frame.
 *
 * Returns an abort function.
 */
export function streamChat({ message, sessionId, onEvent, onError, onDone }) {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionId }),
        signal: controller.signal,
      });

      if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try {
          detail = (await res.json()).detail ?? detail;
        } catch {
          /* keep the status-code message */
        }
        onError?.(detail);
        onDone?.();
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);

          let event = "message";
          const dataLines = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          try {
            onEvent?.(event, JSON.parse(dataLines.join("\n")));
          } catch {
            /* a malformed frame is dropped rather than killing the stream */
          }
        }
      }
      onDone?.();
    } catch (err) {
      if (err.name !== "AbortError") onError?.(err.message);
      onDone?.();
    }
  })();

  return () => controller.abort();
}
