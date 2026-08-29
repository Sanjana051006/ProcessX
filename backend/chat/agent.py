"""The agent loop.

    while the model asks for tools:
        run them, feed the results back
    then stream the answer

Everything the UI needs to render a turn is emitted as an event: `tool_started`
and `tool_finished` drive the activity strip, `token` streams the reply,
`turn_completed` closes it. The loop is a generator, so the HTTP layer can turn
those events straight into SSE without a queue or a background task.

Sessions are in-memory and per-process. Conversation history is the product's
scope here — nothing about a chat is worth a ninth table.
"""

import time
import uuid
from collections import OrderedDict

from backend.chat import prompt as prompt_mod
from backend.chat.provider import OpenCodeProvider, ProviderError
from backend.chat.toolkit import build_registry
from backend.events import publishers as pub

# Tool rounds per turn. Three is enough for the deepest legitimate chain
# (schema -> query -> a second query to check something); past that the model is
# usually looping rather than making progress.
MAX_TOOL_ROUNDS = 6

# Turns kept per session. A turn is a user message plus everything the assistant
# said and called, so this is a real amount of context.
MAX_HISTORY_TURNS = 12

# Sessions kept in memory, oldest evicted first.
MAX_SESSIONS = 64

_SESSIONS = OrderedDict()


def _session(session_id):
    if session_id in _SESSIONS:
        _SESSIONS.move_to_end(session_id)
        return _SESSIONS[session_id]
    while len(_SESSIONS) >= MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    _SESSIONS[session_id] = {"id": session_id, "history": [], "created_at": time.time()}
    return _SESSIONS[session_id]


def history(session_id):
    """The visible transcript — what the UI reloads a conversation from."""
    return list(_session(session_id)["history"])


def reset_session(session_id):
    _SESSIONS.pop(session_id, None)


def new_session_id():
    return uuid.uuid4().hex[:16]


def _short(args, limit=90):
    text = ", ".join("%s=%s" % (k, v) for k, v in (args or {}).items()
                     if not k.startswith("_"))
    return text if len(text) <= limit else text[:limit - 1] + "…"


class ChatAgent:
    """One agent, wired to the live app state. Cheap to construct per request:
    the registry closes over `state`, and the provider holds no connection."""

    def __init__(self, state, model=None):
        self.state = state
        self.registry = build_registry(state)
        self.provider = OpenCodeProvider(model=model)

    def tool_detail(self):
        return self.registry.detail()

    # ------------------------------------------------------------------------

    def _messages(self, session, user_input):
        try:
            run_id = self.state.current_run_id()
        except Exception:
            run_id = None
        messages = [{
            "role": "system",
            "content": prompt_mod.system_prompt(run_id, self.registry.names()),
        }]
        for turn in session["history"][-MAX_HISTORY_TURNS:]:
            if turn["role"] in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_input})
        return messages

    def run(self, user_input, session_id=None):
        """Yield `(event_type, payload)` for one turn.

        Events: `session`, `tool_started`, `tool_finished`, `token`,
        `turn_completed`, `error`.
        """
        session_id = session_id or new_session_id()
        session = _session(session_id)
        started = time.time()
        yield "session", {"session_id": session_id}

        try:
            bus_run_id = self.state.current_run_id()
        except Exception:
            bus_run_id = None
        pub.chat_turn_started(session_id, bus_run_id, user_input)

        messages = self._messages(session, user_input)
        tool_defs = self.registry.definitions()
        steps, answer, first_token = [], "", None

        try:
            for round_no in range(MAX_TOOL_ROUNDS + 1):
                # The last round runs without tools: the model has spent its
                # budget and must answer from what it already has, rather than
                # asking for a call that will be refused and leaving a blank turn.
                allow_tools = round_no < MAX_TOOL_ROUNDS
                resp = None
                streamed = False
                for kind, value in self.provider.stream(
                        messages, tools=tool_defs if allow_tools else None):
                    if kind == "token":
                        if first_token is None:
                            first_token = time.time() - started
                        streamed = True
                        yield "token", {"text": value}
                    else:
                        resp = value

                if not resp.has_tool_calls:
                    text = resp.content.strip()
                    if not text:
                        # A tool-less empty response ends the turn with nothing
                        # to show. Say so rather than closing an empty bubble.
                        raise ProviderError(
                            "The model returned an empty response. Try rephrasing, or "
                            "set OPENCODE_MODEL to a model that supports tool calling.")
                    answer = text
                    break

                # Text that arrived alongside a tool call is the model narrating
                # what it is about to do — it is not the answer. It has already
                # been streamed, so `rewind` tells the UI to lift it out of the
                # bubble and into the activity strip, where it belongs.
                note = resp.content.strip()
                if note or streamed:
                    if note:
                        steps.append({"type": "note", "text": note})
                    yield "note", {"text": note, "rewind": streamed}

                messages.append({"role": "assistant", "content": resp.content or "",
                                 "tool_calls": resp.tool_calls})

                for call in resp.tool_calls:
                    yield "tool_started", {"tool": call.name, "args": call.args,
                                           "summary": _short(call.args)}
                    t0 = time.time()
                    result = self.registry.execute(call.name, call.args)
                    elapsed = time.time() - t0
                    step = {
                        "type": "tool", "tool": call.name, "args": call.args,
                        "ok": result.ok, "elapsed": elapsed,
                        "output": result.as_message_content()[:1200],
                    }
                    steps.append(step)
                    pub.chat_tool_called(session_id, bus_run_id, call.name,
                                         result.ok, elapsed, _short(call.args))
                    yield "tool_finished", {**step}
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "name": call.name,
                                     "content": result.as_message_content()})
            else:
                answer = answer or "I ran out of tool steps before I could finish that."
        except ProviderError as exc:
            yield "error", {"message": str(exc)}
            return
        except Exception as exc:  # noqa: BLE001 - the UI must see why a turn died
            yield "error", {"message": "%s: %s" % (type(exc).__name__, exc)}
            return

        now = time.time()
        meta = {"elapsed": now - started, "ttft": first_token,
                "model": self.provider.active_model(),
                "tools_used": [s["tool"] for s in steps if s["type"] == "tool"]}
        session["history"].append({"role": "user", "content": user_input, "at": started})
        session["history"].append({"role": "assistant", "content": answer, "at": now,
                                   "steps": steps, "meta": meta})
        pub.chat_turn_completed(session_id, bus_run_id, meta, answer)
        yield "turn_completed", {"content": answer, "steps": steps, "meta": meta}
