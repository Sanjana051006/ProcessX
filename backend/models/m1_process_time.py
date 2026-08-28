"""M1 -- process-time prediction.

GradientBoostingRegressor(loss="absolute_error", n_estimators=150, max_depth=3,
learning_rate=0.1, random_state=42) over the per case-stage feature set,
time-split.

The loss has to match the metric. Stage duration is queue wait plus a lognormal
service draw, so the target is heavily right-tailed; squared error chases that
tail and lands on a conditional mean that scores WORSE on MAE than simply
predicting each activity's average (-15% against the per-stage baseline).
Absolute error puts it back ahead of that baseline.

Its residuals are the point: M2 takes a stage's share of unexplained delay as
25% of its bottleneck score, and M4 takes the window-mean residual as a feature.
"""

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from backend.models import features


class M1:
    def __init__(self):
        self.model = GradientBoostingRegressor(
            loss="absolute_error", n_estimators=150, max_depth=3,
            learning_rate=0.1, random_state=42
        )
        self.columns = None
        self.metrics = {}

    def fit(self, events, cases):
        X, y, meta = features.build_m1_features(events, cases)
        self.columns = list(X.columns)
        train, test, cutoff = features.time_split(meta)

        self.model.fit(X.to_numpy()[train], y.to_numpy()[train])
        pred_test = self.model.predict(X.to_numpy()[test])
        y_test = y.to_numpy()[test]

        mae = float(np.mean(np.abs(y_test - pred_test)))
        # The headline baseline: a single global mean.
        mean_pred = float(y.to_numpy()[train].mean())
        mae_mean = float(np.mean(np.abs(y_test - mean_pred)))
        # A tougher reference: predict each stage's own training mean.
        stage_means = (
            meta.loc[train].assign(y=y.to_numpy()[train]).groupby("stage")["y"].mean()
        )
        stage_pred = meta.loc[test, "stage"].map(stage_means).to_numpy()
        mae_stage = float(np.mean(np.abs(y_test - stage_pred)))

        self.metrics = {
            "mae_hours": mae,
            "mae_mean_predictor": mae_mean,
            "improvement_vs_mean": 1.0 - mae / mae_mean,
            "mae_stage_mean_predictor": mae_stage,
            "improvement_vs_stage_mean": 1.0 - mae / mae_stage,
            "n_train": int(train.sum()),
            "n_test": int(test.sum()),
            "split_hour": cutoff,
        }
        return self

    def predict(self, events, cases):
        X, _, _ = features.build_m1_features(events, cases)
        return self.model.predict(X[self.columns].to_numpy())

    def residuals(self, events, cases):
        """actual - predicted, in hours. Positive means slower than explained."""
        X, y, _ = features.build_m1_features(events, cases)
        return y.to_numpy() - self.model.predict(X[self.columns].to_numpy())

    def metric_card(self):
        return {
            "model": "M1",
            "name": "Process-time prediction",
            "metric": "MAE vs mean-predictor",
            "value": self.metrics["improvement_vs_mean"],
            "display": "%.1f%% better than mean" % (100 * self.metrics["improvement_vs_mean"]),
            "detail": "MAE %.3f h vs %.3f h (mean) / %.3f h (per-stage mean)" % (
                self.metrics["mae_hours"], self.metrics["mae_mean_predictor"],
                self.metrics["mae_stage_mean_predictor"]),
            "target": 0.30,
            # Beating a single global mean is easy when last_mile takes 14 h and
            # closure takes 3 minutes, so the card also requires beating the
            # per-activity mean. Without that second clause a model that has
            # learnt nothing but "which activity is this" still passes.
            "pass": (self.metrics["improvement_vs_mean"] > 0.30
                     and self.metrics["improvement_vs_stage_mean"] > 0.0),
        }
