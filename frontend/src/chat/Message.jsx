import { useState } from "react";
import Activity from "./Activity.jsx";
import Markdown from "./Markdown.jsx";
import Logo from "../components/Logo.jsx";

/**
 * One turn.
 *
 * The user's message sits in a bubble on the right; the assistant's is
 * full-width rich text on the left with the mark beside it — the same
 * asymmetry the Namma Agent UI uses, and for the same reason: the reply carries
 * tables, code and headings, and a bubble would either clip them or become a
 * box around the entire page.
 */
export default function Message({ role, content, at, steps, meta, running, error }) {
  if (role === "user") return <UserTurn content={content} at={at} />;
  return (
    <AssistantTurn
      content={content}
      at={at}
      steps={steps}
      meta={meta}
      running={running}
      error={error}
    />
  );
}

function UserTurn({ content }) {
  return (
    <div className="flex justify-end animate-rise">
      <div className="max-w-[82%] rounded-2xl rounded-br-md border border-ink/14 bg-paper-sink/70 px-4 py-2.5">
        <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed">{content}</p>
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
    <div className="group flex gap-3 animate-rise">
      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border border-ink/12 bg-paper">
        <Logo size={17} />
      </span>

      <div className="min-w-0 flex-1">
        <Activity steps={steps} running={running} />

        {error ? (
          <div className="rounded-lg border border-red/30 bg-red/[0.06] px-3.5 py-3">
            <p className="eyebrow text-red">The turn failed</p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-mid">{error}</p>
          </div>
        ) : content ? (
          <Markdown>{content}</Markdown>
        ) : (
          <span className="inline-block h-4 w-[7px] animate-blink rounded-sm bg-ink-faint align-middle" />
        )}

        {content && !running && (
          <div className="mt-2.5 flex items-center gap-3 font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-faint">
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
          </div>
        )}
      </div>
    </div>
  );
}
