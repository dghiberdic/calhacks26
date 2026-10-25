"""Blackout v1 (the Iberian grid outage of 28 Apr 2025) on a small hand-made world.

An external event's airport windows join the METAR storm windows at that station. A cancelled flight inside an event
window at either end, with no decisive AOG, is ``external_event`` / ``external_event_window``: one Legal question
per event (no precedent). Legal's ruling templates a ``legal_ruling`` SET_EXTRAORDINARY on ``event.kind`` plus the
in-window features, which then settles those flights automatically. Flights cancelled after the window closed are
judged on their own evidence: a crew-duty or positioning line in the OCC log is an internal cause (owed), a pure
knock-on keeps the knock-on pattern.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from contracts import fields
from contracts.models import (
    Cause, EventAirportWindow, Extraordinary, ExternalEvent, OpsLogEntry, Question, Role, Rule, RuleAction, Ruling,
    Session, SourceKind, TechLogEntry, World,
)
from engine import dsl
from engine import rules as rb
from engine.case import stations_for
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.lifecycle import Lifecycle, template_rule
from engine.tests.mini_world import Builder, calm_obs, flight
from engine.trace import TraceStore

DAY = date(2025, 4, 28)
EVENT_ID = "EVT-IBERIA-BLACKOUT@2025-04-28"
KNOWN = datetime(2025, 4, 29, 8, 0, tzinfo=UTC)
NOTICE = ("ENTSO-E, 28 April 2025: At 12:33 CEST (10:33Z) the power systems of Spain and Portugal blacked out. "
          "Restoration proceeded through the evening. https://www.entsoe.eu/publications/blackout/"
          "28-april-2025-Iberian-blackout")
TITLE_Q = ("Is the Iberian Peninsula blackout an extraordinary circumstance for flights scheduled inside its "
           "outage window?")
OPTIONS = ["Extraordinary inside the outage window", "Not extraordinary", "Decide flight by flight"]
LEGAL = Session(principal="legal:li", role=Role.LEGAL, name="li", issued_at=KNOWN)


def z(hhmm: str, day: int = 28) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2025, 4, day, int(h), int(m), tzinfo=UTC)


def fid(number: str) -> str:
    return f"{number}@{DAY.isoformat()}"


def build(*, notice_at: datetime = z("11:00"), notice_tier: int = 1, ns512_spare: bool = True) -> World:
    b = Builder()
    b.meta = {"carrier": "Northstar Air", "distances_km": {"DUB-LIS": 1643, "DUB-MAD": 1450}}
    for st in ("EIDW", "LPPT", "LEMD"):
        b.metar[f"{st}@2025-04-28"] = calm_obs(st, z("04:00"), 30)
    b.source("SRC-EVT-ENTSOE", SourceKind.EXTERNAL_EVENT, "ENTSO-E: Iberian blackout", NOTICE, notice_at,
             notice_tier, ["ops"])

    def add(number, o, d, std, sta, tail, *, code="87", pax=12, **kw):
        f = b.add_flight(flight(number, o, d, std, sta, pax, tail, code=code, day=DAY, notified_at=z("10:50"), **kw))
        b.add_coupons(f, [(pax // 2, "refund", {}), (pax - pax // 2, "none", {})])
        return f

    ns500 = add("NS500", "DUB", "LIS", z("11:00"), z("13:45"), "EI-NSA")          # arrives inside the LIS window
    add("NS501", "LIS", "DUB", z("14:45"), z("17:25"), "EI-NSA", inbound_flight_id=ns500.id,
        outbound_pair_id=ns500.id)                                                 # departs inside it
    add("NS510", "LIS", "DUB", z("22:40"), z("01:20", 29), "EI-NSC")               # after the LIS window: crew duty
    add("NS512", "MAD", "DUB", z("21:30"), z("23:55"), "EI-NSD")                   # after the MAD window: positioning
    ns520 = add("NS520", "DUB", "MAD", z("15:00"), z("17:30"), "EI-NSE")           # arrives inside the MAD window
    add("NS521", "MAD", "DUB", z("21:45"), z("23:59"), "EI-NSE", inbound_flight_id=ns520.id,
        outbound_pair_id=ns520.id)                                                 # pure knock-on, after the window
    add("NS530", "DUB", "LIS", z("16:00"), z("18:45"), "EI-NSF")                   # AOG + outage: concurrent
    b.add_flight(flight("NS540", "DUB", "LHR", z("12:00"), z("13:15"), 150, "EI-NSG", status="operated", day=DAY,
                        actual_dep=z("12:05"), actual_arr=z("13:20")))
    b.tech_log.append(TechLogEntry(id="TL-EI-NSF-1", aircraft="EI-NSF", logged_at=z("08:00"), station="DUB", ata="2913",
                                   text="28APR 08:00Z EI-NSF DUB N/S. HYD PUMP LEAK. NO MEL RELIEF. A/C AOG.",
                                   mel_relief=False, aog=True, rts_est=z("20:00", 29)))
    b.ops_log += [
        OpsLogEntry(id="OCC-1050", at=z("10:50"), kind="occ", code="87",
                    flight_ids=[fid(n) for n in ("NS500", "NS501", "NS520", "NS530")], author="OCC DM",
                    text="10:50Z OCC DM: LPPT/LEMD GRID OUTAGE (IBERIAN BLACKOUT). CNL NS500/501 NS520 NS530 RSN 87."),
        OpsLogEntry(id="OCC-2205", at=z("22:05"), kind="occ", code="87", flight_ids=[fid("NS510")], author="OCC DM",
                    text="22:05Z OCC: NS510 CNL RSN 87. CREW OUT OF FDP AFTER BLACKOUT DELAYS, NO RESERVE CREW "
                         "AT LIS."),
        OpsLogEntry(id="OCC-2110", at=z("21:10"), kind="occ", code="87", flight_ids=[fid("NS512")], author="OCC DM",
                    text="21:10Z OCC: NS512 CNL RSN 87. A/C EI-NSD OUT OF POSITION AT LIS AFTER THE BLACKOUT."),
        *([OpsLogEntry(id="SPARES-NS512", at=z("21:15"), kind="spares", flight_ids=[fid("NS512")],
                       author="OCC fleet desk",
                       text="NS512: no tail at MAD. Spare EI-NSZ serviceable at MAD = STD+1h00, not assigned.")]
          if ns512_spare else []),
        OpsLogEntry(id="OCC-2120", at=z("21:20"), kind="occ", code="93", flight_ids=[fid("NS521")], author="OCC DM",
                    text="21:20Z OCC: NS521 CNL RSN 93. INBD NS520 CNL."),
    ]
    w = b.world()
    event = ExternalEvent(id=EVENT_ID, kind="grid_outage", title="Iberian Peninsula blackout",
                          source_ids=["SRC-EVT-ENTSOE"],
                          airports=[EventAirportWindow(icao="LPPT", start=z("10:33"), end=z("22:00"),
                                                       note="approximate: terminals reopened late evening"),
                                    EventAirportWindow(icao="LEMD", start=z("10:33"), end=z("21:00"),
                                                       note="approximate: Aena traffic reductions lifted")])
    return w.model_copy(update={"events": [event]})


@pytest.fixture(scope="module")
def world() -> World:
    return build()


@pytest.fixture(scope="module")
def engine(world) -> Engine:
    return Engine(world, calibration=default_calibration())


def decide(engine, w, number, rules=(), at=KNOWN):
    return engine.decide_in(w, fid(number), list(rules), at)


def event_rule(action=RuleAction.SET_EXTRAORDINARY) -> Rule:
    return Rule(id="R-LEG-7", version=1, kind="cause", tier="legal_ruling", authority_required=Role.LEGAL, scope={},
                condition={"all": [{"f": "event.kind", "op": "eq", "v": "grid_outage"},
                                   {"any": [{"f": "flight.in_event_window_dep", "op": "eq", "v": "in"},
                                            {"f": "flight.in_event_window_arr", "op": "eq", "v": "in"}]}]},
                action=action, valid_from=None, recorded_at=z("06:00", 29), status="active")


# ---------- windows ----------

def test_event_windows_join_the_station_windows(world):
    st = stations_for(world, KNOWN).get("LPPT")
    assert st.windows == []                                      # calm METAR: no storm window
    (w,) = st.event_windows
    assert (w.kind, w.start, w.end, w.station) == ("grid_outage", z("10:33"), z("22:00"), "LPPT")
    assert w.label == "Grid outage (Iberian Peninsula blackout)" and "approximate" in w.definition
    assert stations_for(world, KNOWN).get("EIDW").event_windows == []


def test_an_event_is_known_only_once_its_tier_1_notice_is_on_file():
    early = build(notice_at=z("11:00"))
    assert stations_for(early, z("10:59")).get("LPPT").event_windows == []
    assert stations_for(early, z("11:00")).get("LPPT").event_windows
    hearsay = build(notice_tier=4)                               # a passenger saying so is not the grid operator
    assert stations_for(hearsay, KNOWN).get("LPPT").event_windows == []


def test_engine_features_include_the_event_features():
    assert dsl.FEATURES == frozenset(fields.ALL_DSL_FEATURES)


# ---------- inside the window: one Legal question ----------

@pytest.mark.parametrize("number, end", [("NS500", "arr"), ("NS501", "dep"), ("NS520", "arr")])
def test_a_flight_inside_the_outage_window_is_an_external_event_for_legal(engine, world, number, end):
    ev = engine.evaluate(world, fid(number), [], KNOWN)
    d = engine.to_decision(world, ev, [], KNOWN)
    assert (d.cause, d.extraordinary, d.outcome, d.routed_to) == (
        Cause.EXTERNAL_EVENT, Extraordinary.NEEDS_LEGAL, "escalated", Role.LEGAL)
    assert ev.finding.pattern == "external_event_window" and ev.finding.reason_tag == "no-precedent"
    assert d.question_id == f"Q-{EVENT_ID}:external_event_window"           # one question per event, every station
    assert getattr(d, f"in_window_{end}") == "in"
    assert ev.features[f"flight.in_event_window_{end}"] == "in" and ev.features["event.kind"] == "grid_outage"
    assert d.confidence.features["in_event_window"] == 1.0
    assert "Iberian Peninsula blackout" in d.reason and "approximate" in d.reason
    cited = [e for e in d.evidence if e.source_id == "SRC-EVT-ENTSOE"]
    assert cited and all(e.trust_tier == 1 for e in cited)
    assert any(e.quote and e.quote in NOTICE and "10:33Z" in e.quote for e in cited)    # quotes the notice itself
    assert {e.field for e in cited} >= {"event.kind", "event.window_start"}
    assert "CJEU C-12/11" in d.legal_basis                                  # care is owed either way (McDonagh)


def test_a_decisive_aog_inside_the_outage_window_is_concurrent(engine, world):
    d = decide(engine, world, "NS530")
    assert (d.cause, d.extraordinary, d.routed_to) == (Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, Role.LEGAL)
    assert "outage" in d.reason


def test_the_storm_run_asks_legal_one_question_with_the_spec_wording(engine, world):
    run = engine.run_storm(world, "LPPT", DAY, [], KNOWN)
    assert run.event_id == EVENT_ID
    assert any(w.kind == "grid_outage" and w.label for w in run.windows)
    assert run.message and "grid outage" in run.message.lower()
    (q,) = [q for q in run.questions if q.pattern == "external_event_window"]
    assert q.title == TITLE_Q and q.options == OPTIONS and q.recommended_option == OPTIONS[0]
    assert q.routed_to == Role.LEGAL and q.reason_tag == "no-precedent"
    assert set(q.case_refs) >= {fid("NS500"), fid("NS501")}
    assert any(e.source_id == "SRC-EVT-ENTSOE" for e in q.evidence)


# ---------- after the window: judged on their own evidence ----------

def test_a_crew_duty_cancellation_after_the_window_is_owed(engine, world):
    d = decide(engine, world, "NS510")
    assert (d.cause, d.extraordinary, d.outcome) == (Cause.CREW, Extraordinary.NO, "auto")
    assert d.in_window_dep == "out" and d.recoded and d.recode_label == "87 → 64"
    assert d.confidence.features["internal_cause_logged"] == 1.0 and d.confidence.features["in_event_window"] == 0
    assert any(e.quote and "CREW OUT OF FDP" in e.quote and e.role == "supports" for e in d.evidence)
    assert {e.status for e in engine.entitlements(d, world, [])} == {"owed"}


def test_an_aircraft_out_of_position_with_a_spare_to_hand_is_owed(engine, world):
    d = decide(engine, world, "NS512")
    assert (d.cause, d.extraordinary, d.outcome) == (Cause.KNOCK_ON, Extraordinary.NO, "auto")
    assert d.recode_label == "87 → 93" and any(e.field == "spare.available_within_h" for e in d.evidence)
    assert any(e.quote and "OUT OF POSITION" in e.quote for e in d.evidence)
    assert {e.status for e in engine.entitlements(d, world, [])} == {"owed"}


def test_out_of_position_with_no_spare_is_not_an_internal_cause():
    """The aircraft was stranded by the event itself and nothing else could fly: not owed on the log line alone."""
    w = build(ns512_spare=False)
    ev = Engine(w, calibration=default_calibration()).evaluate(w, fid("NS512"), [], KNOWN)
    assert ev.finding.pattern != "internal_cause_logged" and ev.finding.extraordinary != Extraordinary.NO


def test_a_pure_knock_on_after_the_window_keeps_the_knock_on_pattern(engine, world):
    ev = engine.evaluate(world, fid("NS521"), [], KNOWN)
    assert ev.finding.cause == Cause.KNOCK_ON and ev.finding.pattern == "knock_on_return"
    assert ev.finding.route == Role.LEGAL


# ---------- Legal's ruling templates the rule; it then settles the window ----------

def _question(engine, world) -> Question:
    run = engine.run_storm(world, "LPPT", DAY, [], KNOWN)
    return next(q for q in run.questions if q.pattern == "external_event_window")


def _ruling(text: str) -> Ruling:
    return Ruling(id="RUL-EVT-1", question_id=f"Q-{EVENT_ID}:external_event_window", author_role=Role.LEGAL,
                  author="legal:li", kind="answer", decision=text, explanation="", at=KNOWN)


def test_the_ruling_templates_a_grounded_legal_rule_on_the_event_window(engine, world):
    q = _question(engine, world)
    feats = engine.evaluate(world, fid("NS500"), [], KNOWN).features
    rule = template_rule(_ruling(OPTIONS[0]), q, feats)
    assert rule is not None and rule.tier == "legal_ruling" and rule.action == RuleAction.SET_EXTRAORDINARY
    assert rule.condition == event_rule().condition and rule.kind == "cause"
    grounded, chk, problems = rb.checks(rule, author_role=Role.LEGAL, ruling=_ruling(OPTIONS[0]), case_feats=feats)
    assert all(chk.values()), problems
    no = template_rule(_ruling(OPTIONS[1]), q, feats)
    assert no is not None and no.action == RuleAction.SET_NOT_EXTRAORDINARY
    assert template_rule(_ruling(OPTIONS[2]), q, feats) is None              # flight by flight: no rule


def test_with_the_rule_the_window_settles_automatically_and_nothing_else_moves(engine, world):
    rule = event_rule()
    for number in ("NS500", "NS501", "NS520"):
        d = decide(engine, world, number, [rule])
        assert (d.extraordinary, d.outcome) == (Extraordinary.YES, "auto") and "R-LEG-7@1" in d.rules_applied
        ents = engine.entitlements(d, world, [rule])
        assert {e.status for e in ents} == {"no_compensation"} and all(e.care_due for e in ents)
    assert decide(engine, world, "NS510", [rule]).extraordinary == Extraordinary.NO      # after the window: owed
    assert decide(engine, world, "NS530", [rule]).extraordinary == Extraordinary.NEEDS_LEGAL   # AOG: still Legal


def test_legal_answers_in_the_lifecycle_and_confirming_resettles_the_window(engine, world):
    trace = TraceStore(":memory:", engine_sha="test", cal_version="cal-default-v1")
    lc = Lifecycle(engine, world, trace)
    run = engine.run_storm(world, "LPPT", DAY, [], KNOWN)
    decisions = [r.decision for r in run.flights if r.decision]
    lc.record_run(decisions, [e for d in decisions for e in engine.entitlements(d, world, [])], KNOWN)
    q = next(q for q in run.questions if q.pattern == "external_event_window")
    resp = lc.answer(q, OPTIONS[0], "", LEGAL, KNOWN + timedelta(minutes=5))
    p = resp.proposal
    assert p is not None and all(p.checks.values()) and p.rule.id.startswith("R-LEG-")
    assert {f.entity_id for f in p.would_flip.flips if f.field == "extraordinary"} >= {fid("NS500"), fid("NS501")}
    done = lc.confirm(p.rule.id, LEGAL, KNOWN + timedelta(minutes=10))
    flipped = {d.flight_id: d for d in done.decisions}
    assert flipped[fid("NS500")].extraordinary == Extraordinary.YES and flipped[fid("NS500")].outcome == "auto"
    assert done.cited >= 2
