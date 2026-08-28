import { useLayoutEffect, useRef, useState } from "react";

const MAX_H = 168;

/**
 * The composer, with the starter questions sitting directly above it.
 *
 * The suggestions are a row of chips rather than a grid of cards: they are a
 * way in, not the point of the page, and a card grid would compete with the
 * conversation for attention every time it is empty. They stay available after
 * the first message — the second question is usually harder to think of than
 * the first — but collapse to a single scrollable row once the conversation has
 * started.
 */
export default function Composer({
  onSend,
  onStop,
  busy,
  suggestions = [],
  showSuggestions,
  disabled,
  placeholder = "Ask about the process, the models, or the data…",
}) {
  const [text, setText] = useState("");
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, MAX_H) + "px";
  }, [text]);

  function submit(value) {
    const message = (value ?? text).trim();
    if (!message || busy || disabled) return;
    onSend(message);
    setText("");
  }

  return (
    <div className="space-y-2.5">
      {suggestions.length > 0 && (
        <div
          className={`flex gap-2 ${
            showSuggestions ? "flex-wrap" : "overflow-x-auto pb-1 [scrollbar-width:none]"
          }`}
        >
          {suggestions.map((s) => (
            <button
              key={s.label}
              type="button"
              disabled={busy || disabled}
              onClick={() => submit(s.prompt)}
              title={s.prompt}
              className="group shrink-0 rounded-full border border-ink/16 bg-paper px-3.5 py-2 text-left
                         transition-all hover:border-ink/40 hover:bg-paper-sink/60
                         disabled:opacity-40 disabled:pointer-events-none"
            >
              <span className="flex items-center gap-2">
                <span className="text-[12.5px] font-medium text-ink-mid group-hover:text-ink">
                  {s.label}
                </span>
                {showSuggestions && s.hint && (
                  <span className="hidden font-mono text-[9px] uppercase tracking-[0.14em] text-ink-faint sm:inline">
                    {s.hint}
                  </span>
                )}
                <span className="text-ink-faint transition-transform group-hover:translate-x-0.5">
                  →
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      <div
        className={`flex items-end gap-2 rounded-2xl border bg-paper p-2 transition-colors ${
          disabled ? "border-ink/10 opacity-60" : "border-ink/16 focus-within:border-ink/45"
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
          className="max-h-[168px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[14.5px]
                     leading-relaxed outline-none placeholder:text-ink-faint"
        />

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-paper
                       transition hover:bg-ink/85"
            title="Stop"
            aria-label="Stop generating"
          >
            <span className="block h-2.5 w-2.5 rounded-[2px] bg-paper" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => submit()}
            disabled={!text.trim() || disabled}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-paper
                       transition hover:bg-ink/85 disabled:bg-ink/20 disabled:text-paper/60"
            title="Send"
            aria-label="Send message"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        )}
      </div>

      <p className="px-1 font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">
        Enter to send · Shift+Enter for a new line · answers come from live tool calls
      </p>
    </div>
  );
}
