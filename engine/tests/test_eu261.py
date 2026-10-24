"""D3 · EU261 entitlements (Arts 3, 5, 7, 8, 9) on the inline mini-world (plan §1.2-1.3)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import (
    Confidence,
    CrmEvent,
    Extraordinary,
    FlightDecision,
    Role,
    Rule,
    RuleAction,
    World,
)
from engine import eu261
from engine.eu261 import band_for, entitlements

from . import mini_world as mw

KNOWN = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)


def decision(flight_id: str, ext: Extraordinary, *, cause: str | None = None, rules=(), qid=None) -> FlightDecision:
    cause = cause or {Extraordinary.YES: "weather", Extraordinary.NO: "technical",
                      Extraordinary.NEEDS_LEGAL: "knock_on"}[ext]
    return FlightDecision(
        flight_id=flight_id, cause=cause, extraordinary=ext, ops_cause_code="71", recoded=False,
        in_window_dep="out", in_window_arr="out",
        confidence=Confidence(score=0.9, kind="cause", label="cause-finding confidence", features={},
                              calibration_version="test"),
        reason="test", evidence=[], rules_applied=list(rules), legal_basis=[],
        outcome="auto" if ext != Extraordinary.NEEDS_LEGAL else "escalated", question_id=qid, known_at=KNOWN)


def rule(rid: str, action: RuleAction, *, tier="mined", scope=None, condition=None, status="active",
         recorded_at=datetime(2025, 1, 1, tzinfo=UTC), valid_from=None, kind="mined_policy",
         authority=Role.CLAIMS_LEAD, version=1) -> Rule:
    return Rule(id=rid, version=version, kind=kind, scope=scope or {}, condition=condition or {"all": []},
                action=action, tier=tier, authority_required=authority, valid_from=valid_from,
                recorded_at=recorded_at, status=status)


REDUCE = rule("R-MINED-REDUCE", RuleAction.APPLY_7_2_REDUCTION,
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]})
R_CL_1 = rule("R-CL-1", RuleAction.DENY_OFFSET, tier="claims_lead_ruling", kind="voucher",
              scope={"voucher.in_lieu": True, "voucher.signed": False, "flight.departs_eu": True},
              recorded_at=datetime(2025, 1, 25, 9, 0, tzinfo=UTC))


@pytest.fixture(scope="module")
def world() -> World:
    return mw.build()


def ents_for(world: World, number: str, ext: Extraordinary, rules=(REDUCE,), **kw):
    return entitlements(decision(mw.fid(number), ext, **kw), world, list(rules))


def by_seat(ents, seat):
    return next(e for e in ents if e.coupon_id.endswith(f":{seat}"))


# ---------- NS31 golden numbers ----------

def test_ns31_total_is_9_900_000(world):
    ents = ents_for(world, "NS31", Extraordinary.NO)
    assert len(ents) == 172
    assert sum(e.compensation_cents for e in ents) == 9_900_000
    assert sum(1 for e in ents if e.compensation_cents == 60_000) == 158
    half = [e for e in ents if e.compensation_cents == 30_000]
    assert len(half) == 14 and all(e.reduction == "art7_2_50pct" for e in half)
    assert all("R-MINED-REDUCE@1" in e.rules_applied for e in half)
    assert {e.band_eur for e in ents} == {600} and {e.distance_km for e in ents} == {4804.0}
    assert ents[0].band_margin_km == 1304.0
    assert eu261.summarize(ents)["status_counts"] == {"needs_ruling": 1, "owed": 171}


def test_14c_unsigned_in_lieu_needs_ruling(world):
    e = by_seat(ents_for(world, "NS31", Extraordinary.NO), "14C")
    assert e.status == "needs_ruling"
    assert e.compensation_cents == 60_000 and e.voucher_offset_cents == 0
    assert "Art.7(3)" in e.article


def test_reduction_only_under_active_mined_rule(world):
    no_rule = ents_for(world, "NS31", Extraordinary.NO, rules=())
    assert sum(e.compensation_cents for e in no_rule) == 172 * 60_000
    assert all(e.reduction == "none" for e in no_rule)
    shadow = REDUCE.model_copy(update={"status": "shadow"})
    assert sum(e.compensation_cents for e in ents_for(world, "NS31", Extraordinary.NO, rules=[shadow])) == 10_320_000


def test_reduction_respects_the_band_limit(world):
    w = world.model_copy(deep=True)
    for el in w.elections:
        if el.coupon_id.startswith("NS31@") and el.kind == "reroute_partner":
            el.arrival_delay_min = 241          # over 4 h for the >3,500 km band
    assert sum(e.compensation_cents for e in ents_for(w, "NS31", Extraordinary.NO)) == 10_320_000
    for el in w.elections:
        if el.coupon_id.startswith("NS31@") and el.kind == "reroute_partner":
            el.arrival_delay_min = 240          # "does not exceed" 4 h
    assert sum(e.compensation_cents for e in ents_for(w, "NS31", Extraordinary.NO)) == 9_900_000


def test_reduction_ignores_rules_recorded_after_known_at(world):
    late = REDUCE.model_copy(update={"recorded_at": KNOWN + timedelta(days=1)})
    assert sum(e.compensation_cents for e in ents_for(world, "NS31", Extraordinary.NO, rules=[late])) == 10_320_000


# ---------- refunds (Art. 8) and the CRM-bot handoff ----------

def test_crm_bot_refunds_not_repeated(world):
    ents = ents_for(world, "NS31", Extraordinary.NO)
    initiated = [e for e in ents if e.refund_already_initiated]
    assert len(initiated) == 32
    assert all(e.refund_due_cents == 0 for e in initiated)
    assert all(e.compensation_cents == 60_000 and e.status == "owed" for e in initiated)  # refund ≠ waiver
    dup = by_seat(ents, "1A")
    assert "duplicate refund" in dup.reason


def test_refund_known_at_filters_crm_events(world):
    early = datetime(2025, 1, 24, 6, 30, tzinfo=UTC)          # only the first few bot refunds exist yet
    ents = entitlements(decision(mw.fid("NS31"), Extraordinary.NO), world, [REDUCE], known_at=early)
    initiated = [e for e in ents if e.refund_already_initiated]
    assert 0 < len(initiated) < 32
    pending = [e for e in ents[:32] if not e.refund_already_initiated]
    assert all(e.refund_due_cents == 51_000 for e in pending)


def test_weather_no_compensation_refunds_and_care_still_due(world):
    ents = ents_for(world, "NS108", Extraordinary.YES)
    assert len(ents) == 192
    assert {e.status for e in ents} == {"no_compensation"}
    assert all(e.compensation_cents == 0 and e.care_due for e in ents)
    refunds = [e for e in ents if e.refund_due_cents]
    assert len(refunds) == 40 and {e.refund_due_cents for e in refunds} == {51_000}
    assert ents[0].article == "EU261 Art.5(3)"


def test_bcn_band_margin_is_14_km(world):
    b = band_for(1486, intra_eu=True)
    assert (b.eur, b.margin_km) == (250, 14.0)
    assert b.note(1486) == "1,486 km · 14 km under the €400 band"
    e = ents_for(world, "NS108", Extraordinary.YES)[0]
    assert e.band_eur == 250 and e.band_margin_km == 14.0


def test_distance_falls_back_to_great_circle(world):
    w = world.model_copy(update={"meta": {}})
    e = ents_for(w, "NS108", Extraordinary.YES)[0]
    assert 1484 <= e.distance_km <= 1487 and int(e.band_margin_km) == 14


# ---------- held (needs Legal) ----------

def test_knock_on_held_at_full_band(world):
    ents = ents_for(world, "NS117", Extraordinary.NEEDS_LEGAL, qid="Q-2")
    assert len(ents) == 168
    assert {e.status for e in ents} == {"held"}
    assert sum(e.compensation_cents for e in ents) == 168 * 25_000
    assert all(e.reduction == "none" for e in ents)      # no reduction while held
    assert "Q-2" in ents[0].reason


# ---------- scope (Art. 3), staff (Art. 3(3)), notice (Art. 5(1)(c)) ----------

def _with_flight_update(world: World, number: str, **upd) -> World:
    w = world.model_copy(deep=True)
    for f in w.flights:
        if f.number == number:
            for k, v in upd.items():
                setattr(f, k, v)
    return w


def test_staff_ticket_no_compensation(world):
    w = world.model_copy(deep=True)
    target = f"{mw.fid('NS31')}:20A"
    for c in w.coupons:
        if c.id == target:
            c.fare_type = "staff_id90"
    e = by_seat(ents_for(w, "NS31", Extraordinary.NO), "20A")
    assert e.status == "staff_ticket" and e.compensation_cents == 0 and e.article == "EU261 Art.3(3)"


def test_notice_14_days_exempt(world):
    f = next(f for f in world.flights if f.number == "NS31")
    w = _with_flight_update(world, "NS31", notified_at=f.sched_dep - timedelta(days=14))
    ents = ents_for(w, "NS31", Extraordinary.NO)
    assert {e.status for e in ents} == {"exempt_notice"}
    assert sum(e.compensation_cents for e in ents) == 0
    assert all(e.care_due for e in ents)
    w2 = _with_flight_update(world, "NS31", notified_at=f.sched_dep - timedelta(days=13, hours=23))
    assert "exempt_notice" not in {e.status for e in ents_for(w2, "NS31", Extraordinary.NO)}


def test_notice_7_to_14_days_needs_departure_advance(world):
    f = next(f for f in world.flights if f.number == "NS31")
    f10 = f.model_copy(update={"notified_at": f.sched_dep - timedelta(days=10)})
    el = next(e for e in world.elections if e.coupon_id.startswith("NS31@") and e.kind == "reroute_partner")
    assert eu261.notice_exemption(f10, el) is None                        # departure advance not shown
    assert eu261.notice_exemption(f10, el, departure_advance_min=90) == "Art.5(1)(c)(ii)"
    assert eu261.notice_exemption(f10, el, departure_advance_min=150) is None
    f3 = f.model_copy(update={"notified_at": f.sched_dep - timedelta(days=3)})
    fast = el.model_copy(update={"arrival_delay_min": 100})
    assert eu261.notice_exemption(f3, fast, departure_advance_min=30) == "Art.5(1)(c)(iii)"
    assert eu261.notice_exemption(f3, el, departure_advance_min=30) is None   # 220 min late ≥ 2 h


def test_scope_non_eu_departure(world):
    # BOS→DUB on an EU carrier is covered (Art. 3(1)(b)); on a non-EU carrier it is not.
    w = _with_flight_update(world, "NS31", origin="BOS", dest="DUB")
    assert {e.status for e in ents_for(w, "NS31", Extraordinary.NO)} >= {"owed"}
    w2 = _with_flight_update(world, "NS31", origin="BOS", dest="DUB", operating_carrier_eu=False)
    ents = ents_for(w2, "NS31", Extraordinary.NO)
    assert {e.status for e in ents} == {"out_of_scope"}
    assert all(not e.care_due and e.compensation_cents == 0 for e in ents)


# ---------- vouchers (Art. 7(3)) ----------

AFTER_RULING = datetime(2025, 1, 25, 10, 0, tzinfo=UTC)


def test_r_cl_1_denies_offset_on_eu_departures(world):
    d = decision(mw.fid("NS31"), Extraordinary.NO)
    before = by_seat(entitlements(d, world, [REDUCE, R_CL_1]), "14C")          # ruling not known yet
    assert before.status == "needs_ruling"
    e = by_seat(entitlements(d, world, [REDUCE, R_CL_1], known_at=AFTER_RULING), "14C")
    assert e.status == "owed" and e.voucher_offset_cents == 0 and e.compensation_cents == 60_000
    assert "R-CL-1@1" in e.rules_applied


def test_r_cl_1_does_not_cover_non_eu_departure(world):
    w = _with_flight_update(world, "NS31", origin="BOS", dest="DUB")
    d = decision(mw.fid("NS31"), Extraordinary.NO)
    e = by_seat(entitlements(d, w, [REDUCE, R_CL_1], known_at=AFTER_RULING), "14C")
    assert e.status == "needs_ruling" and "R-CL-1@1" not in e.rules_applied


def test_signed_in_lieu_voucher_offsets(world):
    w = world.model_copy(deep=True)
    for ev in w.crm:
        if ev.id == "CRM-14C-VIL":
            ev.signed_acceptance_sha256 = "ab" * 32
    e = by_seat(ents_for(w, "NS31", Extraordinary.NO), "14C")
    assert e.status == "owed" and e.voucher_offset_cents == 30_000 and e.compensation_cents == 60_000


def test_allow_offset_rule_offsets_unsigned(world):
    allow = rule("R-LEG-9", RuleAction.ALLOW_OFFSET, tier="legal_ruling", kind="voucher",
                 scope={"voucher.in_lieu": True}, authority=Role.LEGAL)
    d = decision(mw.fid("NS31"), Extraordinary.NO)
    e = by_seat(entitlements(d, world, [REDUCE, allow, R_CL_1], known_at=AFTER_RULING), "14C")
    assert e.voucher_offset_cents == 30_000 and "R-LEG-9@1" in e.rules_applied   # legal tier beats claims lead


def test_in_lieu_voucher_recorded_after_known_at_is_unknown(world):
    early = datetime(2025, 1, 24, 10, 0, tzinfo=UTC)
    ents = entitlements(decision(mw.fid("NS31"), Extraordinary.NO), world, [REDUCE], known_at=early)
    assert by_seat(ents, "14C").status == "owed"


def test_operated_flight_has_no_entitlements(world):
    assert entitlements(decision(mw.fid("NS120"), Extraordinary.NO), world, []) == []


# ---------- bands (Art. 7(1)) ----------

@pytest.mark.parametrize("km,intra,eur,margin", [
    (449, False, 250, 1051), (786, True, 250, 714), (1500, True, 250, 0), (1500.1, True, 400, 0.1),
    (2876, True, 400, 1376), (2876, False, 400, 624), (3500, False, 400, 0), (3500.1, False, 600, 0.1),
    (3600, True, 400, 2100), (4804, False, 600, 1304), (1643, True, 400, 143), (1381, True, 250, 119),
])
def test_band_table(km, intra, eur, margin):
    b = band_for(km, intra)
    assert b.eur == eur and b.margin_km == pytest.approx(margin)


@settings(max_examples=50, deadline=None)
@given(st.floats(min_value=1, max_value=20_000, allow_nan=False), st.booleans())
def test_band_monotonic_and_margin_nonnegative(km, intra):
    b = band_for(km, intra)
    assert b.margin_km >= 0
    assert band_for(km + 100, intra).eur >= b.eur
    if not intra:
        assert band_for(km, True).eur <= b.eur


@settings(max_examples=50, deadline=None)
@given(st.lists(st.sampled_from(["refund", "voucher", "reaccommodated_own", "reroute_partner", "none"]),
                min_size=1, max_size=20),
       st.lists(st.integers(min_value=0, max_value=3000), min_size=20, max_size=20),
       st.sampled_from(list(Extraordinary)))
def test_compensation_is_band_half_or_zero(kinds, delays, ext):
    b = mw.Builder()
    f = b.add_flight(mw.flight("NS31", "DUB", "BOS", mw.z("16:30"), mw.z("23:10"), len(kinds), "EI-NSB"))
    b.add_coupons(f, [(1, k, {"delay": d}) for k, d in zip(kinds, delays)])
    ents = entitlements(decision(f.id, ext), b.world(), [REDUCE])
    assert len(ents) == len(kinds)
    for e in ents:
        assert e.compensation_cents in {0, 30_000, 60_000}
        assert e.care_due
        if ext == Extraordinary.YES:
            assert e.compensation_cents == 0 and e.status == "no_compensation"
        if e.reduction != "none":
            assert e.compensation_cents == 30_000


def test_chargeback_after_refund_flagged(world):
    w = world.model_copy(deep=True)
    c = next(c for c in w.coupons if c.id.endswith(":2A") and c.flight_id == mw.fid("NS31"))
    w.crm.append(CrmEvent(id="CRM-CB", coupon_id=c.id, at=mw.z("12:00"), kind="chargeback", amount_cents=51_000,
                          actor="acquirer", text="Chargeback"))
    e = by_seat(ents_for(w, "NS31", Extraordinary.NO), "2A")
    assert e.refund_due_cents == 0 and "chargeback" in e.reason
