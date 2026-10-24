"""F8b: the remaining postings, exact cents per IMPLEMENTATION_PLAN §1.3 (sale, refunds via 2125, vouchers, FIM,
reaccommodation, vouchers in lieu, care, recodes, IAS 8.5 out-of-period adjustment)."""
from __future__ import annotations

from collections import Counter
from datetime import date
from fractions import Fraction

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from books import Books, BooksError
from books.money import round_half_up
from contracts.models import Cause, Coupon, CrmEvent, Election, Extraordinary, JournalEntry

from .helpers import (
    CONTROLLER,
    EOWYN,
    FixedClock,
    cr,
    dr,
    liability_delta,
    make_claim,
    make_decision,
    make_world,
    ts,
)
from .pss import (
    C14,
    FARE,
    FARE100,
    NS31,
    NS100,
    REACC_SEATS,
    REROUTE_SEATS,
    SEATS100,
    SIG,
    TAX,
    TAX100,
    VOUCHER_SEATS,
    crm_event,
    ent,
    eowyn,
    invoice_rows,
)

DAY1 = ts("2025-01-25T07:00:00Z")


def day1(books: Books, **kw) -> tuple:
    world, decisions, ents = eowyn(DAY1, **kw)
    return world, decisions, ents, books.post_storm(EOWYN, world, decisions, ents, DAY1)


def only(jes: list[JournalEntry], kind: str, flight: str | None = None, preparer: str | None = None) -> JournalEntry:
    hits = [j for j in jes if j.kind == kind and (flight is None or j.lines[0].dims.get("flight") == flight)
            and (preparer is None or j.preparer == preparer)]
    assert len(hits) == 1, [(j.id, j.kind, j.memo[:60]) for j in hits]
    return hits[0]


def balanced(je: JournalEntry) -> bool:
    return sum(l.dr_cents for l in je.lines) == sum(l.cr_cents for l in je.lines) > 0


# ---------------------------------------------------------------- sale

def test_sale_fares_incl_yq_yr_to_atl_and_taxes_to_2110(books: Books):
    *_, jes = day1(books, ns100=False)
    sale = only(jes, "sale", NS31)
    assert dr(sale, "1110") == 8_772_000                          # 172 × (€450 + €60)
    assert cr(sale, "2100") == 7_740_000 and cr(sale, "2110") == 1_032_000    # ATL €77,400 · taxes €10,320
    assert "YQ/YR" in sale.memo and sale.event_date == date(2025, 1, 24) and sale.built_from == 172
    assert len(books.coupon_events(kind="sale")) == 172
    # the sale is the PSS's own posting: recorded as posted, never a StormCheck draft to approve
    assert sale.status == "posted" and sale.preparer == "system.pss"
    assert sale.id in {j.id for j in books.journal(status="posted")}
    with pytest.raises(BooksError):
        books.approve(sale.id, CONTROLLER)


# ---------------------------------------------------------------- refunds: CRM bot via 2125, BSP duplicate

def test_crm_bot_refunds_clear_2125_to_zero_and_bsp_duplicate_is_detected(books: Books):
    *_, jes = day1(books, ns100=False)
    bot = only(jes, "refund", preparer="agent.crm_bot")
    assert dr(bot, "2125") == 1_632_000 and cr(bot, "1110") == 1_632_000 and bot.status == "posted"
    clear = only(jes, "refund", NS31, preparer="agent.engine")
    assert clear.status == "draft"
    assert dr(clear, "2100") == 1_440_000 and dr(clear, "2110") == 192_000      # ATL €14,400 + tax €1,920
    assert cr(clear, "2125") == 1_632_000 and {l.account for l in clear.lines} == {"2100", "2110", "2125"}
    assert books.gl_balance("2125") == 0                                         # no double refund
    dups = books.coupon_events(kind="duplicate")
    assert [(d["coupon_id"], d["channel"], d["crm_event_id"]) for d in dups] == [
        (f"{NS31}:1A", "bsp", "CRM-BSP-DUP")]
    assert [e["channel"] for e in books.coupon_events(coupon_id=f"{NS31}:1A") if e["kind"] == "relief"] == [
        "crm_bot"]
    assert books.gl_balance("2120") == 0                                         # the BSP refund was never posted


