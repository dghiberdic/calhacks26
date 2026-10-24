"""Accounting periods ("YYYY-MM") and claim-curve development age."""
from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta

_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_DATE_IN_ID = re.compile(r"(\d{4}-\d{2}-\d{2})")

LIMITATION_YEARS = 6          # Ireland, C-139/11 Moré
M1_MIN_DAYS = 28              # M1 = first month-end at least 28 days after the event


def parse_period(p: str) -> tuple[int, int]:
    m = _PERIOD.match(p or "")
    if not m:
        raise ValueError(f"period must be YYYY-MM, got {p!r}")
    return int(m.group(1)), int(m.group(2))


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def period_start(p: str) -> date:
    y, m = parse_period(p)
    return date(y, m, 1)


def period_end(p: str) -> date:
    y, m = parse_period(p)
    return date(y, m, calendar.monthrange(y, m)[1])


def next_period(p: str) -> str:
    y, m = parse_period(p)
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def months_between(p1: str, p2: str) -> int:
    """p2 − p1 in months."""
    y1, m1 = parse_period(p1)
    y2, m2 = parse_period(p2)
    return (y2 - y1) * 12 + (m2 - m1)


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def first_month_end(event: date) -> date:
    """M1: the first month-end at least 28 days after the event."""
    return month_end(event + timedelta(days=M1_MIN_DAYS))


def age_months(event: date, period: str) -> int:
    """Development age at the close of `period`: 0 before M1, 1 at M1, 12 at M12, …"""
    m1 = period_of(first_month_end(event))
    n = months_between(m1, period)
    return n + 1 if n >= 0 else 0


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + n, day=28)


def limitation_expiry(event: date) -> date:
    return add_years(event, LIMITATION_YEARS)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def utc_date(dt: datetime) -> date:
    return to_utc(dt).date()


def iso(dt: datetime) -> str:
    """Fixed-width UTC timestamp so stored strings compare chronologically."""
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def end_of_day_iso(d: date) -> str:
    return f"{d.isoformat()}T23:59:59.999999Z"


def date_in_id(s: str | None) -> date | None:
    m = _DATE_IN_ID.search(s or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None
