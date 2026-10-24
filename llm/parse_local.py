"""Typed re-parse of a Fact value FROM its verbatim span (local stand-in for ``contracts/parse.py``).

Every Reader fact must survive ``reparse(field, span, ref)``: the value the LLM claims is compared to the value
this module derives from the quoted span alone. Parsers are deliberately small and strict; anything ambiguous raises
``ParseError`` and the fact is dropped (``dropped_unverifiable``).

``ref`` is the source's ``received_at``: it supplies the year (and the date, for a bare ``HH:MMZ``).
When David's ``contracts/parse.py`` lands, ``llm/verify.py`` switches to it (see llm/DECISIONS.md).
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any


class ParseError(ValueError):
    pass


def norm_ws(s: str) -> str:
    """Whitespace normalisation used for span matching: NFC, every whitespace run → one space, stripped."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_MON = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?"
_DATE_TOKEN = re.compile(rf"(?<![0-9])(\d{{1,2}})\s?{_MON}(?:\s?(\d{{4}}))?(?![A-Z])", re.I)
_ISO_DATE = re.compile(r"(?<![0-9])(\d{4})-(\d{2})-(\d{2})(?![0-9])")
_ISO_DT = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s?(Z|[+-]00:?00)?")
_TIME_Z = re.compile(r"(?<![0-9:])(\d{2}):?(\d{2})\s?Z\b", re.I)          # "21:40Z", "1400z"
_DMY = re.compile(r"(?<![0-9/])(\d{1,2})/(\d{1,2})/(\d{4})(?![0-9/])")       # European "24/01/2025"


def _year_for(month: int, day: int, ref: datetime) -> int:
    """The year that puts (month, day) closest to ``ref`` (handles a Dec/Jan rollover)."""
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        gap = abs((d - ref.date()).days)
        if best is None or gap < best[0]:
            best = (gap, y)
    if best is None:
        raise ParseError(f"invalid day {day} for month {month}")
    return best[1]


def _dates(span: str, ref: datetime) -> list[tuple[int, date]]:
    """All date tokens in the span as (position, date)."""
    out: list[tuple[int, date]] = []
    for m in _ISO_DATE.finditer(span):
        try:
            out.append((m.start(), date(int(m[1]), int(m[2]), int(m[3]))))
        except ValueError as e:
            raise ParseError(str(e)) from e
    for m in _DMY.finditer(span):
        try:
            out.append((m.start(), date(int(m[3]), int(m[2]), int(m[1]))))
        except ValueError as e:
            raise ParseError(str(e)) from e
    for m in _DATE_TOKEN.finditer(span):
        day, mon = int(m[1]), MONTHS[m[2].upper()[:3]]
        year = int(m[3]) if m[3] else _year_for(mon, day, ref)
        try:
            out.append((m.start(), date(year, mon, day)))
        except ValueError as e:
            raise ParseError(str(e)) from e
    return sorted(out)


def iso_z(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def p_datetime(span: str, ref: datetime) -> str:
    """'23JAN 21:40Z' → 2025-01-23T21:40:00Z. The LAST time in the span, dated by the last date token before it
    (else the reference date). A full ISO datetime is taken as is."""
    m = _ISO_DT.search(span)
    if m:
        y, mo, d, hh, mm, ss = (int(x) if x else 0 for x in m.groups()[:6])
        return iso_z(datetime(y, mo, d, hh, mm, ss, tzinfo=UTC))
    times = list(_TIME_Z.finditer(span))
    if not times:
        raise ParseError(f"no HH:MMZ time in {span!r}")
    t = times[-1]
    hh, mm = int(t[1]), int(t[2])
    if hh > 23 or mm > 59:
        raise ParseError(f"bad time {t[0]!r}")
    before = [d for pos, d in _dates(span, ref) if pos < t.start()]
    day = before[-1] if before else ref.astimezone(UTC).date()
    return iso_z(datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC))


def c_datetime(v: Any) -> str:
    if isinstance(v, datetime):
        return iso_z(v if v.tzinfo else v.replace(tzinfo=UTC))
    s = str(v).strip().replace(" ", "T")
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ParseError(f"not an ISO datetime: {v!r}") from e
    return iso_z(t if t.tzinfo else t.replace(tzinfo=UTC))


