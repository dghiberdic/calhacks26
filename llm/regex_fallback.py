"""``fallback:regex@1``: deterministic extractors used when the LLM is unavailable (offline miss, timeout, refusal,
cap). They produce the same keys as the LLM schemas (``llm/fields.py``) and only pick spans: every value is the
re-parse of its span, and the candidates go through the same verification as the LLM's. Coverage: tech-log, MCC,
OCC, spares, claim/email and CRM/BSP lines, and manufacturer notices.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from contracts.models import SourceKind
from llm.parse_local import AGENCY_RE, CODE_RE, INSTRUCTION_RE, TAIL_RE
from llm.verify import Candidate

EXTRACTOR = "fallback:regex@1"

_TAIL = TAIL_RE.replace("((?:", "(?:(?:", 1)          # same pattern, non-capturing
_MONS = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?"
_DDMON = rf"\d{{1,2}}\s?{_MONS}"
_TIME = r"\d{2}:?\d{2}\s?Z"
_DT = rf"{_DDMON}\s+{_TIME}"
_DATE = rf"(?:{_DDMON}\s?\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|{_DDMON})"
_MONEY = (r"(?:€|EUR|£|GBP|\$|USD)\s?\d[\d,]*(?:[.,]\d{2})?(?![0-9])|"
          r"(?<![0-9.,])\d[\d,]*(?:[.,]\d{2})?\s?(?:EUR|GBP|USD)\b")
_FLT = r"NS\d{1,4}(?:/\d{1,4}(?![0-9A-Z]))*"
_SEAT = r"\d{1,2}[A-K](?![A-Z0-9])"


def _first(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(0).strip(" .,;·") if m else None


def _add(out: list[Candidate], key: str, span: str | None, value: object = None, **meta) -> None:
    if span:
        out.append(Candidate(key, value, span, {"regex": True, **meta}))


def _instruction(text: str) -> str | None:
    m = re.search(rf"[^.\n]*?(?:{INSTRUCTION_RE})[^.\n]*", text, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _common(text: str, out: list[Candidate]) -> list[Candidate]:
    _add(out, "instruction", _instruction(text))
    return out


def _outside_instruction(span: str | None, text: str) -> str | None:
    """Drop an amount that sits inside an instruction attempt ('approve a €5,000 payment')."""
    inst = _instruction(text)
    return None if span and inst and span in inst else span


# ---------------------------------------------------------------- maintenance
def _aog(text: str, out: list[Candidate], *, loose_time: bool = False) -> None:
    _add(out, "tail", _first(_TAIL, text, 0))
    # an AMOS header time is "<ddMON> <hh:mmZ> <tail>" or "RAISED <ddMON> <hh:mmZ>"; a bare time only in a tech log
    _add(out, "logged_at", _first(rf"{_DT}(?=\s+{_TAIL})", text) or _first(rf"RAISED\s+{_DT}", text)
         or (_first(_DT, text) if loose_time else None))
    _add(out, "mel_relief", _first(r"MEL:\s?NIL(?:\s?-\s?NO-?GO)?|NO[- ]MEL RELIEF|\bNO[- ]MEL\b|MEL RELIEF|"
                                   r"\bMEL\s?\d[\d-]*(?:\s?CAT\s?[ABCD])?(?:\s+DEFERRED)?|MEL:\s?DEFERRED", text))
    _add(out, "aog", _first(r"(?:A/C\s+)?\bAOG\b", text, 0))
    _add(out, "ata", _first(r"\bATA\s?\d{2}[-\s]?\d{2}\b", text))


def tech_log(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    _aog(text, out, loose_time=True)
    m = re.search(rf"{_TAIL}\s+([A-Z]{{3}})\b", text)
    if m:
        _add(out, "station", m.group(1))
    _add(out, "rts_est", _first(rf"RTS\s+(?:EST\s+)?{_DDMON}\s+{_TIME}", text))
    # defect text: after "<ddMON> <time> <tail> <stn> [N/S.]", up to the MEL / AOG statement
    m = re.search(rf"{_DT}\s+{_TAIL}\s+[A-Z]{{3}}\s*(?:N/S\.?)?\s*(.+?)\s*(?:NO[- ]MEL|\bMEL\b|DEFERRED|A/C AOG|\bAOG\b|$)",
                  text)
    if m and len(m.group(1).strip(" .")) >= 3:
        _add(out, "defect_text", m.group(1).strip(" ."))
    return _common(text, out)


def _mcc(text: str, out: list[Candidate]) -> None:
    _add(out, "part_eta", _first(rf"{_DDMON}\s+ETA\s+{_TIME}|ETA\s+{_DDMON}\s+{_TIME}", text))
    _add(out, "rts_est", _first(rf"RTS\s+(?:EST\s+)?{_DDMON}\s+{_TIME}", text))   # only with its own date


def mcc_log(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    _add(out, "tail", _first(_TAIL, text, 0))
    _mcc(text, out)
    return _common(text, out)


def occ_log(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    spans: list[str] = []
    # "RSN 71. NS100/101 ... NS31" | "INBD NS20 NS30 RSN 72" | "CNL NS106 NS114 RSN 71" | "NS30 BOS-DUB 25JAN CNL RSN 41"
    for pat in (rf"\b(?:RSN|CODE|DLY)\s?\d{{2}}\.?\s+(?:{_FLT}[\s,]*)+",
                rf"(?:{_FLT}[\s,]+)+(?:CNL\s+)?(?:RSN|CODE|DLY)\s?\d{{2}}\b",
                rf"{_FLT}\s+[A-Z]{{3}}-[A-Z]{{3}}(?:\s+{_DDMON})?\s+CNL\s+(?:RSN|CODE)\s?\d{{2}}\b"):
        for m in re.finditer(pat, text):
            span = m.group(0).strip(" .,")
            if len(CODE_RE.findall(span)) == 1 and not any(span in s or s in span for s in spans):
                spans.append(span)
    for s in spans:
        _add(out, "occ_group", s)
    return _common(text, out)


def spares(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    _add(out, "flight", _first(rf"^\s*{_FLT}(?=:)", text, 0))
    _add(out, "available_within_h", _first(r"STD\s?\+\s?\d{1,2}\s?h\s?\d{0,2}", text))
    return _common(text, out)


# ---------------------------------------------------------------- passengers / claims / CRM
def _flight_ref(text: str) -> str | None:
    return (_first(rf"\bNS\d{{1,4}}/{_DDMON}", text)                         # "NS31/24JAN"
            or _first(rf"\bNS\d{{1,4}}\b[^.;\n·]{{0,40}}?{_DATE}", text)        # "NS31 Dublin to Boston on 24 January 2025"
            or _first(r"\bNS\d{1,4}\b", text, 0))


def _passengers(text: str, out: list[Candidate]) -> None:
    seats = [m.group(0) for m in re.finditer(rf"(?:\bseat|\bSEAT|\bpassenger|\bpax)\s+{_SEAT}", text)]
    if not seats:
        seats = [m.group(0) for m in re.finditer(rf"NS\d{{1,4}}/{_DDMON}\s+{_SEAT}", text)]
    pnrs = [m.group(0) for m in re.finditer(r"\b(?:PNR|Booking ref(?:erence)?|BOOKING REF)\s?:?\s?[A-Z0-9]{6}\b", text)]
    coupons = [m.group(0) for m in re.finditer(rf"NS\d{{1,4}}@\d{{4}}-\d{{2}}-\d{{2}}:{_SEAT}", text)]
    for i, s in enumerate(seats):
        _add(out, "seat", s, group=i)
        if len(pnrs) == len(seats):
            _add(out, "pnr", pnrs[i], group=i)
    if seats and len(pnrs) == 1 and len(seats) > 1:
        for i in range(len(seats)):
            _add(out, "pnr", pnrs[0], group=i)
    for i, c in enumerate(coupons):
        _add(out, "coupon", c, group=len(seats) + i)


def _claim_fields(text: str, out: list[Candidate]) -> None:
    m = re.search(r"([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})\s+(?:on behalf of|acting for)\b", text)
    agency = m.group(1).strip(" .") if m else _first(r"[A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*\s+(?:Ltd|LLC|GmbH|BV|"
                                                      r"Inc|SAS|SRL)\b", text, 0)
    _add(out, "agency", agency)
    if re.search(AGENCY_RE, text.upper()):
        _add(out, "channel", _first(r"on behalf of|\bact(?:ing|s)? for\b|\bagency\b|claims? (?:company|agent|firm)",
                                    text))
    _add(out, "authority", _first(r"power of attorney|\bPOA\b|\bassign(?:ed|ment)\b|no (?:authority|mandate)", text))
    amount = _first(rf"\bclaim\w*\s+(?:the\s+|for\s+)?(?:{_MONEY})", text) \
        or _first(rf"compensation of\s+(?:{_MONEY})", text) \
        or _outside_instruction(_first(_MONEY, text, 0), text)
    _add(out, "amount", amount)
    _add(out, "currency", amount)
    _add(out, "regime", _first(r"\b(?:EU|UK)\s?261\b|Regulation \(EC\) (?:No\.? )?261/2004", text))
    if re.search(r"voucher|in lieu", text, re.IGNORECASE):
        _add(out, "voucher_disputed", _first(r"[^.\n]*\b(?:never (?:agreed|accepted)|did ?n[o']t (?:agree|"
                                             r"accept))\b[^.\n]*", text))
    _add(out, "voucher_signed", _first(r"\bUNSIGNED\b|NOT SIGNED|NO SIGNATURE[^.\n]*|DID ?N[O']T SIGN[^.\n]*|"
                                       r"SIGNATURE:\s?NOT CAPTURED|\bNO SIG\b[^.\n]*|SIGNED ACCEPTANCE[^.\n]*", text))


def claim(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    _add(out, "flight", _flight_ref(text))
    _passengers(text, out)
    _claim_fields(text, out)
    return _common(text, out)


def _rights_email(text: str) -> str | None:
    return _first(r"[^\n]*\b(?:weather|wx)\b[^\n]*?no compensation[^.\n]*\.?", text)


def email(text: str) -> list[Candidate]:
    out = claim(text)
    _aog(text, out)
    _mcc(text, out)
    for m in re.finditer(r"\bNS\d{1,4}\b[^.\n(]{0,30}?\b(?:batch|CNL)\b[^.\n(,]*", text, re.IGNORECASE):
        _add(out, "cancelled", m.group(0).strip(" ."))
    _add(out, "rights_email", _rights_email(text))
    m = re.search(r"\bRED\b[^,\n]*?(\d{2}:\d{2}\s?-\s?\d{2}:\d{2})", text)
    if m:
        _add(out, "red_warning", m.group(0), m.group(1))
    m = re.search(r"\bORANGE\b[^,.\n]*?((?:until|til)\s+\d{2}:\d{2})", text)
    if m:
        _add(out, "orange_warning", m.group(0), m.group(1))
    return out


def crm(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for pat in (r"charge ?back", r"\bBSP\b[^.\n]*\bR(?:E)?F(?:U)?ND\b", r"(?:voucher\s+)?in lieu(?: of compensation)?",
                r"refund voucher(?: issued)?|voucher issued", r"refund(?:\s+initiated)?|\bRFND\b", r"voucher",
                r"hotel|meal"):
        kind = _first(pat, text)            # priority order, not leftmost match
        if kind:
            _add(out, "event_kind", kind)
            break
    _add(out, "flight", _flight_ref(text))
    _passengers(text, out)
    in_lieu = re.search(r"in lieu", text, re.IGNORECASE)
    if in_lieu:
        _add(out, "voucher_in_lieu", _first(r"IN LIEU(?: OF COMPENSATION)?", text))
        _add(out, "voucher_amount", _first(rf"(?:{_MONEY})(?=\s+VOUCHER)", text))
    elif not re.search(r"\bwants\b", text, re.IGNORECASE):
        _add(out, "crm_amount", _first(_MONEY, text, 0))
    _add(out, "voucher_accepted", _first(r"[^.\n]*\bNEVER (?:AGREED|ACCEPTED)\b[^,.\n]*", text)
         or _first(r"\b(?:PAX\s+)?(?:ACCEPTED|DECLINED|REFUSED)\b", text))
    _add(out, "voucher_signed", _first(r"\bUNSIGNED\b|NOT SIGNED|SIGNATURE:\s?NOT CAPTURED|NO SIGNATURE[^.\n]*|"
                                       r"DID ?N[O']T SIGN|\bNO SIG\b[^.\n]*", text))
    if in_lieu:
        _add(out, "issued_by", _first(r"T\d SERVICE DESK \d+|\bT\d-\d{2}\b", text))
    _add(out, "rights_email", _rights_email(text))
    return _common(text, out)


def manufacturer(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    _add(out, "hidden_defect", _first(r"(?:hidden|latent|manufacturing)\b[^.]{0,30}\bdefect", text))
    _add(out, "part_number", _first(r"\bP/?N\s?:?\s?[A-Z0-9][A-Z0-9-]*[A-Z0-9]", text))
    tails = re.findall(_TAIL, text)
    if tails:
        start = text.find(tails[0])
        end = text.find(tails[-1]) + len(tails[-1])
        _add(out, "mfr_aircraft", text[start:end])
    return _common(text, out)


EXTRACTORS: dict[SourceKind, Callable[[str], list[Candidate]]] = {
    SourceKind.TECH_LOG: tech_log,
    SourceKind.MCC_LOG: mcc_log,
    SourceKind.OCC_LOG: occ_log,
    SourceKind.SPARES: spares,
    SourceKind.CLAIM: claim,
    SourceKind.EMAIL: email,
    SourceKind.CRM: crm,
    SourceKind.BSP: crm,
    SourceKind.MANUFACTURER: manufacturer,
}


def extract(kind: SourceKind, text: str) -> list[Candidate]:
    """Regex candidates (keys of llm/fields.py). The value is the re-parse of the span (regex only picks spans)."""
    fn = EXTRACTORS.get(kind)
    return fn(text) if fn else []          # raw text: line breaks bound spans; verify() normalises whitespace
