"""Hard controls in code: SoD, payout authority, locked periods, append-only storage, purity."""
from __future__ import annotations

import ast
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from books import Books, Forbidden, PeriodLocked, SoDViolation
from books.coa import ACCOUNTS
from contracts import interfaces
from contracts.models import JournalLine, Role

from .helpers import (
    CLAIMS_LEAD,
    CONTROLLER,
    EOWYN,
    FixedClock,
    cr,
    flight_id,
    make_claim,
    session,
    storm,
    ts,
)

DAY1 = ts("2025-01-25T07:00:00Z")


def _day1(books: Books):
    world, decisions, ents = storm(["NS31"], DAY1)
    return books.post_storm(EOWYN, world, decisions, ents, DAY1)[0], ents


# ---------------------------------------------------------------- chart of accounts

def test_chart_of_accounts_is_contract_section_5():
    assert ACCOUNTS == {
        "1000": "Bank", "1110": "Card acquirer",
        "2000": "Trade payables", "2100": "ATL", "2110": "Taxes payable", "2120": "Refunds payable",
        "2125": "Refund clearing", "2131": "Refund vouchers", "2132": "Compensation vouchers",
        "2140": "EU261 compensation liability (estimated)", "2141": "EU261 compensation payable",
        "2150": "Accrued care", "2160": "Interline payable", "2170": "Legal costs provision (IAS 37)",
        "4000": "Passenger revenue", "4010": "Breakage",
        "4090": "EU261 compensation (reduction of passenger revenue)",
        "6100": "Care", "6110": "Rerouting", "6120": "Claims legal",
    }


def test_books_implements_every_books_api_method():
    names = [n for n, v in vars(interfaces.BooksAPI).items() if callable(v) and not n.startswith("_")]
    assert len(names) == 14
    for name in names:
        assert callable(getattr(Books, name, None)), name


# ---------------------------------------------------------------- SoD

def test_preparer_cannot_approve_own_entry(books: Books):
    je, _ = _day1(books)
    with pytest.raises(SoDViolation):
        books.approve(je.id, session(Role.CONTROLLER, principal=je.preparer))
    manual = books.post_entry(kind="change_in_estimate", event_date=date(2025, 1, 25), known_at=DAY1,
                              memo="manual top-up", preparer=CONTROLLER.principal, ias8_class="change_in_estimate",
                              lines=[JournalLine(account="4090", account_name="", dr_cents=100),
                                     JournalLine(account="2140", account_name="", cr_cents=100)])
    with pytest.raises(SoDViolation):
        books.approve(manual.id, CONTROLLER)
    assert books.journal(status="approved") == []


def test_wrong_role_cannot_approve(books: Books, clock: FixedClock):
    je, ents = _day1(books)
    for s in (CLAIMS_LEAD, session(Role.CFO), session(Role.DRAFTER), session(Role.JUDGE)):
        with pytest.raises(SoDViolation):
            books.approve(je.id, s)
    approved = books.approve(je.id, CONTROLLER)
    assert approved.status == "approved" and approved.approver == CONTROLLER.principal
    assert books.approve(je.id, CONTROLLER) == approved          # idempotent

    claim_jes = books.post_claim(make_claim(ents[0], DAY1), ents[0], DAY1)
    for je2 in claim_jes:                                         # payouts need the Claims Lead
        with pytest.raises(SoDViolation):
            books.approve(je2.id, CONTROLLER)
        assert books.approve(je2.id, CLAIMS_LEAD).status == "approved"
    assert [j.id for j in books.journal(status="draft")] == []


def test_denied_approvals_are_logged(books: Books):
    je, _ = _day1(books)
    with pytest.raises(SoDViolation):
        books.approve(je.id, CLAIMS_LEAD)
    events = books.audit(je.id)["events"]
    assert [e["kind"] for e in events] == ["drafted", "denied"]


# ---------------------------------------------------------------- locked periods

