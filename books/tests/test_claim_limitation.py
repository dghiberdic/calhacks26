"""The simulated Irish six-year policy gates claims by receipt, not processing time."""
from books import Books

from .helpers import EOWYN, FixedClock, make_claim, storm, ts


def setup():
    at = ts("2025-01-25T07:00:00Z")
    world, decisions, ents = storm(["NS31"], at)
    books = Books(":memory:", FixedClock(at))
    books.post_storm(EOWYN, world, decisions, ents, at)
    return books, ents[0]


def test_claim_received_after_limitation_creates_no_payout_or_liability():
    books, ent = setup()
    before = books.gl_balance("2140")
    late = ts("2031-01-25T08:00:00Z")
    assert books.post_claim(make_claim(ent, late), ent, late) == []
    assert books.gl_balance("2140") == before
    assert books.gl_balance("2141") == 0
    assert not [j for j in books.journal() if j.kind == "claim_paid"]


def test_timely_claim_processed_after_expiry_is_still_a_valid_claim():
    books, ent = setup()
    received = ts("2031-01-23T08:00:00Z")
    processed = ts("2031-01-25T08:00:00Z")
    entries = books.post_claim(make_claim(ent, received), ent, processed)
    assert any(j.kind == "claim_approved" for j in entries)
    assert any(j.kind == "claim_paid" for j in entries)