def test_refund_vouchers_at_ticket_value_incl_taxes(books: Books):
    *_, jes = day1(books, ns100=False)
    v = only(jes, "voucher", NS31)
    assert cr(v, "2131") == 714_000 and dr(v, "2100") == 630_000 and dr(v, "2110") == 84_000   # €7,140


def test_partner_reroutes_fim_net_to_interline_payable(books: Books):
    *_, jes = day1(books, ns100=False)
    fim = only(jes, "reroute_fim", NS31)
    assert cr(fim, "2160") == 714_000 and dr(fim, "2100") == 630_000 and dr(fim, "2110") == 84_000
    assert dr(fim, "6110") == 0 and "IATA SIS" in fim.memo


def test_reroute_fim_excess_goes_to_rerouting(books: Books):
    world, decisions, ents = eowyn(DAY1, ns100=False)
    fims = {f"{NS31}:{s}": 55_000 for s in REROUTE_SEATS}
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1, fim_values=fims)
    fim = only(jes, "reroute_fim", NS31)
    assert cr(fim, "2160") == 770_000 and dr(fim, "6110") == 56_000 and balanced(fim)


def test_interline_bill_clears_2160_with_excess_to_6110(books: Books, clock: FixedClock):
    day1(books, ns100=False)
    clock.set(ts("2025-03-20T09:00:00Z"))
    bill = books.post_interline_bill(NS31, 750_000, clock.now(), bill_ref="SIS-2025-03-BA-0042")
    assert dr(bill, "2160") == 714_000 and dr(bill, "6110") == 36_000 and cr(bill, "2000") == 750_000
    assert books.gl_balance("2160") == 0 and bill.period == "2025-03"
    assert books.post_interline_bill(NS31, 750_000, clock.now(), bill_ref="SIS-2025-03-BA-0042").id == bill.id


# ---------------------------------------------------------------- reaccommodation and ATL relieved once

def test_reaccommodated_own_stays_in_atl(books: Books):
    day1(books, ns100=False)
    assert books.gl_balance("2100") == 112 * FARE == 5_040_000          # revenue is recognised when they fly
    assert books.gl_balance("2110") == 112 * TAX == 672_000
    relieved = {e["coupon_id"] for e in books.coupon_events(kind="relief")}
    assert not relieved & {f"{NS31}:{s}" for s in REACC_SEATS}


def test_atl_relieved_exactly_once_per_coupon_and_reruns_post_nothing(books: Books):
    world, decisions, ents, jes = day1(books)
    reliefs = Counter(e["coupon_id"] for e in books.coupon_events(kind="relief"))
    assert set(reliefs.values()) == {1}
    assert len(reliefs) == 32 + 14 + 14 + 20
    gl = {a: books.gl_balance(a) for a in ("2100", "2110", "2120", "2125", "2131", "2160", "2140", "2150")}
    again = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert {j.id for j in again} == {j.id for j in jes}
    assert books.post_operations(EOWYN, world, DAY1) == []
    assert {a: books.gl_balance(a) for a in gl} == gl


