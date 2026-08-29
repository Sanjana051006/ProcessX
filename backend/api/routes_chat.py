"""Chat endpoints.

`POST /api/chat` streams a turn back as server-sent events. SSE rather than a
WebSocket because a turn is one request with one answer: there is nothing to
push the other way once it has started, and SSE survives a proxy that a socket
upgrade would not.
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.api.deps import get_state
from backend.chat import agent as agent_mod, provider as provider_mod
from backend.chat.prompt import SUGGESTIONS

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event, payload):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(payload, default=str))


@router.post("")
def chat(body: ChatRequest):
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    if not provider_mod.configured():
        raise HTTPException(status_code=503, detail=provider_mod.KEY_HELP)

    chat_agent = agent_mod.ChatAgent(get_state())

    def stream():
        try:
            for event, payload in chat_agent.run(body.message, body.session_id):
                yield _sse(event, payload)
        except Exception as exc:  # noqa: BLE001 - a dead stream must say why
            yield _sse("error", {"message": "%s: %s" % (type(exc).__name__, exc)})
        yield _sse("done", {})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and friends buffer SSE by default, which holds every token
            # until the turn ends and makes the stream look broken.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/suggestions")
def suggestions():
    """The starter questions the composer offers above an empty conversation."""
    return {"suggestions": SUGGESTIONS}


@router.get("/health")
def chat_health():
    """Whether the agent can run, and what it can do — the chat page's preflight."""
    state = get_state()
    configured = provider_mod.configured()
    tools = []
    if configured or state.registry is not None:
        try:
            tools = agent_mod.ChatAgent(state).tool_detail()
        except Exception:
            tools = []
    return {
        "configured": configured,
        "provider": provider_mod.PROVIDER_NAME,
        "model": provider_mod.DEFAULT_MODEL,
        "fallback_models": provider_mod.FALLBACK_MODELS,
        "base_url": provider_mod.BASE_URL,
        "n_tools": len(tools),
        "tools": tools,
        "detail": None if configured else provider_mod.KEY_HELP,
    }


@router.get("/models")
def chat_models():
    """Every model the configured key can address, and the order this provider
    will try them in. The chat page shows the active one; this is how an
    operator finds out what else is on the key."""
    if not provider_mod.configured():
        raise HTTPException(status_code=503, detail=provider_mod.KEY_HELP)
    available = provider_mod.list_models()
    return {
        "configured_model": provider_mod.DEFAULT_MODEL,
        "try_order": provider_mod.model_candidates(),
        "available": available,
        "configured_is_available": provider_mod.DEFAULT_MODEL in available,
    }


@router.get("/session/{session_id}")
def get_session(session_id: str):
    return {"session_id": session_id, "messages": agent_mod.history(session_id)}


@router.delete("/session/{session_id}")
def clear_session(session_id: str):
    agent_mod.reset_session(session_id)
    return {"session_id": session_id, "cleared": True}
