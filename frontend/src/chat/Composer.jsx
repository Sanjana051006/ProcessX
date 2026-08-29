import { useLayoutEffect, useRef, useState } from "react";

const MAX_H = 156;

/**
 * The composer.
 *
 * A rounded input surface that grows with the text up to a cap and then holds,
 * with the send control inside it rather than beside it. The suggestion row
 * above only appears once a conversation has started — before that the empty
 * state owns the starter questions and showing them twice would be noise.
 *
 * Its height is bounded on purpose: it is a fixed grid track on the chat page,
 * and an unbounded textarea would push the conversation band out of the
 * viewport as the user types.
 */
export default function Composer({
  onSend,
  onStop,
  busy,
  suggestions = [],
  disabled,
  placeholder = "Ask about the process, the models, the agent, or the event trail…",
}) {
  const [text, setText] = useState("");
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_H)}px`;
  }, [text]);

  function submit(value) {
    const message = (value ?? text).trim();
    if (!message || busy || disabled) return;
    onSend(message);
    setText("");
  }

  return (
    <div className="space-y-2">
      {suggestions.length > 0 && (
        <div className="no-bar flex gap-1.5 overflow-x-auto pb-0.5">
          {suggestions.map((s) => (
            <button
              key={s.label}
              type="button"
              disabled={busy || disabled}
              onClick={() => submit(s.prompt)}
              title={s.prompt}
              className="chip shrink-0 transition-colors hover:border-line/25 hover:text-ink
                         disabled:pointer-events-none disabled:opacity-40"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      <div
        className={`flex items-end gap-2 rounded-2xl border bg-surface p-2 shadow-soft transition-colors ${
          disabled ? "border-line/8 opacity-60" : "border-line/10 focus-within:border-accent/45"
        }`}
      >
        <textarea
          ref={ref}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          className="max-h-[156px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[14px]
                     leading-relaxed text-ink outline-none placeholder:text-ink-4"
        />

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-white transition hover:bg-ink/85"
            title="Stop"
            aria-label="Stop generating"
          >
            <span className="block h-2.5 w-2.5 rounded-[3px] bg-white" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => submit()}
            disabled={!text.trim() || disabled}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent text-white
                       shadow-accent transition hover:bg-accent-2
                       disabled:bg-line/12 disabled:text-ink-4 disabled:shadow-none"
            title="Send"
            aria-label="Send message"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        )}
      </div>

      <p className="px-1 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-4">
        Enter to send · Shift+Enter for a new line · answers come from live tool calls
      </p>
    </div>
  );
}
