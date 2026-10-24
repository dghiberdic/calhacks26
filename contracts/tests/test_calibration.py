"""D0b: calibration_schema.json + calibration_default.json (+ the contracts-side scorer)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from contracts import calibration
from contracts.models import Confidence

ROOT = Path(__file__).resolve().parents[2]


def test_schema_lists_every_confidence_kind_and_encodes_every_feature():
    s = calibration.schema()
    kinds = set(get_args(Confidence.model_fields["kind"].annotation))
    assert set(s["x-features"]) == kinds == set(calibration.KINDS)
    assert set(s["properties"]["models"]["propertyNames"]["enum"]) == kinds
    feats = {f for fs in s["x-features"].values() for f in fs}
    assert feats <= set(s["x-encoding"]), feats - set(s["x-encoding"])
    assert s["x-features"]["cause"] == ["in_window_dep", "in_window_arr", "window_margin_h", "aog_before_window",
                                        "aog_inside_window", "root_cause_internal", "sources_disagree",
                                        "precedent_count", "knock_on"]          # CONTRACTS §6
    assert s["x-features"]["voucher"] == ["in_lieu", "signed", "sources_disagree", "precedent_count"]


def test_default_validates_and_leaves_claim_validity_uncalibrated():
    doc = json.loads(calibration.DEFAULT_PATH.read_text())
    assert calibration.validate(doc) == []
    assert "claim_validity" not in doc["models"]
    assert calibration.score(doc, "claim_validity", {}) is None


def test_engine_and_data_calibration_files_follow_the_schema():
    for p in (ROOT / "engine" / "default_calibration.json", ROOT / "data" / "calibration.json"):
        if p.is_file():
            assert calibration.validate(json.loads(p.read_text())) == [], p


def test_validate_catches_bad_files():
    assert calibration.validate({"models": {}}) == ["version: non-empty string required"]
    bad = {"version": "x", "models": {"cause": {"features": ["vibes"], "coef": [1.0, 2.0], "intercept": 0}}}
    errs = calibration.validate(bad)
    assert any("coef" in e for e in errs) and any("x-features" in e for e in errs)
    assert calibration.validate({"version": "x", "models": {"mood": {}}}) == ["models.mood: unknown Confidence.kind"]


def test_score_is_logistic():
    doc = {"version": "t", "models": {"voucher": {"features": ["in_lieu"], "coef": [0.0], "intercept": 0.0}}}
    assert calibration.score(doc, "voucher", {"in_lieu": 1.0}) == 0.5
    doc["models"]["voucher"]["intercept"] = 50.0
    assert calibration.score(doc, "voucher", {}) == 1.0
    assert calibration.load()["version"]
