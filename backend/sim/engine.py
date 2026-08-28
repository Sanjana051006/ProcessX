"""Discrete-event simulator for the NovaCart fulfilment pipeline.

Plain Python event loop (§A2 -- no SimPy). Time is in hours, t = 0 is Monday
00:00. Cases walk the 5 stages in order; at each stage they join a FIFO queue,
wait for a free server, are served for a lognormal duration, and move on.
There are no rework loops (§A10) -- queues and capacity alone produce both
bottlenecks.

Reproducibility contract (§A4): simulate(config, overrides, seed) draws the
arrival stream, every case attribute and every service-time shock from one RNG
stream that depends on the seed alone. Capacity and routing changes therefore
cannot shift the arrival stream, and a counterfactual differs from its parent
only by the intervention. That is what makes the M5 delta attributable.
"""

import heapq
import math
from collections import deque

import numpy as np
import pandas as pd

from backend.sim import config as C

# Event kinds. The priority ordering matters at equal timestamps: departures
# free a server before new arrivals compete for it, and the hourly capacity
# tick runs last. With the monotonic counter as the final tie-break the whole
# loop is deterministic.
_DEPARTURE, _ARRIVAL, _TICK = 0, 1, 2

# How long past the horizon the loop keeps running so every case that arrived
# inside the horizon reaches last_mile completion, even behind a large backlog.
_COOLDOWN_DAYS = 20