def test_refund_elected_without_payment_is_queued_then_the_bot_pays_it(books: Books, clock: FixedClock):
    world, _decisions, _ents, jes = day1(books)
    queued = only(jes, "refund", NS100)
    assert dr(queued, "2100") == 20 * FARE100 and dr(queued, "2110") == 20 * TAX100
    assert cr(queued, "2120") == 240_000 and "queued" in queued.memo
    clock.set(ts("2025-01-26T09:00:00Z"))
    paid = [crm_event(f"CRM-REF-100-{i}", f"{NS100}:{s}", "2025-01-26T08:00:00Z", "refund_initiated",
                      FARE100 + TAX100, actor="agent.crm_bot") for i, s in enumerate(SEATS100[:5])]
    world2 = world.model_copy(update={"crm": world.crm + paid})
    new = books.post_operations(EOWYN, world2, clock.now())
    bot = only(new, "refund", preparer="agent.crm_bot")
    settle = only(new, "refund", NS100, preparer="agent.engine")
    assert dr(bot, "2125") == 60_000 and dr(settle, "2120") == 60_000 and cr(settle, "2125") == 60_000
    assert books.gl_balance("2125") == 0 and books.gl_balance("2120") == 180_000
    assert set(Counter(e["coupon_id"] for e in books.coupon_events(kind="relief")).values()) == {1}


def test_bsp_refund_then_bot_refund_is_flagged_and_2125_still_nets_to_zero(books: Books, clock: FixedClock):
    coupon = f"{NS100}:{SEATS100[0]}"
    extra = [crm_event("CRM-BSP-100", coupon, "2025-01-24T12:00:00Z", "bsp_refund", 12_000, actor="bsp")]
    world, _decisions, _ents, jes = day1(books, extra_crm=extra)
    bsp = [j for j in jes if j.kind == "refund" and "BSP" in j.memo]
    assert len(bsp) == 1 and cr(bsp[0], "2120") == 12_000
    clock.set(ts("2025-01-27T09:00:00Z"))
    bot = crm_event("CRM-REF-100-X", coupon, "2025-01-27T08:00:00Z", "refund_initiated", 12_000,
                    actor="agent.crm_bot")
    books.post_operations(EOWYN, world.model_copy(update={"crm": world.crm + [bot]}), clock.now())
    assert books.gl_balance("2125") == 0
    flags = [d for d in books.coupon_events(coupon_id=coupon) if d["kind"] == "duplicate"]
    assert len(flags) == 1 and "recall" in flags[0]["detail"]


def test_bot_refund_on_a_voucher_coupon_is_a_double_refund_left_open_in_2125(books: Books, clock: FixedClock):
    world, _decisions, _ents, _ = day1(books, ns100=False)
    coupon = f"{NS31}:{VOUCHER_SEATS[0]}"
    clock.set(ts("2025-01-26T09:00:00Z"))
    bot = crm_event("CRM-REF-DBL", coupon, "2025-01-26T08:00:00Z", "refund_initiated", FARE + TAX,
                    actor="agent.crm_bot")
    books.post_operations(EOWYN, world.model_copy(update={"crm": world.crm + [bot]}), clock.now())
    assert books.gl_balance("2125") == -(FARE + TAX)                       # debit balance: cash out twice
    assert [e["kind"] for e in books.coupon_events(coupon_id=coupon)] == ["sale", "relief", "bot_refund",
                                                                         "double_refund"]


def test_chargeback_without_refund_relieves_atl_against_the_acquirer(books: Books):
    coupon = f"{NS31}:{REACC_SEATS[0]}"
    extra = [crm_event("CRM-CB-1", coupon, "2025-01-24T18:00:00Z", "chargeback", FARE + TAX, actor="acquirer")]
    *_, jes = day1(books, ns100=False, extra_crm=extra)
    cb = [j for j in jes if j.kind == "refund" and "chargeback" in j.memo]
    assert len(cb) == 1 and cr(cb[0], "1110") == FARE + TAX and dr(cb[0], "2100") == FARE
    assert books.gl_balance("2100") == 111 * FARE


# ---------------------------------------------------------------- vouchers in lieu of compensation

