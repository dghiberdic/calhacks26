"""Local semantic checks on a span, on top of the binding re-parse in ``contracts/parse.py``.

``contracts/parse.py`` re-parses times, dates, ATA codes, money, seats, MEL and signature wording. This module adds
the checks the contracts parsers can't make because they are generic (``bool``) or absent (structured fields):
e.g. ``voucher.in_lieu = true`` must quote a span that says "in lieu", an OCC group must name its flights and exactly
one code, a registration needs a known nationality prefix. Every check raises ``ParseError`` when the span doesn't
state the value; ``llm/verify.py`` then drops the key.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any


class ParseError(ValueError):
    pass


def norm_ws(s: str) -> str:
    """Whitespace normalisation used for span matching: NFC, every whitespace run → one space, stripped."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def iso_z(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- dates inside flight references
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_MON = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?"
_DATE_TOKEN = re.compile(rf"(?<![0-9])(\d{{1,2}})\s?{_MON}(?:\s?(\d{{4}}))?(?![A-Z])", re.IGNORECASE)
_ISO_DATE = re.compile(r"(?<![0-9])(\d{4})-(\d{2})-(\d{2})(?![0-9])")
_DMY = re.compile(r"(?<![0-9/])(\d{1,2})/(\d{1,2})/(\d{4})(?![0-9/])")       # European "24/01/2025"


def _year_for(month: int, day: int, ref: datetime) -> int:
    """The year that puts (month, day) closest to ``ref`` (handles a Dec/Jan rollover)."""
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            gap = abs((date(y, month, day) - ref.date()).days)
        except ValueError:
            continue
        if best is None or gap < best[0]:
            best = (gap, y)
    if best is None:
        raise ParseError(f"invalid day {day} for month {month}")
    return best[1]


def _dates(span: str, ref: datetime) -> list[date]:
    out: list[date] = []
    try:
        out += [date(int(m[1]), int(m[2]), int(m[3])) for m in _ISO_DATE.finditer(span)]
        out += [date(int(m[3]), int(m[2]), int(m[1])) for m in _DMY.finditer(span)]
        for m in _DATE_TOKEN.finditer(span):
            day, mon = int(m[1]), MONTHS[m[2].upper()[:3]]
            out.append(date(int(m[3]) if m[3] else _year_for(mon, day, ref), mon, day))
    except ValueError as e:
        raise ParseError(str(e)) from e
    return out


def _one(pattern: str, span: str, flags: int = 0, group: int = 1) -> str:
    found = {m.group(group) for m in re.finditer(pattern, span, flags)}
    if len(found) != 1:
        raise ParseError(f"expected exactly one match of {pattern!r} in {span!r}, got {sorted(found)}")
    return found.pop()


# ---------------------------------------------------------------- registrations, stations
# Nationality prefixes we accept (Europe + North America + common lessors): keeps "EX-TLS" (ex-Toulouse) from
# reading as a tail.
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


# ---------------------------------------------------------------- flights and OCC groups
# "NS100/101" is two flights; "NS31/24JAN" is NS31 on 24 Jan (a slash followed by a date is not a flight).
_FLIGHT_TOKEN = re.compile(r"(?<![A-Z0-9])NS(\d{1,4})((?:/\d{1,4}(?![0-9A-Z]))*)(?![0-9])")
CODE_RE = re.compile(r"\b(?:RSN|CODE|DLY|DL)\s?(\d{2})\b")


def _expand(m: re.Match) -> list[str]:
    first = m[1]
    out = [f"NS{first}"]
    for tail in filter(None, m[2].split("/")):
        out.append(f"NS{first[:len(first) - len(tail)]}{tail}" if len(tail) < len(first) else f"NS{tail}")
    return out


def _flights(span: str) -> list[str]:
    out: list[str] = []
    for m in _FLIGHT_TOKEN.finditer(span.upper()):
        out += [f for f in _expand(m) if f not in out]
    return out


def p_occ_group(span: str, ref: datetime) -> dict[str, Any]:
    """'RSN 71. NS100/101 NS102/103 ...' → {"code": "71", "flights": ["NS100", "NS101", ...]} (exactly one code)."""
    codes = {m[1] for m in CODE_RE.finditer(span.upper())}
    if len(codes) != 1:
        raise ParseError(f"expected exactly one delay code in {span!r}")
    flights = _flights(span)
    if not flights:
        raise ParseError(f"no flights in {span!r}")
    return {"code": codes.pop(), "flights": flights}


