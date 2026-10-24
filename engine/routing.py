"""D6 · Routing: who decides, and whether the engine may act alone.

Thresholds: score >= 0.90 is automatic **subject to the materiality gate** (per-flight drafted liability < €50k);
0.60-0.90 goes to batch review (``outcome="human"``); below 0.60 a person is asked (``outcome="escalated"``). A
cause the engine cannot settle in law (``needs_legal``) is always escalated, whatever the score.

| Case | Goes to |
|---|---|
| Cause/legal patterns, concurrent causes | Legal |
| Voucher and claim disputes | Claims Lead |
| Releases and changes in estimate | Controller |
| Data gaps / ``unknown`` | Ops |
"""
from __future__ import annotations

import math

from dataclasses import dataclass

from contracts.models import Confidence, Extraordinary, Role

AUTO_THRESHOLD = 0.90
BATCH_THRESHOLD = 0.60
MATERIALITY_CENTS = 5_000_000           # €50k per flight (hard control)

PATTERN_ROLE = {
    "knock_on_return": Role.LEGAL, "concurrent_causes": Role.LEGAL, "external_event": Role.LEGAL,
    "new_legal_pattern": Role.LEGAL, "rule_conflict": Role.LEGAL,
    "voucher_in_lieu_unsigned": Role.CLAIMS_LEAD, "claim_dispute": Role.CLAIMS_LEAD,
    "cohort_release": Role.CONTROLLER, "change_in_estimate": Role.CONTROLLER, "materiality": Role.CONTROLLER,
    "window_unknown": Role.OPS, "weather_code_contradicted": Role.OPS, "cause_unknown": Role.OPS,
    "technical_unverified": Role.OPS, "crew": Role.OPS, "atc": Role.OPS, "unresolved_subject": Role.OPS,
}


@dataclass(frozen=True)
class Route:
    outcome: str                 # "auto" | "human" | "escalated"
    routed_to: Role | None
    gate: str | None = None      # why it is not automatic: "needs_legal" | "low_confidence" | "batch_review" | ...


def role_for(pattern: str, default: Role = Role.OPS) -> Role:
    return PATTERN_ROLE.get(pattern, default)


def route(*, extraordinary: Extraordinary, confidence: Confidence, pattern: str, liability_cents: int = 0,
          role: Role | None = None, settled_by_rule: bool = False) -> Route:
    who = role or role_for(pattern)
    if extraordinary == Extraordinary.NEEDS_LEGAL:
        return Route("escalated", who, "needs_legal")
    s = confidence.score
    if s is None or not math.isfinite(s):          # NaN compares False to every threshold: fail closed
        return Route("human", who, "uncalibrated")
    if s < BATCH_THRESHOLD and not settled_by_rule:
        return Route("escalated", who, "low_confidence")
    if s < AUTO_THRESHOLD and not settled_by_rule:
        return Route("human", who, "batch_review")
    if liability_cents >= MATERIALITY_CENTS:
        return Route("human", Role.CONTROLLER, "materiality")
    return Route("auto", None, None)
