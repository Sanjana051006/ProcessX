"""The bus: publish here, subscribe there, and neither side knows the other.

Two backends behind one interface.

`memory` is the default and is what the demo runs on: a bounded ring buffer plus
one queue per live subscriber. It is durable enough to replay a whole run
(events survive the subscriber, not the process) and needs nothing installed.

`redis` is the same interface over Redis Streams — XADD to publish, XREAD to
consume, XRANGE to replay. Streams rather than plain Redis Pub/Sub deliberately:
plain Pub/Sub is at-most-once, so an event published while the dashboard is
reconnecting is simply gone, and "replay the run" is the feature this bus exists
for.

Selection is by environment, and a Redis that will not connect degrades to
memory rather than taking the API down with it:

    PROCESSX_BUS=memory | redis        (default: redis if REDIS_URL is set)
    REDIS_URL=redis://localhost:6379/0
"""

import json
import os
import queue
import threading
import time

from backend.events.schema import TOPICS, make_event, topic_of

# Events held for replay. A 7-day pipeline run publishes a few hundred, so this
# is several full runs deep.
HISTORY_LIMIT = int(os.getenv("PROCESSX_BUS_HISTORY", "3000"))

# A subscriber that stops reading must not be able to grow memory without bound.
# Past this, its oldest pending events are dropped and it is told so.
SUBSCRIBER_QUEUE_LIMIT = 512

STREAM_KEY = os.getenv("PROCESSX_BUS_STREAM", "processx:events")


class Subscription:
    """One live listener. Iterate it to receive; close it when done."""

    def __init__(self, bus, run_id=None, topics=None, types=None):
        self.bus = bus
        self.run_id = run_id
        self.topics = set(topics) if topics else None
        self.types = set(types) if types else None
        self.queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_LIMIT)
        self.dropped = 0
        self.closed = False
        self.created_at = time.time()

    def matches(self, event):
        if self.run_id and event.get("run_id") not in (self.run_id, None):
            return False
        if self.topics and event.get("topic") not in self.topics:
            return False
        if self.types and event.get("type") not in self.types:
            return False
        return True

    def offer(self, event):
        """Non-blocking put. A full queue drops its oldest rather than blocking
        the publisher — a slow dashboard must never stall the simulator."""
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass
            self.dropped += 1

    def listen(self, timeout=15.0):
        """Yield events as they arrive; yield `None` on an idle timeout so the
        caller can emit an SSE keep-alive instead of letting the socket die."""
        while not self.closed:
            try:
                yield self.queue.get(timeout=timeout)
            except queue.Empty:
                yield None

    def close(self):
        self.closed = True
        self.bus.unsubscribe(self)


class MemoryBus:
    """In-process, thread-safe, replayable. The default."""

    name = "memory"

    def __init__(self, history_limit=HISTORY_LIMIT):
        self._lock = threading.RLock()
        self._history = []
        self._limit = history_limit
        self._subs = []
        self._published = 0

    # ------------------------------------------------------------ publish --
    def publish(self, event_type, **kwargs):
        event = make_event(event_type, **kwargs)
        return self.emit(event)

    def emit(self, event):
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._limit:
                del self._history[: len(self._history) - self._limit]
            self._published += 1
            targets = [s for s in self._subs if not s.closed and s.matches(event)]
        for sub in targets:
            sub.offer(event)
        return event

    # ---------------------------------------------------------- subscribe --
    def subscribe(self, run_id=None, topics=None, types=None, replay=0):
        sub = Subscription(self, run_id=run_id, topics=topics, types=types)
        with self._lock:
            self._subs.append(sub)
            backlog = self.history(run_id=run_id, topics=topics, types=types,
                                   limit=replay, _locked=True) if replay else []
        for event in backlog:
            sub.offer(event)
        return sub

    def unsubscribe(self, sub):
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    # ------------------------------------------------------------ history --
    def history(self, run_id=None, topics=None, types=None, limit=200,
                since_seq=None, _locked=False):
        def _filter(rows):
            out = []
            for e in rows:
                if run_id and e.get("run_id") not in (run_id, None):
                    continue
                if topics and e.get("topic") not in set(topics):
                    continue
                if types and e.get("type") not in set(types):
                    continue
                if since_seq is not None and e.get("seq", 0) <= since_seq:
                    continue
                out.append(e)
            return out[-limit:] if limit else out

        if _locked:
            return _filter(self._history)
        with self._lock:
            return _filter(list(self._history))

    def stats(self):
        with self._lock:
            return {
                "backend": self.name,
                "published": self._published,
                "buffered": len(self._history),
                "buffer_limit": self._limit,
                "subscribers": len([s for s in self._subs if not s.closed]),
                "topics": list(TOPICS),
                "connected": True,
                "detail": "In-process ring buffer. Replayable, no broker required.",
            }

    def clear(self):
        with self._lock:
            self._history.clear()