def c_occ_group(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ParseError("occ group must be an object")
    return {"code": re.sub(r"\D", "", str(v.get("code", ""))),
            "flights": [str(f).upper().replace(" ", "") for f in v.get("flights") or []]}


def eq_occ_group(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["code"] == b["code"] and sorted(a["flights"]) == sorted(b["flights"])


def p_cancel_note(span: str, ref: datetime) -> str:
    """'NS31 went in the batch too' / 'NS31 CNL' → 'NS31' (one flight, plus a cancel-list marker)."""
    if not re.search(r"\bBATCH\b|\bCNL\b|\bCANCEL", span.upper()):
        raise ParseError(f"no cancellation marker in {span!r}")
    flights = _flights(span)
    if len(flights) != 1:
        raise ParseError(f"expected exactly one flight in {span!r}")
    return flights[0]


def p_flight_ref(span: str, ref: datetime) -> str:
    """'NS31 24 Jan 2025' / 'NS31/24JAN' / 'NS31 DUB-BOS of 24/01/2025' → 'NS31@2025-01-24'; bare 'NS31' → 'NS31'."""
    flights = _flights(span)
    if len(flights) != 1:
        raise ParseError(f"expected exactly one Northstar flight in {span!r}")
    ds = set(_dates(span, ref))
    if len(ds) > 1:
        raise ParseError(f"more than one date in {span!r}")
    return f"{flights[0]}@{ds.pop().isoformat()}" if ds else flights[0]


def p_coupon(span: str, ref: datetime) -> str:
    return _one(r"(NS\d{1,4}@\d{4}-\d{2}-\d{2}:\d{1,2}[A-K])(?![A-Z0-9])", span.upper())


def p_pnr(span: str, ref: datetime) -> str:
    return _one(r"\b(?:PNR|BOOKING(?:\s+REF(?:ERENCE)?)?)\s?:?\s?([A-Z0-9]{6})(?![A-Z0-9])", span.upper())


# ---------------------------------------------------------------- claims
AGENCY_RE = (r"ON BEHALF OF|\bACT(?:ING|S)? FOR\b|\bAGENCY\b|CLAIMS? (?:COMPANY|AGENT|FIRM)|"
             r"\b(?:LTD|LLC|GMBH|BV|INC|SAS|SRL)\b")


def p_channel(span: str, ref: datetime) -> str:
    if re.search(AGENCY_RE, span.upper()):
        return "agency"
    raise ParseError(f"no agency marker in {span!r}")


def p_authority(span: str, ref: datetime) -> str:
    up = span.upper()
    if re.search(r"POWER OF ATTORNEY|\bPOA\b|\bMANDATE\b", up) and not re.search(r"\bNO (?:POWER|MANDATE)", up):
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


def p_regime(span: str, ref: datetime) -> str:
    up = span.upper()
    found = {m[1] + "261" for m in re.finditer(r"\b(EU|UK)\s?261\b", up)}
    if re.search(r"REG(?:ULATION|\.)?\s?\(EC\)\s?(?:NO\.?\s?)?261/2004", up):
        found.add("EU261")
    if len(found) != 1:
        raise ParseError(f"expected exactly one regime in {span!r}")
    return found.pop()


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


# ---------------------------------------------------------------- CRM / vouchers
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
    if re.search(r"\b(?:DECLINED|REFUSED|REJECTED|NOT ACCEPTED|NEVER (?:AGREED|ACCEPTED)|DID ?N[O']T (?:AGREE|ACCEPT))\b",
                 up):
        return False
    if re.search(r"\b(?:ACCEPTED|AGREED)\b", up):
        return True
    raise ParseError(f"no acceptance statement in {span!r}")


# ---------------------------------------------------------------- manufacturer, weather
def p_hidden_defect(span: str, ref: datetime) -> bool:
    if re.search(r"(?:HIDDEN|LATENT|MANUFACTURING)\b.{0,30}\bDEFECT", span.upper()):
        return True
    raise ParseError(f"no hidden-defect statement in {span!r}")


def p_part_number(span: str, ref: datetime) -> str:
    return _one(r"\bP/?N\s?:?\s?([A-Z0-9][A-Z0-9-]*[A-Z0-9])", span.upper())


def p_red(span: str, ref: datetime) -> bool:
    if re.search(r"\bRED\b", span.upper()):
        return True
    raise ParseError(f"no red warning in {span!r}")


def p_orange(span: str, ref: datetime) -> bool:
    if re.search(r"\bORANGE\b", span.upper()):
        return True
    raise ParseError(f"no orange warning in {span!r}")


# ---------------------------------------------------------------- canonicalisers
def c_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "yes", "1"}:
        return True
    if s in {"false", "no", "0"}:
        return False
    raise ParseError(f"not a boolean: {v!r}")


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


def c_upper(v: Any) -> str:
    return str(v).strip().upper()


def c_lower(v: Any) -> str:
    return str(v).strip().lower()


def c_regime(v: Any) -> str:
    return re.sub(r"\s", "", str(v)).upper()


def c_list_upper(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip().upper() for x in v]


def eq_default(a: Any, b: Any) -> bool:
    return a == b


def eq_list(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)


Parser = Callable[[str, datetime], Any]
Canon = Callable[[Any], Any]
Eq = Callable[[Any, Any], bool]

# parser name → (parse from span, canonicalise the LLM's value, equality)
PARSERS: dict[str, tuple[Parser, Canon, Eq]] = {
    "tail": (p_tail, c_upper, eq_default),
    "tails": (p_tails, c_list_upper, eq_list),
    "iata": (p_iata, c_upper, eq_default),
    "occ_group": (p_occ_group, c_occ_group, eq_occ_group),
    "cancel_note": (p_cancel_note, c_upper, eq_default),
    "flight_ref": (p_flight_ref, c_upper, eq_default),
    "coupon": (p_coupon, c_upper, eq_default),
    "pnr": (p_pnr, c_upper, eq_default),
    "channel": (p_channel, c_lower, eq_default),
    "authority": (p_authority, c_lower, eq_default),
    "money_cents": (p_money_cents, c_int, eq_default),
    "currency": (p_currency, c_upper, eq_default),
    "regime": (p_regime, c_regime, eq_default),
    "instruction": (p_instruction, c_bool, eq_default),
    "crm_kind": (p_crm_kind, c_lower, eq_default),
    "in_lieu": (p_in_lieu, c_bool, eq_default),
    "accepted": (p_accepted, c_bool, eq_default),
    "hidden_defect": (p_hidden_defect, c_bool, eq_default),
    "part_number": (p_part_number, c_upper, eq_default),
    "red": (p_red, c_bool, eq_default),
    "orange": (p_orange, c_bool, eq_default),
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
