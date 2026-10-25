"""Views over Books' journals for the UI. Books computes every amount; these only name, link and label what Books
returned:

- each journal entry's `approver_role` (the Claims Lead for payouts, the Controller for journals; Books' own SoD rule)
  and `period_locked`;
- each rollforward row's `je_ids`: the journals whose 2140 lines for that cohort make up the row's movement in the
  period (a release proposal still awaiting approval is not on the GL, so it is not named);
- the CFO view's `cohort` (the one storm it covers, None for several) and its voucher split (GL 2131 refund vouchers,
  GL 2132 compensation vouchers, each Books' `gl_balance` over the same cohorts);
- blame labels on a journal that lead with the money and the Dr / Cr accounts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from contracts.models import CfoMetrics, JournalEntry, Role, Rollforward

from . import compose
from .impls import _module

_books = _module("books.books")
PAYOUT_KINDS = frozenset(getattr(_books, "PAYOUT_KINDS", None) or {"claim_approved", "claim_paid"})
UNASSIGNED = str(getattr(_books, "UNASSIGNED", None) or "unassigned")
STATUS = {"draft": "drafted, pending approval", "approved": "approved · parked, not posted", "posted": "posted"}


def approver_role(kind: str) -> Role:
    return Role.CLAIMS_LEAD if kind in PAYOUT_KINDS else Role.CONTROLLER


def locked_periods(books: Any) -> set[str]:
    fn = getattr(books, "locked_periods", None)
    try:
        return set(fn()) if fn is not None else set()
    except Exception:
        return set()


def entries(jes: Iterable[JournalEntry], locked: set[str]) -> list[JournalEntry]:
    return [je.model_copy(update={"approver_role": approver_role(je.kind), "period_locked": je.period in locked})
            for je in jes]


def on_gl(je: JournalEntry) -> bool:
    """Books keeps a gated release proposal off the GL until it is approved."""
    return not (je.status == "draft" and (je.estimate_ref or "").startswith("release:"))


def rollforward(books: Any, rf: Rollforward) -> Rollforward:
    named: dict[str, list[str]] = defaultdict(list)
    for je in books.journal(rf.period):
        if not on_gl(je):
            continue
        for cohort in dict.fromkeys(line.dims.get("cohort", UNASSIGNED) for line in je.lines if line.account == "2140"):
            named[cohort].append(je.id)
    rows = [r.model_copy(update={"je_ids": r.je_ids or named.get(r.cohort, [])}) for r in rf.rows]
    return rf.model_copy(update={"rows": rows, "locked": rf.locked or rf.period in locked_periods(books)})


def cfo(books: Any, known_at: datetime, storms: list[str], cohort: str | None = None) -> CfoMetrics:
    """`storms`: the storm cohorts that have happened by `known_at` (Books' default scope)."""
    m = books.cfo_metrics(known_at, cohort=cohort) if cohort else books.cfo_metrics(known_at)
    period = m.as_of.strftime("%Y-%m")
    rf = rollforward(books, books.rollforward(period))
    scope = [cohort] if cohort else storms
    split = {acct: sum(books.gl_balance(acct, period=period, cohort=c) for c in scope) for acct in ("2131", "2132")}
    return m.model_copy(update={
        "liability_bridge": [next((r for r in rf.rows if r.cohort == b.cohort), b) for b in m.liability_bridge],
        "cohort": m.cohort or cohort or (scope[0] if len(scope) == 1 else None),
        "refund_vouchers_outstanding_cents": split["2131"],
        "compensation_vouchers_outstanding_cents": split["2132"]})


def _accounts(je: JournalEntry, side: str) -> str:
    codes = dict.fromkeys(f"{line.account} {line.account_name}" for line in je.lines
                          if (line.dr_cents if side == "dr" else line.cr_cents))
    return ", ".join(codes)


def blame_label(je: JournalEntry, line_no: int | None = None) -> str:
    """"€34,650 · Dr 4090 … / Cr 2140 … · JE-000004:2 · compensation estimate · drafted, pending approval · period
    2025-01": the amount (the line's, or the entry's total) and the accounts first."""
    line = je.lines[line_no - 1] if line_no and 0 < line_no <= len(je.lines) else None
    amount = (line.dr_cents or line.cr_cents) if line else sum(x.dr_cents for x in je.lines)
    ref = f"{je.id}:{line_no}" if line else je.id
    return (f"{compose.eur(amount)} · Dr {_accounts(je, 'dr')} / Cr {_accounts(je, 'cr')} · {ref} · "
            f"{je.kind.replace('_', ' ')} · {STATUS.get(je.status, je.status)} · period {je.period}")
