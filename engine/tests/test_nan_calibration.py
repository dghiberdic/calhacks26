"""A calibration file with NaN/inf (json.loads reads those literals) must never produce an automatic decision."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from contracts.models import World
from engine.confidence import default_calibration
from engine.engine import Engine

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_calibration_fails_closed(bad):
    cal = json.loads(json.dumps(default_calibration()))
    cal["models"]["cause"]["intercept"] = bad
    w = World.model_validate_json((GOLDEN / "world.json").read_bytes())
    k = datetime.fromisoformat(w.meta["storms"]["EIDW@2025-01-24"]["known_at"].replace("Z", "+00:00"))
    d = Engine(w, calibration=cal).decide("NS31@2025-01-24", [], [], k)
    assert d.confidence.score is None and d.outcome != "auto"
