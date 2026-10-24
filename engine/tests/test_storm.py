"""run_storm on the inline mini-world: counts come from the engine, never hand-typed."""
from __future__ import annotations

from datetime import UTC, date, datetime

import orjson
import pytest

from contracts.models import Role, Rule, RuleAction, StormRun
from engine.confidence import default_calibration
from engine.engine import Engine, expected_liability

from . import mini_world as mw

KNOWN = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active", support="41 of 42")


@pytest.fixture(scope="module")
def run() -> StormRun:
    w = mw.build()
    return Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 24), [REDUCE], KNOWN)


def test_run_identity_and_windows(run):
    assert run.id == "EIDW@2025-01-24" and run.station == "EIDW"
    main = max(run.windows, key=lambda w: w.end - w.start)
    assert main.start == mw.z("02:30") and main.end == mw.z("15:00")
    assert run.metar and run.message is None
    assert {a.iata for a in run.airports} >= {"DUB", "BOS", "MUC"}


def test_counters(run):
    c = run.counters
    assert c["cancelled"] == 5 and c["operated"] == 2
    assert c["passengers"] == 172 + 192 + 182 + 170 + 168
    assert c["recoded"] == 1 and c["weather"] == 3
    assert c["drafted"] == 171                       # NS31 owed coupons (14C waits for the Claims Lead)
    assert c["held"] == 168 + 1
    assert c["questions"] == 2 and c["people"] == 2  # Legal (NS117) + Claims Lead (14C)
    assert c["rules_cited"] == 14                    # R-MINED-REDUCE on 14 partner reroutes


def test_money(run):
    assert run.entitlement_cents == 9_900_000
    assert run.liability_drafted_cents == 3_465_000 + 840_000   # NS31 35% + NS117 168 × 25,000 × 20%


def test_questions(run):
    q = {x.pattern: x for x in run.questions}
    ko = q["knock_on_return"]
    assert ko.routed_to == Role.LEGAL and ko.case_refs == [mw.fid("NS117")]
    assert ko.confidence.score < 0.60 and ko.reason_tag == "no-precedent"
    assert ko.holds_cents == 840_000 and ko.remind_at == mw.z("09:00", 25)
    v = q["voucher_in_lieu_unsigned"]
    assert v.routed_to == Role.CLAIMS_LEAD and v.case_refs == [f"{mw.fid('NS31')}:14C"]
    assert v.confidence.score < 0.60 and v.reason_tag == "sources-disagree" and v.confidence.kind == "voucher"
    assert v.holds_cents == 60_000
    assert v.recommended_option == v.options[0]


def test_feed_and_rows(run):
    assert [e.seq for e in run.feed] == list(range(1, len(run.feed) + 1))
    ns31 = next(e for e in run.feed if e.ref == mw.fid("NS31"))
    assert ns31.chip == "DRAFTED" and "recoded 71 → 41" in ns31.summary and ns31.amount_cents == 3_465_000
    assert sum(1 for e in run.feed if e.chip == "ASKED") == 2
    operated = [r for r in run.flights if r.flight.status == "operated"]
    assert len(operated) == 2 and all(r.decision is None for r in operated)


def test_run_is_deterministic():
    w = mw.build()
    a = Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 24), [REDUCE], KNOWN)
    b = Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 24), [REDUCE], KNOWN)
    dump = lambda r: orjson.dumps(r.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)  # noqa: E731
    assert dump(a) == dump(b)


def test_calm_day_message():
    w = mw.build()
    run = Engine(w, calibration=default_calibration()).run_storm(w, "EIDW", date(2025, 1, 25), [], KNOWN)
    assert run.windows == [] and run.message and run.message.endswith("no storm window")


def test_expected_liability_rounds_per_flight_segment():
    from contracts.models import Entitlement
    e = lambda fid, c, band=600: Entitlement(coupon_id=f"{fid}:x", flight_id=fid, distance_km=4000, band_eur=band,  # noqa: E731
                                             band_margin_km=0, compensation_cents=c, status="owed", article="", reason="")
    assert expected_liability([e("A", 1), e("A", 1), e("B", 1)]) == 1 + 0       # 2×.35=.7→1 ; .35→0
    assert expected_liability([e("A", 30_000, 250)]) == 6_000
