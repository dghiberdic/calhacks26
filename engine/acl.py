"""D9 · ACL broker for people AND agents: who may read, write and approve what, and what each one sees of PII.

The matrix (THREAD_DAVID D9):

    Ops          flights and logs, no PII            Reader      sources incl. PII; emits pseudonymous facts
    Drafter      no PII (names merged after drafting) Claims Lead PII for claims; approves payouts
    Legal        case facts without PII              Controller  aggregates + journal entries; approves JEs, locks
    Judge        demo read + desk / inject           (CFO, Engine, CRM bot: see MATRIX)

Hard controls are code here, not configuration:
- agents never approve anything;
- preparer ≠ approver;
- payouts need the Claims Lead;
- journal entries and period locks need the Controller;
- an external party never satisfies an internal approval (an email or claim text saying "approved" is just text;
  only a signed internal ``Session`` approves);
- a simulated persona (``persona:<role>``, llm/personas.py) is an external party, even holding a (forged) internal
  session: it never approves, pays or locks a period; it may only read case facts redacted and answer questions
  (its answers are recorded as simulated), and as an LLM it sees no PII.

Every check becomes an ``AccessDecision`` in ``Broker.log``; every denial is also an ``access_denied`` commit
(``agent.drafter approve_payout → DENIED · SoD``) when the broker has a trace store.

Session tokens are ``<base64url(canonical Session JSON)>.<hex HMAC-SHA256>``. The secret is passed in; any problem
fails closed (``InvalidToken``, or the read-only judge via ``session_or_judge``).

Pure: no wall clock (the injected clock or an explicit ``at``), no randomness, no LLM.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import orjson
from pydantic import BaseModel

from contracts.models import (
    AccessDecision,
    AccessMatrix,
    Claim,
    Coupon,
    CrmEvent,
    Evidence,
    Fact,
    Role,
    Session,
    Source,
    SourceKind,
)
from engine.controls import PERSONA_DENIAL, is_persona, persona_role
from engine.trace import canonical, utc

MASK = "[redacted:pii]"

AGENT_ROLES = frozenset({Role.READER, Role.DRAFTER, Role.ENGINE, Role.CRM_BOT})
ROLE_VALUES = frozenset(r.value for r in Role)

PRINCIPALS = ("ops", "agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot", "claims_lead", "legal",
              "controller", "cfo", "judge")
RESOURCES = ("flights", "ops_logs", "tech_log", "sources", "pii", "claims", "case_facts", "questions", "journal",
             "aggregates", "rules", "approve_payout", "approve_je", "lock_period", "desk", "inject")
PII_RESOURCES = frozenset({"pii", "claims", "sources"})
APPROVALS = {"approve_payout": "approve payouts", "approve_je": "approve journal entries",
             "lock_period": "lock periods"}
APPROVAL_NEEDS = {"approve_payout": "payouts need the Claims Lead",
                  "approve_je": "journal entries need the Controller",
                  "lock_period": "only the Controller locks a period"}
READ_LEVELS = frozenset({"read", "write", "approve", "redacted"})


def _row(**cells: str) -> dict[str, str]:
    row = {r: "none" for r in RESOURCES}
    unknown = set(cells) - set(RESOURCES)
    if unknown:
        raise ValueError(f"unknown resources {sorted(unknown)}")
    row.update(cells)
    return row


_LOGS = {"flights": "read", "ops_logs": "read", "tech_log": "read"}
MATRIX: dict[str, dict[str, str]] = {
    "ops": _row(**_LOGS, sources="redacted", case_facts="read", questions="write", rules="read"),
    "agent.reader": _row(**_LOGS, sources="read", pii="read", claims="read", case_facts="write"),
    "agent.drafter": _row(**_LOGS, sources="redacted", claims="redacted", case_facts="read", questions="read",
                          journal="read", aggregates="read", rules="read"),
    "agent.engine": _row(**_LOGS, sources="redacted", claims="redacted", case_facts="write", questions="write",
                         journal="write", aggregates="write", rules="read"),
    "agent.crm_bot": _row(flights="read", pii="read", claims="read"),
    "claims_lead": _row(**_LOGS, sources="read", pii="read", claims="write", case_facts="read", questions="write",
                        journal="read", aggregates="read", rules="write", approve_payout="approve"),
    "legal": _row(**_LOGS, sources="redacted", claims="redacted", case_facts="read", questions="write",
                  aggregates="read", rules="write"),
    "controller": _row(flights="read", questions="write", journal="write", aggregates="read", rules="write",
                       approve_je="approve", lock_period="approve"),
    "cfo": _row(flights="read", questions="read", journal="read", aggregates="read", rules="read"),
    "judge": _row(**_LOGS, sources="redacted", pii="redacted", claims="redacted", case_facts="read", questions="read",
                  journal="read", aggregates="read", rules="read", desk="write", inject="write"),
}
# a simulated persona, whatever role it simulates: reads redacted, answers questions, nothing else (not in the
# displayed matrix: it is not a principal of the business, only of an unattended run)
PERSONA_ROW = _row(**_LOGS, sources="redacted", claims="redacted", case_facts="read", questions="write",
                   rules="read")
PERSONA_NOTE = "{p} is a simulated persona: it answers as simulated, sees no PII and never approves"

ROLE_NOTES = {
    "ops": "Ops sees flights and logs, no PII",
    "agent.reader": "Reader reads sources incl. PII and emits pseudonymous facts",
    "agent.drafter": "Drafter sees no PII; names are merged in code after drafting",
    "agent.engine": "the engine decides on pseudonymous facts, no PII",
    "agent.crm_bot": "CRM bot handles passenger contact only",
    "claims_lead": "Claims Lead sees PII for claims",
    "legal": "Legal sees case facts without PII",
    "controller": "Controller sees aggregates and journal entries",
    "cfo": "CFO sees aggregates and journal entries",
    "judge": "Judge has demo read access plus desk and inject; PII masked",
}

# free-form keys that hold personal data in dicts (models are handled field by field)
PII_KEYS = frozenset({
    "name", "full_name", "first_name", "last_name", "surname", "given_name", "pax_name", "passenger_name",
    "email", "email_address", "phone", "phone_number", "mobile", "address", "street", "postcode", "iban", "bic",
    "card", "card_number", "pan", "passport", "passport_number", "dob", "date_of_birth", "pnr", "ffn",
    "frequent_flyer",
})
PII_SOURCE_KINDS = frozenset({SourceKind.CLAIM, SourceKind.EMAIL, SourceKind.MANIFEST, SourceKind.PSS,
                              SourceKind.CRM, SourceKind.BSP, SourceKind.CHALLENGE})

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+\d[\d\s().-]{6,}\d")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}|(?: [A-Z0-9]{4}){3,7}(?: [A-Z0-9]{1,3})?)\b")
_APPROVED = re.compile(r"\bapprov(?:e|ed|al|es|ing)\b", re.IGNORECASE)
_ID = re.compile(r"[A-Za-z0-9@.:_-]+")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FLIGHT_ID = re.compile(r"[A-Z0-9]{2,8}@\d{4}-\d{2}-\d{2}")
_COUPON_ID = re.compile(r"[A-Z0-9]{2,8}@\d{4}-\d{2}-\d{2}:[A-Za-z0-9]+")


# ---------- errors ----------

class AccessDenied(PermissionError):
    """``code`` matches the CONTRACTS §3 error envelope: ``sod_violation`` for approvals, else ``forbidden``."""

    def __init__(self, decision: AccessDecision, code: str = "forbidden"):
        super().__init__(decision.reason)
        self.decision = decision
        self.code = code
        self.message = decision.reason


class InvalidToken(Exception):
    code = "forbidden"


# ---------- text scrubbing ----------

def iban_ok(candidate: str) -> bool:
    """ISO 13616 check: 15-34 characters and mod-97 of the rearranged number is 1 (flight lists like
    ``NS21 NS41 NS51`` look like spaced IBANs but fail the checksum)."""
    c = candidate.replace(" ", "").upper()
    if not 15 <= len(c) <= 34 or not c.isalnum():
        return False
    return int("".join(str(int(ch, 36)) for ch in c[4:] + c[:4])) % 97 == 1


def _iban_sub(m: re.Match[str]) -> str:
    return MASK if iban_ok(m.group(0)) else m.group(0)


def scrub_text(s: str) -> str:
    """Mask e-mail addresses, international phone numbers and (checksum-valid) IBANs inside free text."""
    s = _EMAIL.sub(MASK, s)
    s = _IBAN.sub(_iban_sub, s)
    return _PHONE.sub(MASK, s)


def _has_pattern(s: str) -> bool:
    return bool(_EMAIL.search(s) or _PHONE.search(s) or any(iban_ok(m.group(0)) for m in _IBAN.finditer(s)))


def _pii_source(src: Source) -> bool:
    return "pii" in src.acl_tags or src.kind in PII_SOURCE_KINDS


def _is_pii_fact(f: Fact) -> bool:
    """A fact is personal if tagged ``pii`` or if its value or span contains an e-mail, phone number or IBAN."""
    return "pii" in f.acl_tags or bool(pii_fields(f.value)) or bool(f.span and _has_pattern(f.span))


def _masked(v: Any) -> bool:
    return v is None or v == MASK


def pii_fields(obj: Any, path: str = "$", pii_sources: Iterable[str] = ()) -> list[str]:
    """Paths of every field in ``obj`` that still holds personal data (empty list = no PII).

    Mirrors ``Broker.redact``: PII-tagged sources' text and facts' value/span, claim and CRM free text, PNRs,
    personal dict keys, and e-mail / phone / IBAN patterns in any string. ``pii_sources`` adds source ids whose
    verbatim quotes count as personal.
    """
    srcs = frozenset(pii_sources)
    out: list[str] = []
    if isinstance(obj, BaseModel):
        tagged = "pii" in (getattr(obj, "acl_tags", None) or [])
        from_pii = getattr(obj, "source_id", None) in srcs
        for name in type(obj).model_fields:
            v = getattr(obj, name)
            p = f"{path}.{name}"
            if _masked(v):
                continue
            if ((isinstance(obj, Source) and name == "text" and _pii_source(obj))
                    or (isinstance(obj, Fact) and name in ("value", "span") and tagged)
                    or (isinstance(obj, Fact) and name == "span" and from_pii)
                    or (isinstance(obj, Evidence) and name in ("value", "quote") and from_pii)
                    or (isinstance(obj, (Claim, CrmEvent)) and name == "text")
                    or (isinstance(obj, Coupon) and name == "pnr")):
                out.append(p)
                continue
            out += pii_fields(v, p, srcs)
    elif isinstance(obj, Mapping):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if isinstance(k, str) and k.lower() in PII_KEYS and not _masked(v):
                out.append(p)
            else:
                out += pii_fields(v, p, srcs)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += pii_fields(v, f"{path}[{i}]", srcs)
    elif isinstance(obj, str):
        if obj != MASK and _has_pattern(obj):
            out.append(path)
    return out


# ---------- principals ----------

@dataclass(frozen=True)
class Principal:
    id: str                     # what AccessDecision.principal records
    role: Role | None           # None = unknown or external
    authenticated: bool         # a signed internal Session
    external: str | None        # "email", "claim", "fact", "text", "persona", ... for an external party
    text: str = ""              # what an external party says (checked for "approved" wording)
    persona: bool = False       # a simulated person (persona:<role>); role = the role it simulates


def principal_for(role: Role | str, name: str) -> str:
    """Agents and the judge are the bare role; people are ``<role>:<name-slug>`` (IDs use ``[A-Za-z0-9@.:_-]``)."""
    role = Role(role)
    if role in AGENT_ROLES or role == Role.JUDGE:
        return role.value
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "anon"
    return f"{role.value}:{slug}"


def _persona(pid: str) -> Principal:
    """Never authenticated, whatever session it came in: its role comes from its id, not from the session."""
    return Principal(pid, persona_role(pid), False, "persona", persona=True)


def principal_of(p: Any) -> Principal:
    if isinstance(p, Session):
        if is_persona(p.principal):
            return _persona(p.principal.strip())
        return Principal(p.principal, Role(p.role), True, None)
    if isinstance(p, Role):
        return Principal(p.value, p, False, None)
    if isinstance(p, str):
        s = p.strip()
        if is_persona(s) and _ID.fullmatch(s):
            return _persona(s)
        if s in ROLE_VALUES:
            return Principal(s, Role(s), False, None)
        head, sep, tail = s.partition(":")
        if sep and tail and head in ROLE_VALUES and _ID.fullmatch(s):
            return Principal(s, Role(head), False, None)
        if s.startswith("external:") and _ID.fullmatch(s):
            return Principal(s, None, False, s.split(":", 2)[1] or "party")
        if s and _ID.fullmatch(s):
            return Principal(s, None, False, None)                 # an unknown id: fails closed
        if not s:
            return Principal("unknown", None, False, None)
        return Principal("external:text", None, False, "text", s)
    if isinstance(p, Source):
        return Principal(f"external:{p.kind.value}", None, False, p.kind.value, p.text or "")
    if isinstance(p, Claim):
        return Principal("external:claim", None, False, "claim", p.text)
    if isinstance(p, CrmEvent):
        return Principal("external:crm", None, False, "crm", p.text)
    if isinstance(p, Fact):
        return Principal("external:fact", None, False, "fact", f"{p.field} {p.value} {p.span or ''}")
    if p is None:
        return Principal("unknown", None, False, None)
    try:
        text = orjson.dumps(p, default=str).decode()
    except TypeError:
        text = str(p)
    return Principal("external:object", None, False, "object", text)


def resource_class(resource: str | None) -> str | None:
    """``claims:NS31@…:14C`` → ``claims``; bare ids map by shape (``SRC-…`` sources, ``JE-…`` journal, ``R-…``
    rules, ``Q-…`` questions, flight ids flights, coupon ids case facts). Unknown → None (fails closed)."""
    r = (resource or "").strip()
    if not r:
        return None
    head = r.split(":", 1)[0]
    if head in RESOURCES:
        return head
    for prefix, cls in (("SRC-", "sources"), ("JE-", "journal"), ("R-", "rules"), ("Q-", "questions")):
        if r.startswith(prefix):
            return cls
    if _COUPON_ID.fullmatch(r):
        return "case_facts"
    if _FLIGHT_ID.fullmatch(r):
        return "flights"
    return None


def access_matrix() -> AccessMatrix:
    return AccessMatrix(principals=list(PRINCIPALS), resources=list(RESOURCES),
                        cells={p: dict(MATRIX[p]) for p in PRINCIPALS})


# ---------- the broker ----------

class LlmContext(BaseModel):
    """What an agent's prompt may be built from: allowed facts (PII facts withheld) and redacted items."""
    principal: str
    purpose: str | None = None
    facts: list[Fact] = []
    items: list[Any] = []
    withheld_facts: int = 0


