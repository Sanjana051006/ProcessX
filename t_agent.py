"""Exercise the agent loop with a scripted provider: no network, real tools."""
import sys
from backend.api.deps import get_state
from backend.chat import agent as agent_mod
from backend.chat.provider import LLMResponse, ToolCall

class Scripted:
    """Replays a list of responses, streaming their content like Groq would."""
    def __init__(self, script):
        self.script = list(script)
        self.seen = []
    def stream(self, messages, tools=None):
        self.seen.append({"n_messages": len(messages), "tools": bool(tools)})
        resp = self.script.pop(0)
        for i in range(0, len(resp.content), 12):
            yield "token", resp.content[i:i+12]
        yield "done", resp

state = get_state()
a = agent_mod.ChatAgent(state)
a.provider = Scripted([
    LLMResponse(content="Checking the ranking.", tool_calls=[
        ToolCall(id="c1", name="get_bottleneck_ranking", args={"limit": 3})]),
    LLMResponse(content="And the investigation.", tool_calls=[
        ToolCall(id="c2", name="get_investigation", args={})]),
    LLMResponse(content="**Evidence review** is the bottleneck at p=1.00."),
])

events = list(a.run("Where is the bottleneck?", session_id="test"))
kinds = [e for e, _ in events]
print("event order:", kinds)
for kind, payload in events:
    if kind == "tool_finished":
        print("  tool %-26s ok=%s %.2fs  out=%s" % (
            payload["tool"], payload["ok"], payload["elapsed"], payload["output"][:110]))
    if kind == "note":
        print("  note rewind=%s: %r" % (payload["rewind"], payload["text"][:60]))
    if kind == "turn_completed":
        print("  final:", repr(payload["content"]))
        print("  tools_used:", payload["meta"]["tools_used"])
tokens = "".join(p["text"] for k, p in events if k == "token")
print("streamed tokens:", repr(tokens))
print("history turns:", len(agent_mod.history("test")))

# Failure path: a bad tool name must come back as an error the model can read,
# not as a dead turn.
a2 = agent_mod.ChatAgent(state)
a2.provider = Scripted([
    LLMResponse(content="", tool_calls=[ToolCall(id="x", name="nope", args={})]),
    LLMResponse(content="That tool does not exist."),
])
ev2 = list(a2.run("bad tool", session_id="t2"))
bad = [p for k, p in ev2 if k == "tool_finished"][0]
print("\nunknown tool -> ok=%s  %s" % (bad["ok"], bad["output"][:90]))

# SQL guard
from backend import analytics
for sql in ["DROP TABLE runs", "SELECT 1; DELETE FROM runs", "UPDATE runs SET label='x'"]:
    try:
        analytics.run_select(sql)
        print("LEAK:", sql)
    except ValueError as e:
        print("blocked %-34s -> %s" % (sql[:32], e))
q, rows = analytics.run_select(
    "SELECT stage, count(*) n FROM event_log WHERE run_id='claims_bottleneck' GROUP BY stage ORDER BY n DESC", limit=3)
print("select ok:", q[-40:], rows)
