"""Helpers shared by the LLM roles (Reader, Drafter, personas). Owner: Filip lane B.

- ``SpanStr`` / ``SpanBool`` / ``SpanInt`` / ``SpanFloat``: the ``{value, span}`` pair every structured output uses
  when it quotes a document.
- ``verify_span(field, value, span, text, ref)``: the binding acceptance test (``contracts.parse.verify``) after
  whitespace normalisation of both span and text, as the F5 brief specifies. Use it for any LLM-quoted fact
  (e.g. tier-4 challenge facts) so every role holds quotes to the same standard as the Reader.
- ``norm_ws``: the normalisation itself.

Calls to Claude go through ``llm.client`` (``LlmClient.call``), never the SDK directly.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from contracts import parse as _cparse
from llm.parse_local import norm_ws

SPAN_DESCRIPTION = "Verbatim quote copied character for character from the document that states this value on its own."


class SpanStr(BaseModel):
    value: str
    span: str = Field(description=SPAN_DESCRIPTION)


class SpanBool(BaseModel):
    value: bool
    span: str = Field(description=SPAN_DESCRIPTION)


class SpanInt(BaseModel):
    value: int = Field(description="Integer minor units (cents/pence), e.g. €300 → 30000.")
    span: str = Field(description=SPAN_DESCRIPTION)


class SpanFloat(BaseModel):
    value: float
    span: str = Field(description=SPAN_DESCRIPTION)


def span_in(span: str | None, text: str | None) -> bool:
    """Is ``span`` a verbatim substring of ``text`` after whitespace normalisation?"""
    return bool(span) and bool(text) and norm_ws(span) in norm_ws(text)


def verify_span(field: str, value: Any, span: str | None, text: str | None,
                ref: datetime | date | None = None) -> tuple[bool, str]:
    """``contracts.parse.verify`` on whitespace-normalised span and text: ``(ok, reason)``."""
    if not span or not text:
        return False, "span_not_in_source"
    return _cparse.verify(field, value, norm_ws(span), norm_ws(text), ref)


__all__ = ["SPAN_DESCRIPTION", "SpanBool", "SpanFloat", "SpanInt", "SpanStr", "norm_ws", "span_in", "verify_span"]