def p_date(span: str, ref: datetime) -> str:
    ds = _dates(span, ref)
    if len({d for _, d in ds}) != 1:
        raise ParseError(f"expected exactly one date in {span!r}")
    return ds[0][1].isoformat()


def c_date(v: Any) -> str:
    try:
        return date.fromisoformat(str(v).strip()[:10]).isoformat()
    except ValueError as e:
        raise ParseError(f"not an ISO date: {v!r}") from e


def _one(pattern: str, span: str, flags: int = 0, group: int = 1) -> str:
    found = {m.group(group) for m in re.finditer(pattern, span, flags)}
    if len(found) != 1:
        raise ParseError(f"expected exactly one match of {pattern!r} in {span!r}, got {sorted(found)}")
    return found.pop()


# Nationality prefixes we accept for registrations (Europe + North America + common lessors). Restricting the
# prefix keeps station codes like "EX-TLS" (ex-Toulouse) from reading as a tail.
REG_PREFIXES = ("EI", "G", "D", "F", "EC", "PH", "OO", "HB", "OE", "LN", "SE", "OY", "OH", "SP", "OK", "HA", "YR",
                "LZ", "SX", "9H", "CS", "I", "TC", "C", "VH", "LX", "ES", "YL", "LY", "S5", "9A", "OM", "TF")
TAIL_RE = rf"(?<![A-Z0-9-])((?:{'|'.join(REG_PREFIXES)})-[A-Z0-9]{{3,5}})(?![A-Z0-9-])"


def p_tail(span: str, ref: datetime) -> str:
    return _one(TAIL_RE, span.upper())


def p_tails(span: str, ref: datetime) -> list[str]:
    tails = list(dict.fromkeys(re.findall(TAIL_RE, span.upper())))
    if not tails:
        raise ParseError(f"no aircraft registration in {span!r}")
    return tails


def p_iata(span: str, ref: datetime) -> str:
    return _one(r"(?<![A-Z])([A-Z]{3})(?![A-Z])", span)


# Component phrase → ATA chapter-section (FAA JASC / ATA Spec 100), in priority order: an external strike wins
# over the engine damage it caused. Covers the generator's defect families (world/texts.py); unknown → no fact.
ATA_KEYWORDS = [
    (r"BIRD ?STRIKE|LIGHTNING ?STRIKE", "0551"),
    (r"\bEDP\b|ENGINE[- ]DRIVEN PUMP", "2913"),
    (r"\bBRK\b|\bBRAKE", "3242"),
    (r"BORESCOPE|\bHPT\b|BLADE CRACK|ENG(?:INE)? CHANGE", "7250"),
    (r"RETRACTION ACTUATOR", "3230"),
    (r"FUEL LEAK", "2810"),
    (r"RUDDER SERVO", "2720"),
    (r"FLAP PCU|\bFLAP\b.*\bPCU\b", "2751"),
    (r"\bAOA SENSOR|\bADR\s?\d", "3411"),
    (r"\bIDG\b", "2422"),
    (r"\bADIRU\b", "3412"),
    (r"\bCPC\s?\d", "2130"),
    (r"\bPACK\s?\d", "2152"),
    (r"WINDSHIELD HEAT|WSHLD HEAT", "3043"),
    (r"CABIN LTG", "3311"),
    (r"\bPSU\b.*READING LT", "3320"),
    (r"APU BLEED", "3611"),
]


def p_ata(span: str, ref: datetime) -> str:
    up = span.upper()
    m = re.search(r"\bATA\s?(\d{2})[-\s]?(\d{2})\b", up)
    if m:
        return m[1] + m[2]
    for pat, code in ATA_KEYWORDS:
        if re.search(pat, up):
            return code
    raise ParseError(f"no ATA reference in {span!r}")


def c_ata(v: Any) -> str:
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 2:
        digits += "00"
    if len(digits) != 4:
        raise ParseError(f"ATA must be 4 digits: {v!r}")
    return digits


def p_mel(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"\bNO[- ]MEL\b|NO MEL RELIEF|\bNO[- ]?GO\b|NOT DEFERRABLE|\bMEL:?\s?NIL\b", up):
        return False
    if re.search(r"MEL RELIEF|\bMEL\s?\d|\bDEFERRED\b|\bCAT\s?[ABCD]\b", up):
        return True
    raise ParseError(f"no MEL statement in {span!r}")


