"""F8c: the CFO view (bridge + method range), estimate-card polish and audit(je_id)."""
from __future__ import annotations

import pytest

from books import Books, NotFound
from books.reporting import cfo_bridge

from .helpers import (
    CLAIMS_LEAD,
    CONTROLLER,
    EOWYN,
    ISHA,
    KNOCK_ONS,
    FixedClock,
    flight_id,
    isha_opening,
    make_claim,
    recode_to_extraordinary,
    ts,
)
from .pss import NS31, eowyn, invoice_rows

DAY1 = ts("2025-01-25T07:00:00Z")


def day1(books: Books, **kw):
    world, decisions, ents = eowyn(DAY1, knock_ons=True, **kw)
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    return world, decisions, ents, jes


def to_feb(books: Books, clock: FixedClock, ents) -> None:
    """R-LEG-1, 6 Jan claims, 16 Feb claims (15 × €600 + 1 × €300), Feb invoices, Feb month end."""
    knock = [e for e in ents if e.flight_id in {flight_id(n) for n in KNOCK_ONS}]
    clock.set(ts("2025-01-25T10:30:00Z"))
    books.post_recode(knock, recode_to_extraordinary(knock), clock.now())
    ns31 = [e for e in ents if e.flight_id == NS31]
    full, half = [e for e in ns31 if e.compensation_cents == 60_000], [e for e in ns31 if e.compensation_cents == 30_000]
    for i, e in enumerate(full[:6]):
        clock.set(ts(f"2025-01-{26 + i:02d}T09:00:00Z"))
        books.post_claim(make_claim(e, clock.now()), e, clock.now())
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    for i, e in enumerate(full[6:21] + half[:1]):
        clock.set(ts(f"2025-02-{4 + i:02d}T09:00:00Z"))
        books.post_claim(make_claim(e, clock.now()), e, clock.now())
    clock.set(ts("2025-02-28T12:00:00Z"))
    books.post_care_invoices(EOWYN, invoice_rows(), clock.now())
    clock.set(ts("2025-02-28T22:00:00Z"))
    books.month_end("2025-02", clock.now())


# ---------------------------------------------------------------- CFO

def test_cfo_bridge_day1_with_knock_ons_held_for_legal(books: Books):
    day1(books)
    m = books.cfo_metrics(DAY1)
    assert cfo_bridge(m) == "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)"
    assert (m.cash_basis_cents, m.full_entitlement_cents, m.drafted_liability_cents, m.sensitivity_5pp_cents) == (
        0, 9_900_000, 3_465_000, 495_000)
    assert m.held_for_legal_cents == 4_749_600                         # 1,922,400 + 1,987,200 + 840,000
    assert m.drafted_liability_cents + m.held_for_legal_cents == books.gl_balance("2140") == 8_214_600
    assert m.method_range_cents == (3_465_000, 3_465_000)              # no development yet: the methods agree
    assert (m.recodes_count, m.recodes_cents) == (1, 3_465_000)         # NS31 71 → 41
    assert m.vouchers_outstanding_cents == 714_000 + 30_000           # 2131 refund vouchers + 2132 14C goodwill
    assert (m.care_accrued_cents, m.care_invoiced_cents) == (22_700_000, 0)
    assert m.refunds_within_7d_pct == 100.0
    assert m.liability_bridge == books.rollforward("2025-01").rows
    assert books.cfo_metrics(DAY1, cohort=EOWYN) == m


def test_cfo_after_the_ruling_and_the_feb_true_up(books: Books, clock: FixedClock):
    _w, _d, ents, _ = day1(books)
    to_feb(books, clock, ents)
    m = books.cfo_metrics(clock.now())
    assert (m.full_entitlement_cents, m.drafted_liability_cents, m.held_for_legal_cents) == (9_900_000, 2_574_000, 0)
    assert m.method_range_cents == (2_175_000, 3_726_667)              # expected-loss … chain-ladder; BF 2,574,000
    assert (m.care_accrued_cents, m.care_invoiced_cents) == (22_700_000, 22_130_000)
    assert cfo_bridge(m) == "Cash basis €0 · full entitlement €99,000 · drafted €25,740 (±5pp ±€4,950)"
    pay = next(j for j in books.journal(status="draft") if j.kind == "claim_paid" and j.period == "2025-02")
    books.approve(pay.id, CLAIMS_LEAD)
    assert books.cfo_metrics(clock.now()).cash_basis_cents == 60_000   # cash only once the Claims Lead releases it


def test_cfo_headline_is_storm_cohorts_and_migrated_balances_sit_in_the_bridge(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1)
    world = world.model_copy(update={"opening_balances": [isha_opening()]})
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    m = books.cfo_metrics(DAY1)
    assert (m.full_entitlement_cents, m.drafted_liability_cents) == (9_900_000, 3_465_000)
    assert {r.cohort for r in m.liability_bridge} == {EOWYN, ISHA}
    isha = books.cfo_metrics(DAY1, cohort=ISHA)
    assert (isha.full_entitlement_cents, isha.drafted_liability_cents) == (6_000_000, 360_000)
    with pytest.raises(NotFound):
        books.cfo_metrics(DAY1, cohort="EIDW@1999-01-01")


# ---------------------------------------------------------------- estimate card

