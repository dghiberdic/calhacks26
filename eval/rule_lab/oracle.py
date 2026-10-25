"""Reviewed Q1 intent, independent of every candidate and engine output.

Source: the existing Q1 ruling and CONTRACTS golden scenario. €600 applies to
DUB–JFK/BOS–DUB; the next-storm short-haul cases use the €250 statutory band.
Signed acceptance, staff fares, notice exemptions and weather remain protected
by the existing engine. Scope widening requires its own human ruling.
"""

PROTECTED_RESULTS = {
    "non-eu-boundary": {"status": "needs_ruling", "cash_cents": 60_000, "voucher_offset_cents": 0},
    "signed-consent": {"status": "owed", "cash_cents": 30_000, "voucher_offset_cents": 30_000},
    "no-voucher": {"status": "owed", "cash_cents": 60_000, "voucher_offset_cents": 0},
    "staff-fare": {"status": "staff_ticket", "cash_cents": 0, "voucher_offset_cents": 0},
    "early-notice": {"status": "exempt_notice", "cash_cents": 0, "voucher_offset_cents": 0},
    "weather": {"status": "no_compensation", "cash_cents": 0, "voucher_offset_cents": 0},
}