def p_aog(span: str, ref: datetime) -> bool:
    if re.search(r"\bAOG\b", span.upper()):
        return True
    raise ParseError(f"no AOG statement in {span!r}")


def p_stock(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"\bNO\b.*\bIN\b.*\bSTORES?\b|NIL STOCK|NOT IN STOCK|OUT OF STOCK", up):
        return False
    if re.search(r"IN STOCK|AVAILABLE IN STORES?|EX[- ]STORES", up):
        return True
    raise ParseError(f"no stock statement in {span!r}")


def p_text(span: str, ref: datetime) -> str:
    s = norm_ws(span)
    if len(s) < 3:
        raise ParseError("text too short")
    return s


def c_text(v: Any) -> str:
    return norm_ws(str(v))


# "NS100/101" is two flights; "NS31/24JAN" is NS31 on 24 Jan (a slash followed by a date is not a flight).
_FLIGHT_TOKEN = re.compile(r"(?<![A-Z0-9])NS(\d{1,4})((?:/\d{1,4}(?![0-9A-Z]))*)(?![0-9])")


def _expand(m: re.Match) -> list[str]:
    first = m[1]
    out = [f"NS{first}"]
    for tail in filter(None, m[2].split("/")):
        out.append(f"NS{first[:len(first) - len(tail)]}{tail}" if len(tail) < len(first) else f"NS{tail}")
    return out


CODE_RE = re.compile(r"\b(?:RSN|CODE|DLY|DL)\s?(\d{2})\b")


def p_occ_group(span: str, ref: datetime) -> dict[str, Any]:
    """'RSN 71. NS100/101 NS102/103 ...' → {"code": "71", "flights": ["NS100", "NS101", ...]} (exactly one code)."""
    codes = {m[1] for m in CODE_RE.finditer(span.upper())}
    if len(codes) != 1:
        raise ParseError(f"expected exactly one delay code in {span!r}")
    flights: list[str] = []
    for m in _FLIGHT_TOKEN.finditer(span.upper()):
        flights += [f for f in _expand(m) if f not in flights]
    if not flights:
        raise ParseError(f"no flights in {span!r}")
    return {"code": codes.pop(), "flights": flights}


