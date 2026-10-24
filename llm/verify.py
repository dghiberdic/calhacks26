"""Span verification: a key survives only if its span is a verbatim substring of the source text (after whitespace
normalisation) AND its typed value re-parses from that span with ``contracts/parse.py`` (plus a local semantic check
where the contracts parser is generic or absent; see ``llm/fields.py``). Used by the Reader and challenge
classification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from contracts import parse as cparse
from llm import parse_local
from llm.fields import KEYS
from llm.parse_local import ParseError, norm_ws


@dataclass
class Candidate:
    """What an extractor (LLM or regex) claims: key, typed value, verbatim span."""
    field: str            # a key in llm.fields.KEYS
    value: Any
    span: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verified:
    field: str
    value: Any            # canonical value re-parsed from the span
    span: str             # whitespace-normalised span, a substring of the normalised source text
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dropped:
    field: str
    span: str
    reason: str           # unknown_key | empty_span | span_not_in_source | unparseable_span | value_mismatch |
                          # unregistered_field


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return parse_local.iso_z(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _contracts(field_name: str, value: Any, span: str, text: str, ref: datetime) -> str | None:
    """None if contracts accepts (value, span); else the reason."""
    ok, reason = cparse.verify(field_name, value, span, text, ref)
    return None if ok else reason


def _check(c: Candidate, span: str, text: str, ref: datetime) -> tuple[Any, str | None]:
    """(canonical value, None) or (None, drop reason)."""
    key = KEYS[c.field]
    regex = bool(c.meta.get("regex"))          # a regex candidate only picks the span; its value IS the re-parse

    # 1. local semantic parse (and the canonical value for keys with no contracts parser)
    local_val = None
    if key.local:
        try:
            local_val = parse_local.reparse(key.local, span, ref)
        except ParseError:
            return None, "unparseable_span"
        if not regex and not key.text and not parse_local.matches(key.local, c.value, local_val):
            return None, "value_mismatch"        # (for text keys the local parser only validates the span)
    claimed = local_val if (regex and not key.text) else c.value

    # 2. the binding contracts re-parse
    name = c.field
    if name == "occ_group":
        try:
            code = cparse.parse_delay_code(span)
        except cparse.ParseError:
            return None, "unparseable_span"
        return (local_val, None) if code == local_val["code"] else (None, "value_mismatch")
    if name == "flight":
        number = local_val.split("@")[0]
        if (r := _contracts("claim.flight_number", number, span, text, ref)) is not None:
            return None, r
        if "@" in local_val and (r := _contracts("claim.flight_date", local_val.split("@")[1], span, text, ref)):
            return None, r
        return local_val, None
    if name in ("amount", "currency"):
        try:
            cents, cur = cparse.parse_money(span)
        except cparse.ParseError:
            return None, "unparseable_span"
        want = cents if name == "amount" else cur
        return (want, None) if want == local_val else (None, "value_mismatch")
    if name == "cancelled":
        if (r := _contracts("flight.cancelled_by_occ", True, span, text, ref)) is not None:
            return None, r
        return local_val, None
    if name == "instruction":
        if (r := _contracts("email.asserts_approval", True, span, text, ref)) is not None:
            return None, r
        return True, None
    if key.field is None:                       # local-only keys (event_kind, mfr_aircraft)
        return local_val, None
    if key.text:
        val = norm_ws(str(c.value if c.value is not None else span))   # a regex candidate may carry a sub-match
        if not val or val.casefold() not in span.casefold():
            return None, "value_mismatch"
        if (r := _contracts(key.field, val, span, text, ref)) is not None:
            return None, r
        return val, None
    if regex and local_val is None:
        try:
            claimed = cparse.reparse(key.field, span, ref)
        except (cparse.ParseError, KeyError):
            return None, "unparseable_span"
    if (r := _contracts(key.field, _jsonable(claimed), span, text, ref)) is not None:
        return None, r
    try:
        parsed = cparse.reparse(key.field, span, ref)
    except (cparse.ParseError, KeyError):
        parsed = claimed                        # structured field (no contracts parser): the local value stands
    return _jsonable(parsed if local_val is None else local_val), None


def verify(c: Candidate, text: str, ref: datetime) -> Verified | Dropped:
    if c.field not in KEYS:
        return Dropped(c.field, c.span or "", "unknown_key")
    span = norm_ws(c.span or "")
    if not span:
        return Dropped(c.field, "", "empty_span")
    ntext = norm_ws(text)
    if span not in ntext:
        return Dropped(c.field, span, "span_not_in_source")
    value, reason = _check(c, span, ntext, ref)
    if reason is not None:
        return Dropped(c.field, span, reason)
    return Verified(c.field, value, span, dict(c.meta))


def verify_all(cands: list[Candidate], text: str, ref: datetime) -> tuple[list[Verified], list[Dropped]]:
    ok: list[Verified] = []
    bad: list[Dropped] = []
    seen: set[tuple[str, str, str, Any]] = set()
    for c in cands:
        r = verify(c, text, ref)
        if isinstance(r, Dropped):
            bad.append(r)
            continue
        k = (r.field, repr(r.value), r.span, r.meta.get("group"))
        if k not in seen:          # the same fact quoted twice counts once
            seen.add(k)
            ok.append(r)
    return ok, bad
