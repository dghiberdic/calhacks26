"""D6 · confidence (logistic per kind, caps apart), thresholds + materiality, routing table, grouping, reminders,
and challenges (route, never flip)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import Confidence, Extraordinary, Fact, Role, World
from engine import confidence as conf
from engine import routing
from engine.challenge import challenge
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.questions import remind_at, status_at

from . import mini_world as mw

KNOWN = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden" / "world.json"


def c(score: float | None, kind="cause") -> Confidence:
    return Confidence(score=score, kind=kind, label="x", features={}, calibration_version="t")


# ---------- confidence ----------

def test_logistic_from_calibration():
    cal = {"version": "t1", "models": {"cause": {"features": ["a", "b"], "coef": [2.0, -1.0], "intercept": 0.5}}}
    got = conf.score("cause", {"a": 1.0, "b": 0.5}, cal)
    assert got.score == pytest.approx(conf.logistic(0.5 + 2.0 - 0.5), abs=1e-4)
    assert got.calibration_version == "t1" and got.label == "cause-finding confidence"


def test_no_model_is_uncalibrated():
    got = conf.score("claim_validity", {"x": 1.0}, default_calibration())
    assert got.score is None and got.kind == "claim_validity"
    bad = {"version": "t", "models": {"cause": {"features": ["a"], "coef": [1.0, 2.0]}}}   # length mismatch
    assert conf.score("cause", {"a": 1}, bad).score is None


def test_caps_never_folded_into_score():
    feats = {"in_window_dep": 1.0, "window_margin_h": 2.0}
    plain = conf.score("cause", feats, default_calibration())
    capped = conf.score("cause", feats, default_calibration(), caps=["capped:sources-disagree"])
    assert plain.score == capped.score and capped.caps == ["capped:sources-disagree"]


def test_calibration_file_override(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"version": "cal-test", "models": {
        "cause": {"features": ["knock_on"], "coef": [5.0], "intercept": 0.0}}}))
    cal = conf.load_calibration(p)
    assert conf.score("cause", {"knock_on": 1.0}, cal).score > 0.99
    assert conf.score("voucher", {}, cal).score is None              # that file has no voucher model


@settings(max_examples=50, deadline=None)
@given(st.dictionaries(st.sampled_from(["in_window_dep", "in_window_arr", "window_margin_h", "aog_before_window",
                                        "aog_inside_window", "root_cause_internal", "sources_disagree",
                                        "precedent_count", "knock_on"]),
                       st.floats(min_value=0, max_value=10, allow_nan=False)))
def test_scores_are_probabilities(feats):
    s = conf.score("cause", feats, default_calibration()).score
    assert 0.0 <= s <= 1.0


# ---------- thresholds and materiality ----------

@pytest.mark.parametrize("score,liability,outcome,role", [
    (0.95, 0, "auto", None),
    (0.95, 4_999_999, "auto", None),
    (0.95, 5_000_000, "human", Role.CONTROLLER),          # materiality gate: < €50k AND >= 0.90
    (0.90, 0, "auto", None),
    (0.8999, 0, "human", Role.OPS),                        # batch review
    (0.60, 0, "human", Role.OPS),
    (0.5999, 0, "escalated", Role.OPS),
    (None, 0, "human", Role.OPS),                          # uncalibrated: a person reviews
])
def test_thresholds(score, liability, outcome, role):
    r = routing.route(extraordinary=Extraordinary.NO, confidence=c(score), pattern="technical_internal",
                      liability_cents=liability)
    assert (r.outcome, r.routed_to) == (outcome, role)


def test_needs_legal_always_escalates():
    r = routing.route(extraordinary=Extraordinary.NEEDS_LEGAL, confidence=c(0.99), pattern="knock_on_return")
    assert (r.outcome, r.routed_to) == ("escalated", Role.LEGAL)


@pytest.mark.parametrize("pattern,role", [
    ("knock_on_return", Role.LEGAL), ("concurrent_causes", Role.LEGAL), ("new_legal_pattern", Role.LEGAL),
    ("voucher_in_lieu_unsigned", Role.CLAIMS_LEAD), ("claim_dispute", Role.CLAIMS_LEAD),
    ("cohort_release", Role.CONTROLLER), ("change_in_estimate", Role.CONTROLLER),
    ("window_unknown", Role.OPS), ("weather_code_contradicted", Role.OPS), ("cause_unknown", Role.OPS),
])
def test_routing_table(pattern, role):
    assert routing.role_for(pattern) == role


def test_large_technical_flight_hits_materiality():
    b = mw.Builder()
    b.metar["EIDW@2025-01-24"] = mw.load_iem_csv(mw.EOWYN_CSV)
    f = b.add_flight(mw.flight("NS21", "DUB", "JFK", mw.z("16:40"), mw.z("23:55"), 268, "EI-NWA"))
    b.add_coupons(f, [(268, "reaccommodated_own", {"delay": 1500})])
    b.tech_log.append(mw.TechLogEntry(id="TL-1", aircraft="EI-NWA", logged_at=mw.z("21:00", 23), station="DUB",
                                      ata="2913", text="EDP LEAK EXCEEDS AMM LIMIT. NO MEL RELIEF. A/C AOG.",
                                      mel_relief=False, aog=True))
    w = b.world()
    d = Engine(w, calibration=default_calibration()).decide_in(w, f.id, [], KNOWN)
    assert d.cause.value == "technical" and d.confidence.score >= 0.90
    assert (d.outcome, d.routed_to) == ("human", Role.CONTROLLER)          # 268 × €600 × 35% = €56,280


# ---------- grouping and reminders ----------

def test_one_question_per_pattern_and_storm():
    def second_knock_on(w: World):
        ns116 = next(f for f in w.flights if f.number == "NS116")
        w.flights.append(ns116.model_copy(update={"id": "NS119@2025-01-24", "number": "NS119", "origin": "MUC",
                                                  "dest": "DUB", "sched_dep": mw.z("14:30"),
                                                  "sched_arr": mw.z("16:45"), "outbound_pair_id": ns116.id,
                                                  "inbound_flight_id": ns116.id}))
    w = mw.build()
    second_knock_on(w)
    from datetime import date
    run = Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 24), [], KNOWN)
    ko = [q for q in run.questions if q.pattern == "knock_on_return"]
    assert len(ko) == 1 and ko[0].case_refs == ["NS117@2025-01-24", "NS119@2025-01-24"]
    assert ko[0].holds == ko[0].case_refs


def test_reminder_three_hours_by_clock():
    w = mw.build()
    from datetime import date
    run = Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 24), [], KNOWN)
    q = run.questions[0]
    assert q.remind_at == remind_at(q.asked_at) == q.asked_at + timedelta(hours=3)
    assert status_at(q, KNOWN + timedelta(hours=2, minutes=59)) == "open"
    assert status_at(q, KNOWN + timedelta(hours=3)) == "reminded"
    assert status_at(q, KNOWN + timedelta(hours=5), answered=True) == "answered"


# ---------- challenges (golden world) ----------

@pytest.fixture(scope="module")
def golden() -> World:
    return World.model_validate_json(GOLDEN.read_bytes())


def _ns31(golden: World):
    return Engine(golden, calibration=default_calibration()).decide_in(golden, "NS31@2025-01-24", [], KNOWN)


def test_challenge_assertion_decision_stands(golden):
    d = _ns31(golden)
    v = challenge(golden, d, "assertion", [], KNOWN, default_calibration())
    assert v.decision_stands and v.question is None
    fields = {e.field for e in v.cited}
    assert {"aog.mel_relief", "aog.logged_at", "metar.gust_kt", "flight.operated_after_window"} <= fields
    ops = next(e for e in v.cited if e.field == "flight.operated_after_window")
    assert ops.value == 11                                # "everyone else flew", 15:30-17:30Z
    gust = [e for e in v.cited if e.field == "metar.gust_kt"]
    assert gust and all(e.value <= 25 for e in gust)


def test_challenge_hidden_defect_routes_to_legal(golden):
    d = _ns31(golden)
    f = Fact(id="F-CH-1", source_id="SRC-CHALLENGE-1", subject="flight:NS31@2025-01-24",
             field="challenge.claim", value="hidden defect in this EDP batch",
             span="Airbus operator notice: hidden defect in this EDP batch", extractor="llm:test@drafter-v1",
             recorded_at=KNOWN)
    v = challenge(golden, d, "new_legal_pattern", [f], KNOWN, default_calibration())
    assert v.decision_stands and v.routed_to == Role.LEGAL
    q = v.question
    assert q.routed_to == Role.LEGAL and q.reason_tag == "new-legal-pattern" and q.confidence.score < 0.60
    assert any(e.trust_tier == 4 and e.role == "contradicts" for e in q.evidence)
    # the decision object is untouched: tier-4 facts never flip it
    assert _ns31(golden) == d


def test_challenge_new_fact_goes_to_ops(golden):
    v = challenge(golden, _ns31(golden), "new_fact", [], KNOWN, default_calibration())
    assert v.decision_stands and v.routed_to == Role.OPS and v.question.routed_to == Role.OPS
