"""Groq provider — the one LLM this project talks to.

Groq serves the OpenAI `/v1/chat/completions` wire format, so this is that
format and nothing else: no adapter layer, no provider registry, no catalogue.
Streaming and tool calling are both implemented here because the agent loop
needs both on every turn.

The API key is read from `GROQ_API_KEY` (a `.env` at the repository root is
loaded at import). It is never logged and never leaves this module.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# A .env at the repository root, if present. Real environment variables win —
# `python-dotenv` does not override what is already set.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # pragma: no cover - dotenv is a convenience, not a requirement
    pass

BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Default model. Groq's Llama 3.3 70B is the strongest tool-calling model they
# serve at a latency that keeps a chat turn interactive; override with
# GROQ_MODEL if a different one is provisioned on the key.
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# A tool round-trip carries the whole tool result back up, so the request body
# grows fast. 120 s covers a slow first token on a long context without letting
# a hung connection wedge the turn.
TIMEOUT_S = float(os.getenv("GROQ_TIMEOUT_S", "120"))
MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "2048"))
TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))


class ProviderError(RuntimeError):
    """Anything that stops a turn: no key, a transport failure, an API error."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    finish_reason: str = ""

    @property
    def has_tool_calls(self):
        return bool(self.tool_calls)


def api_key():
    return (os.getenv("GROQ_API_KEY") or "").strip()


def configured():
    return bool(api_key())


def _parse_args(raw):
    """Tool arguments arrive as a JSON *string*. A model that emits malformed
    JSON gets told so through the tool result rather than crashing the turn."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, ValueError) as exc:
        return {"_json_error": str(exc), "_raw_args": str(raw)[:400]}


def _to_wire_messages(messages):
    """Neutral messages -> OpenAI chat format."""
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            })
        elif role == "assistant":
            # Never null: the endpoint rejects an assistant message where
            # neither content nor tool_calls is set.
            wire = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                wire["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(wire)
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _to_wire_tools(tools):
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


class _ToolCallAccumulator:
    """Streamed tool calls arrive as deltas keyed by index: the name lands in
    one chunk, the arguments dribble in across many. Collect by index and
    materialise once the stream ends."""

    def __init__(self):
        self._by_index = {}

    def feed(self, deltas):
        for d in deltas or []:
            slot = self._by_index.setdefault(
                d.get("index", 0), {"id": "", "name": "", "args": ""})
            if d.get("id"):
                slot["id"] = d["id"]
            fn = d.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finish(self):
        calls = []
        for i in sorted(self._by_index):
            slot = self._by_index[i]
            if not slot["name"]:
                continue
            calls.append(ToolCall(
                id=slot["id"] or ("call_%d_%d" % (i, int(time.time() * 1000))),
                name=slot["name"],
                args=_parse_args(slot["args"]),
            ))
        return calls


class GroqProvider:
    """One model, one endpoint. `generate()` is the whole surface."""

    def __init__(self, model=None, key=None, base_url=None,
                 temperature=TEMPERATURE, max_tokens=MAX_TOKENS):
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._key = key

    def key(self):
        return (self._key or api_key()).strip()

    def _headers(self):
        key = self.key()
        if not key:
            raise ProviderError(
                "GROQ_API_KEY is not set. Put it in a .env file at the repository "
                "root as  GROQ_API_KEY=gsk_...  and restart the backend.")
        return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def _body(self, messages, tools, stream):
        body = {
            "model": self.model,
            "messages": _to_wire_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        wire_tools = _to_wire_tools(tools)
        if wire_tools:
            body["tools"] = wire_tools
            body["tool_choice"] = "auto"
        if stream:
            # Groq only reports usage on a stream when asked to.
            body["stream_options"] = {"include_usage": True}
        return body

    # ------------------------------------------------------------ generate --

    def generate(self, messages, tools=None, stream=True, on_token=None):
        if stream:
            return self._generate_stream(messages, tools, on_token)
        return self._generate_once(messages, tools)

    def stream(self, messages, tools=None):
        """Generator form of `generate`, for a caller that is itself a generator.

        Yields `("token", text)` as the answer arrives and finally
        `("done", LLMResponse)`. The agent loop needs this shape: a callback
        cannot yield out of the generator that owns the HTTP response, so with
        `on_token` the tokens can only be flushed after the round has already
        finished — which is not streaming at all.
        """
        # Re-implemented rather than wrapped around `_generate_stream`: the wire
        # loop has to yield from inside itself.
        content = []
        calls = _ToolCallAccumulator()
        usage, finish = {}, ""
        try:
            with httpx.Client(timeout=TIMEOUT_S) as client:
                with client.stream("POST", self.base_url + "/chat/completions",
                                   headers=self._headers(),
                                   json=self._body(messages, tools, True)) as r:
                    if r.status_code >= 400:
                        _raise_for_status(r, r.read().decode("utf-8", "replace"))
                    for line in r.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                        text = delta.get("content")
                        if text:
                            content.append(text)
                            yield "token", text
                        calls.feed(delta.get("tool_calls"))
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("Groq stream failed: %s" % exc) from exc

        yield "done", LLMResponse(content="".join(content), tool_calls=calls.finish(),
                                  usage=usage, finish_reason=finish)

    def _generate_once(self, messages, tools):
        try:
            with httpx.Client(timeout=TIMEOUT_S) as client:
                r = client.post(self.base_url + "/chat/completions",
                                headers=self._headers(),
                                json=self._body(messages, tools, False))
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach Groq: %s" % exc) from exc
        _raise_for_status(r, r.text)
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=[
                ToolCall(id=tc.get("id", ""),
                         name=(tc.get("function") or {}).get("name", ""),
                         args=_parse_args((tc.get("function") or {}).get("arguments")))
                for tc in (msg.get("tool_calls") or [])
            ],
            usage=data.get("usage") or {},
            finish_reason=choice.get("finish_reason") or "",
        )

    def _generate_stream(self, messages, tools, on_token):
        content = []
        calls = _ToolCallAccumulator()
        usage, finish = {}, ""

        try:
            with httpx.Client(timeout=TIMEOUT_S) as client:
                with client.stream("POST", self.base_url + "/chat/completions",
                                   headers=self._headers(),
                                   json=self._body(messages, tools, True)) as r:
                    if r.status_code >= 400:
                        _raise_for_status(r, r.read().decode("utf-8", "replace"))
                    for line in r.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                        text = delta.get("content")
                        if text:
                            content.append(text)
                            if on_token:
                                on_token(text)
                        calls.feed(delta.get("tool_calls"))
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("Groq stream failed: %s" % exc) from exc

        return LLMResponse(content="".join(content), tool_calls=calls.finish(),
                           usage=usage, finish_reason=finish)


def _raise_for_status(response, text):
    if response.status_code < 400:
        return
    detail = text
    try:
        body = json.loads(text)
        detail = (body.get("error") or {}).get("message") or text
    except ValueError:
        pass
    if response.status_code == 401:
        raise ProviderError("Groq rejected the API key (401). Check GROQ_API_KEY.")
    if response.status_code == 404:
        raise ProviderError(
            "Groq does not serve model '%s' on this key (404). Set GROQ_MODEL to one "
            "it does. %s" % (DEFAULT_MODEL, detail))
    if response.status_code == 429:
        raise ProviderError("Groq rate limit reached (429). Wait a moment and retry.")
    raise ProviderError("Groq error %d: %s" % (response.status_code, detail[:400]))