def test_unsigned_in_lieu_voucher_is_goodwill_then_cash_claim_then_void(books: Books, clock: FixedClock):
    _world, _decisions, ents, jes = day1(books, ns100=False)
    vil = only(jes, "voucher_in_lieu", NS31)
    assert dr(vil, "4090") == 30_000 and cr(vil, "2132") == 30_000 and dr(vil, "2140") == 0
    assert books.gl_balance("2140") == 3_465_000                                # the estimate is untouched
    assert vil.lines[0].dims["coupon"] == C14 and "no signed acceptance" in vil.memo

    # after R-CL-1 ("no signed acceptance, no offset"): the €600 is owed in cash at face value
    e14 = ent(C14, ents).model_copy(update={"status": "owed", "rules_applied": ["R-CL-1@1"]})
    clock.set(ts("2025-01-26T09:00:00Z"))
    approval = next(j for j in books.post_claim(make_claim(e14, clock.now()), e14, clock.now())
                    if j.kind == "claim_approved")
    assert dr(approval, "2140") == 60_000 and cr(approval, "2141") == 60_000

    # unredeemed → void: Dr 2132 / Cr 4090
    clock.set(ts("2025-03-01T09:00:00Z"))
    void = books.void_voucher(C14, clock.now())
    assert void.kind == "voucher_void" and dr(void, "2132") == 30_000 and cr(void, "4090") == 30_000
    assert void.reverses == vil.id and books.gl_balance("2132") == 0
    assert books.void_voucher(C14, clock.now()).id == void.id               # idempotent


def test_signed_in_lieu_voucher_settles_in_kind(books: Books, clock: FixedClock):
    _world, _decisions, ents, jes = day1(books, ns100=False, in_lieu_signed=SIG)
    vil = only(jes, "voucher_in_lieu", NS31)
    assert dr(vil, "2140") == 30_000 and cr(vil, "2132") == 30_000 and dr(vil, "4090") == 0
    assert books.gl_balance("2140") == 3_465_000 - 30_000
    row = books.register(coupon_id=C14)[0]
    assert row["settlement"] == "in_kind" and row["voucher_signed_sha256"] == SIG and vil.id in row["je_ids"]
    rf = books.rollforward("2025-01")
    assert rf.ties_to_gl and rf.rows[0].settled_in_kind_cents == 30_000
    # the residual €300 stays claimable (Art. 15(2)): approved at face value net of the signed offset
    e14 = ent(C14, ents).model_copy(update={"voucher_offset_cents": 30_000})
    clock.set(ts("2025-01-28T09:00:00Z"))
    approval = next(j for j in books.post_claim(make_claim(e14, clock.now()), e14, clock.now())
                    if j.kind == "claim_approved")
    assert dr(approval, "2140") == 30_000
    with pytest.raises(BooksError):
        books.void_voucher(C14, clock.now())


def test_an_offset_without_a_signed_hash_is_never_applied(books: Books, clock: FixedClock):
    _world, _decisions, ents, _ = day1(books, ns100=False)                       # 14C unsigned
    e14 = ent(C14, ents).model_copy(update={"voucher_offset_cents": 30_000})  # a rule tried to offset it
    approval = next(j for j in books.post_claim(make_claim(e14, DAY1), e14, DAY1) if j.kind == "claim_approved")
    assert dr(approval, "2140") == 60_000 and "offset denied" in approval.memo


# ---------------------------------------------------------------- care

def test_care_accrual_then_invoice_true_up(books: Books, clock: FixedClock):
    _world, _decisions, _ents, jes = day1(books)
    acc = only(jes, "care_accrual")
    assert dr(acc, "6100") == 22_700_000 and cr(acc, "2150") == 22_700_000 and acc.period == "2025-01"
    assert "McDonagh" in acc.memo
    clock.set(ts("2025-02-28T12:00:00Z"))
    inv = books.post_care_invoices(EOWYN, invoice_rows(), clock.now())
    assert len(inv) == 1 and inv[0].kind == "care_invoice" and inv[0].period == "2025-02"
    assert dr(inv[0], "2150") == 22_700_000 and cr(inv[0], "2000") == 22_130_000 and cr(inv[0], "6100") == 570_000
    assert books.gl_balance("2150") == 0 and books.gl_balance("6100") == 22_130_000
    assert books.post_care_invoices(EOWYN, invoice_rows(), clock.now()) == []          # idempotent