def c_occ_group(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ParseError("occ group must be an object")
    code = re.sub(r"\D", "", str(v.get("code", "")))
    flights = [str(f).upper().replace(" ", "") for f in v.get("flights") or []]
    return {"code": code, "flights": flights}


def eq_occ_group(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["code"] == b["code"] and sorted(a["flights"]) == sorted(b["flights"])


def p_code(span: str, ref: datetime) -> str:
    return _one(CODE_RE.pattern, span.upper())


def p_hours(span: str, ref: datetime) -> float:
    up = span.upper()
    m = re.search(r"STD\s?\+\s?(\d{1,2})\s?H\s?(\d{1,2})?", up)
    if m:
        return round(int(m[1]) + int(m[2] or 0) / 60, 2)
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s?(?:H|HRS?|HOURS?)\b", up)
    if m:
        return round(float(m[1]), 2)
    raise ParseError(f"no duration in {span!r}")


def c_float(v: Any) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError) as e:
        raise ParseError(f"not a number: {v!r}") from e


def eq_float(a: float, b: float) -> bool:
    return abs(a - b) < 0.011


def p_tail_at_station(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"\bNO\b(?:\s+[\w-]+){0,2}\s+(?:TAIL|SPARE|AIRCRAFT)\b", up):
        return False
    if re.search(r"(?:TAIL|SPARE|AIRCRAFT)\s+AVAILABLE", up):
        return True
    raise ParseError(f"no spare-tail statement in {span!r}")


def p_flight_ref(span: str, ref: datetime) -> str:
    """'NS31 24 Jan 2025' → 'NS31@2025-01-24'; a bare 'NS31' → 'NS31'."""
    flights = {f for m in _FLIGHT_TOKEN.finditer(span.upper()) for f in _expand(m)}
    if len(flights) != 1:
        raise ParseError(f"expected exactly one Northstar flight in {span!r}")
    f = flights.pop()
    ds = {d for _, d in _dates(span, ref)}
    if len(ds) > 1:
        raise ParseError(f"more than one date in {span!r}")
    return f"{f}@{ds.pop().isoformat()}" if ds else f


def c_upper(v: Any) -> str:
    return str(v).strip().upper()


def p_pax(span: str, ref: datetime) -> str:
    return _one(r"(?<![A-Z0-9@:])(\d{1,2}[A-K])(?![A-Z0-9])", span.upper())


def p_coupon(span: str, ref: datetime) -> str:
    return _one(r"(NS\d{1,4}@\d{4}-\d{2}-\d{2}:\d{1,2}[A-K])(?![A-Z0-9])", span.upper())


AGENCY_RE = (r"ON BEHALF OF|\bACT(?:ING|S)? FOR\b|\bAGENCY\b|CLAIMS? (?:COMPANY|AGENT|FIRM)|"
             r"\b(?:LTD|LLC|GMBH|BV|INC|SAS|SRL)\b")


def p_channel(span: str, ref: datetime) -> str:
    if re.search(AGENCY_RE, span.upper()):
        return "agency"
    raise ParseError(f"no agency marker in {span!r}")


def c_lower(v: Any) -> str:
    return str(v).strip().lower()


def p_authority(span: str, ref: datetime) -> str:
    up = span.upper()
    if re.search(r"POWER OF ATTORNEY|\bPOA\b|\bMANDATE\b(?! NOT)", up) and not re.search(r"\bNO (?:POWER|MANDATE)", up):
        return "poa"
    if re.search(r"\bASSIGN(?:ED|MENT)\b", up):
        return "assignment"
    if re.search(r"\bNO (?:AUTHORITY|MANDATE|POWER OF ATTORNEY)\b|WITHOUT (?:AUTHORITY|A MANDATE)", up):
        return "none"
    raise ParseError(f"no authority statement in {span!r}")


_MONEY = [   # "€600", "EUR 510.00", "EUR 600,00" (decimal comma), "EUR 46,417.39", "€5,000"
    re.compile(r"(€|EUR|£|GBP|\$|USD)\s?(\d{1,3}(?:,\d{3})+|\d+)(?:[.,](\d{2}))?(?![0-9])"),
    re.compile(r"(?<![0-9.,])(\d{1,3}(?:,\d{3})+|\d+)(?:[.,](\d{2}))?\s?(EUR|GBP|USD)\b"),
]
_CUR = {"€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "$": "USD", "USD": "USD"}


def _money(span: str) -> tuple[str, int]:
    found: set[tuple[str, int]] = set()
    up = span.upper()
    for m in _MONEY[0].finditer(up):
        found.add((_CUR[m[1]], int(m[2].replace(",", "")) * 100 + int(m[3] or 0)))
    for m in _MONEY[1].finditer(up):
        found.add((_CUR[m[3]], int(m[1].replace(",", "")) * 100 + int(m[2] or 0)))
    if len(found) != 1:
        raise ParseError(f"expected exactly one amount in {span!r}, got {sorted(found)}")
    return found.pop()


def p_money_cents(span: str, ref: datetime) -> int:
    return _money(span)[1]


def p_currency(span: str, ref: datetime) -> str:
    return _money(span)[0]


def c_int(v: Any) -> int:
    if isinstance(v, bool):
        raise ParseError("bool is not an amount")
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise ParseError(f"not an integer: {v!r}") from e
    if f != int(f):
        raise ParseError(f"not an integer: {v!r}")
    return int(f)


def p_regime(span: str, ref: datetime) -> str:
    up = span.upper()
    found = {m[1] + "261" for m in re.finditer(r"\b(EU|UK)\s?261\b", up)}
    if re.search(r"REG(?:ULATION|\.)?\s?\(EC\)\s?(?:NO\.?\s?)?261/2004", up):
        found.add("EU261")
    if len(found) != 1:
        raise ParseError(f"expected exactly one regime in {span!r}")
    return found.pop()


def c_regime(v: Any) -> str:
    return re.sub(r"\s", "", str(v)).upper()


def p_voucher_dispute(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"VOUCHER|IN LIEU", up) and re.search(
            r"NEVER (?:AGREED|ACCEPTED|SIGNED)|DID ?N[O']T (?:AGREE|ACCEPT|SIGN)|NOT (?:AGREE|ACCEPT)|REFUSED?|"
            r"WITHOUT MY (?:CONSENT|AGREEMENT)|DID NOT CONSENT", up):
        return True
    raise ParseError(f"no voucher dispute in {span!r}")


INSTRUCTION_RE = (r"IGNORE (?:ALL |ANY )?(?:PREVIOUS|PRIOR|ABOVE|EARLIER|THE) (?:INSTRUCTIONS|TECH LOG|RULES)|"
                  r"\bDISREGARD\b|\bSYSTEM(?: NOTE)?\b[^:\n]{0,30}:|\bASSISTANT\s?:|\bINSTRUCTIONS?\s?:|<!--|"
                  r"\bYOU ARE NOW\b|\bMARK\b.{0,40}\bAPPROVED\b|\bAPPROVE (?:ALL|THE|THIS|THESE|A)\b|"
                  r"\bAPPROVED BY\b|\bOVERRIDE\b|\bAUTHORI[SZ]E (?:YOU|THE |ALL )|SKIP THE APPROVAL|"
                  r"\bREPLY APPROVED\b|RELEASE (?:THE )?PAY(?:MENT|OUT)|\bSET [A-Z_.]+\s?=|TREAT THIS (?:EMAIL|"
                  r"MESSAGE) AS")


def p_instruction(span: str, ref: datetime) -> bool:
    if re.search(INSTRUCTION_RE, span.upper()):
        return True
    raise ParseError(f"no instruction marker in {span!r}")


CRM_KINDS = [  # first match wins
    (r"CHARGE ?BACK", "chargeback"),
    (r"\bBSP\b.*\bR(?:E)?F(?:U)?ND|\bR(?:E)?F(?:U)?ND\b.*\bBSP\b", "bsp_refund"),
    (r"IN LIEU", "voucher_in_lieu_of_compensation"),
    (r"REFUND VOUCHER|VOUCHER ISSUED", "voucher_issued"),
    (r"REFUND|\bRFND\b", "refund_initiated"),
    (r"VOUCHER", "voucher_issued"),
    (r"HOTEL|MEAL|CARE|TAXI|TRANSPORT", "care_issued"),
    (r"RIGHTS|NOTICE|EMAIL", "rights_email_sent"),
]


def p_crm_kind(span: str, ref: datetime) -> str:
    up = span.upper()
    for pat, kind in CRM_KINDS:
        if re.search(pat, up):
            return kind
    raise ParseError(f"no CRM event kind in {span!r}")


def p_in_lieu(span: str, ref: datetime) -> bool:
    if re.search(r"IN LIEU", span.upper()):
        return True
    raise ParseError(f"no 'in lieu' in {span!r}")


def p_accepted(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"\b(?:DECLINED|REFUSED|REJECTED|NOT ACCEPTED)\b", up):
        return False
    if re.search(r"\b(?:ACCEPTED|AGREED)\b", up):
        return True
    raise ParseError(f"no acceptance statement in {span!r}")


def p_signed(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"\bUNSIGNED\b|NOT SIGNED|NO SIGNATURE|NO SIGNED|WITHOUT (?:A )?SIGNATURE|DID ?N[O']T SIGN|"
                 r"NOT CAPTURED|\bNO SIG\b|W/O SIG", up):
        return False
    if re.search(r"\bSIGNED\b|SIGNATURE ON FILE|\bSIGNATURE\b", up):
        return True
    raise ParseError(f"no signature statement in {span!r}")


def p_hidden_defect(span: str, ref: datetime) -> bool:
    up = span.upper()
    if re.search(r"(?:HIDDEN|LATENT|MANUFACTURING)\b.{0,30}\bDEFECT", up):
        return True
    raise ParseError(f"no hidden-defect statement in {span!r}")


def p_part_number(span: str, ref: datetime) -> str:
    return _one(r"\bP/?N\s?:?\s?([A-Z0-9][A-Z0-9-]*[A-Z0-9])", span.upper())


def p_pnr(span: str, ref: datetime) -> str:
    return _one(r"\b(?:PNR|BOOKING(?:\s+REF(?:ERENCE)?)?)\s?:?\s?([A-Z0-9]{6})(?![A-Z0-9])", span.upper())


def p_not_weather(span: str, ref: datetime) -> bool:
    """An internal note that a cancellation coded as weather was not weather ('NOT a wx cancel', 'AOG anyway')."""
    if re.search(r"\bNOT (?:A )?(?:WX|WEATHER)\b|\bAOG ANYWAY\b|\bWAS AOG\b|\bNOT WX\b", span.upper()):
        return True
    raise ParseError(f"no not-weather statement in {span!r}")


def p_weather_no_comp(span: str, ref: datetime) -> bool:
    """A passenger notice that says 'weather, no compensation' (what the CRM bot sent)."""
    up = span.upper()
    if re.search(r"WEATHER|\bWX\b", up) and re.search(r"NO COMPENSATION", up):
        return True
    raise ParseError(f"no weather/no-compensation statement in {span!r}")


def p_invoice_ref(span: str, ref: datetime) -> str:
    return _one(r"\b(INV[-/]?[A-Z0-9][A-Z0-9-]*[0-9])\b", span.upper())


def p_warning_level(span: str, ref: datetime) -> str:
    return _one(r"\b(RED|ORANGE|YELLOW)\b", span.upper())


def c_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "yes", "1"}:
        return True
    if s in {"false", "no", "0"}:
        return False
    raise ParseError(f"not a boolean: {v!r}")


def eq_default(a: Any, b: Any) -> bool:
    return a == b


def eq_text(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def eq_list(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)


def c_list_upper(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip().upper() for x in v]


Parser = Callable[[str, datetime], Any]
Canon = Callable[[Any], Any]
Eq = Callable[[Any, Any], bool]

# parser name → (parse from span, canonicalise the LLM's value, equality)
PARSERS: dict[str, tuple[Parser, Canon, Eq]] = {
    "datetime": (p_datetime, c_datetime, eq_default),
    "date": (p_date, c_date, eq_default),
    "tail": (p_tail, c_upper, eq_default),
    "tails": (p_tails, c_list_upper, eq_list),
    "iata": (p_iata, c_upper, eq_default),
    "ata": (p_ata, c_ata, eq_default),
    "mel": (p_mel, c_bool, eq_default),
    "aog": (p_aog, c_bool, eq_default),
    "stock": (p_stock, c_bool, eq_default),
    "text": (p_text, c_text, eq_text),
    "occ_group": (p_occ_group, c_occ_group, eq_occ_group),
    "code": (p_code, lambda v: re.sub(r"\D", "", str(v)), eq_default),
    "hours": (p_hours, c_float, eq_float),
    "tail_at_station": (p_tail_at_station, c_bool, eq_default),
    "flight_ref": (p_flight_ref, c_upper, eq_default),
    "pax": (p_pax, c_upper, eq_default),
    "coupon": (p_coupon, c_upper, eq_default),
    "channel": (p_channel, c_lower, eq_default),
    "authority": (p_authority, c_lower, eq_default),
    "money_cents": (p_money_cents, c_int, eq_default),
    "currency": (p_currency, c_upper, eq_default),
    "regime": (p_regime, c_regime, eq_default),
    "voucher_dispute": (p_voucher_dispute, c_bool, eq_default),
    "instruction": (p_instruction, c_bool, eq_default),
    "crm_kind": (p_crm_kind, c_lower, eq_default),
    "in_lieu": (p_in_lieu, c_bool, eq_default),
    "accepted": (p_accepted, c_bool, eq_default),
    "signed": (p_signed, c_bool, eq_default),
    "hidden_defect": (p_hidden_defect, c_bool, eq_default),
    "part_number": (p_part_number, c_upper, eq_default),
    "pnr": (p_pnr, c_upper, eq_default),
    "not_weather": (p_not_weather, c_bool, eq_default),
    "weather_no_comp": (p_weather_no_comp, c_bool, eq_default),
    "invoice_ref": (p_invoice_ref, c_upper, eq_default),
    "warning_level": (p_warning_level, c_upper, eq_default),
}


def reparse(parser: str, span: str, ref: datetime) -> Any:
    """Typed value from the span alone (raises ParseError)."""
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return PARSERS[parser][0](norm_ws(span), ref)


def matches(parser: str, claimed: Any, parsed: Any) -> bool:
    """Does the LLM's claimed value equal the value re-parsed from the span?"""
    _, canon, eq = PARSERS[parser]
    try:
        return eq(canon(claimed), parsed)
    except ParseError:
        return False


__all__ = ["ParseError", "PARSERS", "TAIL_RE", "matches", "norm_ws", "reparse", "iso_z"]
