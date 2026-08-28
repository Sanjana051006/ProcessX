"""M1 -- process-time prediction (§A5).

GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.1,
random_state=42) over the per case-stage feature set, time-split.

Its residuals are the point: M2 takes a stage's share of unexplained delay as
25% of its bottleneck score, and M4 takes the window-mean residual as a feature.
"""

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from backend.models import features


class M1:
    def __init__(self):
        self.model = GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.1, random_state=42
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
        # The metric §A5 names: a single global mean.
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
            "pass": self.metrics["improvement_vs_mean"] > 0.30,
        }
