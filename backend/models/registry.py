"""train all models, persist them, produce the four metric cards.

The registry owns the order of operations, which matters: M1 must be fitted
before M3 and M4 because both take M1's residual as a window feature.

Ground-truth separation: M1 and M3 are fitted on the runs' own event logs,
M4 on its own synthetic fault corpus. The `ground_truth` table is read in one
place only -- `metric_cards()` -- and never reaches a feature matrix.
"""

import time
from pathlib import Path

import joblib

from backend.models import features
from backend.models.m1_process_time import M1
from backend.models.m2_bottleneck import metric_card as m2_card, rank
from backend.models.m3_anomaly import M3
from backend.models.m4_cause import M4
from backend.sim import engine, scenarios

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "models.joblib"


class Registry:
    """Holds the fitted models plus the worlds they were fitted against."""

    def __init__(self):
        self.m1 = None
        self.m3 = None
        self.m4 = None
        self.cards = []
        self.timings = {}

    # ------------------------------------------------------------- training --
    def train(self, current, healthy, verbose=True):
        """`current` and `healthy` are simulate() results."""
        t = time.time()
        self.m1 = M1().fit(current["events"], current["cases"])
        self.timings["m1"] = time.time() - t
        if verbose:
            print("  M1 fitted in %.1fs -- %s" % (self.timings["m1"], self.m1.metric_card()["display"]))

        t = time.time()
        healthy_windows = self.windows(healthy)
        self.m3 = M3().fit(healthy_windows)
        self.timings["m3"] = time.time() - t
        if verbose:
            print("  M3 fitted in %.1fs on %d healthy weekday windows"
                  % (self.timings["m3"], self.m3.metrics["n_train_windows"]))

        t = time.time()
        self.m4 = M4().fit(verbose=verbose)
        self.timings["m4"] = time.time() - t
        if verbose:
            print("  M4 fitted in %.1fs on %d windows, balance %s"
                  % (self.timings["m4"], self.m4.metrics["n_train_windows"],
                     self.m4.metrics["class_balance"]))
        return self

    # ------------------------------------------------------------- scoring ---
    def windows(self, result):
        """Window features for a run, carrying M1 residuals when M1 exists."""
        residuals = None
        if self.m1 is not None:
            residuals = self.m1.residuals(result["events"], result["cases"])
        return features.build_window_features(result["events"], result["cases"], residuals)

    def ranking(self, result):
        residuals = self.m1.residuals(result["events"], result["cases"]) if self.m1 else None
        return rank(result["events"], result["cases"], result["config"],
                    result["horizon_hours"], residuals)

    def flagged_windows(self, result):
        return self.m3.flag(self.windows(result))

    # -------------------------------------------------------- metric cards ---
    def metric_cards(self, evaluation):
        """`evaluation` maps scenario name -> {result, truth_stage, truth_cause,
        injected_at}. The ONLY place ground truth is read."""
        m2_results, m3_scored, m3_extra, m4_evals = [], [], [], []

        for name, spec in evaluation.items():
            result = spec["result"]
            stage, cause = spec.get("truth_stage"), spec.get("truth_cause")
            if stage is None:
                continue
            m2_results.append((name, self.ranking(result), stage))
            flagged = self.flagged_windows(result)
            lead = self.m3.detection_lead_time(flagged, stage, spec.get("injected_at", 0.0))
            entry = (name, stage, lead)
            (m3_scored if spec.get("injected") else m3_extra).append(entry)
            m4_evals.append((name, stage, cause, flagged))

        self.cards = [
            self.m1.metric_card(),
            m2_card(m2_results),
            self.m3.metric_card(m3_scored, supplementary=m3_extra),
            self.m4.metric_card(m4_evals),
        ]
        return self.cards

    # ------------------------------------------------------------ persistence
    def save(self, path=ARTIFACT_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"m1": self.m1, "m3": self.m3, "m4": self.m4, "cards": self.cards}, path)
        return path

    @classmethod
    def load(cls, path=ARTIFACT_PATH):
        blob = joblib.load(path)
        reg = cls()
        reg.m1, reg.m3, reg.m4 = blob["m1"], blob["m3"], blob["m4"]
        reg.cards = blob.get("cards", [])
        return reg


def standard_worlds():
    """The healthy world, the demo world, and the evaluation worlds."""
    healthy = engine.simulate(scenarios.healthy_config())
    current = engine.simulate(scenarios.scenario_config(scenarios.DEMO_SCENARIO))
    others = {
        name: engine.simulate(scenarios.scenario_config(name))
        for name in scenarios.EVALUATION_SCENARIOS
        if name != scenarios.DEMO_SCENARIO
    }
    return healthy, current, others


def evaluation_spec(worlds):
    """The `metric_cards` input: every fault scenario, with its ground truth.

    A scenario is *scored* by M3 only when its fault has a real onset hour --
    otherwise the lead time measures how long the queue took to build rather
    than how long M3 took to see it.
    """
    spec = {}
    for name, result in worlds.items():
        truth = scenarios.ground_truth_for(name)
        onset = scenarios.injected_at(name)
        spec[name] = {
            "result": result,
            "truth_stage": truth["bottleneck_stage"],
            "truth_cause": truth["true_cause"],
            "injected_at": onset if onset is not None else 0.0,
            "injected": onset is not None,
        }
    return spec


def train_all(verbose=True):
    """Train on the standard worlds and score the four cards."""
    healthy, current, others = standard_worlds()
    reg = Registry().train(current, healthy, verbose=verbose)
    worlds = {scenarios.DEMO_SCENARIO: current}
    worlds.update(others)
    cards = reg.metric_cards(evaluation_spec(worlds))
    return reg, cards, (healthy, current, others)
