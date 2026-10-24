"""Span verification: a fact survives only if its span is a verbatim substring of the source text (after whitespace
normalisation) AND its typed value re-parses from that span. Used by the Reader and by challenge classification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from llm import parse_local
from llm.fields import FIELDS, FORBIDDEN_FIELDS
from llm.parse_local import ParseError, norm_ws


@dataclass
class Candidate:
    """What an extractor (LLM or regex) claims: field, typed value, verbatim span."""
    field: str
    value: Any
    span: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verified:
    field: str
    value: Any            # re-parsed from the span (canonical form)
    span: str             # whitespace-normalised span, a substring of the normalised source text
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dropped:
    field: str
    span: str
    reason: str           # unknown_field | forbidden_field | empty_span | span_not_in_source | unparseable_span |
                          # value_mismatch


def verify(c: Candidate, text: str, ref: datetime) -> Verified | Dropped:
    if c.field in FORBIDDEN_FIELDS:
        return Dropped(c.field, c.span or "", "forbidden_field")
    spec = FIELDS.get(c.field)
    if spec is None:
        return Dropped(c.field, c.span or "", "unknown_field")
    span = norm_ws(c.span or "")
    if not span:
        return Dropped(c.field, "", "empty_span")
    if span not in norm_ws(text):
        return Dropped(c.field, span, "span_not_in_source")
    try:
        parsed = parse_local.reparse(spec.parser, span, ref)
    except ParseError:
        return Dropped(c.field, span, "unparseable_span")
    # A regex candidate only picks the span; its value IS the re-parse. An LLM candidate's value must match it.
    if not c.meta.get("regex") and not parse_local.matches(spec.parser, c.value, parsed):
        return Dropped(c.field, span, "value_mismatch")
    return Verified(c.field, parsed, span, dict(c.meta))


def verify_all(cands: list[Candidate], text: str, ref: datetime) -> tuple[list[Verified], list[Dropped]]:
    ok: list[Verified] = []
    bad: list[Dropped] = []
    seen: set[tuple[str, str, str]] = set()
    for c in cands:
        r = verify(c, text, ref)
        if isinstance(r, Dropped):
            bad.append(r)
            continue
        key = (r.field, repr(r.value), r.span)
        if key not in seen:          # the same fact quoted twice counts once
            seen.add(key)
            ok.append(r)
    return ok, bad