class RedisBus(MemoryBus):
    """Redis Streams, with the in-memory buffer kept as a local read cache.

    Subclassing MemoryBus is not laziness: local subscribers still need queue
    fan-out inside this process, and the local ring buffer keeps `history()`
    answerable when Redis is briefly unreachable. Redis is what makes the stream
    durable and shared across processes; the parent class is what makes it fast
    here.
    """

    name = "redis"

    def __init__(self, url, history_limit=HISTORY_LIMIT):
        super().__init__(history_limit=history_limit)
        import redis  # imported lazily: absent redis must not break the app

        self.url = url
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._client.ping()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._consume, daemon=True)
        self._last_id = "$"
        self._reader.start()

    def emit(self, event):
        try:
            self._client.xadd(
                STREAM_KEY,
                {"json": json.dumps(event, default=str)},
                maxlen=self._limit,
                approximate=True,
            )
        except Exception:
            # A broker outage degrades to local delivery. The alternative is
            # letting a Redis hiccup 500 the simulate endpoint, which is worse.
            pass
        return super().emit(event)

    def _consume(self):
        """Deliver events other processes published into the same stream."""
        seen = set()
        while not self._stop.is_set():
            try:
                batch = self._client.xread({STREAM_KEY: self._last_id},
                                           block=5000, count=64)
            except Exception:
                time.sleep(2.0)
                continue
            for _stream, entries in batch or []:
                for entry_id, fields in entries:
                    self._last_id = entry_id
                    try:
                        event = json.loads(fields["json"])
                    except (KeyError, ValueError):
                        continue
                    # Our own emit() already delivered it locally.
                    if event["event_id"] in seen:
                        continue
                    seen.add(event["event_id"])
                    if len(seen) > 4096:
                        seen = set(list(seen)[-2048:])
                    with self._lock:
                        mine = any(e["event_id"] == event["event_id"]
                                   for e in self._history[-256:])
                    if not mine:
                        super().emit(event)

    def stats(self):
        base = super().stats()
        try:
            length = self._client.xlen(STREAM_KEY)
            connected = True
        except Exception:
            length, connected = 0, False
        base.update({
            "backend": self.name, "url": self.url, "stream": STREAM_KEY,
            "stream_length": length, "connected": connected,
            "detail": "Redis Streams — durable, replayable, shared across processes.",
        })
        return base


# ------------------------------------------------------------- singleton ----

_BUS = None
_BUS_LOCK = threading.Lock()


def _build():
    choice = (os.getenv("PROCESSX_BUS") or "").strip().lower()
    url = os.getenv("REDIS_URL", "").strip()
    if choice == "memory":
        return MemoryBus()
    if choice == "redis" or (not choice and url):
        try:
            return RedisBus(url or "redis://localhost:6379/0")
        except Exception:
            # Named explicitly and still unreachable: the demo continues on the
            # in-process bus rather than failing to boot.
            return MemoryBus()
    return MemoryBus()


def get_bus():
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = _build()
                _BUS.publish("system.bus.online",
                             summary="%s event bus online" % _BUS.name,
                             payload={"backend": _BUS.name, "topics": list(TOPICS)})
    return _BUS


def publish(event_type, **kwargs):
    """Module-level shorthand. Never raises — a broken bus must not be able to
    break the thing it is observing."""
    try:
        return get_bus().publish(event_type, **kwargs)
    except Exception:
        return None


__all__ = ["MemoryBus", "RedisBus", "Subscription", "get_bus", "publish",
           "topic_of", "TOPICS"]
