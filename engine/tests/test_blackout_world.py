"""Blackout v1 on the world agent's scenario (``world.events.blackout_world``): Dublin's run on 28 Apr 2025.

Before the ruling: the 8 in-window cancellations are one Legal question (no precedent); NS128 (aircraft out of
position with a serviceable spare not assigned) and NS129 (crew out of FDP, no reserve called) are owed. After Legal
answers "Extraordinary inside the outage window", the 8 settle automatically, citing the templated rule.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from contracts.models import Cause, Extraordinary, Role, Rule, RuleAction, Session

events = pytest.importorskip("world.events")

from engine.confidence import default_calibration  # noqa: E402
from engine.engine import Engine  # noqa: E402
from engine.lifecycle import Lifecycle  # noqa: E402
from engine.trace import TraceStore  # noqa: E402

DAY = date(2025, 4, 28)
PLANTED_IN = {f"{n}@2025-04-28" for n in ("NS111", "NS113", "NS170", "NS171", "NS172", "NS173", "NS174", "NS175")}
NS128, NS129 = "NS128@2025-04-28", "NS129@2025-04-28"
LEGAL = Session(principal="legal:li", role=Role.LEGAL, name="li", issued_at=events.KNOWN_AT)
# the carrier's mined Art. 7(2) policy, active on the demo as on golden; the answer key's amounts assume it
REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=events.KNOWN_AT - timedelta(days=30), status="active")


@pytest.fixture(scope="module")
def world():
    return events.blackout_world()


@pytest.fixture(scope="module")
def engine(world):
    return Engine(world, calibration=default_calibration())


@pytest.fixture(scope="module")
def run(engine, world):
    return engine.run_storm(world, "EIDW", DAY, [], events.KNOWN_AT)


def decisions(run):
    return {r.flight.id: r.decision for r in run.flights if r.decision}


def test_the_run_names_the_event_not_a_storm(run):
    assert run.name == events.NAME and not run.name.startswith("Storm")
    assert run.event_id == events.EVENT_ID
    outage = {w.station for w in run.windows if w.kind == "grid_outage"}
    assert outage == {"LPPT", "LEMD", "LEBL"}                       # the far ends' windows, on Dublin's run
    assert run.message and "Grid outage" in run.message


def test_the_eight_in_window_cancellations_are_one_legal_question(run):
    d = decisions(run)
    for fid in PLANTED_IN:
        assert (d[fid].cause, d[fid].extraordinary, d[fid].routed_to) == (
            Cause.EXTERNAL_EVENT, Extraordinary.NEEDS_LEGAL, Role.LEGAL), fid
    (q,) = [q for q in run.questions if q.pattern == "external_event_window"]
    assert set(q.case_refs) == PLANTED_IN and q.routed_to == Role.LEGAL and q.reason_tag == "no-precedent"
    assert q.id == f"Q-{events.EVENT_ID}:external_event_window"
    assert all(not q.id[2:].isdigit() for q in run.questions)       # never a golden short id (Q-1, Q-2, ...)


def test_post_restoration_cancellations_are_owed(run, engine, world):
    d = decisions(run)
    assert (d[NS128].cause, d[NS128].extraordinary, d[NS128].outcome) == (
        Cause.KNOCK_ON, Extraordinary.NO, "auto")                    # out of position, spare not assigned
    assert (d[NS129].cause, d[NS129].extraordinary, d[NS129].outcome) == (Cause.CREW, Extraordinary.NO, "auto")
    key = events.answer_key()["flights"]
    for fid in (NS128, NS129):
        assert d[fid].confidence.score >= 0.90
        ents = engine.entitlements(d[fid], world, [REDUCE])
        # owed, or owed in cash pending Claims Lead's ruling on an unsigned voucher in lieu (Q voucher_in_lieu)
        owed = [e for e in ents if e.status in ("owed", "needs_ruling")]
        assert len(owed) == key[fid]["owed"]
        assert sum(e.compensation_cents for e in owed) == key[fid]["compensation_cents"]


def test_after_legal_rules_the_eight_settle_and_the_two_stay_owed(engine, world, run):
    trace = TraceStore(":memory:", engine_sha="test", cal_version="cal-default-v1")
    lc = Lifecycle(engine, world, trace)
    ds = [r.decision for r in run.flights if r.decision]
    lc.record_run(ds, [e for d in ds for e in engine.entitlements(d, world, [])], events.KNOWN_AT)
    q = next(q for q in run.questions if q.pattern == "external_event_window")
    p = lc.answer(q, q.options[0], "", LEGAL, events.KNOWN_AT + timedelta(minutes=5)).proposal
    assert p is not None and all(p.checks.values()), p.checks
    done = lc.confirm(p.rule.id, LEGAL, events.KNOWN_AT + timedelta(minutes=10))
    after = engine.run_storm(world, "EIDW", DAY, lc.rules_at(events.KNOWN_AT + timedelta(minutes=10)),
                             events.KNOWN_AT + timedelta(minutes=10))
    d = decisions(after)
    ref = f"{p.rule.id}@1"
    for fid in PLANTED_IN:
        assert (d[fid].extraordinary, d[fid].outcome) == (Extraordinary.YES, "auto") and ref in d[fid].rules_applied
    assert d[NS128].extraordinary == Extraordinary.NO and d[NS129].extraordinary == Extraordinary.NO
    assert not [q for q in after.questions if q.pattern == "external_event_window"]
    assert done.cited >= len(PLANTED_IN)
