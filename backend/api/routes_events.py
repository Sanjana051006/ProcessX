"""The event bus, exposed to the browser.

`GET /api/events/stream` is the live tap: one long-lived SSE response per
subscriber, fed straight off the bus. SSE rather than a WebSocket because the
traffic is entirely one-way — the browser never pushes an event back — and SSE
reconnects itself, survives proxies, and needs no framing library.

Every other endpoint here is a read over the same buffer: replay for the
simulation panel, a filtered slice for the audit trail, and the counters the
"Live" indicator in the navbar shows.
"""

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.events import CATALOGUE, TOPICS, get_bus
from backend.jsonsafe import clean

router = APIRouter(prefix="/api/events", tags=["events"])

# Idle gap after which a comment frame is written to keep the connection alive.
KEEPALIVE_S = 15.0


def _frame(event, payload):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(payload, default=str))


def _split(value):
    return [p for p in (value or "").split(",") if p.strip()] or None


@router.get("/stream")
async def stream(request: Request, run_id: str = None, topics: str = None,
                 types: str = None, replay: int = 40):
    """Subscribe. `replay` back-fills the last N matching events before going live,
    so a page that opens mid-run still draws a timeline instead of a blank box."""
    bus = get_bus()
    sub = bus.subscribe(run_id=run_id, topics=_split(topics), types=_split(types),
                        replay=max(0, min(replay, 400)))

    def generate():
        try:
            yield _frame("ready", {
                "backend": bus.stats().get("backend"),
                "run_id": run_id,
                "replayed": max(0, min(replay, 400)),
                "at": time.time(),
            })
            for event in sub.listen(timeout=KEEPALIVE_S):
                if event is None:
                    # A comment frame: keeps proxies and the browser from
                    # deciding a quiet stream is a dead one.
                    yield ": keep-alive\n\n"
                    continue
                yield _frame("event", clean(event))
        finally:
            sub.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("")
def history(run_id: str = None, topics: str = None, types: str = None,
            limit: int = 200, since_seq: int = None):
    """The replay buffer. This is what Forward/Backward on the simulation page
    steps through, and what the audit panel lists."""
    bus = get_bus()
    events = bus.history(run_id=run_id, topics=_split(topics), types=_split(types),
                         limit=max(1, min(limit, 1000)), since_seq=since_seq)
    return clean({
        "run_id": run_id,
        "n": len(events),
        "events": events,
        "latest_seq": events[-1]["seq"] if events else (since_seq or 0),
    })


@router.get("/stats")
def stats():
    """What the Live indicator reads: backend, counters, subscriber count."""
    return clean(get_bus().stats())


@router.get("/catalogue")
def catalogue():
    """Every type the system can publish, with its module and severity. The
    architecture panel renders publishers and subscribers from this."""
    return {
        "topics": list(TOPICS),
        "types": [
            {"type": t, "topic": t.split(".", 1)[0], "module": module,
             "label": label, "severity": severity}
            for t, (module, label, severity) in sorted(CATALOGUE.items())
        ],
    }
