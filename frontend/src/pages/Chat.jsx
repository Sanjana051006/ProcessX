import { useCallback, useEffect, useRef, useState } from "react";
import { clearChatSession, getChatHealth, getSuggestions, streamChat } from "../api.js";
import Composer from "../chat/Composer.jsx";
import Message from "../chat/Message.jsx";
import Logo from "../components/Logo.jsx";
import { LiveDot } from "../components/ui.jsx";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";

/**
 * The analyst.
 *
 * Two layout rules, and the first one is the reason this page was rebuilt.
 *
 * 1. **An empty conversation does not scroll.** The old page laid its intro out
 *    as ordinary document flow inside a scroll container, so a fresh page with
 *    nothing in it still scrolled — which reads as broken before the user has
 *    typed a single character. Here the conversation band is a fixed grid track
 *    and the intro is centred inside it with `overflow-hidden`: it is sized to
 *    fit, so there is nothing to scroll until there are messages.
 * 2. **The page itself never scrolls, only the conversation does.** The whole
 *    screen is a `100dvh` grid — reserved navbar space, a context bar, the
 *    conversation, the composer — so messages stop cleanly at the top of their
 *    own box instead of travelling under the floating navbar, which is what a
 *    plain `overflow-y: auto` on the body would allow, translucent navbar or
 *    not.
 *
 * `100dvh` rather than `100vh`: on mobile the URL bar collapses and `vh` leaves
 * the composer under the fold.
 */
export default function Chat({ bus }) {
  const { status } = useRun();
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const pinnedRef = useRef(true);

  const health = useAsync(() => getChatHealth(), []);
  const suggestions = useAsync(() => getSuggestions(), []);

  // Follow the stream only while the reader is already at the bottom. Yanking
  // someone back down while they are reading an earlier answer is the single
  // most irritating thing a chat UI can do.
  const scrollToEnd = useCallback((smooth) => {
    const el = scrollRef.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    scrollToEnd(false);
  }, [messages, scrollToEnd]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  }

  const send = useCallback(
    (text) => {
      pinnedRef.current = true;
      setBusy(true);
      setMessages((m) => [
        ...m,
        { role: "user", content: text, at: Date.now() },
        { role: "assistant", content: "", steps: [], running: "thinking", at: Date.now() },
      ]);

      // `live` is what has streamed since the last commit point. A tool round
      // rewinds it — the model's narration before a call is not the answer, so
      // it moves into the activity strip and the bubble goes back to empty.
      let live = "";

      const patch = (fn) =>
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = fn({ ...next[next.length - 1] });
          return next;
        });

      abortRef.current = streamChat({
        message: text,
        sessionId,
        onEvent: (event, payload) => {
          if (event === "session") {
            setSessionId(payload.session_id);
          } else if (event === "token") {
            live += payload.text;
            patch((msg) => ({ ...msg, content: live, running: "responding" }));
          } else if (event === "note") {
            if (payload.rewind) live = "";
            patch((msg) => ({
              ...msg,
              content: live,
              steps: payload.text
                ? [...msg.steps, { type: "note", text: payload.text }]
                : msg.steps,
              running: "working",
            }));
          } else if (event === "tool_started") {
            patch((msg) => ({
              ...msg,
              running: `running ${payload.tool.replace(/_/g, " ")}`,
            }));
          } else if (event === "tool_finished") {
            patch((msg) => ({
              ...msg,
              steps: [...msg.steps, { ...payload, type: "tool" }],
              running: "thinking",
            }));
          } else if (event === "turn_completed") {
            live = payload.content;
            patch((msg) => ({
              ...msg,
              content: payload.content,
              steps: payload.steps ?? msg.steps,
              meta: payload.meta,
              running: null,
            }));
          } else if (event === "error") {
            patch((msg) => ({ ...msg, error: payload.message, running: null }));
          }
        },
        onError: (message) => patch((msg) => ({ ...msg, error: message, running: null })),
        onDone: () => {
          setBusy(false);
          abortRef.current = null;
          patch((msg) => ({ ...msg, running: null }));
        },
      });
    },
    [sessionId],
  );

  function stop() {
    abortRef.current?.();
    abortRef.current = null;
    setBusy(false);
  }

  async function reset() {
    stop();
    if (sessionId) await clearChatSession(sessionId).catch(() => {});
    setSessionId(null);
    setMessages([]);
  }

  const empty = messages.length === 0;
  const notConfigured = health.data && !health.data.configured;
  // The model that actually served the last turn. The gateway falls through to
  // the next candidate when a route is down, so the configured name and the
  // serving name are not always the same — and saying which one answered is
  // more honest than printing the one from the config file.
  const servedBy = [...messages].reverse().find((m) => m.meta?.model)?.meta?.model;

  return (
    <div
      className="grid overflow-hidden"
      style={{ height: "100dvh", gridTemplateRows: "var(--nav-space) auto minmax(0,1fr) auto" }}
    >
      <div aria-hidden />

      {/* ------------------------------------------------------ context bar -- */}
      <div className="mx-auto w-full max-w-3xl min-w-0 px-4 pb-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="chip">
            <LiveDot on={bus?.connected} />
            Bus {(bus?.events ?? []).length}
          </span>
          <span className="chip truncate" title="The model serving this conversation">
            {servedBy ?? health.data?.model ?? "—"}
          </span>
          <span className="chip">{health.data?.n_tools ?? 0} tools</span>
          {status?.run_id && (
            <span className="chip truncate" title={status.label}>
              reading {status.run_id}
            </span>
          )}
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="ml-auto font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-3 hover:text-ink"
            >
              New conversation
            </button>
          )}
        </div>
      </div>

      {/* ---------------------------------------------------- conversation -- */}
      {empty ? (
        // Centred and clipped: the intro is sized to the band it is given, so an
        // untouched chat page has nothing to scroll.
        <div className="min-h-0 overflow-hidden">
          <Intro
            health={health.data}
            status={status}
            suggestions={suggestions.data?.suggestions ?? []}
            onPick={send}
            disabled={notConfigured}
          />
        </div>
      ) : (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          id="main"
          className="mask-top min-h-0 overflow-y-auto"
        >
          <div className="mx-auto max-w-3xl space-y-6 px-4 pb-6 pt-2">
            {messages.map((m, i) => (
              <Message key={i} {...m} />
            ))}
          </div>
        </div>
      )}

      {/* -------------------------------------------------------- composer -- */}
      <div className="border-t border-line/8 bg-surface/80 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl px-4 py-3">
          {notConfigured && (
            <div className="mb-2.5 rounded-xl border border-warn/30 bg-warn/[0.06] px-3.5 py-2.5">
              <p className="eyebrow text-warn">Not configured</p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">
                {health.data.detail}
              </p>
            </div>
          )}

          <Composer
            onSend={send}
            onStop={stop}
            busy={busy}
            disabled={notConfigured}
            showSuggestions={false}
            suggestions={empty ? [] : (suggestions.data?.suggestions ?? [])}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * The empty state.
 *
 * It says what the agent can actually reach, because "ask me anything" over a
 * domain this specific is worse than useless. The starter questions are cards
 * rather than chips here — with the whole band to spend, a card can carry the
 * question *and* which part of the toolchain it exercises, which is what turns
 * a suggestion into an explanation of the product.
 */
