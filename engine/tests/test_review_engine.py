"""Regression tests for the confirmed engine review findings (domain review, integrity review, F9 held-out eval).

Each test is a probe from /tmp/review-domain or /tmp/review-integrity (named in the test), rebuilt on a modified copy
of the golden world, so it runs fast and needs no generator.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.models import (
    Cause,
    Confidence,
    Extraordinary,
    Fact,
    Role,
    Rule,
    RuleAction,
    Source,
    SourceKind,
    TechLogEntry,
    World,
)
from engine import eu261, routing
from engine.case import build_case, find_source
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.trace import TraceStore

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
KA = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
LATER = datetime(2025, 1, 25, 8, 0, tzinfo=UTC)
REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active")
# the knock-on ruling as Legal wrote it (no pattern pinned, no AOG clause): the probes' R-LEG-1
R_LEG_1 = Rule(id="R-LEG-1", version=1, kind="cause", tier="legal_ruling", authority_required=Role.LEGAL,
               scope={"rotation.prev_cause": "weather"},
               condition={"all": [{"f": "flight.is_return_sector", "op": "eq", "v": True},
                                  {"f": "rotation.prev_cancelled", "op": "eq", "v": True},
                                  {"f": "spare.available_within_h", "op": "gt", "v": 3},
                                  {"f": "pax.reroute_earliest_offered", "op": "eq", "v": True}]},
               action=RuleAction.SET_EXTRAORDINARY, valid_from=None,
               recorded_at=datetime(2025, 1, 25, 7, 0, tzinfo=UTC), status="active")


@pytest.fixture(scope="module")
def golden() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_bytes())


@pytest.fixture
def w(golden) -> World:
    return golden.model_copy(deep=True)


def flight(w: World, fid: str):
    return next(f for f in w.flights if f.id == fid)


def decide(w: World, fid: str, rules=(REDUCE,), ka: datetime = KA, cal=None):
    return Engine(w, calibration=cal or default_calibration()).decide_in(w, fid, list(rules), ka)


def ents(w: World, d, rules=(REDUCE,), ka: datetime = KA):
    return eu261.entitlements(d, w, list(rules), ka)


def aog(tail: str, at: datetime, *, station="DUB", text=None, rts=None, ata="2913", mel=False) -> TechLogEntry:
    return TechLogEntry(id=f"TECHLOG-{tail}-TEST-{at:%d%H%M}", aircraft=tail, logged_at=at, station=station, ata=ata,
                        text=text or f"{at:%d%b %H:%MZ} {tail} {station} N/S. HYD PUMP LEAK. NO MEL RELIEF. A/C AOG.",
                        mel_relief=mel, aog=True, rts_est=rts or at + timedelta(days=2))


def source(sid: str, text: str, tier: int, kind=SourceKind.EMAIL, at=datetime(2025, 1, 24, 20, tzinfo=UTC)) -> Source:
    return Source(id=sid, kind=kind, title=sid, text=text, sha256=hashlib.sha256(text.encode()).hexdigest(),
                  received_at=at, trust_tier=tier)


def concurrent_ns117(w: World) -> World:
    """p12: NS117's tail AOG inside the storm window (before the 05:12Z OCC batch) and STA moved inside the DUB
    window."""
    w.tech_log.append(aog("EI-NSL", datetime(2025, 1, 24, 4, 30, tzinfo=UTC), station="MUC", ata="3242",
                          text="24JAN 04:30Z EI-NSL MUC N/S. BRAKE 3 WORN BEYOND LIMIT. NO MEL RELIEF. A/C AOG.",
                          rts=datetime(2025, 1, 25, 9, 0, tzinfo=UTC)))
    f = flight(w, "NS117@2025-01-24")
    f.sched_arr = datetime(2025, 1, 24, 14, 50, tzinfo=UTC)
    f.sched_dep = f.sched_arr - timedelta(hours=2, minutes=15)
    return w


# ---------- domain 1 (p12, p18): a ruling settles only its own pattern; never concurrent causes without aog.* ----

def test_knock_on_ruling_never_settles_concurrent_causes(w):
    w = concurrent_ns117(w)
    d = decide(w, "NS117@2025-01-24", [REDUCE, R_LEG_1], LATER)
    assert d.cause == Cause.CONCURRENT and d.extraordinary == Extraordinary.NEEDS_LEGAL
    assert d.outcome == "escalated" and d.routed_to == Role.LEGAL and "R-LEG-1@1" not in d.rules_applied
    assert {e.status for e in ents(w, d, [REDUCE, R_LEG_1], LATER)} == {"held"}


def test_a_pattern_pinned_ruling_settles_only_its_pattern(w):
    pinned = R_LEG_1.model_copy(update={"scope": {**R_LEG_1.scope, "pattern": "knock_on_return"}})
    base = decide(w, "NS117@2025-01-24", [REDUCE, pinned], LATER)
    assert base.extraordinary == Extraordinary.YES and "R-LEG-1@1" in base.rules_applied   # its own pattern
    other = pinned.model_copy(update={"scope": {**R_LEG_1.scope, "pattern": "external_event"}})
    assert decide(w, "NS117@2025-01-24", [REDUCE, other], LATER).extraordinary == Extraordinary.NEEDS_LEGAL


def test_a_concurrent_ruling_with_an_aog_clause_does_settle(w):
    w = concurrent_ns117(w)
    rule = Rule(id="R-LEG-9", version=1, kind="cause", tier="legal_ruling", authority_required=Role.LEGAL,
                scope={"pattern": "concurrent_causes"},
                condition={"all": [{"f": "aog.inside_window", "op": "eq", "v": True}]},
                action=RuleAction.SET_NOT_EXTRAORDINARY, valid_from=None, recorded_at=KA, status="active")
    d = decide(w, "NS117@2025-01-24", [REDUCE, rule], LATER)
    assert d.extraordinary == Extraordinary.NO and "R-LEG-9@1" in d.rules_applied


def test_spares_are_blanked_whenever_an_aog_grounds_the_tail(w):
    w = concurrent_ns117(w)
    ev = Engine(w, calibration=default_calibration()).evaluate(w, "NS117@2025-01-24", [REDUCE], LATER)
    assert ev.finding.cause == Cause.CONCURRENT and ev.features["spare.available_within_h"] is None
    assert ev.features["pattern"] == "concurrent_causes"


# ---------- domain 10 (p17): Legal patterns are never routed away from Legal ----------

def test_route_to_never_moves_a_legal_pattern_away_from_legal(w):
    f = flight(w, "NS31@2025-01-24")
    f.sched_dep = datetime(2025, 1, 24, 12, 30, tzinfo=UTC)          # NS31 inside the window -> concurrent
    route = Rule(id="R-CTL-2", version=1, kind="routing", tier="controller_ruling", authority_required=Role.CONTROLLER,
                 scope={}, condition={"all": [{"f": "aog.inside_window", "op": "eq", "v": False}]},
                 action=RuleAction.ROUTE_TO, action_arg="ops", valid_from=None, recorded_at=KA, status="active")
    d = decide(w, "NS31@2025-01-24", [REDUCE, route], LATER)
    assert d.cause == Cause.CONCURRENT and d.routed_to == Role.LEGAL and "R-CTL-2@1" not in d.rules_applied


# ---------- domain 2 + 6 (p1, p1b, p8): an OCC non-weather code inside the window is never auto weather ----------

@pytest.mark.parametrize("code", ["41", "64", "46"])
@pytest.mark.parametrize("fid", ["NS21@2025-01-24", "NS100@2025-01-24"])
def test_occ_technical_or_crew_code_in_the_window_goes_to_ops(w, fid, code):
    flight(w, fid).ops_cause_code = code
    d = decide(w, fid)
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.outcome == "escalated" and d.routed_to == Role.OPS
    assert "no_compensation" not in {e.status for e in ents(w, d)}


def test_occ_code_in_window_is_not_auto_even_with_storm_at_both_ends(w):
    """p1b: synthetic storm METAR at LHR too, so the score clears 0.90."""
    eidw = w.metar["EIDW@2025-01-24"]
    w.metar["EGLL@2025-01-24"] = [o.model_copy(update={"station": "EGLL", "raw": o.raw.replace("EIDW", "EGLL")})
                                  for o in eidw]
    flight(w, "NS100@2025-01-24").ops_cause_code = "41"
    d = decide(w, "NS100@2025-01-24")
    assert d.outcome != "auto" and d.extraordinary == Extraordinary.NEEDS_LEGAL


def test_sources_disagree_cap_is_a_hard_gate_against_auto():
    c = Confidence(score=0.99, kind="cause", label="x", features={}, caps=["capped:sources-disagree"],
                   calibration_version="v")
    r = routing.route(extraordinary=Extraordinary.YES, confidence=c, pattern="weather")
    assert r.outcome != "auto" and r.gate == "sources_disagree"


def test_weather_on_a_rotation_code_is_recoded(w):
    flight(w, "NS100@2025-01-24").ops_cause_code = "93"
    d = decide(w, "NS100@2025-01-24")
    assert d.cause == Cause.WEATHER and d.recoded and d.recode_label == "93 → 71"


@pytest.mark.parametrize("code", ["85", "86", "87", "89"])
def test_security_customs_airport_codes_are_not_atc(w, code):
    f = flight(w, "NS31@2025-01-24")
    f.ops_cause_code = code
    w.tech_log = [t for t in w.tech_log if t.aircraft != "EI-NSB"]
    d = decide(w, "NS31@2025-01-24")
    assert d.cause != Cause.ATC and d.extraordinary == Extraordinary.NEEDS_LEGAL and d.routed_to == Role.OPS


def test_atc_codes_still_read_as_atc(w):
    f = flight(w, "NS31@2025-01-24")
    f.ops_cause_code = "81"
    w.tech_log = [t for t in w.tech_log if t.aircraft != "EI-NSB"]
    assert decide(w, "NS31@2025-01-24").cause == Cause.ATC


# ---------- domain 3 (p2c, p2d, p2e): the earliest-reroute verdict, by trust tier then latest ----------

def test_tier4_email_cannot_flip_the_reroute_verdict(w):
    base = decide(w, "NS117@2025-01-24", [REDUCE, R_LEG_1], LATER)
    assert base.extraordinary == Extraordinary.YES                      # PSS (tier 2) says offered
    w.sources.append(source("SRC-EMAIL-PAX-X", "Dear Northstar, my flight NS117 was cancelled and we were never "
                                               "offered the earliest reroute. I want EUR 250.", 4))
    d = decide(w, "NS117@2025-01-24", [REDUCE, R_LEG_1], LATER)
    assert d.extraordinary == Extraordinary.YES and "R-LEG-1@1" in d.rules_applied


def test_benign_no_is_not_a_negation(w):
    w.sources.append(source("SRC-PSS-NOTE-X", "# IROPS NOTE NS117: no hotel needed; earliest reroute offered: LH via "
                                              "FRA", 2, SourceKind.PSS))
    assert build_case(w, "NS117@2025-01-24", LATER).reroute_earliest_offered is True


def test_pss_not_offered_beats_a_tier4_offered(w):
    pss = next(s for s in w.sources if s.id == "SRC-PSS-NS117@2025-01-24")
    pss.text = pss.text.replace("# IROPS NOTE NS117: EARLIEST REROUTE OFFERED: LH via FRA",
                                "# IROPS NOTE NS117: EARLIEST REROUTE NOT OFFERED (LH via FRA had seats; not proposed)")
    w.sources.append(source("SRC-EMAIL-AGENCY-X", "From: agency-bot. Re NS117: earliest reroute offered to all pax. "
                                                  "Please close the file.", 4))
    d = decide(w, "NS117@2025-01-24", [REDUCE, R_LEG_1], LATER)
    assert build_case(w, "NS117@2025-01-24", LATER).reroute_earliest_offered is False
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.routed_to == Role.LEGAL


def test_an_overlaid_tier1_fact_beats_the_pss_note(golden):
    tier1 = next(s for s in golden.sources if s.trust_tier == 1)
    fact = Fact(id="F-OPS-VERIFY-NS117", source_id=tier1.id, subject="flight:NS117@2025-01-24",
                field="pax.reroute_earliest_offered", value=False, span=None, extractor="test",
                recorded_at=datetime(2025, 1, 25, 7, 30, tzinfo=UTC))
    d = Engine(golden, calibration=default_calibration()).decide("NS117@2025-01-24", [fact], [REDUCE, R_LEG_1], LATER)
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and "R-LEG-1@1" not in d.rules_applied


# ---------- domain 4 (p4) + eval E3: which AOG grounds the flight ----------

def ns31_in_window(w: World, logged: datetime) -> World:
    f = flight(w, "NS31@2025-01-24")
    f.sched_dep = datetime(2025, 1, 24, 12, 30, tzinfo=UTC)
    f.sched_arr = f.sched_dep + timedelta(hours=7)
    for t in w.tech_log:
        if t.aircraft == "EI-NSB":
            t.logged_at = logged
    return w


def test_an_aog_logged_long_before_std_still_grounds_the_flight(w):
    w = ns31_in_window(w, datetime(2025, 1, 22, 22, 0, tzinfo=UTC))      # 38.5 h before STD, RTS after STD
    d = decide(w, "NS31@2025-01-24")
    assert d.cause == Cause.CONCURRENT and d.routed_to == Role.LEGAL


def test_an_aog_returned_to_service_before_std_does_not(w):
    w = ns31_in_window(w, datetime(2025, 1, 22, 22, 0, tzinfo=UTC))
    for t in w.tech_log:
        if t.aircraft == "EI-NSB":
            t.rts_est = datetime(2025, 1, 23, 8, 0, tzinfo=UTC)
    assert decide(w, "NS31@2025-01-24").cause == Cause.WEATHER


def test_an_aog_is_cleared_when_the_tail_flew_in_between(w):
    w = ns31_in_window(w, datetime(2025, 1, 22, 22, 0, tzinfo=UTC))
    op = flight(w, "NS120@2025-01-24").model_copy(update={
        "id": "NS900@2025-01-23", "number": "NS900", "aircraft": "EI-NSB", "status": "operated",
        "sched_dep": datetime(2025, 1, 23, 10, 0, tzinfo=UTC), "sched_arr": datetime(2025, 1, 23, 11, 15, tzinfo=UTC)})
    w.flights.append(op)
    assert decide(w, "NS31@2025-01-24").cause == Cause.WEATHER


def test_an_aog_logged_after_the_occ_cancellation_is_not_the_cause(w):
    """E3: NS100 was in the 05:12Z OCC weather batch; an AOG logged at 05:30Z cannot have cancelled it."""
    w.tech_log.append(aog("EI-NSC", datetime(2025, 1, 24, 5, 30, tzinfo=UTC)))
    d = decide(w, "NS100@2025-01-24")
    assert d.cause == Cause.WEATHER and d.outcome == "auto"


def test_an_aog_logged_before_the_occ_cancellation_is_concurrent(w):
    w.tech_log.append(aog("EI-NSC", datetime(2025, 1, 24, 5, 0, tzinfo=UTC)))
    assert decide(w, "NS100@2025-01-24").cause == Cause.CONCURRENT


# ---------- eval E2: an AOG inside an earlier window never makes an out-of-window flight concurrent ----------

def test_out_of_window_flight_with_an_internal_aog_logged_in_an_earlier_window_is_technical(w):
    for t in w.tech_log:
        if t.aircraft == "EI-NSB":
            t.logged_at = datetime(2025, 1, 24, 3, 30, tzinfo=UTC)       # in the 02:30-15:00Z DUB window, pre-batch
    d = decide(w, "NS31@2025-01-24")                                     # STD 16:30Z, out at both ends
    assert d.cause == Cause.TECHNICAL and d.extraordinary == Extraordinary.NO
    assert "neither end" not in d.reason


def test_out_of_window_flight_with_a_weather_damage_aog_stays_a_legal_question(w):
    for t in w.tech_log:
        if t.aircraft == "EI-NSB":
            t.logged_at = datetime(2025, 1, 24, 3, 30, tzinfo=UTC)
            t.ata, t.text = "0510", "24JAN 03:30Z EI-NSB DUB N/S. LIGHTNING STRIKE INSPECTION. NO MEL RELIEF. A/C AOG."
    d = decide(w, "NS31@2025-01-24")
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.routed_to == Role.LEGAL


def test_an_aog_at_the_outbound_station_makes_the_return_a_knock_on(w):
    """NS169-style: the tail is AOG at DUB, so the LIS→DUB return never had an aircraft: a knock-on, not technical."""
    w.tech_log.append(aog("EI-NSJ", datetime(2025, 1, 24, 5, 0, tzinfo=UTC)))
    d = decide(w, "NS113@2025-01-24")
    assert d.cause == Cause.KNOCK_ON


# ---------- eval E4: ≥14 days' notice makes the cause question moot ----------

@pytest.mark.parametrize("fid", ["NS113@2025-01-24", "NS31@2025-01-24"])
def test_notice_of_14_days_routes_auto_whatever_the_cause(w, fid):
    f = flight(w, fid)
    f.notified_at = f.sched_dep - timedelta(days=20)
    if fid == "NS31@2025-01-24":
        f.ops_cause_code = "09"
        w.tech_log = [t for t in w.tech_log if t.aircraft != "EI-NSB"]   # no cause evidence at all
    d = decide(w, fid)
    assert d.outcome == "auto" and d.routed_to is None and d.question_id is None
    assert "Art.5(1)(c)(i)" in " ".join(d.legal_basis) and "Art. 5(1)(c)(i)" in d.reason
    assert {e.status for e in ents(w, d)} == {"exempt_notice"}


def test_the_return_of_a_noticed_outbound_is_not_exempt_by_itself(w):
    out = flight(w, "NS112@2025-01-24")
    out.notified_at = out.sched_dep - timedelta(days=20)
    d = decide(w, "NS113@2025-01-24")
    assert d.outcome == "escalated"                                       # its own passengers had no notice


# ---------- domain 7 (p10): materiality is the auto gate, for rule-settled cases too ----------

@pytest.mark.parametrize("score", [0.05, 0.31, 0.59, 0.89])
def test_a_rule_never_lifts_a_low_score_to_auto(score):
    c = Confidence(score=score, kind="cause", label="x", features={}, calibration_version="v")
    r = routing.route(extraordinary=Extraordinary.NO, confidence=c, pattern="knock_on_return",
                      liability_cents=4_000_000, settled_by_rule=True)
    assert r.outcome == "human" and r.gate == "batch_review"


def test_materiality_still_applies_at_high_scores():
    c = Confidence(score=0.95, kind="cause", label="x", features={}, calibration_version="v")
    assert routing.route(extraordinary=Extraordinary.NO, confidence=c, pattern="technical_internal",
                         liability_cents=5_000_000).gate == "materiality"
    assert routing.route(extraordinary=Extraordinary.NO, confidence=c, pattern="technical_internal",
                         liability_cents=4_999_999).outcome == "auto"


# ---------- domain 8 + integrity 1 (p14, probe_tier4_aog, probe_blame_overlay): overlay provenance ----------

def email_aog_facts(src_id: str, tail: str, rec: datetime) -> list[Fact]:
    return [Fact(id=f"F-X-{k}", source_id=src_id, subject=f"aircraft:{tail}", field=k, value=v,
                 span="hydraulic pump leak", extractor="llm:claude@reader-v1", recorded_at=rec)
            for k, v in [("aog.logged_at", "2025-01-24T01:30:00Z"), ("aog.ata_chapter", "2913"),
                         ("aog.defect_text", "HYD PUMP LEAK"), ("aog.mel_relief", False)]]


@pytest.mark.parametrize("fid", ["NS113@2025-01-24", "NS101@2025-01-24"])
def test_a_tier4_aog_claim_never_becomes_a_tech_log_line(w, fid):
    src = source("SRC-EMAIL-PAX-77", "Passenger email: the crew told us it had a hydraulic pump leak.", 4)
    w.sources.append(src)
    tail = flight(w, fid).aircraft
    eng = Engine(w, calibration=default_calibration())
    d = eng.decide(fid, email_aog_facts(src.id, tail, datetime(2025, 1, 24, 18, 5, tzinfo=UTC)), [REDUCE], KA)
    assert d.cause != Cause.TECHNICAL and not d.recoded
    assert d.outcome == "escalated" and d.routed_to == Role.OPS
    aog_ev = [e for e in d.evidence if e.field.startswith("aog.")]
    assert aog_ev and all(e.trust_tier == 4 and e.source_id == src.id for e in aog_ev)


def test_an_unknown_source_fails_closed_to_tier_4(golden):
    case = build_case(golden, "NS31@2025-01-24", KA)
    assert find_source(case, SourceKind.TECH_LOG, "no such text anywhere", "SRC-NOPE") == ("SRC-NOPE", 4)


def test_blame_reaches_an_overlaid_tech_log_fact(w):
    fid = "NS113@2025-01-24"
    tail = flight(w, fid).aircraft
    text = f"{tail} 23JAN 20:00Z HYD PUMP LEAK, NO MEL RELIEF, ATA 2913"
    src = source("SRC-TL-INJ-1", text, 1, SourceKind.TECH_LOG, at=KA - timedelta(minutes=2))
    w.sources.append(src)
    rec = KA - timedelta(minutes=1)
    facts = [Fact(id=f"F:inj:{i}", source_id=src.id, subject=f"aircraft:{tail}", field=k, value=v, span=sp,
                  extractor="llm:x@reader-v1", recorded_at=rec)
             for i, (k, v, sp) in enumerate([("aog.logged_at", "2025-01-23T20:00:00Z", "23JAN 20:00Z"),
                                             ("aog.ata_chapter", "2913", "ATA 2913"), ("aog.station", "LIS", "LIS"),
                                             ("aog.mel_relief", False, "NO MEL RELIEF")], 1)]
    d = Engine(w, calibration=default_calibration()).decide(fid, facts, [], KA)
    assert d.cause == Cause.TECHNICAL and d.recode_label == "71 → 41"
    ev = {e.field: e for e in d.evidence if e.field.startswith("aog.")}
    assert ev["aog.logged_at"].fact_id == "F:inj:1" and ev["aog.mel_relief"].fact_id == "F:inj:4"
    assert {e.source_id for e in ev.values()} == {src.id} and {e.trust_tier for e in ev.values()} == {1}
    t = TraceStore(":memory:", engine_sha="x", cal_version="c")
    t.record_source(src, "agent.reader", KA)
    t.record_facts(facts, "agent.reader", KA)
    t.record_decision(d, "agent.engine", KA)
    refs = {s.commit.payload_ref for s in t.blame(fid).steps}
    assert {"F:inj:1", src.id} <= refs


# ---------- integrity 5A (probe_nan_cal): a non-finite calibration fails closed ----------

@pytest.mark.parametrize("where", ["intercept", "coef"])
def test_nan_calibration_fails_closed(golden, where):
    cal = json.loads(json.dumps(default_calibration()))
    if where == "intercept":
        cal["models"]["cause"]["intercept"] = float("nan")
    else:
        cal["models"]["cause"]["coef"][0] = float("inf")
    for fid in ("NS113@2025-01-24", "NS31@2025-01-24", "NS100@2025-01-24"):
        d = decide(golden, fid, [REDUCE], KA, cal=cal)
        assert d.confidence.score is None                                 # "uncalibrated", never a NaN score
        assert "capped:uncalibrated" in d.confidence.caps and d.outcome != "auto"
        assert all(math.isfinite(v) for v in d.confidence.features.values())


# ---------- calibration: an explicit concurrent-causes feature ----------

def test_cause_features_carry_concurrent_causes(golden, w):
    assert decide(golden, "NS31@2025-01-24").confidence.features["concurrent_causes"] == 0.0
    d = decide(concurrent_ns117(w), "NS117@2025-01-24", [REDUCE], LATER)
    assert d.confidence.features["concurrent_causes"] == 1.0
