"""Typed re-parse of a Fact value from its verbatim span (CONTRACTS §2 shared helpers).

The Reader (LLM) proposes `(field, value, span)`. We check the span is a substring of the source text and re-parse
the value FROM the span with the field's parse kind (contracts/fields.py). A mismatch drops the fact. So the LLM can
point at evidence, but every number, time, code and tail that reaches the engine was parsed here, deterministically.

All parsers raise `ParseError` (a ValueError) when the span doesn't contain what they look for.
Times are tz-aware UTC. Money is integer cents.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import fields as _fields


class ParseError(ValueError):
    pass


MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                          "DEC"))}
_MON = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*"


def _ref_date(ref: datetime | date | None) -> date | None:
    if ref is None:
        return None
    if isinstance(ref, datetime):
        return ref.astimezone(UTC).date() if ref.tzinfo else ref.date()
    return ref


def _year_for(month: int, ref: date | None) -> int:
    if ref is None:
        raise ParseError("no year in span and no reference date")
    y = ref.year
    if month - ref.month > 6:      # "28DEC" read in January → last year
        return y - 1
    if ref.month - month > 6:      # "02JAN" read in December → next year
        return y + 1
    return y


# ---------------------------------------------------------------- times
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]00:?00|UTC)?",
                     re.IGNORECASE)
_DMY_TIME_RE = re.compile(
    rf"(?<![0-9])(\d{{1,2}})\s?({_MON})\.?(?:\s?(\d{{4}}))?(?![A-Z])[^0-9]{{0,12}}?(?<![0-9])(\d{{2}}):?(\d{{2}})\s?(?:Z|UTC)",
    re.IGNORECASE)
_TIME_RE = re.compile(r"(?<![0-9:])(\d{2}):?(\d{2})\s?(?:Z|UTC)(?![A-Za-z])", re.IGNORECASE)
_COLON_TIME_RE = re.compile(r"(?<![0-9:])(\d{2}):(\d{2})\s?(?:Z|UTC)?(?![0-9A-Za-z])", re.IGNORECASE)
_DDHHMM_RE = re.compile(r"(?<![0-9])(\d{2})(\d{2})(\d{2})Z\b")
_HHMM_RE = re.compile(r"(?<![0-9])(\d{2})(\d{2})\s?Z\b")


def _on_day(hh: int, mm: int, rd: date | None, not_before: datetime | None, span: str) -> datetime:
    if rd is None:
        raise ParseError(f"time without a date and no reference: {span!r}")
    if hh > 23 or mm > 59:
        raise ParseError(f"bad time {span!r}")
    t = datetime(rd.year, rd.month, rd.day, hh, mm, tzinfo=UTC)
    if not_before is not None and t < not_before:
        t += timedelta(days=1)
    return t


def parse_time(span: str, ref: datetime | date | None = None, not_before: datetime | None = None) -> datetime:
    """'2025-01-23T21:40:00Z', '23JAN 21:40Z', '24 Jan 2025 21:40Z', '25JAN ETA 14:00Z', '21:40Z', '2140Z',
    '241630Z' (METAR day+time). A time with no date takes `ref`'s date (and rolls to the next day if it would fall
    before `not_before`)."""
    s = span.strip()
    m = _ISO_RE.search(s)
    if m:
        y, mo, d, hh, mm, ss = (int(x) if x else 0 for x in m.groups()[:6])
        return datetime(y, mo, d, hh, mm, ss, tzinfo=UTC)
    rd = _ref_date(ref)
    m = _DMY_TIME_RE.search(s)
    if m:
        day, mon, year, hh, mm = m.groups()
        month = MONTHS[mon.upper()[:3]]
        y = int(year) if year else _year_for(month, rd)
        return datetime(y, month, int(day), int(hh), int(mm), tzinfo=UTC)
    m = _COLON_TIME_RE.search(s)
    if m:
        return _on_day(int(m.group(1)), int(m.group(2)), rd, not_before, span)
    m = _DDHHMM_RE.search(s)
    if m and rd is not None:
        d, hh, mm = (int(x) for x in m.groups())
        y, mo = rd.year, rd.month
        if d - rd.day > 15:
            mo -= 1
        elif rd.day - d > 15:
            mo += 1
        if mo == 0:
            y, mo = y - 1, 12
        if mo == 13:
            y, mo = y + 1, 1
        return datetime(y, mo, d, hh, mm, tzinfo=UTC)
    m = _HHMM_RE.search(s)
    if m:
        return _on_day(int(m.group(1)), int(m.group(2)), rd, not_before, span)
    raise ParseError(f"no time in {span!r}")


def parse_times(span: str, ref: datetime | date | None = None) -> list[datetime]:
    """Every HH:MMZ in the span, dated like parse_time."""
    out = []
    for m in _TIME_RE.finditer(span):
        out.append(parse_time(m.group(0), ref))
    return out


# ---------------------------------------------------------------- dates
_DATE_ISO = re.compile(r"(?<![0-9])(\d{4})-(\d{2})-(\d{2})(?![0-9])")
_DATE_DMY_NUM = re.compile(r"(?<![0-9])(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})(?![0-9])")
_DATE_DMY_TXT = re.compile(rf"(?<![0-9])(\d{{1,2}})(?:st|nd|rd|th)?\s?({_MON})\.?,?(?:\s?(\d{{4}}|\d{{2}}))?(?![0-9])",
                           re.IGNORECASE)
_DATE_MDY_TXT = re.compile(rf"\b({_MON})\.?\s(\d{{1,2}})(?:st|nd|rd|th)?,?\s(\d{{4}})\b", re.IGNORECASE)


def parse_date(span: str, ref: datetime | date | None = None) -> date:
    """'2025-01-24', '24/01/2025' (day first), '24 Jan 2025', '24 January 2025', '24JAN', '24JAN25',
    'Jan 24, 2025', '12 March 2018'."""
    s = span.strip()
    m = _DATE_ISO.search(s)
    if m:
        return date(*(int(x) for x in m.groups()))
    m = _DATE_DMY_NUM.search(s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return date(y + 2000 if y < 100 else y, mo, d)
    m = _DATE_MDY_TXT.search(s)
    if m:
        mon, d, y = m.groups()
        return date(int(y), MONTHS[mon.upper()[:3]], int(d))
    m = _DATE_DMY_TXT.search(s)
    if m:
        d, mon, y = m.groups()
        month = MONTHS[mon.upper()[:3]]
        year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else _year_for(month, _ref_date(ref))
        return date(year, month, int(d))
    raise ParseError(f"no date in {span!r}")


# ---------------------------------------------------------------- codes, tails, numbers
_ATA_RE = re.compile(r"\bATA\s?(\d{2})(?:[-\s]?(\d{2}))?(?![0-9])", re.IGNORECASE)
_ATA_DASH_RE = re.compile(r"(?<![0-9-])(\d{2})-(\d{2})(?:-\d{2})?(?![0-9])")
_ATA_BARE_RE = re.compile(r"^\s*(\d{4}|\d{2})\s*$")


def parse_ata(span: str, ref: Any = None) -> str:
    """'ATA 2913' / 'ATA 29-13' / '29-13' / '2913' → '2913'; 'ATA 29' → '29'."""
    for rx in (_ATA_RE, _ATA_DASH_RE, _ATA_BARE_RE):
        m = rx.search(span)
        if m:
            return "".join(g for g in m.groups() if g)
    raise ParseError(f"no ATA code in {span!r}")


_TAIL_RE = re.compile(r"(?<![A-Z0-9-])([A-Z]{1,2}-[A-Z0-9]{3,5})(?![A-Z0-9-])")
_N_TAIL_RE = re.compile(r"(?<![A-Z0-9])(N[1-9]\d{0,4}[A-Z]{0,2})(?![A-Z0-9])")


def parse_tail(span: str, ref: Any = None) -> str:
    """'EI-NSB', 'ei-nsb', 'G-EUPT', 'N123AB' → upper-case registration."""
    s = span.upper()
    m = _TAIL_RE.search(s) or _N_TAIL_RE.search(s)
    if not m:
        raise ParseError(f"no tail in {span!r}")
    return m.group(1)


_FLIGHT_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4})(?![0-9])")


def parse_flight_number(span: str, ref: Any = None) -> str:
    """'NS31', 'NS 31', 'ns0031' → 'NS31'."""
    m = _FLIGHT_RE.search(span.upper())
    if not m:
        raise ParseError(f"no flight number in {span!r}")
    return f"{m.group(1)}{int(m.group(2))}"


_IATA_RE = re.compile(r"(?<![A-Z])([A-Z]{3})(?![A-Z])")


def parse_iata(span: str, ref: Any = None) -> str:
    m = _IATA_RE.search(span.upper())
    if not m:
        raise ParseError(f"no IATA code in {span!r}")
    return m.group(1)


_SEAT_RE = re.compile(r"(?:SEAT\s?)?(?<![0-9A-Z])(\d{1,2}[A-K])(?![A-Z0-9])", re.IGNORECASE)


def parse_seat(span: str, ref: Any = None) -> str:
    m = _SEAT_RE.search(span)
    if not m:
        raise ParseError(f"no seat in {span!r}")
    return m.group(1).upper()


_DELAY_RE = re.compile(r"(?:RSN|RSN:|CODE|DL|DLY|IATA)\s?(\d{2})(?![0-9])", re.IGNORECASE)


def parse_delay_code(span: str, ref: Any = None) -> str:
    """'RSN 71' / 'CODE 41' / '71' → '71'."""
    m = _DELAY_RE.search(span) or re.fullmatch(r"\s*(\d{2})\s*", span)
    if not m:
        raise ParseError(f"no delay code in {span!r}")
    return m.group(1)


_INT_RE = re.compile(r"(?<![0-9.,])(-?\d{1,3}(?:,\d{3})+|-?\d+)(?![0-9])")


def parse_int(span: str, ref: Any = None) -> int:
    """First integer; '5,292' → 5292."""
    m = _INT_RE.search(span)
    if not m:
        raise ParseError(f"no integer in {span!r}")
    return int(m.group(1).replace(",", ""))


def parse_float(span: str, ref: Any = None) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", span)
    if not m:
        raise ParseError(f"no number in {span!r}")
    return float(m.group(0))


def parse_pct(span: str, ref: Any = None) -> float:
    """'29%' → 0.29; '0.29' → 0.29."""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s?%", span)
    if m:
        return round(float(m.group(1)) / 100, 6)
    v = parse_float(span)
    return v if v <= 1 else round(v / 100, 6)


# ---------------------------------------------------------------- money
_CUR = {"€": "EUR", "EUR": "EUR", "EURO": "EUR", "EUROS": "EUR", "£": "GBP", "GBP": "GBP", "$": "USD", "USD": "USD"}
_AMT = r"\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY_PRE = re.compile(rf"(€|£|\$|\bEUR|\bGBP|\bUSD)\s?({_AMT})(?![0-9])", re.IGNORECASE)
_MONEY_POST = re.compile(rf"(?<![0-9.,])({_AMT})\s?(€|£|EUR\b|EUROS?\b|GBP\b|USD\b)", re.IGNORECASE)


def _amount_to_cents(raw: str) -> int:
    s = raw.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    elif s.count(".") == 1 and len(s.rpartition(".")[2]) == 3:
        s = s.replace(".", "")                       # 1.234 (European thousands)
    elif s.count(".") > 1:
        s = s.replace(".", "")
    value = round(float(s) * 100)
    return int(value)


def parse_money(span: str, ref: Any = None) -> tuple[int, str]:
    """'€300' / 'EUR300' / 'EUR 510.00' / '600,00 €' / '€1,234.56' / '£520' → (cents, ISO currency)."""
    m = _MONEY_PRE.search(span)
    if m:
        return _amount_to_cents(m.group(2)), _CUR[m.group(1).upper()]
    m = _MONEY_POST.search(span)
    if m:
        return _amount_to_cents(m.group(1)), _CUR[m.group(2).upper()]
    raise ParseError(f"no amount with a currency in {span!r}")


def parse_eur(span: str, ref: Any = None) -> int:
    cents, cur = parse_money(span)
    if cur != "EUR":
        raise ParseError(f"amount is {cur}, not EUR: {span!r}")
    return cents


def parse_gbp(span: str, ref: Any = None) -> int:
    cents, cur = parse_money(span)
    if cur != "GBP":
        raise ParseError(f"amount is {cur}, not GBP: {span!r}")
    return cents


# ---------------------------------------------------------------- durations
_HM_RE = re.compile(r"(\d{1,3})\s?h(?:ours?|rs?)?\s?(\d{1,2})?\s?(?:m(?:in(?:utes?)?)?)?(?![a-z])", re.IGNORECASE)
_MIN_RE = re.compile(r"(\d{1,5})\s?(?:min(?:utes?)?|mins|m\b)", re.IGNORECASE)


def parse_minutes(span: str, ref: Any = None) -> int:
    """'STD+4h20' → 260, '+3h40' / '3 h 40 min' → 220, '220 min' → 220, '4h' → 240."""
    m = _HM_RE.search(span)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m = _MIN_RE.search(span)
    if m:
        return int(m.group(1))
    raise ParseError(f"no duration in {span!r}")


def parse_duration_h(span: str, ref: Any = None) -> float:
    """Hours, 2 dp: 'STD+4h20' → 4.33."""
    return round(parse_minutes(span) / 60, 2)


# ---------------------------------------------------------------- booleans with domain wording
def parse_bool(span: str, ref: Any = None) -> bool:
    s = span.strip().upper()
    if re.search(r"\b(NOT|NO|NEVER|FALSE|NIL)\b", s) and not re.search(r"\bNOT ONLY\b", s):
        return False
    if s:
        return True
    raise ParseError("empty span")


def parse_mel_relief(span: str, ref: Any = None) -> bool:
    """'NO MEL RELIEF' / 'MEL: NIL' → False; 'MEL 33-20-01 CAT C DEFERRED' → True."""
    s = span.upper()
    if re.search(r"NO\s+MEL(\s+RELIEF)?|MEL\s*:?\s*(NIL|NONE|N/A)|NOT\s+MEL|NO-GO", s):
        return False
    if re.search(r"MEL\s*[\d-]+|CAT\s?[A-D]\b|DEFER", s):
        return True
    raise ParseError(f"no MEL statement in {span!r}")


def parse_aog(span: str, ref: Any = None) -> bool:
    s = span.upper()
    if re.search(r"\bAOG\b", s):
        return not re.search(r"\bNOT\s+AOG\b|\bAOG\s+(CLEARED|LIFTED)\b", s)
    if re.search(r"\b(RTS|RELEASED|SERVICEABLE)\b", s):
        return False
    raise ParseError(f"no AOG statement in {span!r}")


def parse_signed(span: str, ref: Any = None) -> bool:
    """'SIGNATURE: NOT CAPTURED' / 'did not sign' / 'unsigned' → False; 'SIGNED ACCEPTANCE' → True."""
    s = span.upper()
    if re.search(r"NOT\s+(CAPTURED|SIGNED)|UNSIGNED|DID\s+NOT\s+SIGN|NO\s+SIG|WITHOUT\s+(A\s+)?SIG|W/O\s+SIG|NEVER\s+SIGN",
                 s):
        return False
    if re.search(r"\bSIGNED\b|SIGNATURE\s*:?\s*(CAPTURED|ON FILE|OK)", s):
        return True
    raise ParseError(f"no signature statement in {span!r}")


def parse_disputed(span: str, ref: Any = None) -> bool:
    """'I never agreed to take a voucher' / 'did not agree' / 'disputes' → True."""
    s = span.upper()
    if re.search(r"NEVER\s+AGREED|DID\s+NOT\s+AGREE|DIDN'T\s+AGREE|NOT\s+AGREE|DISPUTE|NEVER\s+ACCEPTED|"
                 r"DID\s+NOT\s+ACCEPT|REFUSED", s):
        return True
    if re.search(r"\bAGREED\b|\bACCEPTED\b", s):
        return False
    raise ParseError(f"no agreement statement in {span!r}")


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Every parser's contract: return a value or raise ParseError, never anything else. An impossible time or date
    (`24JAN 25:99Z`, `2025-02-30`), a non-string span or an odd number token becomes ParseError, so verify() can
    reject the span instead of crashing its caller (a bare ValueError once surfaced as a 500 on /api/inject)."""
    import functools

    @functools.wraps(fn)
    def wrapper(span: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(span, str):
            raise ParseError(f"span must be text, got {type(span).__name__}")
        try:
            return fn(span, *args, **kwargs)
        except ParseError:
            raise
        except (ValueError, OverflowError, TypeError, KeyError, IndexError, AttributeError) as e:
            raise ParseError(f"unparseable {span[:40]!r}: {e}") from None
    return wrapper


for _name in ("parse_time", "parse_times", "parse_date", "parse_ata", "parse_tail", "parse_flight_number",
              "parse_iata", "parse_seat", "parse_delay_code", "parse_int", "parse_float", "parse_pct", "parse_money",
              "parse_eur", "parse_gbp", "parse_minutes", "parse_duration_h", "parse_bool", "parse_mel_relief",
              "parse_aog", "parse_signed", "parse_disputed"):
    globals()[_name] = _guard(globals()[_name])


PARSERS: dict[str, Callable[..., Any]] = {
    "time": parse_time, "date": parse_date, "ata": parse_ata, "tail": parse_tail, "flight_number": parse_flight_number,
    "iata": parse_iata, "seat": parse_seat, "delay_code": parse_delay_code, "int": parse_int, "float": parse_float,
    "pct": parse_pct, "eur": parse_eur, "gbp": parse_gbp, "minutes": parse_minutes, "duration_h": parse_duration_h,
    "bool": parse_bool, "mel_relief": parse_mel_relief, "aog": parse_aog, "signed": parse_signed,
    "disputed": parse_disputed,
}


def reparse(field: str, span: str, ref: datetime | date | None = None) -> Any:
    """Re-parse `field`'s value from `span` with the registered parse kind. Raises ParseError / UnknownField."""
    spec = _fields.get(field)
    if spec.parse is None:
        raise ParseError(f"{field} has no parser (structured-only field)")
    fn = PARSERS[spec.parse]
    return fn(span, ref)


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        try:
            if "T" in v and v.endswith("Z"):
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                return date.fromisoformat(v)
        except ValueError:
            return v
    if isinstance(v, float):
        return round(v, 2)
    return v


def values_match(a: Any, b: Any) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 0.01
        except (TypeError, ValueError):
            return False
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().upper() == b.strip().upper()
    return a == b


def verify(field: str, value: Any, span: str | None, source_text: str | None,
           ref: datetime | date | None = None) -> tuple[bool, str]:
    """The Reader's acceptance test: (ok, reason). ok only if the field is registered, the span is a verbatim
    substring of the source text, and re-parsing the span gives the claimed value (when the field has a parser)."""
    if not _fields.is_registered(field):
        return False, "unregistered_field"
    if not span or not source_text or span not in source_text:
        return False, "span_not_in_source"
    if _fields.get(field).parse is None:
        return True, "structured"
    try:
        got = reparse(field, span, ref)
    except ParseError:
        return False, "unparseable_span"
    except Exception:  # noqa: BLE001  (defence in depth: a parser bug must reject the span, never crash)
        return False, "unparseable_span"
    try:
        same = values_match(got, value)
    except Exception:  # noqa: BLE001
        same = False
    return (True, "reparsed") if same else (False, "value_mismatch")