function Intro({ health, status, suggestions, onPick, disabled }) {
  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col justify-center gap-6 px-4 py-2">
      <div className="animate-rise flex items-start gap-4">
        <span className="card grid h-12 w-12 shrink-0 place-items-center rounded-2xl">
          <Logo size={25} />
        </span>
        <div className="min-w-0">
          <h1 className="title-xl text-[clamp(1.6rem,3.4vw,2.2rem)]">Ask the process.</h1>
          <p className="lede mt-2 max-w-xl text-[13.5px]">
            An agent with {health?.n_tools ?? "several"} tools over the ProcessX database,
            every model in the stack, and the live event bus. It answers from real tool
            calls, and every call is shown under the reply — so you can check the working,
            not just the conclusion.
          </p>
          {status?.run_id && (
            <p className="mt-2 font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-4">
              Currently reading <span className="text-ink-2">{status.run_id}</span>
              {status.label ? ` — ${status.label}` : ""}
            </p>
          )}
        </div>
      </div>

      <div className="grid min-h-0 gap-2.5 sm:grid-cols-2">
        {suggestions.slice(0, 4).map((s, i) => (
          <button
            key={s.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s.prompt)}
            style={{ animationDelay: `${i * 55}ms` }}
            className="card-lift animate-rise group flex min-w-0 flex-col gap-1.5 p-3.5 text-left
                       disabled:pointer-events-none disabled:opacity-40"
          >
            <span className="flex items-center gap-2">
              <span className="truncate text-[13.5px] font-semibold text-ink">{s.label}</span>
              <span className="ml-auto shrink-0 text-ink-4 transition-transform group-hover:translate-x-0.5">
                →
              </span>
            </span>
            <span className="clamp-2 text-[11.5px] leading-snug text-ink-3">{s.prompt}</span>
            {s.hint && (
              <span className="mt-0.5 truncate font-mono text-[9px] uppercase tracking-[0.12em] text-accent">
                {s.hint}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="flex min-w-0 flex-wrap gap-1.5">
        {groupTools(health?.tools ?? []).map(([category, tools]) => (
          <span key={category} className="chip" title={tools.map((t) => t.name).join(", ")}>
            {CATEGORY_LABEL[category] ?? category}
            <span className="tabular-nums text-ink-4">{tools.length}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

const CATEGORY_LABEL = {
  database: "Database",
  simulation: "Simulated world",
  analysis: "Operational analytics",
  models: "Model scorecards",
  agent: "Agent · M5 · M6",
  events: "Event bus",
};

function groupTools(tools) {
  const by = new Map();
  for (const t of tools) {
    if (!by.has(t.category)) by.set(t.category, []);
    by.get(t.category).push(t);
  }
  return [...by.entries()].sort((a, b) => b[1].length - a[1].length);
}