def test_lock_requires_controller(books: Books):
    with pytest.raises(Forbidden):
        books.lock_period("2025-01", CLAIMS_LEAD)
    books.lock_period("2025-01", CONTROLLER)
    assert books.locked_periods() == ["2025-01"]


def test_direct_post_into_locked_period_raises(books: Books, clock: FixedClock):
    _day1(books)
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    lines = [JournalLine(account="4090", account_name="", dr_cents=500),
             JournalLine(account="2140", account_name="", cr_cents=500)]
    with pytest.raises(PeriodLocked):
        books.post_entry(kind="change_in_estimate", event_date=date(2025, 1, 31), lines=lines, memo="late",
                         known_at=clock.now())
    with pytest.raises(PeriodLocked):
        books.month_end("2025-01", clock.now())
    assert books.gl_balance("2140", period="2025-01") == 3_465_000


def test_late_post_with_locked_event_date_goes_to_open_period_flagged(books: Books, clock: FixedClock):
    _day1(books)
    jan_before = books.rollforward("2025-01")
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    # a Jan-24 flight discovered late: its event date is in locked Jan
    world, decisions, ents = storm(["NS117"], clock.now())
    jes = books.post_storm(EOWYN, world, decisions, ents, clock.now())
    assert len(jes) == 1
    je = jes[0]
    assert je.period == "2025-02" and je.event_date == date(2025, 2, 3)
    assert all(l.dims["adjusted_from_period"] == "2025-01" for l in je.lines)
    assert all(l.dims["original_event_date"] == "2025-01-24" for l in je.lines)
    assert "locked" in je.memo
    assert cr(je, "2140") == 840_000
    assert books.rollforward("2025-01") == jan_before            # Jan untouched
    feb = books.rollforward("2025-02")
    row = next(r for r in feb.rows if r.cohort == EOWYN)
    assert row.out_of_period_cents == 840_000 and feb.ties_to_gl
    # a claim on a locked-period date also lands in the open period
    ent = ents[0].model_copy(update={"status": "owed"})
    claim_jes = books.post_claim(make_claim(ent, ts("2025-01-30T09:00:00Z")), ent, clock.now())
    assert {j.period for j in claim_jes} == {"2025-02"}


def test_approval_in_locked_period_raises(books: Books, clock: FixedClock):
    je, _ = _day1(books)
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    with pytest.raises(PeriodLocked):
        books.approve(je.id, CONTROLLER)


# ---------------------------------------------------------------- storage

def test_tables_are_append_only(books: Books):
    _day1(books)
    conn = books._conn
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'books_%'")]
    assert {"books_je", "books_je_lines", "books_je_events", "books_register_events", "books_period_events"} <= set(tables)
    for t in tables:
        if conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0:
            continue
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"UPDATE {t} SET rowid = rowid")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"DELETE FROM {t}")


def test_file_database_reopens(tmp_path: Path, clock: FixedClock):
    path = tmp_path / "books.db"
    b1 = Books(str(path), clock)
    world, decisions, ents = storm(["NS31"], DAY1)
    b1.post_storm(EOWYN, world, decisions, ents, DAY1)
    b1.close()
    b2 = Books(str(path), clock)
    assert b2.gl_balance("2140") == 3_465_000
    assert len(b2.register(flight_id=flight_id("NS31"))) == 172


# ---------------------------------------------------------------- purity (no LLM, no wall clock, no randomness)

BANNED_MODULES = {"anthropic", "random", "secrets", "uuid"}
BANNED_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
                ("time", "time"), ("time", "time_ns"), ("time", "monotonic")}


def test_books_is_pure():
    root = Path(__file__).resolve().parent.parent
    files = [p for p in root.rglob("*.py") if "tests" not in p.parts]
    assert files
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & BANNED_MODULES, path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in BANNED_MODULES, path
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = node.func.value
                name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
                assert (name, node.func.attr) not in BANNED_CALLS, f"{path}:{node.lineno}"