def test_care_invoices_in_the_world_post_once_they_are_known(books: Books, clock: FixedClock):
    world, decisions, ents = eowyn(DAY1, invoices=True)
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert not [j for j in jes if j.kind == "care_invoice"]                         # dated Feb: not known yet
    clock.set(ts("2025-02-28T12:00:00Z"))
    inv = only(books.post_operations(EOWYN, world, clock.now()), "care_invoice")
    assert cr(inv, "6100") == 570_000 and books.gl_balance("2150") == 0


# ---------------------------------------------------------------- recodes (weather ↔ technical / extraordinary)

def test_recode_weather_to_technical_and_back(books: Books, clock: FixedClock):
    _world, _decisions, ents, _ = day1(books)
    before = [e for e in ents if e.flight_id == NS100]
    assert books.gl_balance("2140") == 3_465_000                                 # NS100 weather: nil
    tech = [e.model_copy(update={"status": "owed", "compensation_cents": 25_000, "article": "EU261 Art.7(1)(a)"})
            for e in before]
    dec = make_decision("NS100", DAY1).model_copy(update={"cause": Cause.TECHNICAL, "extraordinary": Extraordinary.NO,
                                                          "recoded": True, "recode_label": "71 → 41",
                                                          "commit": "commit-NS100-r"})
    clock.set(ts("2025-01-26T09:00:00Z"))
    up = books.post_recode(before, tech, clock.now(), decisions=[dec])
    assert len(up) == 1 and liability_delta(up[0]) == 930_000                    # 186 × €250 × 20%
    row = books.register(coupon_id=f"{NS100}:1A")[0]
    assert row["cause"] == "technical" and row["recoded"] and row["decision_commit"] == "commit-NS100-r"
    # a later Legal ruling makes it extraordinary again: the liability is released, refunds and care unchanged
    back = [e.model_copy(update={"status": "no_compensation", "compensation_cents": 0}) for e in tech]
    down = books.post_recode(tech, back, clock.now())
    assert liability_delta(down[0]) == -930_000 and books.gl_balance("2140") == 3_465_000
    assert books.gl_balance("2120") == 240_000 and books.gl_balance("2150") == 22_700_000


def test_weather_to_technical_with_evidence_before_the_lock_is_a_prior_period_error(books: Books,
                                                                                    clock: FixedClock):
    _world, _decisions, ents, _ = day1(books)
    before = [e for e in ents if e.flight_id == NS100]
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    jan = books.rollforward("2025-01")
    tech = [e.model_copy(update={"status": "owed", "compensation_cents": 25_000}) for e in before]
    jes = books.post_recode(before, tech, clock.now(), evidence_received_at=ts("2025-01-23T21:40:00Z"))
    assert len(jes) == 1
    je = jes[0]
    assert je.kind == "out_of_period_adjustment" and je.ias8_class == "prior_period_error" and je.period == "2025-02"
    sh = books.curve("short_le1500")                     # golden SH-v1: M1 5.14% → 4,650,000 × 14.86% = 690,990
    expected = round_half_up(4_650_000 * (Fraction(str(sh.ultimate)) - Fraction(str(dict(sh.points)[1]))))
    assert liability_delta(je) == expected > 0
    assert "prior-period error, corrected in current period (immaterial)" in je.memo
    assert books.rollforward("2025-01") == jan
    feb = books.rollforward("2025-02")
    assert feb.ties_to_gl and feb.rows[0].out_of_period_cents == expected


# ---------------------------------------------------------------- every entry balances

