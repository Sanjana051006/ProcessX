"""Make model output safe to serialise.

Ratios computed from real data legitimately produce `inf` (a group with delay
but no volume) and `nan` (an empty slice). Python's own json module writes
those as `Infinity` / `NaN`, which is not valid JSON -- Starlette refuses them
outright and returns a 500. Both become `null`, which every JSON client can
read and the dashboard can render as a dash.
"""

import math


def finite(value, default=None):
    """One float, or `default` when it is inf/-inf/nan."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def clean(obj):
    """Recursively replace non-finite floats with None."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj
