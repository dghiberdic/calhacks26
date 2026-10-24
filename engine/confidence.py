"""D6 · Confidence: one logistic model per ``Confidence.kind``, coefficients from a calibration file.

``data/calibration.json`` (fitted by eval/) wins; ``engine/default_calibration.json`` (hand-set priors) is the
fallback. A kind with no model gets ``score=None`` ("uncalibrated"). Caps are reported in ``caps`` as separate
chips and are never folded into the score.

Pure: reads only repo files; no wall clock, no randomness.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from contracts.models import Confidence

ROOT = Path(__file__).resolve().parent.parent
DATA_CALIBRATION = ROOT / "data" / "calibration.json"
DEFAULT_CALIBRATION = Path(__file__).resolve().parent / "default_calibration.json"

LABELS = {
    "cause": "cause-finding confidence",
    "voucher": "voucher-offset confidence",
    "release": "release confidence",
    "claim_validity": "claim-validity confidence",
}
MARGIN_CAP_H = 4.0
PRECEDENT_CAP = 10.0


@lru_cache(maxsize=8)
def _read(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_calibration(path: str | Path | None = None) -> dict[str, Any]:
    """Explicit path, else data/calibration.json if present and valid, else the shipped default."""
    if path is not None:
        return _read(str(path))
    if DATA_CALIBRATION.is_file():
        try:
            cal = _read(str(DATA_CALIBRATION))
            if isinstance(cal.get("models"), dict):
                return cal
        except (OSError, ValueError):
            pass
    return _read(str(DEFAULT_CALIBRATION))


def default_calibration() -> dict[str, Any]:
    return _read(str(DEFAULT_CALIBRATION))


def _model(cal: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    m = (cal.get("models") or {}).get(kind)
    if not isinstance(m, Mapping):
        return None
    feats, coef = m.get("features"), m.get("coef")
    if not isinstance(feats, list) or not isinstance(coef, list) or len(feats) != len(coef) or not feats:
        return None
    return m


def logistic(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def score(kind: str, features: Mapping[str, float], cal: Mapping[str, Any] | None = None,
          caps: list[str] | None = None) -> Confidence:
    """Score ``features`` with the ``kind`` model. Missing features read as 0."""
    cal = cal if cal is not None else load_calibration()
    version = str(cal.get("version", "uncalibrated"))
    m = _model(cal, kind)
    feats = {k: round(float(v), 4) for k, v in features.items()}
    if m is None:
        return Confidence(score=None, kind=kind, label=LABELS[kind], features=feats, caps=list(caps or []),
                          calibration_version=version)
    try:
        z = float(m.get("intercept", 0.0)) + sum(float(c) * feats.get(f, 0.0)
                                                 for f, c in zip(m["features"], m["coef"]))
    except (TypeError, ValueError):
        z = math.nan
    if not math.isfinite(z) or not all(math.isfinite(v) for v in feats.values()):
        # a NaN/inf coefficient or feature would make every score NaN, and NaN compares False to every threshold:
        # fail closed to "uncalibrated" (score None, never automatic) with a chip saying so
        return Confidence(score=None, kind=kind, label=LABELS[kind], features=feats,
                          caps=list(dict.fromkeys([*(caps or []), "capped:uncalibrated"])),
                          calibration_version=version)
    return Confidence(score=round(logistic(z), 4), kind=kind, label=LABELS[kind], features=feats,
                      caps=list(dict.fromkeys(caps or [])), calibration_version=version)


def pos(p: str) -> float:
    return 1.0 if p == "in" else 0.0


def margin_h(minutes: int | None) -> float:
    if minutes is None:
        return 0.0
    return round(min(MARGIN_CAP_H, abs(minutes) / 60), 2)


def precedents(n: float) -> float:
    return float(min(PRECEDENT_CAP, max(0.0, n)))
