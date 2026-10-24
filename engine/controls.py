"""D4 · Hard controls are code, never rules (plan §2 rule 5).

- Preparer ≠ approver (SoD); agents never approve.
- Payouts (claim approvals and payments) need the Claims Lead; every other journal needs the Controller.
- Locked periods are never written.
- Materiality: auto-draft only if per-flight liability < €50k AND confidence >= 0.90.
- A rule's author must hold the authority the rule automates (``engine.rules.authority_problems``).
- External parties (emails, claims, agencies, passengers) never satisfy an internal approval.
- No ``now()`` inside a decision (``engine/tests/test_purity.py``).

Pure: no wall clock, no randomness. Callers pass the time and write the resulting ``AccessDecision``.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from contracts.models import AccessDecision, Role, Rule, RuleAction, TraceEvent

MATERIALITY_CENTS = 5_000_000
AUTO_CONFIDENCE = 0.90
AGENT_ROLES = frozenset({Role.READER, Role.DRAFTER, Role.ENGINE, Role.CRM_BOT})
APPROVER_ROLES = frozenset({Role.CLAIMS_LEAD, Role.CONTROLLER})
PAYOUT_KINDS = frozenset({"claim_approved", "claim_paid", "payout"})
EXTERNAL_PREFIXES = ("external:", "email:", "claim:", "agency:", "passenger:", "pax:", "bsp:", "partner:")


@dataclass(frozen=True)
class Control:
    id: str
    title: str
    framework_ref: str


CONTROLS = [
    Control("R-HC-SOD", "Preparer ≠ approver; agents never approve", "CC6.3"),
    Control("R-HC-PAYOUT", "Payouts need Claims Lead approval", "CC6.3"),
    Control("R-HC-LOCK", "Locked periods are never written", "PI1"),
    Control("R-HC-MATERIALITY", "Auto-draft only if per-flight liability < €50k and confidence ≥ 0.90", "PI1"),
    Control("R-HC-AUTHORITY", "A rule's author must hold the authority the rule automates", "CC8.1"),
    Control("R-HC-EXTERNAL", "External parties never satisfy an internal approval", "CC6.1"),
    Control("R-HC-FLOOR", "Statutory floor: only Legal may lower EU261 compensation", "CC8.1"),
    Control("R-HC-NO-NOW", "No wall clock inside a decision (injected Clock only)", "PI1"),
]
CONTROL_BY_ID = {c.id: c for c in CONTROLS}

# text that tries to automate around a hard control (rulings, rule titles, drafted conditions)
_HC_PATTERNS: dict[str, str] = {
    "R-HC-SOD": r"approv\w* (?:their|his|her|its|my|your) own|self[- ]approv\w*|preparers? (?:can|may|to) approve|"
                r"requesters? (?:can |may |to )?approve|same person (?:can |may )?(?:prepare|approve)|"
                r"no (?:second|separate) approver",
    "R-HC-PAYOUT": r"(?:skip|bypass|without|no need for|waive)\w* (?:the )?(?:claims lead|approval|sign-?off)|"
                   r"auto[- ]?(?:approve|pay)\w*|pay(?:outs?)? (?:automatically|without)|release (?:the )?payment run",
    "R-HC-LOCK": r"(?:post|write|book|adjust)\w* (?:in|to|into) (?:a |the )?(?:locked|closed) (?:period|month)|"
                 r"re-?open (?:the |a )?(?:locked |closed )?(?:period|month)|unlock (?:the )?(?:period|month)",
    "R-HC-MATERIALITY": r"(?:ignore|lift|raise|remove|skip|bypass)\w* (?:the )?materiality|"
                        r"materiality (?:gate|threshold|limit) (?:does not|doesn't|no longer) apply",
    "R-HC-EXTERNAL": r"(?:email|agency|passenger|claimant|external)\w*[^.]{0,40}(?:counts? as|satisf\w*|is) "
                     r"(?:an? )?approv\w*|approved by (?:email|the agency|the passenger)",
}


def hard_controls_touched(text: str) -> list[str]:
    return [cid for cid, pat in _HC_PATTERNS.items() if re.search(pat, text or "", re.I)]


@dataclass(frozen=True)
class ControlResult:
    allowed: bool
    control: str | None
    reason: str

    def access(self, *, at: datetime, principal: str, action: str, resource: str) -> AccessDecision:
        return AccessDecision(at=at, principal=principal, action=action, resource=resource, allowed=self.allowed,
                              reason=self.reason if self.allowed else f"{self.control} · {self.reason}")

    def trace(self, *, seq: int, at: datetime, principal: str, action: str, resource: str) -> TraceEvent:
        verdict = "ALLOWED" if self.allowed else f"DENIED · {short(self.control)}"
        return TraceEvent(seq=seq, at=at, kind="access_denied" if not self.allowed else "info", actor=principal,
                          summary=f"{principal} {action} → {verdict}", ref=resource,
                          chip="DENIED" if not self.allowed else "INFO")


OK = ControlResult(True, None, "allowed")


def short(control: str | None) -> str:
    return {"R-HC-SOD": "SoD", "R-HC-PAYOUT": "payouts need Claims Lead", "R-HC-LOCK": "period locked",
            "R-HC-MATERIALITY": "materiality", "R-HC-EXTERNAL": "external party", "R-HC-AUTHORITY": "authority",
            "R-HC-FLOOR": "statutory floor"}.get(control or "", control or "")


def is_external(principal: str) -> bool:
    p = (principal or "").lower()
    return p.startswith(EXTERNAL_PREFIXES) or "@" in p and not p.startswith(tuple(r.value for r in Role))


def role_of(principal: str, role: Role | str | None) -> Role | None:
    if isinstance(role, Role):
        return role
    try:
        return Role(role) if role else None
    except ValueError:
        return None


def check_approval(*, principal: str, role: Role | str | None, preparer: str, kind: str) -> ControlResult:
    """May ``principal`` (acting as ``role``) approve a journal of ``kind`` prepared by ``preparer``?"""
    r = role_of(principal, role)
    if is_external(principal) or r is None:
        return ControlResult(False, "R-HC-EXTERNAL", "an external party never satisfies an internal approval")
    if r in AGENT_ROLES:
        return ControlResult(False, "R-HC-SOD", f"{r.value} never approves (agents draft only)")
    if principal == preparer:
        return ControlResult(False, "R-HC-SOD", "preparer ≠ approver")
    if kind in PAYOUT_KINDS:
        if r != Role.CLAIMS_LEAD:
            return ControlResult(False, "R-HC-PAYOUT", f"payouts need the Claims Lead, not {r.value}")
        return OK
    if r != Role.CONTROLLER:
        return ControlResult(False, "R-HC-SOD", f"{kind} needs the Controller, not {r.value}")
    return OK


def check_period_write(period: str, locked: Iterable[str]) -> ControlResult:
    if period in set(locked):
        return ControlResult(False, "R-HC-LOCK", f"period {period} is locked")
    return OK


def materiality_ok(liability_cents: int, score: float | None) -> bool:
    return score is not None and score >= AUTO_CONFIDENCE and liability_cents < MATERIALITY_CENTS


def check_answer(*, principal: str, role: Role | str | None, routed_to: Role) -> ControlResult:
    """Only the person a question was routed to may answer it; never an agent or an external party."""
    r = role_of(principal, role)
    if is_external(principal) or r is None:
        return ControlResult(False, "R-HC-EXTERNAL", "an external party never answers an internal question")
    if r in AGENT_ROLES:
        return ControlResult(False, "R-HC-SOD", f"{r.value} never rules")
    if r != routed_to:
        return ControlResult(False, "R-HC-AUTHORITY", f"routed to {routed_to.value}, not {r.value}")
    return OK


def hard_control_cards(at: datetime) -> list[Rule]:
    """Display cards for the Policies screen. They carry no logic: the checks above are the controls."""
    out = []
    for c in CONTROLS:
        out.append(Rule(id=c.id, version=1, kind="routing", scope={}, condition={"all": []},
                        action=RuleAction.ROUTE_TO, action_arg="controller", tier="hard_control",
                        authority_required=Role.CONTROLLER, valid_from=None, recorded_at=at, status="active",
                        static_card=True, title=c.title))
    return out