class Broker:
    """``Broker(clock=..., trace=...)``: ``read``, ``can``/``check``/``require``, ``redact``, ``context``.

    ``trace`` (a ``engine.trace.TraceStore``) receives an ``access_denied`` commit for every denial.
    ``register_sources`` teaches the broker which source ids are personal documents, so verbatim quotes from them
    (``Evidence.quote``, ``Fact.span``) are masked for principals without PII access.
    """

    def __init__(self, clock: Any = None, trace: Any = None, pii_sources: Iterable[str] = ()):
        self.clock = clock
        self.trace = trace
        self.log: list[AccessDecision] = []
        self._pii_sources: set[str] = set(pii_sources)

    def register_sources(self, sources: Iterable[Source]) -> None:
        self._pii_sources |= {s.id for s in sources if _pii_source(s)}

    @property
    def pii_source_ids(self) -> frozenset[str]:
        return frozenset(self._pii_sources)

    def _at(self, at: datetime | None) -> datetime:
        if at is not None:
            return utc(at)
        if self.clock is None or not callable(getattr(self.clock, "now", None)):
            raise ValueError("Broker needs an injected clock (or an explicit at=); it never reads the wall clock")
        return utc(self.clock.now())

    # ------------------------------------------------------------------ decisions

    @staticmethod
    def _level(role: Role | None, column: str) -> str:
        if role is None:
            return "none"
        return MATRIX.get(role.value, {}).get(column, "none")

    @classmethod
    def _level_of(cls, pr: Principal, column: str) -> str:
        if pr.persona:
            return PERSONA_ROW.get(column, "none") if pr.role is not None else "none"
        return cls._level(pr.role, column)

    def _decide(self, pr: Principal, action: str, resource: str | None,
                preparer: str | None) -> tuple[bool, str, str]:
        """(allowed, reason, error code). Reasons read "<Tag>: <why>"; the tag lands in the denial commit."""
        if action in APPROVALS:
            if pr.persona:
                return False, f"External: {PERSONA_DENIAL.format(p=pr.id)}", "sod_violation"
            if pr.role in AGENT_ROLES:
                return False, f"SoD: agents never {APPROVALS[action]}", "sod_violation"
            if not pr.authenticated:
                if pr.external and _APPROVED.search(pr.text or ""):
                    why = (f"{pr.external} text says 'approved'; external parties never satisfy an internal "
                           f"approval")
                else:
                    why = f"{pr.id} is not a signed internal session; approvals need one"
                return False, f"External: {why}", "sod_violation"
            if preparer is not None and preparer == pr.id:
                return False, f"SoD: preparer ≠ approver ({pr.id} prepared it)", "sod_violation"
            if self._level(pr.role, action) != "approve":
                return False, f"SoD: {APPROVAL_NEEDS[action]}", "sod_violation"
            return True, f"{ROLE_NOTES[pr.role.value]}; may {APPROVALS[action].split()[0]}", ""
        if pr.role is None:
            return False, f"Fail closed: unknown principal {pr.id!r}", "forbidden"
        if action in ("desk", "inject"):
            column, ok = action, {"write"}
        elif action == "read":
            column, ok = resource_class(resource), READ_LEVELS
        elif action in ("write", "answer"):
            column, ok = resource_class(resource), {"write"}
        else:
            return False, f"Fail closed: unknown action {action!r}", "forbidden"
        if column is None:
            return False, f"Fail closed: unknown resource {resource!r}", "forbidden"
        level = self._level_of(pr, column)
        note = PERSONA_NOTE.format(p=pr.id) if pr.persona else ROLE_NOTES[pr.role.value]
        if level in ok:
            return True, note + (" (PII masked)" if level == "redacted" else ""), ""
        tag = "No PII" if column in PII_RESOURCES and level == "none" else "Least privilege"
        return False, f"{tag}: {note}", "forbidden"

    def _record(self, d: AccessDecision) -> AccessDecision:
        self.log.append(d)
        if not d.allowed and self.trace is not None:
            self.trace.record_access_denied(d)
        return d

    def check(self, principal: Any, action: str, resource: str | None, *, preparer: str | None = None,
              at: datetime | None = None) -> AccessDecision:
        """Decide, log, and (on a denial) commit. ``preparer`` is who prepared the thing being approved."""
        when = self._at(at)
        pr = principal_of(principal)
        allowed, reason, _ = self._decide(pr, action or "", resource, preparer)
        return self._record(AccessDecision(at=when, principal=pr.id, action=action or "?", resource=resource or "-",
                                           allowed=allowed, reason=reason))

    def can(self, principal: Any, action: str, resource: str | None, *, preparer: str | None = None,
            at: datetime | None = None) -> bool:
        return self.check(principal, action, resource, preparer=preparer, at=at).allowed

    def require(self, principal: Any, action: str, resource: str | None, *, preparer: str | None = None,
                at: datetime | None = None) -> AccessDecision:
        """``check`` that raises ``AccessDenied`` (code ``sod_violation`` for approvals, else ``forbidden``)."""
        when = self._at(at)
        pr = principal_of(principal)
        allowed, reason, code = self._decide(pr, action or "", resource, preparer)
        d = self._record(AccessDecision(at=when, principal=pr.id, action=action or "?", resource=resource or "-",
                                        allowed=allowed, reason=reason))
        if not d.allowed:
            raise AccessDenied(d, code or "forbidden")
        return d

    def read(self, principal: Any, resource: str, obj: Any = None, *, at: datetime | None = None) -> Any:
        """Check ``read`` on ``resource`` (raises ``AccessDenied``), then return ``obj`` redacted for the principal."""
        self.require(principal, "read", resource, at=at)
        return self.redact(principal, obj) if obj is not None else None

    # ------------------------------------------------------------------ redaction

    def sees_pii(self, principal: Any) -> bool:
        return self._level_of(principal_of(principal), "pii") == "read"

    def redact(self, principal: Any, obj: Any) -> Any:
        """``obj`` as ``principal`` may see it: unchanged for PII readers (Reader, Claims Lead, CRM bot), else a
        copy with personal data masked. Never mutates ``obj``; unknown principals get the redacted copy."""
        if self.sees_pii(principal):
            return obj
        return self._scrub(obj)

    def pii_fields(self, obj: Any) -> list[str]:
        return pii_fields(obj, pii_sources=self._pii_sources)

    def _scrub(self, v: Any) -> Any:
        if isinstance(v, BaseModel):
            return self._scrub_model(v)
        if isinstance(v, Mapping):
            return {k: (MASK if isinstance(k, str) and k.lower() in PII_KEYS and x is not None else self._scrub(x))
                    for k, x in v.items()}
        if isinstance(v, list):
            return [self._scrub(x) for x in v]
        if isinstance(v, tuple):
            return tuple(self._scrub(x) for x in v)
        if isinstance(v, str):
            return scrub_text(v)
        return v

    def _scrub_model(self, m: BaseModel) -> BaseModel:
        tagged = "pii" in (getattr(m, "acl_tags", None) or [])
        from_pii = getattr(m, "source_id", None) in self._pii_sources
        updates: dict[str, Any] = {}
        for name in type(m).model_fields:
            v = getattr(m, name)
            if v is None:
                continue
            if ((isinstance(m, Source) and name == "text" and _pii_source(m))
                    or (isinstance(m, Fact) and name in ("value", "span") and tagged)
                    or (isinstance(m, Fact) and name == "span" and from_pii)
                    or (isinstance(m, Evidence) and name in ("value", "quote") and from_pii)
                    or (isinstance(m, (Claim, CrmEvent)) and name == "text")
                    or (isinstance(m, Coupon) and name == "pnr")):
                updates[name] = MASK
                continue
            new = self._scrub(v)
            if new is not v and new != v:
                updates[name] = new
        return m.model_copy(update=updates) if updates else m

    # ------------------------------------------------------------------ LLM contexts and escalation packets

    def context(self, principal: Any, *, facts: Iterable[Fact] = (), items: Iterable[Any] = (),
                purpose: str | None = None, at: datetime | None = None) -> LlmContext:
        """Build an agent's (or a recipient's) context only from what it may see.

        Requires ``read`` on case facts. For principals without PII access, personal facts are withheld entirely
        (not just masked) and every other item is redacted, so a Drafter prompt carries 0 PII fields.
        """
        when = self._at(at)
        pr = principal_of(principal)
        allowed, reason, code = self._decide(pr, "read", "case_facts", None)
        facts = list(facts)
        if not allowed:
            d = self._record(AccessDecision(at=when, principal=pr.id, action="context",
                                            resource=purpose or "case_facts", allowed=False, reason=reason))
            raise AccessDenied(d, code or "forbidden")
        if self.sees_pii(principal):
            kept, withheld = facts, 0
        else:
            kept = [self._scrub_model(f) for f in facts if not _is_pii_fact(f)]
            withheld = len(facts) - len(kept)
        if withheld:
            reason += f" · {withheld} PII facts withheld"
        self._record(AccessDecision(at=when, principal=pr.id, action="context", resource=purpose or "case_facts",
                                    allowed=True, reason=reason))
        return LlmContext(principal=pr.id, purpose=purpose, facts=kept,
                          items=[self.redact(principal, x) for x in items], withheld_facts=withheld)

    def packet(self, recipient: Any, obj: Any, *, purpose: str | None = None, at: datetime | None = None) -> Any:
        """An escalation packet (question, evidence, case) redacted for its recipient."""
        self._record(AccessDecision(at=self._at(at), principal=principal_of(recipient).id, action="packet",
                                    resource=purpose or "questions", allowed=True,
                                    reason="escalation packet redacted per recipient"))
        return self.redact(recipient, obj)


