"""F8a golden numbers, exact cents (CONTRACTS §5, IMPLEMENTATION_PLAN §1.3). Entitlements built inline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from books import Books
from contracts.models import JournalEntry, Rollforward

from .helpers import (
    CLAIMS_LEAD,
    CONTROLLER,
    EOWYN,
    ISHA,
    KNOCK_ONS,
    FixedClock,
    cr,
    dr,
    flight_id,
    isha_opening,
    liability_delta,
    make_claim,
    make_ents,
    make_world,
    recode_to_extraordinary,
    storm,
    ts,
)

DAY1 = ts("2025-01-25T07:00:00Z")
RULING = ts("2025-01-25T10:30:00Z")


# ---------------------------------------------------------------- day 1

def test_ns31_day1_liability(books: Books):
    world, decisions, ents = storm(["NS31"], DAY1)
    assert sum(e.compensation_cents for e in ents) == 9_900_000          # 158 × 60,000 + 14 × 30,000
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert len(jes) == 1
    je = jes[0]
    assert je.kind == "compensation_estimate"
    assert je.status == "draft" and je.preparer == "agent.engine" and je.approver is None
    assert je.event_date == date(2025, 1, 24) and je.period == "2025-01"
    assert dr(je, "4090") == 3_465_000 and cr(je, "2140") == 3_465_000
    assert {l.account for l in je.lines} == {"4090", "2140"}
    assert books.gl_balance("2140") == 3_465_000
    assert books.gl_balance("4090") == 3_465_000


def test_knock_on_accruals_at_segment_rates(books: Books):
    world, decisions, ents = storm(KNOCK_ONS, DAY1)
    jes = {j.lines[0].dims["flight"]: j for j in books.post_storm(EOWYN, world, decisions, ents, DAY1)}
    assert cr(jes[flight_id("NS113")], "2140") == 1_922_400   # 178 × 40,000 × 0.27
    assert cr(jes[flight_id("NS115")], "2140") == 1_987_200   # 184 × 40,000 × 0.27
    assert cr(jes[flight_id("NS117")], "2140") == 840_000     # 168 × 25,000 × 0.20
    assert all(j.status == "draft" for j in jes.values())


def test_storm_day1_total_and_weather_has_no_compensation_entry(books: Books):
    world, decisions, ents = storm(["NS31", *KNOCK_ONS, "NS100"], DAY1)
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert len(jes) == 4                                     # NS100 (weather) gets no compensation JE
    assert flight_id("NS100") not in {l.dims.get("flight") for j in jes for l in j.lines}
    assert sum(liability_delta(j) for j in jes) == 8_214_600
    assert books.gl_balance("2140") == 8_214_600


def test_post_storm_is_idempotent(books: Books):
    world, decisions, ents = storm(["NS31", *KNOCK_ONS], DAY1)
    first = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    again = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert [j.id for j in first] == [j.id for j in again]
    assert books.gl_balance("2140") == 8_214_600


def test_obligation_register_one_row_per_coupon(books: Books):
    world, decisions, ents = storm(["NS31", "NS117", "NS100"], DAY1)
    jes = books.post_storm(EOWYN, world, decisions, ents, DAY1)
    rows = books.register()
    assert len(rows) == 172 + 168 + 186 == len({r["coupon_id"] for r in rows})
    r14c = next(r for r in rows if r["coupon_id"] == "NS31@2025-01-24:14C")
    assert r14c["segment"] == "long_haul_gt3500" and r14c["status"] == "owed"
    assert r14c["compensation_cents"] == 60_000 and r14c["cohort"] == EOWYN
    assert r14c["limitation_expiry"] == "2031-01-24"
    ns31_je = next(j for j in jes if j.lines[0].dims["flight"] == flight_id("NS31"))
    assert r14c["je_ids"] == [ns31_je.id]
    assert r14c["decision_commit"] == "commit-NS31" and r14c["cause"] == "technical"
    weather = next(r for r in rows if r["flight_id"] == flight_id("NS100"))
    assert weather["status"] == "no_compensation" and weather["je_ids"] == []
    held = next(r for r in rows if r["flight_id"] == flight_id("NS117"))
    assert held["segment"] == "short_le1500" and held["status"] == "held" and held["je_ids"]


# ---------------------------------------------------------------- recode (R-LEG-1)

def test_preview_and_post_recode_knock_ons(books: Books, clock: FixedClock):
    world, decisions, ents = storm(["NS31", *KNOCK_ONS], DAY1)
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    before = [e for n in KNOCK_ONS for e in make_ents(n)]
    after = recode_to_extraordinary(before)
    clock.set(RULING)

    diff = books.preview(before, after)
    assert diff.total_delta_cents == -4_749_600
    assert {f.entity_id: f.delta_cents for f in diff.flips} == {
        flight_id("NS113"): -1_922_400, flight_id("NS115"): -1_987_200, flight_id("NS117"): -840_000}
    assert books.gl_balance("2140") == 8_214_600              # preview is a dry run

    jes = books.post_recode(before, after, RULING)
    assert sum(liability_delta(j) for j in jes) == -4_749_600
    assert all(j.kind == "recode" and j.ias8_class == "change_in_estimate" and j.status == "draft" for j in jes)
    assert all(j.period == "2025-01" for j in jes)
    assert all(dr(j, "2140") == cr(j, "4090") > 0 for j in jes)
    assert books.gl_balance("2140") == 3_465_000
    assert books.post_recode(before, after, RULING) == []    # idempotent against the register
    assert books.gl_balance("2140") == 3_465_000
    assert {r["status"] for r in books.register(flight_id="NS113@2025-01-24")} == {"no_compensation"}


# ---------------------------------------------------------------- full NS31 rollforward to Feb 28

@dataclass
class Golden:
    books: Books
    clock: FixedClock
    day1: list[JournalEntry] = field(default_factory=list)
    recode: list[JournalEntry] = field(default_factory=list)
    jan_claims: list[JournalEntry] = field(default_factory=list)
    jan_month_end: list[JournalEntry] = field(default_factory=list)
    jan_rf: Rollforward | None = None
    feb_claims: list[JournalEntry] = field(default_factory=list)
    feb_month_end: list[JournalEntry] = field(default_factory=list)
    feb_rf: Rollforward | None = None


def run_golden(books: Books, clock: FixedClock) -> Golden:
    g = Golden(books, clock)
    world, decisions, ents = storm(["NS31", *KNOCK_ONS, "NS100"], DAY1)
    g.day1 = books.post_storm(EOWYN, world, decisions, ents, DAY1)

    before = [e for e in ents if e.flight_id in {flight_id(n) for n in KNOCK_ONS}]
    clock.set(RULING)
    g.recode = books.post_recode(before, recode_to_extraordinary(before), RULING)

    ns31 = [e for e in ents if e.flight_id == flight_id("NS31")]
    full = [e for e in ns31 if e.compensation_cents == 60_000]
    half = [e for e in ns31 if e.compensation_cents == 30_000]

    # Jan: 6 claims (the overnight ones), approved at face value
    for i, ent in enumerate(full[:6]):
        at = ts(f"2025-01-{26 + i:02d}T09:00:00Z")
        clock.set(at)
        g.jan_claims += books.post_claim(make_claim(ent, at), ent, at)
    clock.set(ts("2025-01-31T22:00:00Z"))
    g.jan_month_end = books.month_end("2025-01", clock.now())
    g.jan_rf = books.rollforward("2025-01")
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)

    # Feb: 15 × 60,000 + 1 × 30,000
    feb = full[6:21] + half[:1]
    for i, ent in enumerate(feb):
        at = ts(f"2025-02-{4 + i:02d}T09:00:00Z")
        clock.set(at)
        g.feb_claims += books.post_claim(make_claim(ent, at), ent, at)
    clock.set(ts("2025-02-28T22:00:00Z"))
    g.feb_month_end = books.month_end("2025-02", clock.now())
    g.feb_rf = books.rollforward("2025-02")
    return g


def _row(rf: Rollforward, cohort: str):
    return next(r for r in rf.rows if r.cohort == cohort)


def test_jan_claims_and_close(books: Books, clock: FixedClock):
    g = run_golden(books, clock)
    approvals = [j for j in g.jan_claims if j.kind == "claim_approved"]
    payments = [j for j in g.jan_claims if j.kind == "claim_paid"]
    assert len(approvals) == 6 and len(payments) == 6
    assert all(dr(j, "2140") == 60_000 and cr(j, "2141") == 60_000 for j in approvals)
    assert all(dr(j, "2141") == 60_000 and cr(j, "1000") == 60_000 for j in payments)
    assert g.jan_month_end == []                              # before M1: no true-up
    row = _row(g.jan_rf, EOWYN)
    assert row.opening_cents == 0
    assert row.new_cents == 8_214_600
    assert row.recode_cents == -4_749_600
    assert row.claims_approved_cents == 360_000
    assert row.change_in_estimate_cents == 0
    assert row.closing_cents == 3_105_000
    assert g.jan_rf.gl_balance_cents == 3_105_000 and g.jan_rf.ties_to_gl
    assert books.gl_balance("2141", period="2025-01") == 360_000   # approved, payout pending Claims Lead


def test_feb_month_end_bf_true_up(books: Books, clock: FixedClock):
    g = run_golden(books, clock)
    assert sum(cr(j, "2141") for j in g.feb_claims if j.kind == "claim_approved") == 930_000
    assert len(g.feb_month_end) == 1
    cie = g.feb_month_end[0]
    assert cie.kind == "change_in_estimate" and cie.ias8_class == "change_in_estimate"
    assert cie.status == "draft" and cie.period == "2025-02" and cie.event_date == date(2025, 2, 28)
    assert dr(cie, "4090") == 399_000 and cr(cie, "2140") == 399_000
    row = _row(g.feb_rf, EOWYN)
    assert row.opening_cents == 3_105_000
    assert row.claims_approved_cents == 930_000
    assert row.change_in_estimate_cents == 399_000
    assert row.closing_cents == 2_574_000 == (35 - 9) * 9_900_000 // 100
    assert row.unclaimed_entitlement_cents == 9_900_000 - 1_290_000
    assert g.feb_rf.closing_total_cents == g.feb_rf.gl_balance_cents == 2_574_000
    assert g.feb_rf.ties_to_gl


def test_estimate_card_feb(books: Books, clock: FixedClock):
    g = run_golden(books, clock)
    card = books.estimate_card(EOWYN, ts("2025-02-28T22:00:00Z"))
    assert card.segment == "long_haul_gt3500" and card.curve_version == "LH-v1"
    assert card.pax == 172 and card.entitlement_cents == 9_900_000
    assert card.months_developed == 1
    assert card.actual_vs_expected == 1.448                    # 1,290,000 / 891,000 (€ basis)
    assert card.bf_cents == 2_574_000 and card.selected == "bf"
    assert card.expected_loss_cents == 2_175_000               # 35% × E − actual
    assert card.chain_ladder_cents == 3_726_667                # actual × 0.35/0.09 − actual
    assert card.sensitivity_5pp_cents == 495_000
    assert card.ias8_class == "change_in_estimate" and card.preparer == "agent.engine"
    assert card.approver is None
    g.books.approve(g.feb_month_end[0].id, CONTROLLER)
    assert books.estimate_card(EOWYN, ts("2025-02-28T22:00:00Z")).approver == CONTROLLER.principal


def test_jan_locked_untouched_after_feb(books: Books, clock: FixedClock):
    g = run_golden(books, clock)
    assert books.rollforward("2025-01") == g.jan_rf
    assert all(j.period != "2025-01" for j in g.feb_claims + g.feb_month_end)
    assert books.journal(period="2025-01") and all(j.period == "2025-01" for j in books.journal(period="2025-01"))


def test_golden_invariants_hold(books: Books, clock: FixedClock):
    run_golden(books, clock)
    results = books.invariants()
    assert results and all(r.ok for r in results), [r for r in results if not r.ok]


def test_payout_approval_moves_cash_only_when_claims_lead_approves(books: Books, clock: FixedClock):
    g = run_golden(books, clock)
    pay = next(j for j in g.feb_claims if j.kind == "claim_paid")
    assert books.gl_balance("1000") == 0                      # cash basis €0 until payouts are released
    books.approve(pay.id, CLAIMS_LEAD)
    assert books.gl_balance("1000") == -60_000
    assert books.gl_balance("2141") == 1_290_000 - 60_000


# ---------------------------------------------------------------- Isha cohort release proposal (Q3)

def test_isha_release_proposal_at_m12(books: Books, clock: FixedClock):
    clock.set(ts("2025-01-31T22:00:00Z"))
    world = make_world([], opening=[isha_opening()])
    assert books.post_storm(ISHA, world, [], [], clock.now()) == []
    assert books.gl_balance("2140") == 360_000

    jes = books.month_end("2025-01", clock.now())             # Isha M12, last claim ≥3 months ago
    assert len(jes) == 1
    prop = jes[0]
    assert prop.status == "draft" and prop.estimate_ref == f"release:{ISHA}"
    assert dr(prop, "2140") == 360_000 and cr(prop, "4090") == 360_000
    assert books.gl_balance("2140") == 360_000                # a proposal, not posted
    rf = books.rollforward("2025-01")
    assert _row(rf, ISHA).closing_cents == 360_000 and rf.ties_to_gl

    card = books.estimate_card(ISHA, clock.now())
    assert card.months_developed == 12 and card.bf_cents == 360_000
    assert books.month_end("2025-01", clock.now()) == jes     # re-run: same proposal, not a second one

    # Controller rejects: "Never release the tail" → R-CTL-1 keep tail
    books.reject(prop.id, CONTROLLER, "Never release the tail.")
    books.keep_tail("R-CTL-1@1", [ISHA], clock.now())
    clock.set(ts("2025-02-28T22:00:00Z"))
    assert books.month_end("2025-02", clock.now()) == []      # no BF reduction, no second proposal
    assert _row(books.rollforward("2025-02"), ISHA).closing_cents == 360_000   # Isha tail kept


def test_isha_without_keep_tail_bf_runs_off(books: Books, clock: FixedClock):
    clock.set(ts("2025-02-28T22:00:00Z"))
    books.post_storm(ISHA, make_world([], opening=[isha_opening()]), [], [], clock.now())
    jes = books.month_end("2025-02", clock.now())             # M13: rate 0.295 → BF 330,000
    bf = [j for j in jes if (j.estimate_ref or "").startswith("BF:")]
    assert len(bf) == 1 and liability_delta(bf[0]) == -30_000


# ---------------------------------------------------------------- curves

def test_curves_match_contract(books: Books):
    lh = books.curve("long_haul_gt3500")
    assert lh.version == "LH-v1" and lh.ultimate == 0.35 and lh.observed_through_month == 18
    assert lh.points == [(1, 0.09), (3, 0.17), (6, 0.24), (12, 0.29), (18, 0.32)]
    assert books.curve("medium_1500_3500").ultimate == 0.27
    assert books.curve("short_le1500").ultimate == 0.20
