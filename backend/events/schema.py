"""Event contracts for the ProcessX bus.

One place that says what an event *is*, so a publisher and a subscriber cannot
disagree about the shape. Everything on the bus is a JSON-serialisable dict with
the same envelope; only `payload` varies by type.

An event is a statement of fact about something that already happened. It is
never a command, never a request, and nothing downstream is allowed to be
required for the publisher to make progress — the simulator does not care
whether a dashboard is listening.
"""

import itertools
import time
import uuid

# --------------------------------------------------------------- topics ----

# The topic is the first segment of the type. Subscribers filter on it, so it
# is deliberately coarse: five channels, not fifty.
TOPICS = ("simulation", "model", "agent", "intervention", "chat", "system")

# Every type the system publishes. A type not in here is still deliverable —
# the bus does not police it — but it will not carry a label or an icon, which
# is the practical reason to keep the table complete.
#
#   type -> (module, human label, severity)
CATALOGUE = {
    # -- the simulated world ------------------------------------------------
    "simulation.run.started":    ("SIM", "Simulation started", "info"),
    "simulation.run.completed":  ("SIM", "World generated", "info"),
    "simulation.case.sampled":   ("SIM", "Case selected", "info"),
    "simulation.stage.entered":  ("SIM", "Stage entered", "info"),
    "simulation.stage.completed": ("SIM", "Stage completed", "info"),
    "simulation.pipeline.started": ("SIM", "Pipeline started", "info"),
    "simulation.pipeline.completed": ("SIM", "Pipeline completed", "info"),

    # -- the six components -------------------------------------------------
    "model.m1.predicted":        ("M1", "Process time predicted", "info"),
    "model.m2.ranked":           ("M2", "Bottlenecks ranked", "info"),
    "model.m3.anomaly_detected": ("M3", "Anomaly detected", "warning"),
    "model.m3.clear":            ("M3", "No anomaly", "info"),
    "model.m4.cause_classified": ("M4", "Cause classified", "warning"),
    "model.m5.counterfactual_completed": ("M5", "Counterfactuals simulated", "info"),
    "model.m6.intervention_selected": ("M6", "Actions selected", "success"),

    # -- the agent ----------------------------------------------------------
    "agent.investigation.started":   ("AGENT", "Investigation started", "info"),
    "agent.probe.selected":          ("AGENT", "Probe selected", "info"),
    "agent.evidence.recorded":       ("AGENT", "Evidence recorded", "info"),
    "agent.investigation.concluded": ("AGENT", "Investigation concluded", "success"),

    # -- acting on it -------------------------------------------------------
    "intervention.applied":      ("APPLY", "Intervention applied", "success"),
    "intervention.measured":     ("APPLY", "Outcome measured", "success"),

    # -- the analyst --------------------------------------------------------
    "chat.turn.started":         ("CHAT", "Question asked", "info"),
    "chat.tool.called":          ("CHAT", "Tool called", "info"),
    "chat.turn.completed":       ("CHAT", "Answer delivered", "info"),

    # -- the bus itself -----------------------------------------------------
    "system.bus.online":         ("BUS", "Event bus online", "info"),
    "system.subscriber.joined":  ("BUS", "Subscriber joined", "info"),
    "system.heartbeat":          ("BUS", "Heartbeat", "info"),
}

# A monotonic per-process sequence. The bus stamps it so a subscriber can tell
# "I have seen everything up to N" without trusting wall-clock ordering, which
# is not reliable at sub-millisecond spacing.
_SEQ = itertools.count(1)


def topic_of(event_type):
    return str(event_type).split(".", 1)[0]


def describe(event_type):
    """`(module, label, severity)` for a type, with a usable default."""
    if event_type in CATALOGUE:
        return CATALOGUE[event_type]
    return ("SYS", str(event_type).replace(".", " ").replace("_", " "), "info")


def make_event(event_type, run_id=None, case_id=None, payload=None,
               summary=None, module=None, severity=None, inv_id=None):
    """Build one envelope. This is the only place an event is constructed."""
    default_module, label, default_severity = describe(event_type)
    return {
        "event_id": "evt_" + uuid.uuid4().hex[:12],
        "seq": next(_SEQ),
        "ts": time.time(),
        "type": event_type,
        "topic": topic_of(event_type),
        "module": module or default_module,
        "label": label,
        "severity": severity or default_severity,
        "run_id": run_id,
        "case_id": int(case_id) if case_id is not None else None,
        "inv_id": inv_id,
        "summary": summary or label,
        "payload": payload or {},
    }