# ---------- signed session tokens ----------

def _key(secret: str | bytes) -> bytes:
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret or b"")
    if not key:
        raise ValueError("a non-empty secret must be passed in")
    return key


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()


def issue(role: Role | str, name: str, secret: str | bytes, *, at: datetime) -> str:
    """``<base64url(Session JSON)>.<HMAC-SHA256 hex>``. ``at`` is the session's ``issued_at`` (no wall clock)."""
    key = _key(secret)
    role = Role(role)
    s = Session(principal=principal_for(role, name), role=role, name=name, issued_at=utc(at))
    payload = _b64(canonical(s))
    return f"{payload}.{_sign(key, payload)}"


def verify(token: Any, secret: str | bytes) -> Session:
    """The signed ``Session``, or ``InvalidToken`` for anything else: fails closed (bad signature, wrong secret,
    empty secret, malformed payload, or a principal that doesn't match its role and name)."""
    try:
        key = _key(secret)
        if not isinstance(token, str):
            raise InvalidToken("token must be a string")
        payload, sep, sig = token.strip().rpartition(".")
        if not sep or not payload or not _HEX64.fullmatch(sig):
            raise InvalidToken("malformed token")
        if not hmac.compare_digest(sig, _sign(key, payload)):
            raise InvalidToken("bad signature")
        s = Session.model_validate(orjson.loads(_unb64(payload)))
        if s.principal != principal_for(s.role, s.name):
            raise InvalidToken("principal does not match role and name")
        return s
    except InvalidToken:
        raise
    except (ValueError, TypeError, AttributeError) as exc:   # base64, UTF-8/ASCII, JSON and pydantic all land here
        raise InvalidToken(f"invalid token: {type(exc).__name__}") from None


def judge_session(at: datetime) -> Session:
    return Session(principal="judge", role=Role.JUDGE, name="Judge", issued_at=utc(at))


def session_or_judge(token: Any, secret: str | bytes, *, at: datetime) -> Session:
    """CONTRACTS §0: no token, or any bad token, is the read-only ``judge``."""
    if not token:
        return judge_session(at)
    try:
        return verify(token, secret)
    except InvalidToken:
        return judge_session(at)
