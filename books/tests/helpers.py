"""Inline golden scenario builders (IMPLEMENTATION_PLAN §1.2–1.3). No dependency on contracts/fixtures/golden/world.json."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from contracts.models import (
    Cause,
    Claim,
    Confidence,
    Entitlement,
    Extraordinary,
    Flight,
    FlightDecision,
    JournalEntry,
    OpeningBalance,
    Role,
    Session,
    World,
)

EOWYN = "EIDW@2025-01-24"
ISHA = "EIDW@2024-01-21"


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


class FixedClock:
    """Injected forward-only clock (CONTRACTS §2 Clock)."""

    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        assert now >= self._now, "clock is forward-only"
        self._now = now


def session(role: Role, principal: str | None = None) -> Session:
    principal = principal or f"{role.value}:test"
    return Session(principal=principal, role=role, name=principal, issued_at=ts("2025-01-25T00:00:00Z"))


CONTROLLER = session(Role.CONTROLLER, "controller:ana")
CLAIMS_LEAD = session(Role.CLAIMS_LEAD, "claims_lead:maria")


def seats(n: int) -> list[str]:
    out: list[str] = []
    row = 1
    while len(out) < n:
        for letter in "ABCDEF":
            out.append(f"{row}{letter}")
        row += 1
    return out[:n]


# (number, origin, dest, std, sta, pax, km, band, specs) where specs = [(count, compensation_cents, status, reduction)]
FLIGHTS = {
    "NS31": ("DUB", "BOS", "2025-01-24T16:30:00Z", "2025-01-24T23:10:00Z", 172, 4804.0, 600,
             [(158, 60_000, "owed", "none"), (14, 30_000, "owed", "art7_2_50pct")], "41"),
    "NS113": ("LIS", "DUB", "2025-01-24T13:20:00Z", "2025-01-24T15:55:00Z", 178, 1643.0, 400,
              [(178, 40_000, "needs_ruling", "none")], "71"),
    "NS115": ("FCO", "DUB", "2025-01-24T14:10:00Z", "2025-01-24T17:00:00Z", 184, 1886.0, 400,
              [(184, 40_000, "held", "none")], "71"),
    "NS117": ("MUC", "DUB", "2025-01-24T14:05:00Z", "2025-01-24T16:20:00Z", 168, 1381.0, 250,
              [(168, 25_000, "held", "none")], "71"),
    "NS100": ("DUB", "LHR", "2025-01-24T06:10:00Z", "2025-01-24T07:25:00Z", 186, 449.0, 250,
              [(186, 0, "no_compensation", "none")], "71"),
}
KNOCK_ONS = ["NS113", "NS115", "NS117"]


def flight_id(number: str, day: str = "2025-01-24") -> str:
    return f"{number}@{day}"


def make_flight(number: str, day: str = "2025-01-24") -> Flight:
    o, d, std, sta, pax, _km, _band, _specs, code = FLIGHTS[number]
    return Flight(id=flight_id(number, day), number=number, date=date.fromisoformat(day), origin=o, dest=d,
                  sched_dep=ts(std), sched_arr=ts(sta), aircraft="EI-NSB" if number == "NS31" else "EI-NSL",
                  status="cancelled", pax=pax, ops_cause_code=code)


def make_ents(number: str, day: str = "2025-01-24") -> list[Entitlement]:
    _o, _d, _std, _sta, pax, km, band, specs, _code = FLIGHTS[number]
    fid = flight_id(number, day)
    out: list[Entitlement] = []
    labels = iter(seats(pax))
    for count, comp, status, reduction in specs:
        for _ in range(count):
            out.append(Entitlement(
                coupon_id=f"{fid}:{next(labels)}", flight_id=fid, distance_km=km, band_eur=band,
                band_margin_km=abs(km - 3500.0 if band == 600 else km - 1500.0), compensation_cents=comp,
                reduction=reduction, status=status,
                article="EU261 Art.7(1)" if comp else "EU261 Art.5(3)",
                reason="test entitlement"))
    assert len(out) == pax
    return out


def recode_to_extraordinary(ents: list[Entitlement]) -> list[Entitlement]:
    return [e.model_copy(update={"status": "no_compensation", "compensation_cents": 0,
                                 "rules_applied": ["R-LEG-1@1"], "article": "EU261 Art.5(3)"}) for e in ents]


def make_decision(number: str, known_at: datetime, day: str = "2025-01-24") -> FlightDecision:
    if number == "NS31":
        cause, ext, recoded, label = Cause.TECHNICAL, Extraordinary.NO, True, "71 → 41"
    elif number in KNOCK_ONS:
        cause, ext, recoded, label = Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, False, None
    else:
        cause, ext, recoded, label = Cause.WEATHER, Extraordinary.YES, False, None
    return FlightDecision(
        flight_id=flight_id(number, day), cause=cause, extraordinary=ext, ops_cause_code=FLIGHTS[number][8],
        recoded=recoded, recode_label=label, in_window_dep="out", in_window_arr="out",
        confidence=Confidence(score=0.91, kind="cause", label="cause-finding confidence", features={},
                              calibration_version="cal-v1"),
        reason="test", evidence=[], rules_applied=[], legal_basis=[], outcome="auto", known_at=known_at,
        commit=f"commit-{number}")


def make_world(numbers: list[str], day: str = "2025-01-24", opening: list[OpeningBalance] | None = None) -> World:
    return World(meta={"carrier": "Northstar Air"}, airports=[], flights=[make_flight(n, day) for n in numbers],
                 tech_log=[], ops_log=[], coupons=[], elections=[], crm=[], claims=[], metar={}, sources=[],
                 opening_balances=opening or [])


def storm(numbers: list[str], known_at: datetime, day: str = "2025-01-24"):
    world = make_world(numbers, day)
    decisions = [make_decision(n, known_at, day) for n in numbers]
    ents = [e for n in numbers for e in make_ents(n, day)]
    return world, decisions, ents


def make_claim(ent: Entitlement, at: datetime, n: int = 0) -> Claim:
    return Claim(id=f"CLM-{ent.coupon_id.replace('@', '-').replace(':', '-')}-{n}", coupon_id=ent.coupon_id,
                 received_at=at, channel="direct", amount_claimed_cents=ent.compensation_cents or 60_000,
                 text="I claim EU261 compensation.")


def isha_opening(as_of: str = "2024-10-31T23:59:59Z") -> OpeningBalance:
    return OpeningBalance(cohort=ISHA, account="2140", entitlement_cents=6_000_000, claimed_cents=1_740_000,
                          balance_cents=360_000, curve_segment="long_haul_gt3500", as_of=ts(as_of))


def dr(je: JournalEntry, account: str) -> int:
    return sum(l.dr_cents for l in je.lines if l.account == account)


def cr(je: JournalEntry, account: str) -> int:
    return sum(l.cr_cents for l in je.lines if l.account == account)


def liability_delta(je: JournalEntry) -> int:
    """Signed effect of a JE on 2140 (credit increases the liability)."""
    return cr(je, "2140") - dr(je, "2140")


def days(start: datetime, n: int) -> list[datetime]:
    return [start + timedelta(hours=6 * i) for i in range(n)]
