"""M3 -- anomaly detection over hourly stage windows (§A5).

IsolationForest(n_estimators=100, contamination=0.05, random_state=42), one per
stage so that last_mile's 14 h service does not swamp carrier_handover's 6 min.

Fitted on HEALTHY WEEKDAY windows only. That restriction is the finding from
P1.10 (Status §D): fixing bottleneck A restores healthy throughput rather than
exceeding it, so post-fix pick_pack is indistinguishable from the healthy
baseline's own weekend strain. A reference set built from normal weekday
operation registers both bottlenecks; one built from all healthy windows
registers neither. No ground-truth label is involved.
"""

import numpy as np
from sklearn.ensemble import IsolationForest

from backend.models import features
from backend.sim import config as C


class M3:
    def __init__(self):
        self.models = {}
        self.reference = {}
        self.metrics = {}

    def fit(self, healthy_windows):
        train = healthy_windows[
            (healthy_windows["is_weekend"] == 0) & (healthy_windows["n_arrivals"] > 0)
        ]
        for stage in C.STAGES:
            sub = train[train["stage"] == stage]
            if len(sub) < 20:
                continue
            model = IsolationForest(
                n_estimators=100, contamination=0.05, random_state=42
            )
            model.fit(sub[features.M3_FEATURES].to_numpy())
            self.models[stage] = model
            # Direction gate. An IsolationForest flags *different*, not *worse*
            # -- an intervention that makes a stage faster is just as unusual as
            # one that breaks it, and without this gate the stage we just fixed
            # trips the trigger. A window must also be bad on its own terms.
            self.reference[stage] = {
                "wait_p95": float(sub["mean_wait"].quantile(0.95)),
                "util_p95": float(sub["utilisation"].quantile(0.95)),
            }
        self.metrics["n_train_windows"] = int(len(train))
        return self

    def flag(self, windows):
        """Add `anomaly` (1/0) and `anomaly_score` to a window frame. Windows
        with no arrivals are never flagged -- an idle stage is not an anomaly."""
        out = windows.copy()
        out["anomaly"] = 0
        out["anomaly_score"] = 0.0
        for stage, model in self.models.items():
            mask = (out["stage"] == stage) & (out["n_arrivals"] > 0)
            if not mask.any():
                continue
            X = out.loc[mask, features.M3_FEATURES].to_numpy()
            unusual = model.predict(X) == -1
            ref = self.reference[stage]
            worse = (
                (out.loc[mask, "mean_wait"] > ref["wait_p95"])
                | (out.loc[mask, "utilisation"] > ref["util_p95"])
            ).to_numpy()
            out.loc[mask, "anomaly"] = (unusual & worse).astype(int)
            # Higher = more anomalous.
            out.loc[mask, "anomaly_score"] = -model.score_samples(X)
        return out

    def detection_lead_time(self, flagged, stage, injected_at, sustained=2):
        """Hours from injection to the first *sustained* anomaly at `stage`.

        A single flagged window is noise -- contamination=0.05 guarantees ~5%
        of even healthy windows trip. Requiring `sustained` consecutive flags
        is what makes this a trigger rather than a twitch.
        """
        sub = flagged[(flagged["stage"] == stage) & (flagged["window"] >= injected_at)]
        sub = sub.sort_values("window")
        flags = sub["anomaly"].to_numpy()
        windows = sub["window"].to_numpy()
        run = 0
        for i, f in enumerate(flags):
            run = run + 1 if f else 0
            if run >= sustained:
                return float(windows[i - sustained + 1] - injected_at)
        return None

    def anomalous_stages(self, flagged, since=0.0, sustained=2):
        """Stages currently tripping -- the agent's trigger list (P2.10)."""
        out = {}
        for stage in C.STAGES:
            sub = flagged[(flagged["stage"] == stage) & (flagged["window"] >= since)]
            if sub.empty:
                continue
            n = int(sub["anomaly"].sum())
            if n >= sustained:
                out[stage] = {
                    "n_anomalous_windows": n,
                    "share": float(sub["anomaly"].mean()),
                    "mean_score": float(sub.loc[sub["anomaly"] == 1, "anomaly_score"].mean()),
                }
        return out

    def metric_card(self, lead_times, supplementary=()):
        """`lead_times` is a list of (scenario_name, stage, hours_or_None).

        Only *injected* faults are scored against the 6-hour target. The cascade
        is not injected -- it emerges when weekend demand meets an unthrottled
        pipeline -- so its detection time is reported but not scored, otherwise
        the card would measure how long the fault takes to manifest rather than
        how long M3 takes to notice it.
        """
        got = [h for _, _, h in lead_times if h is not None]
        worst = max(got) if got else None
        detail = "; ".join(
            "%s/%s %s" % (n, s, ("%.0f h" % h) if h is not None else "not detected")
            for n, s, h in lead_times)
        if supplementary:
            detail += "  |  not scored: " + "; ".join(
                "%s/%s %s" % (n, s, ("%.0f h" % h) if h is not None else "not detected")
                for n, s, h in supplementary)
        return {
            "model": "M3",
            "name": "Anomaly detection",
            "metric": "detection lead time",
            "value": worst if worst is not None else float("inf"),
            "display": ("%.0f h worst case" % worst) if worst is not None else "not detected",
            "detail": detail,
            "target": 6.0,
            "pass": len(got) == len(lead_times) and worst is not None and worst < 6.0,
        }
