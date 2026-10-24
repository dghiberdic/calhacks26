"""F8c: the 11 books invariants (THREAD_FILIP F8c). Green on a clean story; each catches a planted violation.

Plants go through the public API where one exists (a manual `post_entry`, a bad entitlement, a late refund, a
direct payment after an assignment notice); otherwise a raw INSERT into the append-only tables stands in for a bug
or an outside write (append-only blocks UPDATE/DELETE, not INSERT).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from books import Books, Forbidden
from contracts.models import CareCost, Claim, JournalLine

from .helpers import CONTROLLER, EOWYN, FixedClock, make_claim, make_decision, ts
from .pss import C14, FARE, NS31, NS100, SEATS100, VOUCHER_SEATS, crm_event, ent, eowyn, operated

DAY1 = ts("2025-01-25T07:00:00Z")
IDS = ["INV-1", "INV-1b", "INV-2", "INV-3", "INV-4", "INV-4b", "INV-5", "INV-6", "INV-7", "INV-7b", "INV-8", "INV-9a",
       "INV-9b", "INV-9c", "INV-10", "INV-11"]


def story(books: Books, clock: FixedClock, **kw):
    world, decisions, ents = eowyn(DAY1, knock_ons=True, **kw)
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    clock.set(ts("2025-01-27T09:00:00Z"))
    for e in [x for x in ents if x.flight_id == NS31][:6]:
        books.post_claim(make_claim(e, clock.now()), e, clock.now())
    return world, decisions, ents


def failing(books: Books) -> set[str]:
    return {r.id for r in books.invariants() if not r.ok}


def result(books: Books, iid: str):
    return next(r for r in books.invariants() if r.id == iid)


def line(account: str, dr: int = 0, cr: int = 0, **dims: str) -> JournalLine:
    return JournalLine(account=account, account_name="", dr_cents=dr, cr_cents=cr, dims=dims)


def manual(books: Books, kind: str, lines: list[JournalLine], **kw):
    return books.post_entry(kind=kind, event_date=date(2025, 1, 27), lines=lines, memo=f"planted {kind}",
                            known_at=books.clock.now(), preparer="controller:planted", **kw)


# ---------------------------------------------------------------- clean

def test_all_invariants_hold_on_the_clean_story(books: Books, clock: FixedClock):
    story(books, clock)
    res = books.invariants()
    assert [r.id for r in res] == IDS
    assert all(r.ok for r in res), [r for r in res if not r.ok]
    detail = {r.id: r.detail for r in res}
    assert detail["INV-4b"] == "Dr €16,320 (CRM bot) = Cr €16,320 (Books)"
    assert "5 cancelled" not in detail["INV-3"] and "= register 5 = OCC 5" in detail["INV-3"]
    assert "2 operated departures ≤ Eurocontrol 179" in detail["INV-3"]
    assert detail["INV-10"].startswith("32 refunded within 7 days · 20 refund drafts queued")


# ---------------------------------------------------------------- 1 · rollforward ties; 2141 subledger

def test_inv1_an_unmapped_2140_posting_breaks_the_tie(books: Books, clock: FixedClock):
    story(books, clock)
    manual(books, "sale", [line("4090", dr=100, cohort=EOWYN), line("2140", cr=100, cohort=EOWYN)])
    assert failing(books) == {"INV-1"}
    assert "rollforward" in result(books, "INV-1").detail


def test_inv1b_2141_without_a_claim_breaks_the_payable_subledger(books: Books, clock: FixedClock):
    story(books, clock)
    manual(books, "change_in_estimate", [line("4090", dr=500), line("2141", cr=500)])
    assert failing(books) == {"INV-1b"}


# ---------------------------------------------------------------- 2 · every JE balances

def test_inv2_an_unbalanced_entry_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    je = books.journal()[0]
    books._conn.execute("INSERT INTO books_je_lines(je_id, line_no, account, dr_cents, cr_cents, cohort, segment, "
                        "flight_id, dims) VALUES (?, 99, '6100', 1, 0, NULL, NULL, NULL, '{}')", [je.id])
    assert failing(books) == {"INV-2"}
    assert je.id in result(books, "INV-2").detail


# ---------------------------------------------------------------- 3 · completeness

def test_inv3_a_cancelled_flight_missing_from_the_register_is_caught(books: Books, clock: FixedClock):
    ghost = operated("NS999", "DUB", "LHR", "2025-01-24T09:30:00Z").model_copy(update={"status": "cancelled"})
    story(books, clock, extra_flights=[ghost])
    assert failing(books) == {"INV-3"}
    assert "not in register: NS999@2025-01-24" in result(books, "INV-3").detail


def test_inv3_a_cancellation_missing_from_the_ops_log_is_caught(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1, knock_ons=True)
    occ = world.ops_log[0].model_copy(update={"flight_ids": [f for f in world.ops_log[0].flight_ids if f != NS100]})
    books.post_storm(EOWYN, world.model_copy(update={"ops_log": [occ]}), decisions, ents, DAY1)
    assert failing(books) == {"INV-3"}
    assert f"missing from the OCC log: {NS100}" in result(books, "INV-3").detail


def test_inv3_more_departures_than_eurocontrol_counted_is_caught(books: Books, clock: FixedClock):
    story(books, clock, eurocontrol=1)
    assert failing(books) == {"INV-3"}
    assert "2 operated departures > Eurocontrol 1" in result(books, "INV-3").detail


# ---------------------------------------------------------------- 4 · ATL relieved once; 2125 nets to 0

def test_inv4_atl_relieved_outside_the_coupon_subledger_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    manual(books, "refund", [line("2100", dr=FARE), line("2120", cr=FARE)])
    assert failing(books) == {"INV-4"}
    assert "GL 2100" in result(books, "INV-4").detail


def test_inv4_a_coupon_relieved_twice_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    row = books.coupon_events(kind="relief")[0]
    books._conn.execute(
        "INSERT INTO books_coupon_events(coupon_id, flight_id, cohort, kind, channel, crm_event_id, fare_cents, "
        "taxes_cents, amount_cents, je_id, event_date, detail, known_at, recorded_at) VALUES "
        "(?, ?, ?, 'relief', 'voucher', NULL, ?, ?, 0, ?, '2025-01-24', 'planted', ?, ?)",
        [row["coupon_id"], row["flight_id"], row["cohort"], row["fare_cents"], row["taxes_cents"], row["je_id"],
         row["known_at"], row["recorded_at"]])
    assert "INV-4" in failing(books)
    assert f"{row['coupon_id']} relieved 2×" in result(books, "INV-4").detail


def test_inv4b_a_double_refund_leaves_2125_open_and_is_caught(books: Books, clock: FixedClock):
    world, _d, _e = story(books, clock)
    coupon = f"{NS31}:{VOUCHER_SEATS[0]}"
    bot = crm_event("CRM-REF-DBL", coupon, "2025-01-27T10:00:00Z", "refund_initiated", 51_000,
                    actor="agent.crm_bot")
    clock.set(ts("2025-01-27T12:00:00Z"))
    books.post_operations(EOWYN, world.model_copy(update={"crm": world.crm + [bot]}), clock.now())
    assert failing(books) == {"INV-4b"}
    assert f"double refunds: {coupon}" in result(books, "INV-4b").detail


# ---------------------------------------------------------------- 5 · one payment per coupon; ≤ entitlement; assignment

def test_inv5_two_payouts_on_one_coupon_are_caught(books: Books, clock: FixedClock):
    story(books, clock)
    c = f"{NS31}:9A"
    for _ in range(2):
        manual(books, "claim_paid", [line("2141", dr=100, coupon=c), line("1000", cr=100, coupon=c)], gated=True)
    assert failing(books) == {"INV-5"}
    assert f"{c}: 2 payout entries" in result(books, "INV-5").detail


def test_inv5_paid_above_the_entitlement_is_caught(books: Books, clock: FixedClock):
    _w, _d, ents = story(books, clock)
    e = [x for x in ents if x.flight_id == NS31][10].model_copy(update={"compensation_cents": 90_000})
    books.post_claim(make_claim(e, clock.now()), e, clock.now())
    assert failing(books) == {"INV-5"}
    assert "paid €900 > entitlement €600" in result(books, "INV-5").detail


def test_inv5_a_direct_payment_after_an_assignment_notice_does_not_discharge(books: Books, clock: FixedClock):
    _w, _d, ents = story(books, clock)
    e = [x for x in ents if x.flight_id == NS31][20]
    clock.set(ts("2025-01-28T09:00:00Z"))
    assert books.post_claim(make_claim(e, clock.now(), n=1), e, clock.now())          # paid directly on the 28th
    agency = Claim(id="CLM-AGENCY-1", coupon_id=e.coupon_id, received_at=ts("2025-01-26T08:00:00Z"),
                   channel="agency", agency="FlightRight-like", authority="assignment", amount_claimed_cents=60_000,
                   text="Assignment of claim (notified 26 Jan).")
    clock.set(ts("2025-01-29T09:00:00Z"))
    assert books.post_claim(agency, e, clock.now()) == []                              # not paid twice
    assert failing(books) == {"INV-5"}
    assert "after the assignment notice of 2025-01-26 (does not discharge)" in result(books, "INV-5").detail


# ---------------------------------------------------------------- 6 · 0 ≤ liability ≤ unclaimed entitlement

def test_inv6_liability_above_unclaimed_entitlement_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    manual(books, "change_in_estimate", [line("4090", dr=50_000_000, cohort=EOWYN, segment="long_haul_gt3500"),
                                         line("2140", cr=50_000_000, cohort=EOWYN, segment="long_haul_gt3500")],
           ias8_class="change_in_estimate")
    assert failing(books) == {"INV-6"}


# ---------------------------------------------------------------- 7 · extraordinary → no compensation; links

def test_inv7_compensation_on_an_extraordinary_flight_is_caught(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1)
    bad = [e.model_copy(update={"status": "owed", "compensation_cents": 25_000}) if e.flight_id == NS100 else e
           for e in ents]                                                   # NS100's decision says extraordinary
    books.post_storm(EOWYN, world, decisions, bad, DAY1)
    assert failing(books) == {"INV-7"}
    assert f"{NS100}: 186 coupons with compensation" in result(books, "INV-7").detail


def test_inv7_care_issued_but_not_accrued_is_caught(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1)
    extra = CareCost(id="CARE-NS33-MEAL", flight_id="NS33@2025-01-24", kind="meal", amount_cents=50_000,
                     vendor="v", at=ts("2025-01-24T20:00:00Z"))
    books.post_storm(EOWYN, world.model_copy(update={"care": world.care + [extra]}), decisions, ents, DAY1)
    assert failing(books) == {"INV-7"}
    assert "NS33@2025-01-24: care issued but not accrued" in result(books, "INV-7").detail


def test_inv7b_an_entitlement_without_a_decision_is_caught(books: Books, clock: FixedClock):
    world, _decisions, ents = eowyn(DAY1)
    books.post_storm(EOWYN, world, [make_decision("NS100", DAY1)], ents, DAY1)  # NS31 posted with no decision
    assert failing(books) == {"INV-7b"}


# ---------------------------------------------------------------- 8 · no offset without a signed hash

def test_inv8_an_offset_without_a_signature_is_caught(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1)
    bad = [e.model_copy(update={"voucher_offset_cents": 30_000}) if e.coupon_id == C14 else e for e in ents]
    books.post_storm(EOWYN, world, decisions, bad, DAY1)
    assert failing(books) == {"INV-8"}
    assert f"{C14}: offset €300 with no signed acceptance" in result(books, "INV-8").detail
    approval = next(j for j in books.post_claim(make_claim(ent(C14, bad), DAY1), ent(C14, bad), DAY1)
                    if j.kind == "claim_approved")
    assert sum(l.dr_cents for l in approval.lines if l.account == "2140") == 60_000    # and post_claim pays cash


# ---------------------------------------------------------------- 9 · SoD, locks, derecognition

def test_inv9a_an_approval_by_the_preparer_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    je = next(j for j in books.journal() if j.kind == "compensation_estimate")
    books._conn.execute("INSERT INTO books_je_events(je_id, kind, principal, role, reason, at) VALUES "
                        "(?, 'approved', ?, 'controller', NULL, '2025-01-27T10:00:00.000000Z')", [je.id, je.preparer])
    assert failing(books) == {"INV-9a"}


def test_inv9b_a_write_into_a_locked_period_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    je = next(j for j in books.journal() if j.kind == "compensation_estimate")
    books._conn.execute("INSERT INTO books_je_events(je_id, kind, principal, role, reason, at) VALUES "
                        "(?, 'approved', 'controller:late', 'controller', NULL, '2025-02-04T09:00:00.000000Z')",
                        [je.id])
    assert failing(books) == {"INV-9b"}


def test_inv9c_derecognition_before_limitation_needs_a_controller_rule(books: Books, clock: FixedClock):
    story(books, clock)
    manual(books, "derecognition", [line("2140", dr=1_000, cohort=EOWYN, segment="long_haul_gt3500"),
                                    line("4090", cr=1_000, cohort=EOWYN, segment="long_haul_gt3500")])
    assert failing(books) == {"INV-9c"}
    assert "before limitation, no Controller rule" in result(books, "INV-9c").detail


def test_inv9c_controller_rule_allows_early_derecognition_and_limitation_needs_none(books: Books, clock: FixedClock):
    story(books, clock)
    with pytest.raises(Forbidden):
        books.derecognise(EOWYN, clock.now())                                  # no rule, no Controller
    je = books.derecognise(EOWYN, clock.now(), CONTROLLER, rule_ref="R-CTL-9@1")
    assert je.kind == "derecognition" and je.status == "draft" and "R-CTL-9@1" in je.memo
    assert books.gl_balance("2140", cohort=EOWYN) == 0
    assert not failing(books)


# ---------------------------------------------------------------- 10 · refunds within 7 days

def test_inv10_a_refund_paid_after_7_days_is_caught(books: Books, clock: FixedClock):
    coupon = f"{NS100}:{SEATS100[100]}"                                         # reaccommodated, then refunded late
    late = crm_event("CRM-LATE", coupon, "2025-02-04T10:00:00Z", "refund_initiated", 12_000, actor="agent.crm_bot")
    world, decisions, ents = eowyn(DAY1, extra_crm=[late])
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    clock.set(ts("2025-02-04T12:00:00Z"))
    books.post_operations(EOWYN, world, clock.now())
    assert failing(books) == {"INV-10"}
    assert f"{coupon}: refunded 2025-02-04, after 2025-01-31" in result(books, "INV-10").detail
    assert books.cfo_metrics(clock.now()).refunds_within_7d_pct == round(100 * 52 / 53, 1)


def test_inv10_a_refund_elected_but_never_drafted_is_caught_after_7_days(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1)
    lost = f"{NS100}:{SEATS100[0]}"
    world = world.model_copy(update={"coupons": [c for c in world.coupons if c.id != lost]})   # no PSS row
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert not failing(books)                                                   # not due yet
    clock.set(ts("2025-01-24T00:00:00Z") + timedelta(days=8))
    assert failing(books) == {"INV-10"}
    assert f"{lost}: refund elected, none drafted by 2025-01-31" in result(books, "INV-10").detail


# ---------------------------------------------------------------- 11 · cut-off

def test_inv11_an_entry_outside_its_event_period_is_caught(books: Books, clock: FixedClock):
    story(books, clock)
    books._conn.execute(
        "INSERT INTO books_je(je_id, event_date, period, kind, memo, ias8_class, reverses, estimate_ref, "
        "source_decision_id, preparer, built_from, ties_to, gated, run_id, cohort, flight_id, flags, known_at, "
        "recorded_at) VALUES ('JE-900001', '2025-01-24', '2025-02', 'care_accrual', 'planted', 'none', NULL, NULL, "
        "NULL, 'agent.engine', 0, '[]', 0, NULL, NULL, NULL, '{}', '2025-01-27T09:00:00.000000Z', "
        "'2025-01-27T09:00:00.000000Z')")
    books._conn.executemany(
        "INSERT INTO books_je_lines(je_id, line_no, account, dr_cents, cr_cents, cohort, segment, flight_id, dims) "
        "VALUES ('JE-900001', ?, ?, ?, ?, NULL, NULL, NULL, '{}')", [(1, "6100", 100, 0), (2, "2000", 0, 100)])
    assert failing(books) == {"INV-11"}
    assert "JE-900001" in result(books, "INV-11").detail