def is_weekend(t):
    return (int(t // 24) % 7) >= 5


def hour_intensity(arrivals, hour_index):
    """Relative arrival intensity for absolute hour `hour_index`, unnormalised."""
    day = (hour_index // 24) % 7
    hod = hour_index % 24
    shape = arrivals["hour_profile"][hod]
    if day >= 5:
        shape *= arrivals["weekend_multiplier"]
    return shape


def _week_grid_mean(arrivals):
    """Mean of the weekday x hour shape over a full week, used to renormalise
    the profile so the realised mean is exactly mean_per_hour."""
    return float(np.mean([hour_intensity(arrivals, h) for h in range(7 * 24)]))


def _generate_world(seed, horizon_days, arrivals):
    """Arrivals, case attributes and service shocks -- all config-independent.

    Every draw here depends only on (seed, horizon_days, arrival profile), and
    the *number* of draws never varies with stage capacity. Two runs with the
    same seed therefore see an identical world and differ only by capacity.
    """
    rng = np.random.default_rng(seed)
    hours = int(horizon_days * 24)
    norm = _week_grid_mean(arrivals)
    lam = np.array([
        arrivals["mean_per_hour"] * hour_intensity(arrivals, h) / norm
        for h in range(hours)
    ])

    counts = rng.poisson(lam)                       # exact NHPP, piecewise-constant
    n = int(counts.sum())
    within = rng.random(n)                          # uniform inside each hour bin
    times = np.repeat(np.arange(hours), counts).astype(float) + within
    times.sort(kind="stable")

    def pick(spec):
        labels = [k for k, _ in spec]
        probs = np.array([p for _, p in spec], dtype=float)
        return rng.choice(labels, size=n, p=probs / probs.sum())

    attrs = {
        "order_value": rng.lognormal(math.log(C.ORDER_VALUE_MEDIAN), C.ORDER_VALUE_SIGMA, n),
        "customer_tier": pick(C.CUSTOMER_TIERS),
        "is_new_customer": (rng.random(n) < C.NEW_CUSTOMER_RATE).astype(int),
        "fraud_risk": rng.beta(*C.FRAUD_RISK_BETA, size=n),
        "region": pick(C.REGIONS),
        "item_category": pick(C.ITEM_CATEGORIES),
    }

    # Standard-normal shock per (case, stage). Held fixed across counterfactuals
    # so a service-time intervention scales the *same* draw -- common random
    # numbers, which is what keeps the M5 confidence interval tight.
    shocks = rng.standard_normal((n, len(C.STAGES)))
    # Legacy manual-review flag at order_validation.
    flagged = rng.random(n) < C.MANUAL_REVIEW_RATE

    return times, attrs, shocks, flagged


def capacity_at(stage_cfg, t):
    """Servers available at time t. Capacity is time-varying: weekends carry
    their own headcount, and an evening shift boosts it for a block of hours."""
    base = stage_cfg["servers"]
    if is_weekend(t):
        base = stage_cfg.get("weekend_servers", base)
    boost = stage_cfg.get("shift_boost")
    if boost and int(t % 24) in boost["hours"]:
        base = int(round(base * boost["factor"]))
    return max(int(base), 0)


def _max_capacity(stage_cfg):
    base = max(stage_cfg["servers"], stage_cfg.get("weekend_servers", stage_cfg["servers"]))
    boost = stage_cfg.get("shift_boost")
    if boost:
        base = int(round(base * boost["factor"]))
    return int(base)


def simulate(config, overrides=(), seed=C.MASTER_SEED):
    """Run one world. Returns cases + events frames plus the resolved config.

    `overrides` is a sequence of catalogue action names (§A6) applied on top of
    `config` -- this is the counterfactual entry point M5 calls.
    """
    cfg = C.apply_actions(config, overrides) if overrides else config
    stage_names = C.STAGES
    n_stages = len(stage_names)
    horizon = float(cfg["horizon_days"] * 24)

    times, attrs, shocks, flagged = _generate_world(seed, cfg["horizon_days"], cfg["arrivals"])
    n = len(times)

    # A case still needs manual review unless an auto-approve rule covers it.
    ov = cfg["stages"]["order_validation"]
    needs_review = flagged.copy()
    auto = ov.get("auto_approve")
    if auto:
        covered = (attrs["order_value"] < auto["max_value"]) & (attrs["fraud_risk"] < auto["max_risk"])
        needs_review &= ~covered

    stage_cfgs = [cfg["stages"][s] for s in stage_names]
    mean_hours = [
        s["mean_service_min"] / 60.0 * s.get("service_factor", 1.0) for s in stage_cfgs
    ]
    # lognormal parameterised on its mean, so service_factor scales the mean exactly
    mus = [math.log(m) - s["sigma"] ** 2 / 2 for m, s in zip(mean_hours, stage_cfgs)]

    arrival_ts = np.full((n, n_stages), np.nan)
    start_ts = np.full((n, n_stages), np.nan)
    end_ts = np.full((n, n_stages), np.nan)
    resource = np.empty((n, n_stages), dtype=object)
    queue_len = np.zeros((n, n_stages), dtype=np.int32)
    servers_busy = np.zeros((n, n_stages), dtype=np.int32)

    queues = [deque() for _ in range(n_stages)]
    free = [list(range(1, _max_capacity(s) + 1)) for s in stage_cfgs]
    for pool in free:
        heapq.heapify(pool)
    busy = [0] * n_stages

    heap = []
    counter = 0

    def push(t, kind, si, ci=-1, sid=-1):
        nonlocal counter
        counter += 1
        heapq.heappush(heap, (t, kind, counter, si, ci, sid))

    for ci in range(n):
        push(float(times[ci]), _ARRIVAL, 0, ci)
    # Hourly capacity tick: capacity only changes on hour boundaries, so this
    # wakes a stage whose queue is waiting on a shift that has just started.
    for h in range(int(horizon) + _COOLDOWN_DAYS * 24):
        push(float(h), _TICK, -1)

    def dispatch(si, t):
        cap = capacity_at(stage_cfgs[si], t)
        q = queues[si]
        while q and busy[si] < cap:
            ci = q.popleft()
            sid = heapq.heappop(free[si])
            start_ts[ci, si] = t
            resource[ci, si] = stage_names[si] + ":r" + str(sid)
            dur = math.exp(mus[si] + stage_cfgs[si]["sigma"] * shocks[ci, si])
            busy[si] += 1
            push(t + dur, _DEPARTURE, si, ci, sid)

    while heap:
        t, kind, _, si, ci, sid = heapq.heappop(heap)

        if kind == _TICK:
            for s in range(n_stages):
                dispatch(s, t)

        elif kind == _ARRIVAL:
            arrival_ts[ci, si] = t
            queue_len[ci, si] = len(queues[si])
            servers_busy[ci, si] = busy[si]
            if si == 0 and not needs_review[ci]:
                # Auto-passes consume no reviewer and take no time (§A4).
                start_ts[ci, si] = t
                end_ts[ci, si] = t
                resource[ci, si] = "order_validation:auto"
                push(t, _ARRIVAL, 1, ci)
            else:
                queues[si].append(ci)
                dispatch(si, t)

        else:  # _DEPARTURE
            end_ts[ci, si] = t
            busy[si] -= 1
            heapq.heappush(free[si], sid)
            if si + 1 < n_stages:
                push(t, _ARRIVAL, si + 1, ci)
            dispatch(si, t)

    created = times
    cases = pd.DataFrame({
        "case_id": np.arange(n, dtype=np.int64),
        "order_value": attrs["order_value"],
        "customer_tier": attrs["customer_tier"],
        "is_new_customer": attrs["is_new_customer"],
        "fraud_risk": attrs["fraud_risk"],
        "region": attrs["region"],
        "item_category": attrs["item_category"],
        "created_ts": created,
        "weekday": ((created // 24) % 7).astype(np.int64),
        "hour": (created % 24).astype(np.int64),
        "needs_review": needs_review.astype(np.int64),
    })

    events = pd.DataFrame({
        "case_id": np.repeat(np.arange(n, dtype=np.int64), n_stages),
        "stage": np.tile(np.array(stage_names, dtype=object), n),
        "arrival_ts": arrival_ts.reshape(-1),
        "start_ts": start_ts.reshape(-1),
        "end_ts": end_ts.reshape(-1),
        "resource_id": resource.reshape(-1),
        "queue_len_at_arrival": queue_len.reshape(-1),
        "servers_busy": servers_busy.reshape(-1),
    })

    return {
        "config": cfg,
        "seed": seed,
        "overrides": list(overrides),
        "cases": cases,
        "events": events,
        "horizon_hours": horizon,
    }
