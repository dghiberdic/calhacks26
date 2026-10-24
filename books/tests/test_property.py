"""Property tests: random claim sequences (each ≤ entitlement) never break the books invariants."""
from __future__ import annotations

from datetime import datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from books import Books
from books.periods import next_period, period_end
from contracts.models import Entitlement

from .helpers import CONTROLLER, EOWYN, FixedClock, make_claim, make_decision, make_world, ts

KINDS = [(600, 60_000, "none"), (600, 30_000, "art7_2_50pct"), (400, 40_000, "none"), (250, 25_000, "none")]
KM = {600: 4804.0, 400: 1643.0, 250: 1381.0}
STATUSES = ["owed", "owed", "owed", "held", "no_compensation"]


def _ents(spec: list[tuple[int, int]]) -> list[Entitlement]:
    out = []
    for i, (k, s) in enumerate(spec):
        band, comp, red = KINDS[k]
        status = STATUSES[s]
        fid = f"NSX{band}@2025-01-24"
        out.append(Entitlement(coupon_id=f"{fid}:{i}", flight_id=fid, distance_km=KM[band], band_eur=band,
                               band_margin_km=100.0, compensation_cents=0 if status == "no_compensation" else comp,
                               reduction=red, status=status, article="EU261 Art.7(1)", reason="prop"))
    return out


def _check(books: Books, period: str) -> None:
    lines = [l for j in books.journal() for l in j.lines]
    assert sum(l.dr_cents for l in lines) == sum(l.cr_cents for l in lines)
    for j in books.journal():
        assert sum(l.dr_cents for l in j.lines) == sum(l.cr_cents for l in j.lines) > 0
    rf = books.rollforward(period)
    assert rf.ties_to_gl
    for row in rf.rows:
        assert 0 <= row.closing_cents <= row.unclaimed_entitlement_cents, row
    for seg_balance in books.segment_balances(EOWYN, period).values():
        assert seg_balance >= 0


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    spec=st.lists(st.tuples(st.integers(0, 3), st.integers(0, 4)), min_size=1, max_size=30),
    claims=st.lists(st.tuples(st.integers(0, 29), st.integers(0, 13)), max_size=45),
    lock=st.booleans(),
)
def test_random_claim_sequences_keep_invariants(spec, claims, lock):
    clock = FixedClock(ts("2025-01-25T07:00:00Z"))
    books = Books(":memory:", clock)
    ents = _ents(spec)
    flights = sorted({e.flight_id for e in ents})
    world = make_world([])
    decisions = [make_decision("NS31", clock.now()).model_copy(update={"flight_id": f, "commit": f"commit-{f}"})
                 for f in flights]                         # every non-zero entitlement traces to a decision (INV-7b)
    books.post_storm(EOWYN, world, decisions, ents, clock.now())
    _check(books, "2025-01")

    by_month: dict[int, list[int]] = {}
    for idx, month in claims:
        by_month.setdefault(month, []).append(idx % len(ents))
    period = "2025-01"
    claimed: set[str] = set()
    for month in range(14):
        start = max(datetime.fromisoformat(f"{period}-02T08:00:00+00:00"), clock.now() + timedelta(hours=1))
        for k, idx in enumerate(by_month.get(month, [])):
            ent = ents[idx]
            at = start + timedelta(hours=k)
            clock.set(at)
            jes = books.post_claim(make_claim(ent, at, n=month * 100 + k), ent, at)
            if ent.coupon_id in claimed or ent.status != "owed":
                assert jes == []                     # duplicates and non-owed claims post nothing
            else:
                claimed.add(ent.coupon_id)
                assert jes
                again = books.post_claim(make_claim(ent, at, n=month * 100 + k), ent, at)
                assert [j.id for j in again] == [j.id for j in jes]   # same claim id: idempotent
            _check(books, period)
        end = datetime.combine(period_end(period), datetime.min.time()).replace(hour=22, tzinfo=start.tzinfo)
        clock.set(end)
        books.month_end(period, end)
        _check(books, period)
        if lock:
            books.lock_period(period, CONTROLLER)
        period = next_period(period)

    paid = sum(e.compensation_cents for e in ents if e.coupon_id in claimed)
    assert paid <= sum(e.compensation_cents for e in ents if e.status == "owed")
    assert books.gl_balance("2141") == paid
    assert all(r.ok for r in books.invariants()), [r for r in books.invariants() if not r.ok]
    assert flights
