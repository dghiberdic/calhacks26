"""The real engine on the golden world (contracts/fixtures/golden/world.json): CP1 numbers from plan §1.2-1.4."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from contracts.models import Cause, Extraordinary, Role, Rule, RuleAction, StormRun, World
from engine.confidence import default_calibration
from engine.engine import Engine

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden" / "world.json"
EOWYN = "EIDW@2025-01-24"
HERMINIA = "EIDW@2025-01-26"
KNOCK_ONS = ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"]

REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active", support="41 of 42")
R_CL_1 = Rule(id="R-CL-1", version=1, kind="voucher", tier="claims_lead_ruling", authority_required=Role.CLAIMS_LEAD,
              scope={"voucher.in_lieu": True, "voucher.signed": False, "flight.departs_eu": True},
              condition={"all": []}, action=RuleAction.DENY_OFFSET, valid_from=None,
              recorded_at=datetime(2025, 1, 25, 9, 30, tzinfo=UTC), status="active")


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json(GOLDEN.read_bytes())


@pytest.fixture(scope="module")
def engine(world) -> Engine:
    return Engine(world, calibration=default_calibration())


def known_at(world: World, storm: str) -> datetime:
    return datetime.fromisoformat(world.meta["storms"][storm]["known_at"].replace("Z", "+00:00"))


def run(engine: Engine, world: World, storm: str, rules) -> StormRun:
    m = world.meta["storms"][storm]
    return engine.run_storm(world, m["station"], date.fromisoformat(m["local_date"]), list(rules),
                            known_at(world, storm))


@pytest.fixture(scope="module")
def eowyn(engine, world) -> StormRun:
    return run(engine, world, EOWYN, [REDUCE])


def decisions(r: StormRun):
    return {row.flight.id: row.decision for row in r.flights if row.decision is not None}


def test_eowyn_flights_match_the_storm_list(eowyn, world):
    assert sorted(r.flight.id for r in eowyn.flights) == sorted(world.meta["storms"][EOWYN]["flight_ids"])
    c = eowyn.counters
    assert (c["passengers"], c["cancelled"], c["operated"]) == (5292, 27, 11)
    assert (c["questions"], c["people"]) == (3, 3)


def test_eowyn_cp1_decisions(eowyn):
    ds = decisions(eowyn)
    ns31 = ds["NS31@2025-01-24"]
    assert (ns31.cause, ns31.extraordinary, ns31.recoded, ns31.outcome, ns31.routed_to) == (
        Cause.TECHNICAL, Extraordinary.NO, True, "auto", None)
    assert ns31.recode_label == "71 → 41" and ns31.confidence.score >= 0.90 and ns31.window_margin_min >= 60
    weather = [d for d in ds.values() if d.cause == Cause.WEATHER]
    assert len(weather) == 13 + 6 + 4
    assert all(d.extraordinary == Extraordinary.YES and d.outcome == "auto" and not d.recoded for d in weather)
    for fid in KNOCK_ONS:
        d = ds[fid]
        assert (d.cause, d.extraordinary, d.recoded, d.outcome, d.routed_to) == (
            Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, False, "escalated", Role.LEGAL)
        assert d.confidence.score < 0.60 and d.in_window_dep == "out" and d.in_window_arr == "out"
    assert len({ds[f].question_id for f in KNOCK_ONS}) == 1


def test_eowyn_money(eowyn):
    assert eowyn.entitlement_cents == 9_900_000
    assert eowyn.liability_drafted_cents == 8_214_600


def test_eowyn_questions(eowyn):
    q = {x.pattern: x for x in eowyn.questions}
    assert set(q) == {"knock_on_return", "voucher_in_lieu_unsigned", "cohort_release"}
    assert q["knock_on_return"].case_refs == KNOCK_ONS and q["knock_on_return"].holds_cents == 4_749_600
    assert q["voucher_in_lieu_unsigned"].case_refs == ["NS31@2025-01-24:14C"]
    assert q["voucher_in_lieu_unsigned"].confidence.score < 0.60
    assert q["voucher_in_lieu_unsigned"].reason_tag == "sources-disagree"
    rel = q["cohort_release"]
    assert rel.routed_to == Role.CONTROLLER and rel.case_refs == ["EIDW@2024-01-21"] and rel.holds_cents == 360_000
    assert rel.confidence.score == pytest.approx(0.72, abs=0.01)


def test_ns31_entitlements(engine, world, eowyn):
    d = decisions(eowyn)["NS31@2025-01-24"]
    ents = engine.entitlements(d, world, [REDUCE])
    assert len(ents) == 172 and sum(e.compensation_cents for e in ents) == 9_900_000
    by = {e.coupon_id: e for e in ents}
    assert by["NS31@2025-01-24:14C"].status == "needs_ruling"
    assert by["NS31@2025-01-24:14C"].compensation_cents == 60_000 and by["NS31@2025-01-24:14C"].voucher_offset_cents == 0
    assert sum(1 for e in ents if e.refund_already_initiated) == 32
    assert "duplicate refund" in by[world.meta["ns31"]["bsp_duplicate_coupon"]].reason
    assert "chargeback" in by[world.meta["ns31"]["chargeback_coupon"]].reason


def test_bcn_margin_14(engine, world, eowyn):
    d = decisions(eowyn)["NS108@2025-01-24"]
    e = engine.entitlements(d, world, [])[0]
    assert (e.distance_km, e.band_eur, e.band_margin_km) == (1486.0, 250, 14.0)
    assert e.status == "no_compensation" and e.care_due


def test_herminia_before_and_after_r_cl_1(engine, world):
    before = run(engine, world, HERMINIA, [REDUCE])
    ds = decisions(before)
    for fid in ("NS106@2025-01-26", "NS110@2025-01-26", "NS30@2025-01-25"):
        assert ds[fid].cause == Cause.TECHNICAL and ds[fid].outcome == "auto", fid
    assert ds["NS106@2025-01-26"].recoded and ds["NS114@2025-01-26"].cause == Cause.WEATHER
    q = next(x for x in before.questions if x.pattern == "voucher_in_lieu_unsigned")
    assert len(q.case_refs) == 32

    after = run(engine, world, HERMINIA, [REDUCE, R_CL_1])
    ents = [e for row in after.flights if row.decision for e in engine.entitlements(row.decision, world,
                                                                                     [REDUCE, R_CL_1])]
    settled = [e for e in ents if "R-CL-1@1" in e.rules_applied]
    assert sorted(e.coupon_id for e in settled) == sorted(world.meta["herminia"]["in_lieu_unsigned_eu_departures"])
    assert all(e.status == "owed" and e.voucher_offset_cents == 0 for e in settled)
    q2 = next(x for x in after.questions if x.pattern == "voucher_in_lieu_unsigned")
    assert q2.case_refs == world.meta["herminia"]["in_lieu_unsigned_non_eu"]        # BOS→DUB asks again


def test_question_ids_short_for_primary_storm_only(engine, world, eowyn):
    assert {q.pattern: q.id for q in eowyn.questions} == {
        "voucher_in_lieu_unsigned": "Q-1", "knock_on_return": "Q-2", "cohort_release": "Q-3"}
    assert all(decisions(eowyn)[f].question_id == "Q-2" for f in KNOCK_ONS)
    herm = run(engine, world, HERMINIA, [REDUCE])
    ids = {q.pattern: q.id for q in herm.questions}
    assert ids["voucher_in_lieu_unsigned"] == "Q-EIDW@2025-01-26:voucher_in_lieu_unsigned"
    assert ids["cohort_release"] == "Q-3"                      # the same cohort question, whichever run shows it
