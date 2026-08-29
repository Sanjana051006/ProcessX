"""OpenCode Zen — the one LLM gateway this project talks to.

OpenCode serves the OpenAI `/v1/chat/completions` wire format, so this module is
that format and nothing else: no adapter layer, no provider registry, no
catalogue. Streaming and tool calling are both implemented here because the
agent loop needs both on every turn.

The key is read from `OPENCODE_API_KEY` and the model from `OPENCODE_MODEL` (a
`.env` at the repository root is loaded at import). The key is never logged and
never leaves this module.

One thing this provider does that a single-model client would not: it keeps an
ordered list of models and moves down it. OpenCode is a gateway in front of many
upstream providers, and an individual model can answer `models` while its
upstream is briefly returning 404 / "Model is unavailable" — a failure of that
route, not of the key or the request. Falling through to the next model turns a
dead chat page into a slightly different answer, which is the right trade for a
demo. `active_model()` always reports which one actually served the turn.
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

BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")

# The model the operator asked for. Everything else is a fallback.
DEFAULT_MODEL = os.getenv("OPENCODE_MODEL", "hy3-free")

# Tried in order when the configured model's upstream is unavailable. All three
# are free-tier routes that were verified to return well-formed OpenAI tool
# calls, which is the only capability the agent loop actually requires.
FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "OPENCODE_FALLBACK_MODELS", "hy3-free,big-pickle,mimo-v2.5-free"
    ).split(",") if m.strip()
]

# A tool round-trip carries the whole tool result back up, so the request body
# grows fast. 120 s covers a slow first token on a long context without letting
# a hung connection wedge the turn.
TIMEOUT_S = float(os.getenv("OPENCODE_TIMEOUT_S", "120"))
MAX_TOKENS = int(os.getenv("OPENCODE_MAX_TOKENS", "2048"))
TEMPERATURE = float(os.getenv("OPENCODE_TEMPERATURE", "0.2"))

PROVIDER_NAME = "opencode"


class ProviderError(RuntimeError):
    """Anything that stops a turn: no key, a transport failure, an API error."""


class ModelUnavailable(ProviderError):
    """This model's upstream is down. The next candidate may still work."""


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
    model: str = ""

    @property
    def has_tool_calls(self):
        return bool(self.tool_calls)


def api_key():
    return (os.getenv("OPENCODE_API_KEY") or "").strip()


def configured():
    return bool(api_key())


KEY_HELP = ("OPENCODE_API_KEY is not set. Put it in a .env file at the repository "
            "root as  OPENCODE_API_KEY=sk-...  and restart the backend.")


def model_candidates(preferred=None):
    """The configured model first, then the fallbacks, without duplicates."""
    ordered, seen = [], set()
    for m in [preferred or DEFAULT_MODEL, *FALLBACK_MODELS]:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


def list_models():
    """Every model the key can address. Used by the chat health preflight."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(BASE_URL + "/models",
                           headers={"Authorization": "Bearer " + api_key()})
        r.raise_for_status()
        return [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
    except Exception:
        return []


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


class OpenCodeProvider:
    """One gateway, one endpoint, an ordered list of models. `generate()` and
    `stream()` are the whole surface."""

    def __init__(self, model=None, key=None, base_url=None,
                 temperature=TEMPERATURE, max_tokens=MAX_TOKENS):
        self.models = model_candidates(model)
        self.model = self.models[0]
        self._active = None
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._key = key

    def active_model(self):
        """Whichever model actually served the last turn — the configured one
        unless it fell through."""
        return self._active or self.model

    def key(self):
        return (self._key or api_key()).strip()

    def _headers(self):
        key = self.key()
        if not key:
            raise ProviderError(KEY_HELP)
        return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def _body(self, model, messages, tools, stream):
        body = {
            "model": model,
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
            # Usage on a stream is only reported when asked for.
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

        Model fallback happens before the first byte of the body is read, so a
        turn never switches models halfway through an answer.
        """
        last_error = None
        for model in self.models:
            try:
                yield from self._stream_one(model, messages, tools)
                return
            except ModelUnavailable as exc:
                last_error = exc
                continue
        raise last_error or ProviderError("No OpenCode model could serve the turn.")

    def _stream_one(self, model, messages, tools):
        content = []
        calls = _ToolCallAccumulator()
        usage, finish = {}, ""
        try:
            with httpx.Client(timeout=TIMEOUT_S) as client:
                with client.stream("POST", self.base_url + "/chat/completions",
                                   headers=self._headers(),
                                   json=self._body(model, messages, tools, True)) as r:
                    if r.status_code >= 400:
                        _raise_for_status(r, r.read().decode("utf-8", "replace"), model)
                    self._active = model
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
            # A transport failure on the first model is worth retrying on the
            # next one: gateway routes fail independently.
            raise ModelUnavailable(
                "OpenCode stream failed on '%s': %s" % (model, exc)) from exc

        yield "done", LLMResponse(content="".join(content), tool_calls=calls.finish(),
                                  usage=usage, finish_reason=finish, model=model)

    def _generate_once(self, messages, tools):
        last_error = None
        for model in self.models:
            try:
                with httpx.Client(timeout=TIMEOUT_S) as client:
                    r = client.post(self.base_url + "/chat/completions",
                                    headers=self._headers(),
                                    json=self._body(model, messages, tools, False))
            except httpx.HTTPError as exc:
                last_error = ModelUnavailable(
                    "Could not reach OpenCode on '%s': %s" % (model, exc))
                continue
            try:
                _raise_for_status(r, r.text, model)
            except ModelUnavailable as exc:
                last_error = exc
                continue
            self._active = model
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
                model=model,
            )
        raise last_error or ProviderError("No OpenCode model could serve the turn.")

    def _generate_stream(self, messages, tools, on_token):
        response = None
        for kind, value in self.stream(messages, tools):
            if kind == "token" and on_token:
                on_token(value)
            elif kind == "done":
                response = value
        return response


# The name the rest of the app imports. Aliased rather than renamed at every
# call site so a future gateway swap is one line here.
Provider = OpenCodeProvider


def _raise_for_status(response, text, model):
    if response.status_code < 400:
        return
    detail = text
    try:
        body = json.loads(text)
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or text
        elif isinstance(body.get("message"), str):
            detail = body["message"]
    except ValueError:
        pass

    lowered = (detail or "").lower()
    # The gateway reports an upstream route failure as a 400/404/503 whose
    # message names the model rather than the request. Those are retryable on a
    # different model; a bad key or an exhausted quota is not.
    if ("unavailable" in lowered or "provider returned error" in lowered
            or "upstream request failed" in lowered or response.status_code == 503):
        raise ModelUnavailable(
            "OpenCode could not serve model '%s': %s" % (model, detail[:200]))

    if response.status_code == 401:
        if "credit" in lowered or "payment" in lowered:
            raise ProviderError(
                "OpenCode rejected model '%s': %s Free-tier models (those ending in "
                "-free, plus big-pickle) work without a payment method — set "
                "OPENCODE_MODEL to one of those." % (model, detail[:200]))
        raise ProviderError("OpenCode rejected the API key (401). Check OPENCODE_API_KEY.")
    if response.status_code == 404:
        raise ModelUnavailable(
            "OpenCode does not serve model '%s' on this key (404). %s" % (model, detail[:200]))
    if response.status_code == 429:
        raise ProviderError("OpenCode rate limit reached (429). Wait a moment and retry.")
    raise ProviderError("OpenCode error %d on '%s': %s"
                        % (response.status_code, model, detail[:400]))