def test_estimate_card_day1_then_approved_with_held_note_and_segments(books: Books):
    day1(books)
    card = books.estimate_card(EOWYN, DAY1)
    assert card.segment == "mixed" and card.curve_version == "LH-v1+MH-v1+SH-v1"
    assert card.ias8_class == "none" and card.approver is None and card.preparer == "agent.engine"
    assert card.bf_cents == card.expected_loss_cents == card.chain_ladder_cents == 8_214_600
    assert "€47,496 of the estimate is on entitlement held pending Legal" in card.constraint_note
    assert "IAG approach" in card.constraint_note
    lh = books.estimate_card(EOWYN, DAY1, segment="long_haul_gt3500")
    assert (lh.segment, lh.pax, lh.entitlement_cents, lh.bf_cents) == ("long_haul_gt3500", 172, 9_900_000, 3_465_000)
    assert "held pending Legal" not in lh.constraint_note
    for je in books.journal(status="draft"):
        if je.kind == "compensation_estimate":
            books.approve(je.id, CONTROLLER)
    assert books.estimate_card(EOWYN, DAY1).approver == CONTROLLER.principal


def test_estimate_card_after_feb_is_a_change_in_estimate_pending_approval(books: Books, clock: FixedClock):
    _w, _d, ents, _ = day1(books)
    to_feb(books, clock, ents)
    card = books.estimate_card(EOWYN, clock.now())
    assert (card.segment, card.bf_cents, card.actual_vs_expected, card.months_developed) == (
        "long_haul_gt3500", 2_574_000, 1.448, 1)
    assert card.ias8_class == "change_in_estimate" and card.approver is None
    assert card.credibility_z == round(9 / 35, 3)
    with pytest.raises(NotFound):
        books.estimate_card("EIDW@1999-01-01", clock.now())


# ---------------------------------------------------------------- audit

def test_audit_of_the_ns31_estimate_traces_to_register_and_decision(books: Books):
    _w, _d, _e, jes = day1(books)
    est = next(j for j in jes if j.kind == "compensation_estimate" and j.lines[0].dims["flight"] == NS31)
    a = books.audit(est.id)
    assert a["je"]["id"] == est.id and [x["line_id"] for x in a["lines"]] == [f"{est.id}:1", f"{est.id}:2"]
    assert a["blame_target"] == f"{est.id}:2"                         # the 2140 line
    assert a["register_count"] == 172 and len(a["register"]) == 50
    assert a["decision_commits"] == ["commit-NS31"]
    assert a["decisions"][0]["cause"] == "technical" and a["decisions"][0]["recoded"] is True
    assert a["events"][0]["kind"] == "drafted" and a["period"] == {"period": "2025-01", "locked": False,
                                                                   "locked_at": None}
    assert a["ties"] == {"2140": 8_214_600, "4090": 8_214_600 + 30_000}   # + 14C's €300 goodwill voucher


def test_audit_of_the_2125_clearing_lists_its_32_coupons(books: Books):
    _w, _d, _e, jes = day1(books)
    clear = next(j for j in jes if j.kind == "refund" and j.preparer == "agent.engine"
                 and j.lines[0].dims["flight"] == NS31)
    a = books.audit(clear.id)
    assert a["coupon_events_count"] == 32 and {r["channel"] for r in a["coupon_events"]} == {"crm_bot"}
    assert a["register_count"] == 32 and a["ties"]["2125"] == 0


def test_audit_of_care_bf_and_unknown(books: Books, clock: FixedClock):
    _w, _d, ents, jes = day1(books)
    care = next(j for j in jes if j.kind == "care_accrual")
    assert len(books.audit(care.id)["care"]) == 5
    to_feb(books, clock, ents)
    bf = next(j for j in books.journal(period="2025-02") if (j.estimate_ref or "").startswith("BF:")
              and j.lines[0].dims["segment"] == "long_haul_gt3500")
    a = books.audit(bf.id)
    assert a["register_count"] == 172                                  # built from the cohort's owed coupons
    assert a["period"]["locked"] is False and a["ties"]["2140"] == books.gl_balance("2140", period="2025-02")
    with pytest.raises(NotFound):
        books.audit("JE-999999")


# ---------------------------------------------------------------- derecognition at limitation

def test_month_end_derecognises_at_limitation(books: Books, clock: FixedClock):
    clock.set(ts("2025-01-31T22:00:00Z"))
    books.post_storm(ISHA, eowyn(DAY1)[0].model_copy(update={"opening_balances": [isha_opening()], "flights": [],
                                                             "coupons": [], "care": []}), [], [], clock.now())
    books.keep_tail("R-CTL-1@1", None, clock.now())
    clock.set(ts("2030-01-31T22:00:00Z"))                              # Isha 2024-01-21 + 6 years
    jes = books.month_end("2030-01", clock.now())
    assert [j.kind for j in jes] == ["derecognition"]
    assert sum(l.dr_cents for l in jes[0].lines if l.account == "2140") == 360_000
    assert "limitation" in jes[0].memo and "Moré" in jes[0].memo
    row = next(r for r in books.rollforward("2030-01").rows if r.cohort == ISHA)
    assert (row.derecognised_cents, row.closing_cents, row.unclaimed_entitlement_cents) == (360_000, 0, 0)
    assert books.month_end("2030-01", clock.now()) == jes              # once
    assert not [r for r in books.invariants() if not r.ok]
