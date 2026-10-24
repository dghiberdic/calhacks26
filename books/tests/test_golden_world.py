"""Books on the real golden fixture: NS31's day-1 journal equals expected/journal_NS31.json, the CFO bridge equals
expected/golden_numbers.json, and the scripted flow to Feb 28 ends on expected/rollforward_2025-02.json exactly."""
from __future__ import annotations

from collections import Counter

import pytest

from books import Books
from books.reporting import cfo_bridge
from contracts.models import JournalEntry, Rollforward

from .golden_world import EOWYN, NS31, expected, golden_decisions, golden_ents, golden_world
from .helpers import CONTROLLER, FixedClock, ts

KNOWN = ts("2025-01-25T06:00:00Z")          # world.meta.storms[EOWYN].known_at
RULING_LEG = ts("2025-01-25T10:30:00Z")
RULING_CL = ts("2025-01-25T11:00:00Z")
ISHA = "EIDW@2024-01-21"


def lines(je: JournalEntry | dict) -> list[tuple[str, int, int]]:
    raw = je.lines if isinstance(je, JournalEntry) else je["lines"]
    return sorted((x.account, x.dr_cents, x.cr_cents) if not isinstance(x, dict)
                  else (x["account"], x["dr_cents"], x["cr_cents"]) for x in raw)


@pytest.fixture
def day1() -> tuple[Books, FixedClock, list[JournalEntry]]:
    clock = FixedClock(KNOWN)
    books = Books(":memory:", clock)
    jes = books.post_storm(EOWYN, golden_world(), golden_decisions(KNOWN), golden_ents(), KNOWN)
    return books, clock, jes


def test_ns31_day1_journal_equals_expected(day1):
    books, _clock, jes = day1
    exp = expected("journal_NS31.json")
    ns31 = [j for j in jes if j.lines[0].dims.get("flight") == NS31]
    drafts = [j for j in ns31 if j.status == "draft"]
    assert [j.kind for j in drafts] == [x["kind"] for x in exp["day1"]]
    for je, x in zip(drafts, exp["day1"], strict=True):
        assert lines(je) == lines(x), je.kind
        if "memo_has" in x:
            assert x["memo_has"] in je.memo
        if "coupon" in x:
            assert {l.dims["coupon"] for l in je.lines} == {x["coupon"]}
    posted = [j for j in ns31 if j.status == "posted"]
    assert [j.kind for j in posted] == ["sale", "refund"]               # the PSS sale and the CRM bot's refunds
    bot = posted[1]
    assert bot.preparer == exp["external"][0]["posted_by"] and lines(bot) == lines(exp["external"][0])
    assert books.gl_balance("2125") == exp["balances"]["2125_after_books"] == 0
    assert books.gl_balance("2140", cohort=EOWYN) == 8_214_600
    assert sum(cr_ - dr_ for j in drafts for (a, dr_, cr_) in lines(j) if a == "2140") == \
        exp["balances"]["2140_day1_ns31"]


def test_golden_day1_bridge_care_duplicates_and_invariants(day1):
    books, _clock, _jes = day1
    g = expected("golden_numbers.json")
    m = books.cfo_metrics(KNOWN)
    assert (m.cash_basis_cents, m.full_entitlement_cents, m.drafted_liability_cents, m.sensitivity_5pp_cents) == (
        g["cfo_bridge"]["cash_basis_cents"], g["cfo_bridge"]["full_entitlement_cents"],
        g["cfo_bridge"]["drafted_liability_cents"], g["cfo_bridge"]["sensitivity_5pp_cents"])
    assert cfo_bridge(m) == "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)"
    assert m.held_for_legal_cents == g["r_leg_1_delta_cents"] * -1 == 4_749_600
    assert m.care_accrued_cents == g["care_accrued_cents"] and m.care_invoiced_cents == 0
    assert m.refunds_within_7d_pct == 100.0 and m.recodes_count == 1 and m.recodes_cents == 3_465_000
    assert {r.cohort for r in m.liability_bridge} == {EOWYN, ISHA}
    flags = {(e["coupon_id"], e["channel"]) for e in books.coupon_events(kind="duplicate")}
    ns31 = golden_world().meta["ns31"]
    assert flags == {(ns31["bsp_duplicate_coupon"], "bsp"), (ns31["chargeback_coupon"], "chargeback")}
    assert not books.coupon_events(kind="double_refund")
    reliefs = Counter(e["coupon_id"] for e in books.coupon_events(kind="relief"))
    assert set(reliefs.values()) == {1}
    bad = [r for r in books.invariants() if not r.ok]
    assert not bad, bad
    inv3 = next(r for r in books.invariants() if r.id == "INV-3")
    assert "27 cancelled" not in inv3.detail and "= register 27 = OCC 27" in inv3.detail
    assert "11 operated departures ≤ Eurocontrol 179" in inv3.detail


