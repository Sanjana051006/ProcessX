import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { clearChatSession, getChatHealth, getSuggestions, streamChat } from "../api.js";
import Composer from "../chat/Composer.jsx";
import Message from "../chat/Message.jsx";
import Logo from "../components/Logo.jsx";
import { Button, Eyebrow } from "../components/ui.jsx";
import { useRun } from "../lib/runContext.js";
import { useAsync } from "../lib/useAsync.js";

/**
 * The analyst.
 *
 * Layout rule that matters most here: the page itself never scrolls. It is a
 * fixed-height column — a reserved band for the floating navbar, then a scroll
 * region, then the composer — so the conversation scrolls *inside* its own box
 * and stops cleanly at the top of that box. Messages therefore never travel
 * behind the capsule, which is what a plain `overflow-y: auto` on the body
 * would let them do, translucent navbar or not.
 *
 * `100dvh` rather than `100vh`: on mobile the URL bar collapses and `vh` leaves
 * the composer under the fold.
 */
export default function Chat() {
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

  return (
    <div
      className="grid overflow-hidden"
      style={{ height: "100dvh", gridTemplateRows: "var(--nav-space) 1fr auto" }}
    >
      {/* The band the floating navbar occupies. Nothing renders here — it is
          reserved space, which is what keeps the conversation out from under
          the capsule. */}
      <div aria-hidden />

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="mask-top min-h-0 overflow-y-auto"
      >
        <div className="mx-auto max-w-3xl px-4 pb-6">
          {empty ? (
            <Intro health={health.data} status={status} />
          ) : (
            <div className="space-y-7 pt-2">
              {messages.map((m, i) => (
                <Message key={i} {...m} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-ink/10 bg-paper/95 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl px-4 py-3">
          {notConfigured && (
            <div className="mb-3 rounded-lg border border-band-amber/35 bg-band-amber/[0.07] px-3.5 py-2.5">
              <p className="eyebrow text-band-amber">Not configured</p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-mid">
                {health.data.detail}
              </p>
            </div>
          )}

          <Composer
            onSend={send}
            onStop={stop}
            busy={busy}
            disabled={notConfigured}
            showSuggestions={empty}
            suggestions={suggestions.data?.suggestions ?? []}
          />

          <div className="mt-2 flex items-center gap-3 font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">
            <span>
              {health.data?.model ?? "—"} · {health.data?.n_tools ?? 0} tools
            </span>
            {status?.run_id && <span>· reading {status.run_id}</span>}
            {messages.length > 0 && (
              <button onClick={reset} className="ml-auto hover:text-ink">
                New conversation
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The empty state. It says what the agent can actually reach, because "ask me
 *  anything" over a domain this specific is worse than useless. */
function Intro({ health, status }) {
  const groups = groupTools(health?.tools ?? []);
  return (
    <div className="animate-rise pt-6">
      <div className="flex items-center gap-3">
        <Eyebrow>The analyst</Eyebrow>
        <span className="h-px flex-1 bg-ink/14" />
      </div>

      <div className="mt-7 flex items-start gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-ink/12 bg-paper-sink/50">
          <Logo size={26} />
        </span>
        <div className="min-w-0">
          <h1 className="text-[clamp(1.7rem,4vw,2.4rem)] font-black uppercase leading-[0.95] tracking-[-0.035em]">
            Ask the process.
          </h1>
          <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-ink-mid">
            An agent with {health?.n_tools ?? "several"} tools over the ProcessX database
            and every model in the stack. It answers from live tool calls, and every call
            it makes is shown under the reply — so you can check the working, not just the
            conclusion.
          </p>
          {status?.run_id && (
            <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
              Currently reading <span className="text-ink-mid">{status.run_id}</span> —{" "}
              {status.label}
            </p>
          )}
        </div>
      </div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {groups.map(([category, tools]) => (
          <div key={category} className="panel p-4">
            <p className="eyebrow mb-2.5">{CATEGORY_LABEL[category] ?? category}</p>
            <ul className="space-y-1">
              {tools.map((t) => (
                <li key={t.name} className="font-mono text-[10.5px] text-ink-light">
                  {t.name}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        <Button as={Link} to="/" variant="outline" size="sm">
          ← Dashboard
        </Button>
        <Button as={Link} to="/simulation" variant="outline" size="sm">
          Simulation panel
        </Button>
      </div>
    </div>
  );
}

const CATEGORY_LABEL = {
  database: "Straight at the database",
  simulation: "The simulated world",
  analysis: "Operational analytics",
  models: "Model scorecards",
  agent: "The agent, M5 and M6",
};

function groupTools(tools) {
  const by = new Map();
  for (const t of tools) {
    if (!by.has(t.category)) by.set(t.category, []);
    by.get(t.category).push(t);
  }
  return [...by.entries()].sort((a, b) => b[1].length - a[1].length);
}
