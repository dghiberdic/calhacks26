"""Acceptance: the real engine against contracts/fixtures/golden/expected/ (never edited to pass; SHA256SUMS-checked).

Decisions compare (cause, extraordinary, recoded, outcome, routed_to) exactly, recode_label where given, confidence
by band only, never the reason text. Questions match by pattern, not by id.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from contracts.models import Role, Rule, RuleAction, StormRun, World
from engine.confidence import default_calibration
from engine.engine import Engine

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
EXPECTED = GOLDEN / "expected"

REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active", support="41 of 42")


def _load(name: str):
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_bytes())


@pytest.fixture(scope="module")
def runs(world) -> dict[str, StormRun]:
    eng = Engine(world, calibration=default_calibration())
    out = {}
    for sid, m in world.meta["storms"].items():
        k = datetime.fromisoformat(m["known_at"].replace("Z", "+00:00"))
        out[sid] = eng.run_storm(world, m["station"], date.fromisoformat(m["local_date"]), [REDUCE], k)
    return out


def _band_ok(score, band) -> bool:
    """``min`` inclusive, ``max`` exclusive (e.g. ``{"max": 0.6}`` = below the ask threshold)."""
    return score is not None and band.get("min", 0.0) <= score < band.get("max", float("inf"))


def test_expected_decisions_exact(runs):
    exp = _load("decisions.json")
    fields = exp["compare"]
    problems = []
    for sid, flights in exp["storms"].items():
        got = {r.flight.id: r.decision for r in runs[sid].flights if r.decision is not None}
        assert set(got) == set(flights), sid
        for fid, want in flights.items():
            d = got[fid].model_dump(mode="json")
            for f in fields:
                if d[f] != want[f]:
                    problems.append(f"{fid}.{f}: got {d[f]!r}, want {want[f]!r}")
            if "recode_label" in want and d["recode_label"] != want["recode_label"]:
                problems.append(f"{fid}.recode_label: got {d['recode_label']!r}, want {want['recode_label']!r}")
            if not _band_ok(d["confidence"]["score"], want.get("confidence", {})):
                problems.append(f"{fid}.confidence {d['confidence']['score']} outside {want['confidence']}")
    assert problems == []


def test_expected_operated_have_no_decision(runs):
    for sid, ids in _load("decisions.json")["operated"].items():
        rows = {r.flight.id: r for r in runs[sid].flights}
        for fid in ids:
            assert fid in rows and rows[fid].decision is None and rows[fid].flight.status == "operated"


def test_expected_ns31_entitlements(world, runs):
    exp = _load("entitlements_NS31.json")
    d = next(r.decision for r in runs["EIDW@2025-01-24"].flights if r.flight.id == exp["flight_id"])
    ents = Engine(world, calibration=default_calibration()).entitlements(d, world, [REDUCE])
    by = {e.coupon_id: e for e in ents}
    s = exp["summary"]
    assert len(ents) == s["coupons"]
    assert sum(e.compensation_cents for e in ents) == s["compensation_cents"]
    counts: dict[str, int] = {}
    for e in ents:
        counts[e.status] = counts.get(e.status, 0) + 1
    assert counts == s["status_counts"]
    assert sum(1 for e in ents if e.refund_already_initiated) == s["refund_already_initiated"]
    assert sum(e.refund_due_cents for e in ents) == s["refund_due_cents"]
    assert sum(e.voucher_offset_cents for e in ents) == s["voucher_offset_cents"]
    assert {e.distance_km for e in ents} == {float(exp["distance_km"])}
    assert {e.band_margin_km for e in ents} == {float(exp["band_margin_km"])}
    for c in exp["coupons"]:
        e = by[c["coupon_id"]]
        for k in ("compensation_cents", "reduction", "status", "voucher_offset_cents", "refund_already_initiated",
                  "refund_due_cents", "care_due"):
            assert getattr(e, k) == c[k], (c["coupon_id"], k)
    no_rule = Engine(world, calibration=default_calibration()).entitlements(d, world, [])
    assert sum(e.compensation_cents for e in no_rule) == s["without_r_mined_reduce_cents"]


def test_expected_questions(runs):
    exp = _load("questions.json")
    for sid, wanted in exp["storms"].items():
        got = {q.pattern: q for q in runs[sid].questions}
        assert set(got) == {w["pattern"] for w in wanted}, sid
        for w in wanted:
            q = got[w["pattern"]]
            assert q.routed_to.value == w["routed_to"] and q.reason_tag == w["reason_tag"], w["key"]
            assert q.case_refs == w["case_refs"] and q.holds == w["holds"] and q.holds_cents == w["holds_cents"]
            assert q.confidence.kind == w["confidence_kind"]
            assert _band_ok(q.confidence.score, w["confidence"]), (w["key"], q.confidence.score)
            if "recommended_option_contains" in w:
                assert w["recommended_option_contains"] in q.recommended_option


def test_expected_golden_numbers(runs):
    g = _load("golden_numbers.json")
    r = runs["EIDW@2025-01-24"]
    assert r.counters["passengers"] == g["total_passengers"]
    assert r.counters["cancelled"] == g["cancelled"] and r.counters["operated"] == g["operated"]
    causes = [row.decision.cause.value for row in r.flights if row.decision]
    assert (causes.count("weather"), causes.count("knock_on"), causes.count("technical")) == (
        g["weather"], g["knock_on"], g["technical"])
    assert r.liability_drafted_cents == g["storm_day1_liability_cents"]
    assert r.entitlement_cents == g["ns31_entitlement_cents"]
    assert r.counters["repeat_questions"] == g["repeat_questions"]
