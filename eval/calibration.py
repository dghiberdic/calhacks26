"""One logistic calibration model per decision kind; train/test separation is explicit."""
from __future__ import annotations

import math
from typing import Any

from sklearn.linear_model import LogisticRegression

from contracts import calibration

LABEL = "calibrated on synthetic labels; validates the pipeline, not the world"


def fit_calibration(records: list[dict[str, Any]], version: str = "cal-synthetic-v1") -> dict[str, Any]:
    allowed = calibration.schema()["x-features"]
    models = {}
    for kind in calibration.KINDS:
        rows = [r for r in records if r["split"] == "train" and r["kind"] == kind]
        if not rows:
            continue
        features = allowed[kind]
        labels = [int(r["correct"]) for r in rows]
        if set(labels) != {0, 1}:
            continue  # A one-class sample cannot calibrate confidence in correctness.
        x = [[float(r["features"].get(f, 0)) for f in features] for r in rows]
        if not all(math.isfinite(value) for row in x for value in row):
            raise ValueError("Calibration features must be finite numbers")
        model = LogisticRegression(random_state=0, max_iter=2000).fit(x, labels)
        models[kind] = {
            "features": features,
            "coef": [round(float(c), 12) for c in model.coef_[0]],
            "intercept": round(float(model.intercept_[0]), 12),
            "trained_on": "2023-07-01..2024-12-31",
            "n": len(rows),
        }
    result = {"version": version, "note": LABEL, "models": models}
    errors = calibration.validate(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def reliability(records: list[dict[str, Any]], fitted: dict[str, Any]) -> tuple[dict, dict]:
    """Five equal-width held-out bins and 95% Wilson intervals, one set per fitted kind."""
    result, coverage = {}, {}
    for kind in calibration.KINDS:
        rows = [r for r in records if r["split"] == "test" and r["kind"] == kind]
        scored = [(calibration.score(fitted, kind, r["features"]), bool(r["correct"])) for r in rows]
        scored = [(p, y) for p, y in scored if p is not None]
        if kind not in fitted.get("models", {}):
            result[kind], coverage[kind] = [], 0.0
            continue
        bins = []
        for i in range(5):
            members = [(p, y) for p, y in scored if min(4, int(p * 5)) == i]
            n = len(members)
            accuracy = sum(y for _, y in members) / n if n else 0.0
            if n:
                z = 1.959963984540054
                denominator = 1 + z * z / n
                center = (accuracy + z * z / (2 * n)) / denominator
                radius = z * math.sqrt(accuracy * (1 - accuracy) / n + z * z / (4 * n * n)) / denominator
                lo, hi = max(0.0, center - radius), min(1.0, center + radius)
            else:
                lo, hi = 0.0, 1.0
            bins.append({"lo": i / 5, "hi": (i + 1) / 5, "n": n,
                         "accuracy": round(accuracy, 6), "wilson_lo": round(lo, 6), "wilson_hi": round(hi, 6)})
        result[kind] = bins
        coverage[kind] = round(sum(p >= 0.9 for p, _ in scored) / len(scored), 6) if scored else 0.0
    return result, coverage