def test_every_entry_balances_across_the_whole_story(books: Books, clock: FixedClock):
    _world, _decisions, ents, _ = day1(books, knock_ons=True, in_lieu_signed=None)
    clock.set(ts("2025-01-26T09:00:00Z"))
    for e in [x for x in ents if x.flight_id == NS31][:6]:
        books.post_claim(make_claim(e, clock.now()), e, clock.now())
    clock.set(ts("2025-02-28T22:00:00Z"))
    books.post_care_invoices(EOWYN, invoice_rows(), clock.now())
    books.month_end("2025-02", clock.now())
    jes = books.journal()
    assert jes and all(balanced(j) for j in jes)
    kinds = {j.kind for j in jes}
    assert {"sale", "refund", "voucher", "reroute_fim", "voucher_in_lieu", "care_accrual", "care_invoice",
            "compensation_estimate", "claim_approved", "claim_paid", "change_in_estimate"} <= kinds
    assert books.gl_balance("2125") == 0
    assert all(r.ok for r in books.invariants()), [r for r in books.invariants() if not r.ok]


# ---------------------------------------------------------------- property: refund channels never relieve twice

COUPONS = [Coupon(id=f"NSP@2025-01-24:{i}", pnr=f"P{i}", pax_ref=f"pax:{i}", flight_id="NSP@2025-01-24",
                  fare_cents=10_000 + 100 * i, taxes_cents=2_000) for i in range(8)]
ELECTION_KINDS = ["refund", "voucher", "reroute_partner", "reaccommodated_own", "none"]
EVENT_KINDS = ["refund_initiated", "bsp_refund", "chargeback"]


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(elections=st.lists(st.integers(0, 4), min_size=8, max_size=8),
       events=st.lists(st.tuples(st.integers(0, 7), st.integers(0, 2), st.integers(0, 3)), max_size=20),
       split=st.integers(0, 20))
def test_random_refund_channels_relieve_atl_once_and_2125_tracks_double_refunds(elections, events, split):
    clock = FixedClock(ts("2025-01-25T07:00:00Z"))
    books = Books(":memory:", clock)
    crm = [CrmEvent(id=f"E{n}", coupon_id=COUPONS[c].id, at=ts(f"2025-01-{24 + day:02d}T10:00:00Z"),
                    kind=EVENT_KINDS[k], amount_cents=COUPONS[c].fare_cents + COUPONS[c].taxes_cents,
                    actor="agent.crm_bot" if k == 0 else "bsp", text="x")
           for n, (c, k, day) in enumerate(events)]
    world = make_world([]).model_copy(update={
        "coupons": COUPONS, "crm": crm,
        "elections": [Election(coupon_id=c.id, kind=ELECTION_KINDS[k], recorded_by="web")
                      for c, k in zip(COUPONS, elections, strict=True)]})
    early = world.model_copy(update={"crm": [e for e in crm if int(e.id[1:]) < split]})
    books.post_operations(EOWYN, early, ts("2025-01-28T12:00:00Z"), flight_ids=["NSP@2025-01-24"])
    clock.set(ts("2025-01-28T12:00:00Z"))
    books.post_operations(EOWYN, world, clock.now(), flight_ids=["NSP@2025-01-24"])

    assert all(balanced(j) for j in books.journal())
    reliefs = Counter(e["coupon_id"] for e in books.coupon_events(kind="relief"))
    assert set(reliefs.values()) <= {1}
    double = sum(e["amount_cents"] for e in books.coupon_events(kind="double_refund"))
    assert books.gl_balance("2125") == -double                     # 2125 ≠ 0 only for flagged double refunds
    sold = sum(c.fare_cents for c in COUPONS)
    relieved = sum(e["fare_cents"] for e in books.coupon_events(kind="relief"))
    assert books.gl_balance("2100") == sold - relieved
    for c, k in zip(COUPONS, elections, strict=True):
        if ELECTION_KINDS[k] in ("reaccommodated_own", "none") and not any(e.coupon_id == c.id for e in crm):
            assert c.id not in reliefs                              # open rebooks stay in 2100