def test_golden_scripted_flow_ends_on_expected_feb_rollforward(day1):
    books, clock, _jes = day1
    world = golden_world()
    ents = {e.coupon_id: e for e in golden_ents()}
    knock = [e for e in ents.values() if e.status == "held"]
    clock.set(RULING_LEG)                                                    # R-LEG-1: knock-ons extraordinary
    rel = books.post_recode(knock, [e.model_copy(update={"status": "no_compensation", "compensation_cents": 0,
                                                         "rules_applied": ["R-LEG-1@1"]}) for e in knock],
                            RULING_LEG, rule_ref="R-LEG-1@1")
    assert sum(sum(l.dr_cents - l.cr_cents for l in j.lines if l.account == "2140") for j in rel) == 4_749_600
    clock.set(RULING_CL)                                                     # R-CL-1: 14C owed in cash
    c14 = ents[world.meta["ns31"]["q1_coupon"]].model_copy(update={"status": "owed", "rules_applied": ["R-CL-1@1"]})
    ents[c14.coupon_id] = c14
    claims = {c.id: c for c in world.claims}
    clock.set(ts("2025-01-27T09:00:00Z"))
    for cid in world.meta["ns31"]["overnight_claims"]:
        c = claims[cid]
        assert books.post_claim(c, ents[c.coupon_id], clock.now()), cid
    clock.set(ts("2025-01-31T22:00:00Z"))
    prop = books.month_end("2025-01", clock.now())
    assert [j.estimate_ref for j in prop] == [f"release:{ISHA}"]           # Q3: the Isha release proposal
    jan = {r.cohort: r for r in books.rollforward("2025-01").rows}
    assert jan[EOWYN].closing_cents == expected("golden_numbers.json")["jan_close_cents"]
    books.reject(prop[0].id, CONTROLLER, "Never release the tail.")
    books.keep_tail("R-CTL-1@1", [ISHA], clock.now())
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    for cid in sorted(world.meta["ns31"]["feb_claims"], key=lambda i: claims[i].received_at):
        c = claims[cid]
        clock.set(max(clock.now(), c.received_at))
        assert books.post_claim(c, ents[c.coupon_id], clock.now()), cid
    clock.set(ts("2025-02-28T12:00:00Z"))
    inv = [j for j in books.post_operations(EOWYN, world, clock.now()) if j.kind == "care_invoice"]
    g = expected("golden_numbers.json")
    assert len(inv) == 1 and sum(l.cr_cents for l in inv[0].lines if l.account == "2000") == g["care_invoiced_cents"]
    assert sum(l.cr_cents for l in inv[0].lines if l.account == "6100") == g["care_reversal_cents"]
    clock.set(ts("2025-02-28T22:00:00Z"))
    feb = books.month_end("2025-02", clock.now())
    assert [sum(l.cr_cents - l.dr_cents for l in j.lines if l.account == "2140") for j in feb] == [
        g["feb_change_in_estimate_cents"]]
    doc = expected("rollforward_2025-02.json")
    doc.pop("_about")
    got, want = books.rollforward("2025-02"), Rollforward.model_validate(doc)
    assert got.model_dump() == want.model_dump()
    m = books.cfo_metrics(clock.now())
    assert (m.full_entitlement_cents, m.drafted_liability_cents, m.cash_basis_cents) == (9_900_000, 2_574_000, 0)
    assert m.method_range_cents == (2_175_000, 3_726_667) and m.care_invoiced_cents == 22_130_000
    card = books.estimate_card(EOWYN, clock.now())
    assert (card.bf_cents, card.actual_vs_expected, card.sensitivity_5pp_cents) == (2_574_000, 1.448, 495_000)
    bad = [r for r in books.invariants() if not r.ok]
    assert not bad, bad
