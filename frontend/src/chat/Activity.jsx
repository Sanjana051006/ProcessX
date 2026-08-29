import { useState } from "react";

/**
 * The tool activity strip under an assistant turn.
 *
 * The agent's honesty depends on this being visible. It answers from tool
 * results, and the difference between an answer grounded in a query and an
 * answer invented out of the prompt is exactly the list of calls it made — so
 * the list is shown by default, collapsed to one line per call, expandable to
 * the raw result the model actually read.
 */

const VERBS = {
  describe_schema: "Read the schema",
  query_database: "Queried the database",
  list_runs: "Listed the simulated worlds",
  get_process_map: "Read the process map",
  get_run_overview: "Pulled the run KPIs",
  get_stage_health: "Read the activity table",
  get_macro_breakdown: "Rolled up the macro-stages",
  get_bottleneck_ranking: "Ran M2's ranking",
  get_anomalies: "Checked M3's anomalies",
  get_model_metrics: "Read the model scorecards",
  get_investigation: "Ran the agent investigation",
  get_interventions: "Priced the interventions",
  get_intervention_catalogue: "Read the action catalogue",
  simulate_intervention: "Simulated a counterfactual",
  get_case_journey: "Followed a case journey",
  find_cases: "Searched the cases",
  compare_runs: "Compared two worlds",
  compare_to_baseline_rule: "Compared against the fixed rule",
  get_event_timeline: "Read the event timeline",
  get_agent_decision_trace: "Walked the decision trace",
  get_event_bus_status: "Checked the event bus",
};

const DETAIL_KEYS = ["sql", "stage", "macro_stage", "case_id", "run_id", "run_id_a", "topics", "types", "actions", "limit"];

function label(tool, args = {}) {
  const verb = VERBS[tool] ?? tool.replace(/_/g, " ");
  for (const k of DETAIL_KEYS) {
    const v = args?.[k];
    if (v === undefined || v === null || v === "") continue;
    const text = Array.isArray(v) ? v.join(" + ") : String(v);
    return { verb, detail: text.length > 70 ? `${text.slice(0, 69)}…` : text };
  }
  return { verb, detail: "" };
}

export default function Activity({ steps, running }) {
  const [openTool, setOpenTool] = useState(null);
  const tools = (steps ?? []).filter((s) => s.type === "tool");
  const notes = (steps ?? []).filter((s) => s.type === "note");
  if (!tools.length && !notes.length && !running) return null;

  return (
    <div className="mb-3 rounded-xl border border-line/8 bg-surface-2 px-2.5 py-2">
      <ol className="space-y-1">
        {(steps ?? []).map((s, i) =>
          s.type === "note" ? (
            <li key={i} className="pl-[18px] text-[11.5px] italic leading-snug text-ink-3">
              {s.text}
            </li>
          ) : (
            <li key={i}>
              <button
                type="button"
                onClick={() => setOpenTool(openTool === i ? null : i)}
                className="flex w-full min-w-0 items-baseline gap-2 rounded-md px-1 py-0.5 text-left hover:bg-surface-3"
              >
                <StatusDot ok={s.ok} />
                <span className="shrink-0 text-[11.5px] font-medium text-ink-2">
                  {label(s.tool, s.args).verb}
                </span>
                {label(s.tool, s.args).detail && (
                  <span className="truncate font-mono text-[10px] text-ink-4">
                    {label(s.tool, s.args).detail}
                  </span>
                )}
                <span className="ml-auto shrink-0 font-mono text-[9px] tabular-nums text-ink-4">
                  {s.elapsed != null ? `${s.elapsed.toFixed(1)}s` : ""}
                </span>
              </button>
              {openTool === i && (
                <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-line/8 bg-surface p-2.5 font-mono text-[10px] leading-relaxed text-ink-3">
                  {s.output || "(no output)"}
                </pre>
              )}
            </li>
          ),
        )}
        {running && (
          <li className="flex items-center gap-2 px-1">
            <span className="h-1.5 w-1.5 shrink-0 animate-blink rounded-full bg-accent" />
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-4">
              {running}
            </span>
          </li>
        )}
      </ol>
    </div>
  );
}

function StatusDot({ ok }) {
  return (
    <span
      className={`mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full ${ok === false ? "bg-danger" : "bg-ok"}`}
      title={ok === false ? "The call failed" : "The call succeeded"}
    />
  );
}
