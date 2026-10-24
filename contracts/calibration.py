"""Calibration files (CONTRACTS §6): validate against contracts/calibration_schema.json and score a logistic model.

The engine has its own scorer (engine/confidence.py); this is the contracts-side reference used by fakes, eval and
tests. No jsonschema dependency: the schema's rules are small enough to check by hand.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "calibration_schema.json"
DEFAULT_PATH = HERE / "calibration_default.json"
DATA_PATH = HERE.parent / "data" / "calibration.json"
KINDS = ("cause", "voucher", "release", "claim_validity")


def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(doc: Any) -> list[str]:
    """Problems with a calibration document ([] = valid)."""
    errs: list[str] = []
    if not isinstance(doc, Mapping):
        return ["not an object"]
    if not isinstance(doc.get("version"), str) or not doc.get("version"):
        errs.append("version: non-empty string required")
    models = doc.get("models")
    if not isinstance(models, Mapping):
        return errs + ["models: object required"]
    allowed = schema()["x-features"]
    for kind, m in models.items():
        if kind not in KINDS:
            errs.append(f"models.{kind}: unknown Confidence.kind")
            continue
        if not isinstance(m, Mapping):
            errs.append(f"models.{kind}: object required")
            continue
        feats, coef, icpt = m.get("features"), m.get("coef"), m.get("intercept")
        if not isinstance(feats, list) or not feats or not all(isinstance(f, str) for f in feats):
            errs.append(f"models.{kind}.features: non-empty list of strings required")
            continue
        if len(set(feats)) != len(feats):
            errs.append(f"models.{kind}.features: duplicates")
        if not isinstance(coef, list) or len(coef) != len(feats) or not all(
                isinstance(c, int | float) and not isinstance(c, bool) for c in coef):
            errs.append(f"models.{kind}.coef: one number per feature required")
        if not isinstance(icpt, int | float) or isinstance(icpt, bool):
            errs.append(f"models.{kind}.intercept: number required")
        unknown = [f for f in feats if f not in allowed[kind]]
        if unknown:
            errs.append(f"models.{kind}.features: not in calibration_schema x-features: {unknown}")
        if "n" in m and (not isinstance(m["n"], int) or m["n"] < 0):
            errs.append(f"models.{kind}.n: non-negative integer")
    return errs


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Explicit path, else data/calibration.json when present and valid, else the shipped default."""
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if DATA_PATH.is_file():
        try:
            doc = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if not validate(doc):
                return doc
        except (OSError, ValueError):
            pass
    return json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))


def score(doc: Mapping[str, Any], kind: str, features: Mapping[str, float]) -> float | None:
    """Logistic score, or None when the file has no model for `kind` (uncalibrated). Missing features read 0."""
    m = (doc.get("models") or {}).get(kind)
    if not isinstance(m, Mapping):
        return None
    z = float(m.get("intercept", 0.0)) + sum(float(c) * float(features.get(f, 0.0))
                                             for f, c in zip(m["features"], m["coef"]))
    p = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
    return round(p, 4)
