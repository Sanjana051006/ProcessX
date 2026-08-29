"""The ProcessX event bus.

Publish/subscribe over one shared stream. The simulator, the six components, the
agent and the analyst all publish what they did; the dashboard, the simulation
replay and the audit trail all subscribe. No publisher knows a subscriber
exists, which is the whole point — adding a fourth consumer costs nothing on the
producing side.

    from backend.events import publish, publishers as pub

    pub.m3_anomaly(run_id, step)              # domain publisher, preferred
    publish("system.heartbeat", payload={})   # raw, for one-offs
"""

from backend.events.bus import get_bus, publish
from backend.events.schema import CATALOGUE, TOPICS, make_event, topic_of

__all__ = ["get_bus", "publish", "make_event", "CATALOGUE", "TOPICS", "topic_of"]
