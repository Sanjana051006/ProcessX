import { useState } from "react";
import Activity from "./Activity.jsx";
import Markdown from "./Markdown.jsx";
import Logo from "../components/Logo.jsx";

/**
 * One turn.
 *
 * The user's message sits in a bubble on the right; the assistant's is
 * full-width rich text on the left with the mark beside it. The asymmetry is
 * deliberate: the reply carries tables, code and headings, and a bubble around
 * it would either clip them or become a box around the entire page.
 */
export default function Message({ role, content, steps, meta, running, error }) {
  if (role === "user") return <UserTurn content={content} />;
  return (
    <AssistantTurn
      content={content}
      steps={steps}
      meta={meta}
      running={running}
      error={error}
    />
  );
}

function UserTurn({ content }) {
  return (
    <div className="animate-rise flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-white shadow-soft">
        <p className="whitespace-pre-wrap text-[14px] leading-relaxed">{content}</p>
      </div>
    </div>
  );
}

function AssistantTurn({ content, steps, meta, running, error }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard denied — nothing worth surfacing */
    }
  }

  return (
    <div className="group animate-rise flex gap-3">
      <span className="card mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full">
        <Logo size={16} />
      </span>

      <div className="min-w-0 flex-1">
        <Activity steps={steps} running={running} />

        {error ? (
          <div className="rounded-xl border border-danger/25 bg-danger/[0.05] px-3.5 py-3">
            <p className="eyebrow text-danger">The turn failed</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{error}</p>
          </div>
        ) : content ? (
          <Markdown>{content}</Markdown>
        ) : (
          <span className="inline-block h-4 w-[7px] animate-blink rounded-sm bg-ink-4 align-middle" />
        )}

        {content && !running && (
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-4">
            <button
              onClick={copy}
              className="opacity-0 transition-opacity hover:text-ink focus:opacity-100 group-hover:opacity-100"
            >
              {copied ? "Copied" : "Copy"}
            </button>
            {meta?.elapsed != null && (
              <span className="tabular-nums">{meta.elapsed.toFixed(1)}s</span>
            )}
            {meta?.tools_used?.length > 0 && (
              <span className="tabular-nums">
                {meta.tools_used.length} tool{meta.tools_used.length === 1 ? "" : "s"}
              </span>
            )}
            {meta?.model && <span className="truncate normal-case">{meta.model}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
