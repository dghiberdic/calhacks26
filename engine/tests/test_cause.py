"""D2 · cause + ATA table on the inline mini-world (plan §1.2): NS31, weather flights, the NS117 knock-on."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import random

import orjson
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import Cause, Extraordinary, Fact, Role, Rule, RuleAction, World
from engine.ata_table import classify
from engine.confidence import default_calibration
from engine.engine import Engine

from . import mini_world as mw

KNOWN = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
SIG = ("cause", "extraordinary", "recoded", "outcome", "routed_to")


def sig(d):
    return (d.cause, d.extraordinary, d.recoded, d.outcome, d.routed_to)


@pytest.fixture(scope="module")
def world() -> World:
    return mw.build()


@pytest.fixture(scope="module")
def engine(world) -> Engine:
    return Engine(world, calibration=default_calibration())


def decide(engine: Engine, world: World, number: str, rules=(), known_at=KNOWN):
    return engine.decide_in(world, mw.fid(number), list(rules), known_at)


def edit(world: World, fn) -> World:
    w = world.model_copy(deep=True)
    fn(w)
    return w


R_LEG_1 = Rule(
    id="R-LEG-1", version=1, kind="cause", tier="legal_ruling", authority_required=Role.LEGAL,
    scope={"flight.is_return_sector": True},
    condition={"all": [
        {"f": "rotation.prev_cancelled", "op": "eq", "v": True},
        {"f": "rotation.prev_cause", "op": "eq", "v": "weather"},
        {"f": "spare.available_within_h", "op": "gt", "v": 3},
        {"f": "pax.reroute_earliest_offered", "op": "eq", "v": True},
    ]},
    action=RuleAction.SET_EXTRAORDINARY, valid_from=None, recorded_at=datetime(2025, 1, 25, 10, 30, tzinfo=UTC),
    status="active", title="Return sector of a storm-cancelled rotation (C-74/19)")
AFTER_RULING = datetime(2025, 1, 25, 11, 0, tzinfo=UTC)


# ---------- ATA table ----------

def test_ata_ns31_edp_leak_is_internal():
    c = classify("2913", mw.TECH_LOG_TEXT)
    assert c.internal and c.chapter == "29" and c.defect == "engine-driven pump leak"


@pytest.mark.parametrize("text", [
    "BIRD STRIKE ENG 1 ON APPROACH. FAN BLADE DAMAGE.", "LIGHTNING STRIKE RADOME. INSP REQD.",
    "HAIL DAMAGE LE SLATS.", "FOD DAMAGE ENG 2 FAN.", "DE-ICING FLUID INGESTION APU.",
])
def test_ata_external_keywords_win_over_chapter(text):
    c = classify("7200", text)
    assert c.category == "external" and not c.internal


def test_ata_unmatched_is_not_internal():
    assert classify("0500", "PAINT SCRATCH").category == "unmatched"
    assert classify("", "PUMP LEAK").category == "unmatched"          # no chapter, no internal call


# ---------- the hero ----------

def test_ns31_technical_recoded(engine, world):
    d = decide(engine, world, "NS31")
    assert sig(d) == (Cause.TECHNICAL, Extraordinary.NO, True, "auto", None)
    assert d.recode_label == "71 → 41" and d.ops_cause_code == "71"
    assert d.confidence.score >= 0.90 and d.confidence.label == "cause-finding confidence"
    assert d.in_window_dep == "out" and d.window_margin_min == 90
    assert {"EU261 Art.5(3)", "CJEU C-549/07", "CJEU C-257/14"} <= set(d.legal_basis)
    occ = [e for e in d.evidence if e.field == "flight.ops_cause_code"]
    assert len(occ) == 1 and occ[0].struck and occ[0].trust_tier == 3 and occ[0].value == "71"
    tl = [e for e in d.evidence if e.field.startswith("aog.")]
    assert tl and all(e.trust_tier == 1 and e.role == "supports" and not e.struck for e in tl)
    assert next(e for e in tl if e.field == "aog.mel_relief").quote == "NO MEL RELIEF."
    for e in d.evidence:                                   # every quote is verbatim from its source text
        src = next((s for s in world.sources if s.id == e.source_id), None)
        if e.quote and src is not None:
            assert e.quote in src.text
    assert "Not weather" in d.reason and "\n" not in d.reason


def test_spares_never_used_for_a_technical_cause(engine, world):
    base = decide(engine, world, "NS31")
    assert not [e for e in base.evidence if e.field.startswith("spare")]

    def spare_now(w):
        for e in w.ops_log:
            if e.id == "SPARES-NS31":
                e.text = "Spare A321XLR EI-NSZ at DUB, available within 1 h."
    alt = decide(engine, edit(world, spare_now), "NS31")
    assert orjson.dumps(alt.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS) == \
        orjson.dumps(base.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)


# ---------- weather ----------

@pytest.mark.parametrize("number,end", [("NS108", "dep"), ("NS101", "arr"), ("NS116", "dep")])
def test_weather_in_window(engine, world, number, end):
    d = decide(engine, world, number)
    assert sig(d) == (Cause.WEATHER, Extraordinary.YES, False, "auto", None)
    assert (d.in_window_dep if end == "dep" else d.in_window_arr) == "in"
    assert d.confidence.score >= 0.90 and d.recode_label is None
    assert "EU261 Art.5(3)" in d.legal_basis


# ---------- knock-on ----------

def test_ns117_knock_on_to_legal(engine, world):
    d = decide(engine, world, "NS117")
    assert sig(d) == (Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.LEGAL)
    assert d.in_window_dep == "out" and d.in_window_arr == "out"
    assert d.confidence.score < 0.60 and "capped:no-precedent" in d.confidence.caps
    assert d.question_id == "Q-2"
    assert "CJEU C-74/19" in d.legal_basis
    spare = [e for e in d.evidence if e.field == "spare.available_within_h"]
    assert spare and spare[0].value == pytest.approx(4.33)


def test_knock_on_without_outstation_metar_still_legal(engine):
    w = mw.build(with_muc_metar=False)
    d = Engine(w, calibration=default_calibration()).decide_in(w, mw.fid("NS117"), [], KNOWN)
    assert d.in_window_dep == "unknown"
    assert sig(d) == (Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.LEGAL)


def test_r_leg_1_settles_knock_on(engine, world):
    d = decide(engine, world, "NS117", rules=[R_LEG_1], known_at=AFTER_RULING)
    assert sig(d) == (Cause.KNOCK_ON, Extraordinary.YES, False, "auto", None)
    assert d.rules_applied == ["R-LEG-1@1"] and d.question_id is None
    assert d.confidence.score >= 0.90
    early = decide(engine, world, "NS117", rules=[R_LEG_1], known_at=KNOWN)   # ruling not recorded yet
    assert early.extraordinary == Extraordinary.NEEDS_LEGAL and early.rules_applied == []
    # the rule never touches the technical case or weather flights' outcome
    assert decide(engine, world, "NS31", rules=[R_LEG_1], known_at=AFTER_RULING).rules_applied == []
    assert decide(engine, world, "NS108", rules=[R_LEG_1], known_at=AFTER_RULING).rules_applied == []


def test_r_leg_1_needs_spares_over_3h(engine, world):
    def spare_soon(w):
        for e in w.ops_log:
            if e.id == "SPARES-NS117":
                e.text = "Tail EI-NSQ at MUC, could operate at STD+1h10."
    d = decide(engine, edit(world, spare_soon), "NS117", rules=[R_LEG_1], known_at=AFTER_RULING)
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.routed_to == Role.LEGAL


# ---------- concurrent, gaps, contradictions ----------

def _tl(w: World, **upd):
    for t in w.tech_log:
        for k, v in upd.items():
            setattr(t, k, v)


def test_aog_inside_window_is_concurrent(engine, world):
    w = edit(world, lambda w: _tl(w, logged_at=mw.z("08:00")))
    d = decide(engine, w, "NS31")
    assert sig(d) == (Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.LEGAL)
    assert d.question_id == "Q-4"


def test_aog_before_window_but_flight_in_window_is_concurrent(engine, world):
    def move(w):
        for f in w.flights:
            if f.number == "NS31":
                f.sched_dep, f.sched_arr = mw.z("12:00"), mw.z("18:40")
    d = decide(engine, edit(world, move), "NS31")
    assert d.cause == Cause.CONCURRENT and d.routed_to == Role.LEGAL


def test_mel_relief_means_no_recode(engine, world):
    d = decide(engine, edit(world, lambda w: _tl(w, mel_relief=True)), "NS31")
    assert sig(d) == (Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.OPS)
    assert d.question_id == "Q-6"


def test_weather_code_contradicted_by_metar_goes_to_ops(engine, world):
    w = edit(world, lambda w: w.tech_log.clear())
    d = decide(engine, w, "NS31")
    assert sig(d) == (Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.OPS)
    assert d.confidence.score < 0.60 and "capped:sources-disagree" in d.confidence.caps
    occ = next(e for e in d.evidence if e.field == "flight.ops_cause_code")
    assert occ.role == "contradicts" and not occ.struck              # no tier-1 winner, nothing struck


def test_external_root_cause_goes_to_legal(engine, world):
    w = edit(world, lambda w: _tl(w, ata="7200", text="23JAN 21:40Z EI-NSB DUB BIRD STRIKE ENG 2 ON LDG. FAN "
                                                       "BLADE DAMAGE. NO MEL RELIEF. A/C AOG."))
    d = decide(engine, w, "NS31")
    assert sig(d) == (Cause.TECHNICAL, Extraordinary.NEEDS_LEGAL, True, "escalated", Role.LEGAL)


def test_no_metar_is_unknown_to_ops(engine, world):
    w = edit(world, lambda w: w.metar.clear())
    d = decide(engine, w, "NS108")
    assert d.in_window_dep == "unknown"
    assert sig(d) == (Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.OPS)
    assert d.confidence.score < 0.60


def test_tech_log_not_known_yet(engine, world):
    w = edit(world, lambda w: _tl(w, logged_at=mw.z("16:20")))
    before = decide(engine, w, "NS31", known_at=mw.z("16:10"))
    after = decide(engine, w, "NS31", known_at=mw.z("16:25"))
    assert before.cause == Cause.UNKNOWN and before.routed_to == Role.OPS
    assert after.cause == Cause.TECHNICAL and after.recoded


def test_ops_code_41_without_tech_log_not_auto(engine, world):
    def code41(w):
        w.tech_log.clear()
        for f in w.flights:
            if f.number == "NS31":
                f.ops_cause_code = "41"
    d = decide(engine, edit(world, code41), "NS31")
    assert d.cause == Cause.TECHNICAL and not d.recoded and d.outcome != "auto" and d.routed_to == Role.OPS


# ---------- EngineAPI.decide over facts ----------

def test_decide_with_injected_tech_log_facts(world):
    bare = world.model_copy(deep=True)
    bare.tech_log.clear()
    eng = Engine(bare, calibration=default_calibration())
    assert eng.decide(mw.fid("NS31"), [], [], KNOWN, "x").cause == Cause.UNKNOWN
    src = "SRC-TECHLOG-EI-NSB-2025-01-23T2140Z"
    rec = mw.z("21:45", 23)

    def fact(field, value, span=None):
        return Fact(id=f"F-INJ-{field}", source_id=src, subject="aircraft:EI-NSB", field=field, value=value,
                    span=span, extractor="fallback:regex@1", recorded_at=rec)
    facts = [fact("aog.logged_at", "2025-01-23T21:40:00Z", "23JAN 21:40Z EI-NSB DUB"),
             fact("aog.ata_chapter", "2913"), fact("aog.mel_relief", False, "NO MEL RELIEF."),
             fact("aog.text", mw.TECH_LOG_TEXT)]
    d = eng.decide(mw.fid("NS31"), facts, [], KNOWN, "x")
    assert sig(d) == (Cause.TECHNICAL, Extraordinary.NO, True, "auto", None)
    late = [f.model_copy(update={"recorded_at": KNOWN + timedelta(hours=1)}) for f in facts]
    assert eng.decide(mw.fid("NS31"), late, [], KNOWN, "x").cause == Cause.UNKNOWN   # bitemporal


def test_decide_matches_decide_in(engine, world):
    a = engine.decide(mw.fid("NS117"), [], [], KNOWN, "x")
    b = decide(engine, world, "NS117")
    assert a == b


# ---------- determinism ----------

def _h(d) -> bytes:
    return orjson.dumps(d.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=0, max_value=2**32 - 1))
def test_input_order_does_not_change_decisions(world, seed):
    rnd = random.Random(seed)
    eng = Engine(world, calibration=default_calibration())
    base = {f.id: _h(eng.decide_in(world, f.id, [], KNOWN)) for f in world.flights if f.status == "cancelled"}
    w = world.model_copy(deep=True)
    for lst in (w.flights, w.tech_log, w.ops_log, w.sources, w.coupons, w.elections, w.crm):
        rnd.shuffle(lst)
    for k in w.metar:
        rnd.shuffle(w.metar[k])
    got = {fid: _h(Engine(w, calibration=default_calibration()).decide_in(w, fid, [], KNOWN)) for fid in base}
    assert got == base
