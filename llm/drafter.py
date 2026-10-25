"""F6 · The Drafter: Claude writes drafts; code checks every number, every phrase and every literal.

``Drafter`` implements ``DrafterAPI`` (contracts/interfaces.py). Every call goes through ``llm/client.py``
(disk cache, ``LLM_MODE``, dollar cap) at effort ``medium``, as principal ``agent.drafter``.

- **Prose** (``explain``, ``je_memo``, ``challenge_reply``, ``rights_notice``) returns a ``Draft``. The *number
  guard* checks that every number in the text appears in the evidence the model was shown; any failure (or an
  unavailable LLM) falls back to a deterministic template built from the same evidence (``template_fallback``).
  ``numbers_verified`` describes the final text.
- **``rights_notice``** is the Art. 14(2) letter. The model sees no PII at all: no coupon id, no name, no contact.
  It writes ``{{passenger_name}}`` / ``{{booking_reference}}`` / ``{{neb_contact}}`` placeholders, and
  ``merge_letter`` fills them in code afterwards. One draft serves every passenger with the same entitlement.
- **``propose_rule``** (structured output) drafts a DSL ``Rule`` from a ruling: features come from the CONTRACTS §4
  allowlist and actions from ``RuleAction`` (both enforced by the output schema, then re-checked), every literal of
  the condition maps to a verbatim phrase of the ruling (numbers must appear in that phrase), scope the ruling does
  not state is copied from the case as ``case:<v>``, and ``tier`` / ``authority_required`` come from the author's
  role in code. The engine verifies the draft (``engine.rules.checks``); the ruler confirms it.
- **``classify_challenge``** (structured output) returns ``assertion | new_fact | new_legal_pattern`` plus trust
  tier 4 facts whose spans are verbatim and whose values re-parse via ``contracts/parse.py``. Keyword rules can
  only escalate the model's class, never lower it.

The LLM never decides who is owed, never computes an amount and never derives a cause.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from contracts import fields as cf
from contracts import parse as cp
from contracts.models import (
    Cause,
    Draft,
    Entitlement,
    Evidence,
    Extraordinary,
    Fact,
    FlightDecision,
    JournalEntry,
    Question,
    Role,
    Rule,
    RuleAction,
    Ruling,
    Source,
    SourceKind,
)
from llm.client import (
    DEFAULT_CACHE_DIR,
    DEMO_CACHE_DIR,
    MODEL,
    AnthropicBackend,
    LlmCallRecord,
    LlmClient,
    LLMUnavailable,
    RawResponse,
    ScriptedBackend,
)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DRAFTER_DEMO_DIR = DEMO_CACHE_DIR / "drafter"
SCENARIOS_FILE = DRAFTER_DEMO_DIR / "scenarios.json"
MANIFEST_FILE = DRAFTER_DEMO_DIR / "MANIFEST.json"

ROLE = "drafter"
PRINCIPAL = Role.DRAFTER.value          # "agent.drafter"
EFFORT = "medium"

PV_EXPLAIN = "drafter-explain-v1"
PV_RIGHTS = "drafter-rights-notice-v1"
PV_JE_MEMO = "drafter-je-memo-v1"
PV_CHALLENGE_REPLY = "drafter-challenge-reply-v1"
PV_RULE = "drafter-rule-v1"
PV_CLASSIFY = "drafter-classify-v1"

DECISION_STANDS = "Decision stands."
CLASSES = ("assertion", "new_fact", "new_legal_pattern")
CHALLENGE_TIER = 4


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"drafter_{name}.md").read_text(encoding="utf-8").strip()


def system_prompt(task: str) -> str:
    """The full system prompt for one Drafter task (common rules + the task prompt)."""
    return _prompt("common") + "\n\n" + _prompt(task)


# ================================================================ number guard
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_UNITS = {"zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_ONES = {"one": 1, **{k: v for k, v in _UNITS.items() if 2 <= v <= 9}}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_WORD_RE = re.compile(r"\b(" + "|".join(_TENS) + r")(?:-(" + "|".join(_ONES) + r"))?\b|\b(" + "|".join(_UNITS)
                      + r")\b", re.IGNORECASE)
# METAR groups carry several numbers in one token: day/hour/minute and direction/speed/gust.
_METAR_TIME_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
_METAR_WIND_RE = re.compile(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b")


def numbers_in(text: str) -> list[Decimal]:
    """Every number written in ``text``: digits ("€34,650", "21:40Z" → 21, 40, "C-74/19" → 74, 19) and number
    words ("seven", "twenty-four"; "one" is ignored because it is mostly not a number in prose)."""
    out = [Decimal(m.group(0).replace(",", "")) for m in _NUM_RE.finditer(text)]
    for m in _WORD_RE.finditer(text):
        if m.group(3):
            out.append(Decimal(_UNITS[m.group(3).lower()]))
        else:
            out.append(Decimal(_TENS[m.group(1).lower()] + (_ONES[m.group(2).lower()] if m.group(2) else 0)))
    return out


def evidence_numbers(evidence: Any) -> set[Decimal]:
    """The numbers a draft may use: every number in the evidence, plus its plain re-expressions (cents as euros,
    ratios as percentages, floats rounded, METAR groups split). Nothing is added or multiplied across values."""
    out: set[Decimal] = set()

    def add_str(s: str) -> None:
        out.update(numbers_in(s))
        for m in _METAR_TIME_RE.finditer(s):
            out.update(Decimal(g) for g in m.groups())
        for m in _METAR_WIND_RE.finditer(s):
            out.update(Decimal(g) for g in m.groups() if g and g != "VRB")

    def walk(x: Any) -> None:
        if x is None or isinstance(x, bool):
            return
        if isinstance(x, BaseModel):
            walk(x.model_dump(mode="json"))
        elif isinstance(x, int):
            d = Decimal(abs(x))
            out.update({d, d / 100})                       # cents → euros
        elif isinstance(x, float):
            d = Decimal(str(abs(x)))
            out.update({d, d.quantize(Decimal(1), ROUND_HALF_UP), d.quantize(Decimal("0.1"), ROUND_HALF_UP),
                        d.quantize(Decimal("0.01"), ROUND_HALF_UP)})
            if d <= 1:                                     # ratios → percentages
                p = d * 100
                out.update({p, p.quantize(Decimal(1), ROUND_HALF_UP), p.quantize(Decimal("0.1"), ROUND_HALF_UP)})
        elif isinstance(x, str):
            add_str(x)
        elif isinstance(x, Mapping):
            for v in x.values():
                walk(v)
        elif isinstance(x, list | tuple | set | frozenset):
            for v in x:
                walk(v)
        elif isinstance(x, datetime | date):
            add_str(x.isoformat())
        else:
            add_str(str(x))

    walk(evidence)
    return out


def verify_numbers(text: str, evidence: Any) -> tuple[bool, list[str]]:
    """(ok, unknown): ``ok`` iff every number in ``text`` appears in ``evidence``."""
    allowed = evidence_numbers(evidence)
    bad = [str(n) for n in numbers_in(text) if n not in allowed]
    return not bad, list(dict.fromkeys(bad))


# ================================================================ PII
REDACTED = "[redacted:pii]"
_EMAIL_RE = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w+])\+\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,4}){2,4}(?!\w)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z]{4}\d{10,26}\b")
PII_FIELDS = frozenset({"pax.name", "pax.contact", "pax.email", "pax.phone", "pax.address", "crm.rights_email_sent",
                        "challenge.text"})


def pii_hits(text: str) -> list[str]:
    """E-mail addresses, phone numbers and IBANs in ``text``."""
    return [m.group(0) for r in (_EMAIL_RE, _PHONE_RE, _IBAN_RE) for m in r.finditer(text)]


def redact(text: str) -> tuple[str, int]:
    n = 0
    for r in (_EMAIL_RE, _PHONE_RE, _IBAN_RE):
        text, k = r.subn(REDACTED, text)
        n += k
    return text, n


def _free_text_field(name: str) -> bool:
    return name.endswith((".text", "_text", ".raw")) or name in PII_FIELDS


def withheld(f: Fact) -> bool:
    """Facts the Drafter never sees: PII-tagged, personal fields and free-text fields."""
    return "pii" in f.acl_tags or _free_text_field(f.field)


# ================================================================ formatting helpers
def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def _h(*parts: Any, n: int = 10) -> str:
    return hashlib.sha256(_dump(parts).encode()).hexdigest()[:n]


def eur(cents: int) -> str:
    """Integer cents → "€34,650" (or "€510.50")."""
    sign = "−" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}€{c // 100:,}" if c % 100 == 0 else f"{sign}€{c / 100:,.2f}"


def _num(flight_id: str) -> str:
    return flight_id.split("@")[0]


def _flight_date(flight_id: str) -> str | None:
    part = flight_id.split("@")[1].split(":")[0] if "@" in flight_id else ""
    return part if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part) else None


def _date_text(iso: str | None) -> str | None:
    if not iso:
        return None
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _clean(text: str) -> str:
    t = text.strip()
    if t.startswith("```") and t.endswith("```"):
        t = t.strip("`").strip()
    return t


def _message(blocks: Sequence[tuple[str, Any]], task: str) -> str:
    parts = [f"<{tag}>\n{obj if isinstance(obj, str) else _dump(obj)}\n</{tag}>" for tag, obj in blocks]
    return "\n\n".join([*parts, task])


# ================================================================ evidence projections (exactly what the model sees)
def _evidence_item(e: Evidence) -> tuple[dict[str, Any], int]:
    quote, n = redact(e.quote) if e.quote else (None, 0)
    value = e.value
    if isinstance(value, str):
        value, k = redact(value)
        n += k
    return {"field": e.field, "value": value, "quote": quote, "role": e.role, "trust_tier": e.trust_tier,
            "struck": e.struck}, n


def decision_payload(d: FlightDecision) -> tuple[dict[str, Any], int]:
    """A decision as the Drafter sees it: no commit hashes, ids or timestamps of the run, PII patterns redacted."""
    ev, n = [], 0
    for e in d.evidence:
        item, k = _evidence_item(e)
        ev.append(item)
        n += k
    reason, k = redact(d.reason)
    return {
        "flight": _num(d.flight_id), "flight_id": d.flight_id, "cause": d.cause.value,
        "extraordinary": d.extraordinary.value, "ops_cause_code": d.ops_cause_code, "recoded": d.recoded,
        "recode_label": d.recode_label, "in_window_dep": d.in_window_dep, "in_window_arr": d.in_window_arr,
        "window_margin_min": d.window_margin_min,
        "confidence": {"label": d.confidence.label, "score": d.confidence.score, "caps": list(d.confidence.caps)},
        "reason": reason, "evidence": ev, "rules_applied": list(d.rules_applied),
        "legal_basis": list(d.legal_basis), "outcome": d.outcome,
        "routed_to": d.routed_to.value if d.routed_to else None,
    }, n + k


LEGAL_EU261: tuple[str, ...] = (
    "Regulation (EC) No 261/2004 (EU261).",
    ("Article 3(1): it applies to passengers departing from an airport in the EU, and to passengers departing from "
    "a third country to the EU on an EU carrier."),
    ("Article 3(3): it does not apply to passengers travelling free of charge or at a reduced fare not available to "
    "the public (e.g. staff tickets)."),
    ("Article 5(1)(c): no compensation if passengers were told of the cancellation at least two weeks before "
    "departure."),
    ("Article 5(3): no compensation if the cancellation was caused by extraordinary circumstances which could not "
    "have been avoided even if all reasonable measures had been taken; refund or re-routing (Article 8) and care "
    "(Article 9) remain due."),
    ("Article 7(1): compensation of €250 for flights of 1,500 km or less, €400 for intra-EU flights over 1,500 km "
    "and other flights of 1,500 to 3,500 km, €600 for all other flights."),
    ("Article 7(2): compensation may be reduced by 50% when the passenger is re-routed and arrives within the time "
    "limits in that article."),
    ("Article 7(3): compensation is paid in cash, by bank transfer or by cheque, or, with the passenger's signed "
    "agreement, in travel vouchers."),
    ("Article 8(1): reimbursement of the ticket within seven days, or re-routing at the earliest opportunity or at "
    "a later date of the passenger's choosing."),
    ("Article 9: meals and refreshments, hotel accommodation where necessary, transport between the airport and the "
    "hotel, and two telephone calls or emails."),
    ("Article 14(2): a written notice setting out the rules for compensation and assistance, with the contact "
    "details of the national enforcement body (Article 16)."),
)
PLACEHOLDERS = ("{{passenger_name}}", "{{booking_reference}}", "{{neb_contact}}")
NEB_CONTACT_IE = ("Irish Aviation Authority, the national enforcement body for Regulation (EC) No 261/2004 in "
                  "Ireland (Article 16)")
WEATHER_PHRASE = "no compensation; refunds and care still due"


def rights_payload(ent: Entitlement, corrects: str | None = None,
                   cause: str | None = None) -> tuple[dict[str, Any], int]:
    """The entitlement as the rights-notice Drafter sees it: no coupon id, no seat, no name, no per-coupon reason.
    Identical for every passenger with the same entitlement, so one draft (and one LLM call) serves them all."""
    fdate = _flight_date(ent.flight_id)
    n = 0
    if corrects:
        corrects, n = redact(corrects)
    if cause:
        cause, k = redact(cause)
        n += k
    return {
        "flight": _num(ent.flight_id), "date": fdate, "date_text": _date_text(fdate), "cause": cause,
        "status": ent.status,
        "regime": ent.regime, "article": ent.article,
        "compensation": eur(ent.compensation_cents) if ent.compensation_cents else None,
        "compensation_cents": ent.compensation_cents, "band_eur": ent.band_eur,
        "distance_km": round(ent.distance_km), "reduction": ent.reduction,
        "refund_due": eur(ent.refund_due_cents) if ent.refund_due_cents else None,
        "refund_already_initiated": ent.refund_already_initiated, "care_due": ent.care_due,
        "voucher_offset": eur(ent.voucher_offset_cents) if ent.voucher_offset_cents else None,
        "corrects": corrects, "placeholders": list(PLACEHOLDERS),
    }, n


JE_BASIS: dict[str, str] = {
    "sale": "ticket sale: fare (incl. YQ/YR) to air traffic liability 2100, taxes to 2110",
    "refund": "refund of an unflown coupon: air traffic liability and taxes to refunds payable",
    "voucher": "refund voucher issued for the ticket value incl. taxes",
    "reroute_fim": "partner reroute through a flight interruption manifest: interline payable",
    "compensation_estimate": "IFRS 15 variable consideration: full Art. 7 entitlement × expected ultimate claim "
                             "rate, presented as a reduction of passenger revenue",
    "claim_approved": "claim approved at face value: estimated liability 2140 to compensation payable 2141",
    "claim_paid": "payment of an approved EU261 claim",
    "change_in_estimate": "change in estimate (IAS 8.36), applied prospectively",
    "derecognition": "derecognition of the remaining liability at limitation",
    "care_accrual": "care under Art. 9 accrued at the estimated cost",
    "care_invoice": "care invoices received: accrual trued up to the invoiced amount",
    "recode": "cause recode (weather ↔ technical/extraordinary): change in estimate (IAS 8.36)",
    "out_of_period_adjustment": "prior-period error, corrected in current period (immaterial) (IAS 8.5)",
    "voucher_in_lieu": "service-desk voucher in lieu of compensation (Art. 7(3))",
    "voucher_void": "unredeemed goodwill voucher voided",
}


def je_payload(je: JournalEntry) -> dict[str, Any]:
    lines = []
    for ln in je.lines:
        side, cents = ("Dr", ln.dr_cents) if ln.dr_cents else ("Cr", ln.cr_cents)
        lines.append({"side": side, "account": ln.account, "account_name": ln.account_name, "eur": eur(cents),
                      "cents": cents, "dims": dict(ln.dims)})
    return {"id": je.id, "kind": je.kind, "basis": JE_BASIS.get(je.kind, je.kind.replace("_", " ")),
            "event_date": je.event_date.isoformat(), "period": je.period, "memo": je.memo, "lines": lines,
            "ias8_class": je.ias8_class, "reverses": je.reverses, "estimate_ref": je.estimate_ref,
            "status": je.status, "built_from": je.built_from, "ties_to": list(je.ties_to)}


NEXT_STEP = {
    "assertion": "none: the challenge brings nothing new to check, so the decision stands",
    "new_fact": "Ops verifies the new fact against tier-1 logs; the decision stands meanwhile",
    "new_legal_pattern": "Legal is asked (e.g. a hidden manufacturing defect, CJEU C-549/07 ¶26); the decision "
                         "stands until Legal rules",
}


# ================================================================ templates (deterministic, evidence-only)
def _verdict(d: FlightDecision) -> str:
    cause = d.cause.value.replace("_", "-")
    if d.recoded and d.cause != Cause.WEATHER and (d.ops_cause_code or "") in ("71", "72"):
        head = "Not weather" + (f" · recoded {d.recode_label}" if d.recode_label else "")
    else:
        head = cause[:1].upper() + cause[1:]
    if d.extraordinary == Extraordinary.YES:
        return f"{head}, extraordinary: {WEATHER_PHRASE}"
    if d.extraordinary == Extraordinary.NO:
        return f"{head}, not extraordinary: compensation owed"
    role = (d.routed_to.value if d.routed_to else "legal").replace("_", " ")
    return f"{head}: held for {'Legal' if role == 'legal' else 'the ' + role.title()}"


def _confidence_text(d: FlightDecision) -> str:
    s = d.confidence.score
    return f"{d.confidence.label} {round(s * 100)}%" if s is not None else f"{d.confidence.label}: uncalibrated"


def explain_template(d: FlightDecision) -> str:
    parts = [f"{_num(d.flight_id)}: {_verdict(d)}.", d.reason.rstrip(".") + "."]
    if d.legal_basis:
        parts.append("Legal basis: " + ", ".join(d.legal_basis) + ".")
    if d.rules_applied:
        parts.append("Rules applied: " + ", ".join(d.rules_applied) + ".")
    parts.append(_confidence_text(d)[:1].upper() + _confidence_text(d)[1:] + ".")
    return " ".join(redact(p)[0] for p in parts)


def je_memo_template(p: Mapping[str, Any]) -> str:
    legs = "; ".join(f"{ln['side']} {ln['account']} {ln['account_name']} {ln['eur']}" for ln in p["lines"])
    head = f"{p['kind'].replace('_', ' ').capitalize()} ({p['period']}), drafted, pending approval: {legs}."
    return f"{head} Basis: {p['basis']}." + (f" {p['memo']}" if p.get("memo") else "")


def challenge_reply_template(cls: str, cited: Sequence[Mapping[str, Any]], stands: bool = True) -> str:
    lead = DECISION_STANDS if stands else "Decision under review."
    body = {
        "assertion": "The challenge restates a view but brings no new evidence, so it does not change the decision.",
        "new_fact": "The new fact is trust tier 4: Ops will verify it against tier-1 logs, and the decision does not "
                    "change unless it is verified.",
        "new_legal_pattern": "It raises a new legal question, so it has gone to Legal; the decision does not change "
                             "unless Legal rules.",
    }[cls]
    quotes = list(dict.fromkeys(str(c.get("quote") or "").strip() for c in cited if c.get("quote")))
    tail = (" Evidence: " + " · ".join(q.rstrip(".") for q in quotes[:6]) + ".") if quotes else ""
    return f"{lead} {body}{tail}"


def rights_notice_template(p: Mapping[str, Any]) -> str:
    when = f" on {p['date_text']}" if p.get("date_text") else ""
    lines = ["Dear {{passenger_name}},", ""]
    if p.get("corrects"):
        lines += [(f"Our earlier message about your booking was wrong. It said: \"{p['corrects']}\" The correct "
                  "position is set out below."), ""]
    because = f" ({p['cause']})" if p.get("cause") else ""
    lines += [(f"Your Northstar Air flight {p['flight']}{when} (booking {{{{booking_reference}}}}) was cancelled"
              f"{because}. This notice sets out your rights under Regulation (EC) No 261/2004, as Article 14(2) "
              "requires."), ""]
    status = p["status"]
    if status == "owed" and p.get("compensation"):
        red = " (reduced by 50% under Article 7(2))" if p.get("reduction") == "art7_2_50pct" else ""
        lines.append(f"Compensation: you are entitled to {p['compensation']} under Article 7{red}. We pay it in cash, "
                     "by bank transfer or by cheque; travel vouchers only with your signed agreement (Article 7(3)).")
    elif status == "no_compensation":
        lines.append(f"Compensation: {WEATHER_PHRASE}. The cancellation was caused by extraordinary circumstances "
                     "(Article 5(3)), so no compensation is payable under Article 7, but your right to a refund or "
                     "re-routing (Article 8) and to care (Article 9) remains.")
    elif status == "exempt_notice":
        lines.append("Compensation: none is payable because you were told of the cancellation at least two weeks "
                     "before departure (Article 5(1)(c)); your right to a refund or re-routing (Article 8) remains.")
    elif status in ("out_of_scope", "staff_ticket"):
        art = "Article 3(3)" if status == "staff_ticket" else "Article 3(1)"
        lines.append(f"Compensation: Regulation (EC) No 261/2004 does not apply to this ticket ({art}).")
    else:
        lines.append("Compensation: we are still assessing whether compensation is due under Article 7 and will "
                     "write to you again once that is decided.")
    if p.get("refund_already_initiated"):
        lines.append("Refund: your refund has already been initiated and will not be repeated (Article 8).")
    elif p.get("refund_due"):
        lines.append(f"Refund: a refund of {p['refund_due']} is due within seven days (Article 8(1)).")
    elif status not in ("out_of_scope", "staff_ticket"):
        lines.append("Refund or re-routing: you may choose a refund of your ticket within seven days, or re-routing "
                     "at the earliest opportunity (Article 8).")
    if p.get("care_due") and status not in ("out_of_scope", "staff_ticket", "exempt_notice"):
        lines.append("Care: meals and refreshments, hotel accommodation where necessary and transport between the "
                     "airport and the hotel (Article 9). Please keep your receipts.")
    lines += ["", "If you need help, you can contact the national enforcement body: {{neb_contact}}.", "",
              "Northstar Air Customer Care"]
    return "\n".join(lines)


def merge_letter(draft: Draft | str, values: Mapping[str, str]) -> str:
    """Merge personal fields into a drafted letter, in code, after drafting (the Drafter never saw them).
    ``values`` maps placeholder names (``passenger_name``, ``booking_reference``; ``neb_contact`` defaults to the
    Irish NEB) to text. Raises ``KeyError`` if a placeholder has no value."""
    text = draft.text if isinstance(draft, Draft) else draft
    vals = {"neb_contact": NEB_CONTACT_IE, **values}

    def sub(m: re.Match[str]) -> str:
        return vals[m.group(1)]

    return re.sub(r"\{\{(\w+)\}\}", sub, text)


# ================================================================ structured outputs
FeatureName = Literal[tuple(cf.DSL_FEATURES)]  # type: ignore[valid-type]
ScopeKeyName = Literal[tuple(cf.DSL_FEATURES + cf.SCOPE_CONTEXT_KEYS)]  # type: ignore[valid-type]
OpName = Literal[tuple(cf.DSL_OPS)]  # type: ignore[valid-type]
ActionName = Literal[tuple(a.value for a in RuleAction)]  # type: ignore[valid-type]
RouteName = Literal["claims_lead", "legal", "controller", "ops"]
CHALLENGE_FIELDS: tuple[str, ...] = (
    "manufacturer.hidden_defect", "manufacturer.part_number", "aog.logged_at", "aog.mel_relief", "aog.ata_chapter",
    "aog.aog", "aog.rts_est", "aog.defect_text", "mcc.part_eta", "metar.gust_kt", "metar.sknt", "metar.vsby_sm",
    "spare.available_within_h", "flight.notified_at", "flight.ops_cause_code",
)
ChallengeFieldName = Literal[CHALLENGE_FIELDS]  # type: ignore[valid-type]


class ClauseDraft(BaseModel):
    feature: FeatureName = Field(description="An allowlisted feature")
    op: OpName
    value_json: str = Field(description='JSON literal, e.g. true, false, 3, 12, "weather", ["refund","voucher"]')
    phrase: str = Field(description="The ruling's own words that state this clause, copied character for character")


class ScopeDraft(BaseModel):
    key: ScopeKeyName = Field(description="An allowlisted feature or a context key")
    value_json: str = Field(description="JSON literal")
    phrase: str | None = Field(description="The ruling's own words that state it, or null when copied from the case")


class RuleDraft(BaseModel):
    action: ActionName
    action_arg: RouteName | None = Field(description="Only for route_to; null otherwise")
    action_phrase: str = Field(description="The ruling's own words that decide the action, copied exactly")
    match: Literal["all", "any"]
    condition: list[ClauseDraft]
    scope: list[ScopeDraft]
    notes: str


class ChallengeFactDraft(BaseModel):
    field: ChallengeFieldName
    value_json: str = Field(description='JSON literal, e.g. true, 22, "2913", "2025-01-24T17:00:00Z"')
    span: str = Field(description="Copied character for character from the challenge text")


class ChallengeDraft(BaseModel):
    classification: Literal["assertion", "new_fact", "new_legal_pattern"]
    reason: str
    facts: list[ChallengeFactDraft]


# ================================================================ rule drafting helpers
_BOOL_FEATURES = frozenset({
    "flight.departs_eu", "flight.arrives_eu", "flight.operating_carrier_eu", "flight.is_return_sector",
    "aog.before_window", "aog.inside_window", "aog.root_cause_internal", "aog.mel_relief", "rotation.prev_cancelled",
    "pax.reroute_earliest_offered", "voucher.in_lieu", "voucher.signed", "claim.duplicate", "claim.after_limitation",
    "cohort.limitation_expired", "sources.disagree",
})
_NUM_FEATURES = frozenset({
    "flight.window_margin_min", "flight.distance_km", "flight.band_eur", "spare.available_within_h",
    "pax.notice_days", "pax.arrival_delay_min", "voucher.amount_cents", "claim.age_months", "cohort.age_months",
    "cohort.months_since_last_claim", "precedent.count",
})
_ENUM_FEATURES: dict[str, tuple[str, ...]] = {
    "flight.in_window_dep": ("in", "out", "unknown"), "flight.in_window_arr": ("in", "out", "unknown"),
    "flight.route_region": ("EU", "EU_US", "EU_UK", "OTHER"),
    "rotation.prev_cause": tuple(c.value for c in Cause),
    "pax.election": ("refund", "voucher", "reaccommodated_own", "reroute_partner", "none"),
    "pax.fare_type": ("revenue", "staff_id90"), "claim.channel": ("direct", "agency"),
    "claim.authority": ("poa", "assignment", "none"), "claim.regime": ("EU261", "UK261"),
}
_STR_FEATURES = frozenset({"flight.ops_cause_code", "aog.ata_chapter"})
FEATURE_KINDS: dict[str, str] = {
    **{f: "bool" for f in _BOOL_FEATURES}, **{f: "num" for f in _NUM_FEATURES},
    **{f: "enum" for f in _ENUM_FEATURES}, **{f: "str" for f in _STR_FEATURES},
}
FIELD_TO_FEATURE = {"coupon.fare_type": "pax.fare_type"}
TIER_OF_ROLE: dict[Role, str] = {Role.CLAIMS_LEAD: "claims_lead_ruling", Role.LEGAL: "legal_ruling",
                                 Role.CONTROLLER: "controller_ruling"}
ID_PREFIX: dict[Role, str] = {Role.CLAIMS_LEAD: "R-CL", Role.LEGAL: "R-LEG", Role.CONTROLLER: "R-CTL"}
KIND_OF_ACTION: dict[RuleAction, str] = {
    RuleAction.SET_EXTRAORDINARY: "cause", RuleAction.SET_NOT_EXTRAORDINARY: "cause",
    RuleAction.ALLOW_OFFSET: "voucher", RuleAction.DENY_OFFSET: "voucher",
    RuleAction.DENY_RELEASE: "release", RuleAction.KEEP_TAIL: "release",
    RuleAction.APPLY_7_2_REDUCTION: "entitlement", RuleAction.ROUTE_TO: "routing",
}
CASE_PREFIX = "case:"
_SINGLE_CASE_KEYS = frozenset({"coupon", "flight"})   # a rule scoped to one coupon/flight could never settle another


class RuleAuthorityError(ValueError):
    """The ruling's author holds no rule-making authority (agents, Ops, CFO, judges never author rules)."""


def ruling_text(r: Ruling) -> str:
    """The ruler's own words: what grounding phrases must be copied from."""
    return "\n".join(t for t in (r.decision.strip(), r.explanation.strip()) if t)


def verbatim(phrase: str | None, text: str) -> str | None:
    """The slice of ``text`` that ``phrase`` quotes (whitespace-normalised, case-insensitive), or None."""
    if not phrase:
        return None
    p = _ws(phrase).strip(" .,;:\"'")
    if len(p) < 2:
        return None
    t = _ws(text)
    i = t.lower().find(p.lower())
    return t[i:i + len(p)] if i >= 0 else None


def grounding_key(feature: str, value: Any) -> str:
    """Grounding keys follow the stub and ``engine.rules``: numbers → "3"; others → "voucher.signed=false"."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(int(value) if float(value).is_integer() else value)
    if isinstance(value, str):
        return f"{feature}={value}"
    return f"{feature}={json.dumps(value)}"


def _scalar_ok(feature: str, v: Any) -> bool:
    kind = FEATURE_KINDS.get(feature)
    if kind == "bool":
        return isinstance(v, bool)
    if kind == "num":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if kind == "enum":
        return isinstance(v, str) and v in _ENUM_FEATURES[feature]
    if kind == "str":
        return isinstance(v, str) and bool(v)
    return isinstance(v, str) and bool(v)                  # context keys: ids


def _coerce(feature: str, v: Any) -> Any:
    kind = FEATURE_KINDS.get(feature)
    if kind == "bool" and isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    if kind == "num" and isinstance(v, str):
        try:
            d = Decimal(v)
            return int(d) if d == d.to_integral_value() else float(d)
        except InvalidOperation:
            return v
    if kind in ("str", None) and isinstance(v, int | float) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, list):
        return [_coerce(feature, x) for x in v]
    return v


def _value_ok(feature: str, op: str, v: Any) -> bool:
    if op == "exists":
        return v is None or isinstance(v, bool)
    if op in ("in", "nin"):
        return isinstance(v, list) and bool(v) and all(_scalar_ok(feature, x) for x in v)
    if op in ("lt", "le", "gt", "ge"):
        return FEATURE_KINDS.get(feature) == "num" and _scalar_ok(feature, v)
    return _scalar_ok(feature, v)


def _states_number(feature: str, v: Any, phrase: str) -> bool:
    """A numeric literal must be written in its grounding phrase (no invented or adjusted thresholds)."""
    vals = v if isinstance(v, list) else [v]
    nums = set(numbers_in(phrase))
    for x in vals:
        if not isinstance(x, int | float) or isinstance(x, bool):
            continue
        d = Decimal(str(x))
        if d in nums or (feature.endswith("_cents") and d / 100 in nums) or (
                feature.endswith("_min") and d / 60 in nums):
            continue
        return False
    return True


def _case_tag(v: Any) -> str | None:
    if isinstance(v, bool):
        return f"{CASE_PREFIX}{json.dumps(v)}"
    if isinstance(v, str):
        return v if v.startswith(CASE_PREFIX) else f"{CASE_PREFIX}{v}"
    return None


_STORM_ID = re.compile(r"^[A-Z]{4}@\d{4}-\d{2}-\d{2}$")


def case_context(question: Question, facts: Iterable[Fact]) -> dict[str, Any]:
    """DSL feature values the case facts state unambiguously, plus the cohort/storm the question is about."""
    seen: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if withheld(f):
            continue
        feat = f.field if f.field in cf.DSL_FEATURES else FIELD_TO_FEATURE.get(f.field)
        if feat:
            seen[feat].add(json.dumps(f.value, sort_keys=True, default=str))
    ctx: dict[str, Any] = {k: json.loads(next(iter(v))) for k, v in seen.items() if len(v) == 1}
    refs = question.case_refs
    if len(refs) == 1 and _STORM_ID.match(refs[0]):
        ctx["cohort" if "cohort" in question.pattern else "storm"] = refs[0]
    return dict(sorted(ctx.items()))


def _clauses(cond: Any) -> list[dict[str, Any]]:
    if isinstance(cond, Mapping):
        if "all" in cond or "any" in cond:
            return [c for x in cond.get("all", cond.get("any", [])) for c in _clauses(x)]
        if "not" in cond:
            return _clauses(cond["not"])
        if "f" in cond:
            return [dict(cond)]
    return []


def grounding_gaps(rule: Rule, ruling: Ruling | str) -> list[str]:
    """Literals of ``rule`` not covered by a verbatim ruling phrase (empty = fully grounded). A condition literal
    needs a grounding phrase found in the ruling (and a number must be written in it); a scope literal needs one too
    unless it is tagged ``case:`` (copied from the case, the rung ``widen`` removes); the action needs its phrase."""
    text = ruling if isinstance(ruling, str) else ruling_text(ruling)
    gaps: list[str] = []

    def covered(feature: str, v: Any) -> bool:
        phrase = rule.grounding.get(grounding_key(feature, v))
        return bool(phrase) and verbatim(phrase, text) is not None and _states_number(feature, v, phrase)

    for c in _clauses(rule.condition):
        if c.get("op") == "exists":
            continue
        if not covered(c["f"], c.get("v")):
            gaps.append(f"condition {c['f']} {c.get('op')} {json.dumps(c.get('v'))}")
    for k, v in rule.scope.items():
        if isinstance(v, str) and v.startswith(CASE_PREFIX):
            continue
        if not covered(k, v):
            gaps.append(f"scope {k}={json.dumps(v)}")
    act = rule.grounding.get(f"action={rule.action.value}")
    if not act or verbatim(act, text) is None:
        gaps.append(f"action {rule.action.value}")
    return gaps


@dataclass
class RuleDraftResult:
    rule: Rule
    record: LlmCallRecord | None
    draft: RuleDraft
    case_scoped: list[str] = field(default_factory=list)   # scope keys copied from the case (case:<v>)
    ungrounded: list[str] = field(default_factory=list)    # literals with no verifiable ruling phrase (the engine
    problems: list[str] = field(default_factory=list)      # flags them; they are never silently dropped)


@dataclass
class ChallengeResult:
    classification: str
    facts: list[Fact]
    source: Source
    record: LlmCallRecord | None
    llm_classification: str | None
    keyword_classification: str
    dropped: int = 0
    reason: str | None = None


_LEGAL_KW = re.compile(r"hidden\s+(?:manufactur\w*\s+)?defect|manufactur\w*|\bairbus\b|\bboeing\b|\bembraer\b|"
                       r"operator'?s?\s+notice|service\s+bulletin|airworthiness\s+directive|\bbatch\b|sabotage|"
                       r"security\s+(?:risk|threat|alert)|terroris", re.IGNORECASE)
_FACT_KW = re.compile(r"tech\s?log|\blogged\b|\bphoto|\breceipt|\battached\b|\bmetar\b|screenshot|\bdocument",
                      re.IGNORECASE)
_HIDDEN_DEFECT_SPAN = re.compile(r"hidden\s+(?:manufactur\w*\s+)?defect[^.;\n]*", re.IGNORECASE)
_RANK = {c: i for i, c in enumerate(CLASSES)}


def keyword_class(text: str) -> str:
    if _LEGAL_KW.search(text):
        return "new_legal_pattern"
    if _FACT_KW.search(text):
        return "new_fact"
    return "assertion"


_TAIL_RE = re.compile(r"\b[A-Z]{1,2}-[A-Z]{3,4}\b")
_ICAO_METAR_RE = re.compile(r"\b([A-Z]{4}) \d{6}Z\b")


def _tail_of(d: FlightDecision) -> str | None:
    for e in d.evidence:
        if e.field in ("flight.aircraft", "aog.tail") and isinstance(e.value, str):
            return e.value
    for e in d.evidence:
        m = _TAIL_RE.search(e.quote or "") or _TAIL_RE.search(e.source_id) or _TAIL_RE.search(e.fact_id)
        if m:
            return m.group(0)
    return None


def _station_of(d: FlightDecision) -> str | None:
    for e in d.evidence:
        m = _ICAO_METAR_RE.search(e.quote or "")
        if m:
            return m.group(1)
    return None


# ================================================================ the Drafter
class Drafter:
    """``DrafterAPI``. ``client`` defaults to an ``LlmClient`` that also reads the committed recordings in
    ``data/cache/demo/drafter/``; ``clock`` (a ``Clock`` or a callable) stamps challenge facts and sources."""

    def __init__(self, client: LlmClient | None = None, *, clock: Any = None, timeout_s: float | None = None):
        self.client = client if client is not None else LlmClient(read_dirs=[DEMO_CACHE_DIR, DRAFTER_DEMO_DIR])
        self._clock = clock
        self.timeout_s = timeout_s
        self.records: list[LlmCallRecord] = []
        self._by_draft: dict[str, LlmCallRecord] = {}
        self._memo: dict[str, tuple[str, LlmCallRecord | None, bool]] = {}
        self._issued: set[str] = set()
        self.stats: dict[str, int] = defaultdict(int)
        self.last_problems: list[str] = []

    # -- bookkeeping
    @property
    def pii_seen(self) -> int:
        """PII patterns in prompts actually sent (always 0: inputs are projected and redacted first)."""
        return self.stats["pii_seen"]

    def record_for(self, draft_id: str) -> LlmCallRecord | None:
        """The ``LlmCallRecord`` behind a draft (the server turns it into an ``llm_call`` commit)."""
        return self._by_draft.get(draft_id)

    def _now(self) -> datetime:
        c = self._clock
        if c is None:
            return datetime.now(UTC)
        return c.now() if hasattr(c, "now") else c()

    def _call(self, task: str, pv: str, user: str, schema: type[BaseModel] | None,
              input_fact_ids: Sequence[str] = ()) -> tuple[Any, LlmCallRecord]:
        leaks = pii_hits(user)
        if leaks:                                           # defence in depth: never send what redaction missed
            self.stats["pii_seen"] += len(leaks)
            raise LLMUnavailable("pii_in_prompt", f"{len(leaks)} PII pattern(s) left in the {task} prompt")
        self.stats["calls"] += 1
        try:
            out, rec = self.client.call(ROLE, system_prompt(task), [{"role": "user", "content": user}], schema,
                                        effort=EFFORT, prompt_version=pv, principal=PRINCIPAL,
                                        input_fact_ids=list(input_fact_ids), timeout_s=self.timeout_s)
        except LLMUnavailable as e:
            if e.record is not None:
                self.records.append(e.record)
            raise
        self.records.append(rec)
        return out, rec

    # -- prose pipeline: LLM → checks → template fallback
    def _prose(self, *, kind: str, draft_id: str, task: str, pv: str, user: str, evidence: Any, template: str,
               checks: Callable[[str], list[str]] | None = None, input_fact_ids: Sequence[str] = (),
               memo_key: str | None = None) -> Draft:
        problems: list[str] = []
        rec: LlmCallRecord | None = None
        text: str | None = None
        hit = self._memo.get(memo_key) if memo_key else None
        if hit is not None:
            text, rec, _ = hit
        else:
            try:
                raw, rec = self._call(task, pv, user, None, input_fact_ids)
                text = _clean(raw)
            except LLMUnavailable as e:
                rec = e.record
                problems.append(f"llm unavailable: {e.code}")
        if rec is not None:
            self._by_draft[draft_id] = rec
        if text is not None:
            if not text:
                problems.append("empty draft")
            ok, bad = verify_numbers(text, evidence)
            if not ok:
                problems.append("numbers not in evidence: " + ", ".join(bad))
            if pii_hits(text):
                problems.append("personal data in draft")
            if checks is not None:
                problems += checks(text)
            if memo_key and hit is None:
                self._memo[memo_key] = (text, rec, not problems)
            if not problems:
                self.last_problems = []
                return Draft(id=draft_id, kind=kind, text=text, numbers_verified=True, template_fallback=False)
        self.stats["template_fallbacks"] += 1
        self.last_problems = problems
        ok, _ = verify_numbers(template, evidence)
        return Draft(id=draft_id, kind=kind, text=template, numbers_verified=ok, template_fallback=True)

    # -- DrafterAPI: prose
    def explain(self, decision: FlightDecision, context: Mapping[str, Any] | None = None) -> Draft:
        """The "Why?" text for a decision. ``context`` adds evidence the decision does not carry (e.g. pax, STD,
        flights that operated); numbers may come from it too."""
        payload, n = decision_payload(decision)
        self.stats["pii_redacted"] += n
        blocks: list[tuple[str, Any]] = [("evidence", payload)]
        if context:
            blocks.append(("context", dict(context)))
        user = _message(blocks, "Explain this decision.")
        return self._prose(kind="explanation", draft_id=f"DRAFT-{decision.flight_id}-explanation", task="explain",
                           pv=PV_EXPLAIN, user=user, evidence=[payload, context or {}],
                           template=explain_template(decision),
                           input_fact_ids=[e.fact_id for e in decision.evidence])

    def je_memo(self, je: JournalEntry) -> Draft:
        payload = je_payload(je)

        def checks(text: str) -> list[str]:
            return [] if "drafted, pending approval" in text.lower() else ["missing 'drafted, pending approval'"]

        user = _message([("evidence", payload)], "Write the memo for this journal entry.")
        return self._prose(kind="je_memo", draft_id=f"DRAFT-{je.id}-je_memo", task="je_memo", pv=PV_JE_MEMO,
                           user=user, evidence=payload, template=je_memo_template(payload), checks=checks)

    def challenge_reply(self, decision: FlightDecision, classification: str, cited: list[Evidence], *,
                        decision_stands: bool = True) -> Draft:
        cls = classification if classification in CLASSES else "assertion"
        dp, n = decision_payload(decision)
        cited_p = []
        for e in cited:
            item, k = _evidence_item(e)
            cited_p.append(item)
            n += k
        self.stats["pii_redacted"] += n
        compact = {k: dp[k] for k in ("flight", "flight_id", "cause", "extraordinary", "recode_label", "reason",
                                      "confidence", "legal_basis")}
        payload = {"decision": compact, "classification": cls, "decision_stands": decision_stands,
                   "next_step": NEXT_STEP[cls], "cited": cited_p}
        lead = DECISION_STANDS if decision_stands else "Decision under review."

        def checks(text: str) -> list[str]:
            return [] if text.startswith(lead) else [f"does not start with {lead!r}"]

        user = _message([("evidence", payload)], "Write the reply to this challenge.")
        return self._prose(kind="challenge_reply", draft_id=f"DRAFT-{decision.flight_id}-challenge_reply-"
                                                            f"{_h(cls, cited_p, decision_stands, n=8)}",
                           task="challenge_reply", pv=PV_CHALLENGE_REPLY, user=user, evidence=payload,
                           template=challenge_reply_template(cls, cited_p, decision_stands), checks=checks,
                           input_fact_ids=[e.fact_id for e in cited])

    def rights_notice(self, ent: Entitlement, *, corrects: str | None = None, cause: str | None = None) -> Draft:
        """The Art. 14(2) written notice, drafted with zero PII. ``corrects`` is an earlier wrong message to correct
        (e.g. the CRM bot's "weather, no compensation" e-mail); ``cause`` is the engine's cause in plain words.
        Merge names with ``merge_letter`` afterwards."""
        payload, n = rights_payload(ent, corrects, cause)
        self.stats["pii_redacted"] += n
        law = list(LEGAL_EU261)

        def checks(text: str) -> list[str]:
            probs = []
            found = set(re.findall(r"\{\{\w+\}\}", text))
            if "{{passenger_name}}" not in found:
                probs.append("missing {{passenger_name}}")
            if found - set(PLACEHOLDERS):
                probs.append("unknown placeholders " + ", ".join(sorted(found - set(PLACEHOLDERS))))
            if "261/2004" not in text:
                probs.append("does not name Regulation (EC) No 261/2004")
            if re.search(r"€\s?0+(?:[.,]0+)?(?![\d]|[.,]\d)", text):
                probs.append("says €0 (use the weather wording)")
            if payload["status"] == "no_compensation" and WEATHER_PHRASE not in text.lower():
                probs.append(f"missing {WEATHER_PHRASE!r}")
            if payload["status"] == "owed" and payload["compensation"] and payload["compensation"] not in text:
                probs.append(f"does not state {payload['compensation']}")
            return probs

        blocks: list[tuple[str, Any]] = [("evidence", {k: v for k, v in payload.items() if k != "corrects"}),
                                         ("law", law)]
        if payload["corrects"]:
            blocks.append(("corrects", payload["corrects"]))
        user = _message(blocks, "Draft the rights notice for this entitlement.")
        return self._prose(kind="rights_notice", draft_id=f"DRAFT-{ent.coupon_id}-rights_notice",
                           task="rights_notice", pv=PV_RIGHTS, user=user, evidence=[payload, law],
                           template=rights_notice_template(payload), checks=checks,
                           memo_key="rights:" + _h(user, n=32))

    def rights_notices(self, ents: Iterable[Entitlement], *, corrects: str | None = None,
                       cause: str | None = None) -> list[Draft]:
        """One draft per entitlement; identical (PII-free) entitlements share one LLM call."""
        return [self.rights_notice(e, corrects=corrects, cause=cause) for e in ents]

    # -- DrafterAPI: rules
    def propose_rule(self, ruling: Ruling, question: Question, case_facts: list[Fact], *,
                     rule_id: str | None = None, existing_ids: Iterable[str] = ()) -> Rule:
        return self.draft_rule(ruling, question, case_facts, rule_id=rule_id, existing_ids=existing_ids).rule

    def _next_id(self, role: Role, existing_ids: Iterable[str]) -> str:
        prefix = ID_PREFIX[role]
        used = {i.split("@")[0] for i in [*existing_ids, *self._issued]}
        nums = [int(m.group(1)) for i in used if (m := re.fullmatch(re.escape(prefix) + r"-(\d+)", i))]
        return f"{prefix}-{max(nums, default=0) + 1}"

    def draft_rule(self, ruling: Ruling, question: Question, case_facts: Sequence[Fact], *,
                   rule_id: str | None = None, existing_ids: Iterable[str] = ()) -> RuleDraftResult:
        """``propose_rule`` with everything the checks found (case-scoped keys, ungrounded literals, problems).
        Raises ``RuleAuthorityError`` for a non-ruling role and ``LLMUnavailable`` when no draft can be made."""
        role = ruling.author_role
        if role not in TIER_OF_ROLE:
            raise RuleAuthorityError(f"{role.value} may not author rules (only claims_lead, legal, controller)")
        text = ruling_text(ruling)
        ctx = case_context(question, case_facts)
        facts_seen, held = [], 0
        for f in case_facts:
            if withheld(f):
                held += 1
                continue
            value = redact(f.value)[0] if isinstance(f.value, str) else f.value
            facts_seen.append({"subject": f.subject, "field": f.field, "value": value})
        facts_seen = sorted({_dump(x): x for x in facts_seen}.values(), key=_dump)
        self.stats["pii_withheld"] += held
        ruling_p = {"author_role": role.value, "kind": ruling.kind, "decision": redact(ruling.decision)[0],
                    "explanation": redact(ruling.explanation)[0]}
        question_p = {k: redact(getattr(question, k))[0] for k in ("pattern", "title", "found", "why_flagged",
                                                                     "recommends", "recommended_option")}
        question_p["options"] = [redact(o)[0] for o in question.options]
        question_p["case_refs"] = list(question.case_refs)
        user = _message([("ruling", ruling_p), ("question", question_p), ("case", {"context": ctx,
                                                                                   "facts": facts_seen})],
                        "Draft the rule this ruling makes.")
        draft, rec = self._call("rule", PV_RULE, user, RuleDraft, [f.id for f in case_facts if not withheld(f)])
        rid = rule_id or self._next_id(role, existing_ids)
        res = self._build_rule(draft, rec, ruling, question, ctx, text, rid)
        self._issued.add(rid)
        self.last_problems = res.problems + [f"ungrounded {u}" for u in res.ungrounded]
        return res

    def _build_rule(self, draft: RuleDraft, rec: LlmCallRecord | None, ruling: Ruling, question: Question,
                    ctx: Mapping[str, Any], text: str, rid: str) -> RuleDraftResult:
        grounding: dict[str, str] = {}
        clauses: list[dict[str, Any]] = []
        scope: dict[str, Any] = {}
        case_scoped: list[str] = []
        ungrounded: list[str] = []
        problems: list[str] = []

        def to_case_scope(key: str, v: Any) -> bool:
            if key in _SINGLE_CASE_KEYS:
                problems.append(f"dropped single-case scope {key}")
                return True
            cv = ctx.get(key, v)                            # the case's own value wins over the model's
            tag = _case_tag(cv)
            if tag is None or not _scalar_ok(key, cv):
                return False
            scope[key] = tag
            case_scoped.append(key)
            return True

        for c in draft.condition:
            try:
                v = _coerce(c.feature, json.loads(c.value_json)) if c.value_json.strip() else None
            except json.JSONDecodeError:
                problems.append(f"condition {c.feature}: value {c.value_json!r} is not JSON")
                continue
            if not _value_ok(c.feature, c.op, v):
                problems.append(f"condition {c.feature} {c.op} {v!r}: wrong value type")
                continue
            clause = {"f": c.feature, "op": c.op} if c.op == "exists" and v is None else \
                {"f": c.feature, "op": c.op, "v": v}
            phrase = verbatim(c.phrase, text)
            if c.op == "exists" or (phrase and _states_number(c.feature, v, phrase)):
                if c.op != "exists":
                    grounding[grounding_key(c.feature, v)] = phrase  # type: ignore[assignment]
                clauses.append(clause)
            elif c.op == "eq" and isinstance(v, bool | str) and to_case_scope(c.feature, v):
                problems.append(f"{c.feature}={json.dumps(v)} is not stated in the ruling: copied from the case")
            else:
                clauses.append(clause)                      # kept, and flagged: the engine's checks fail it
                ungrounded.append(f"{c.feature} {c.op} {json.dumps(v)}")
        in_condition = {c["f"] for c in clauses}
        for s in draft.scope:
            if s.key in in_condition or s.key in scope:
                continue
            try:
                v = _coerce(s.key, json.loads(s.value_json))
            except json.JSONDecodeError:
                problems.append(f"scope {s.key}: value {s.value_json!r} is not JSON")
                continue
            if s.key in cf.SCOPE_CONTEXT_KEYS:
                if not isinstance(v, str) or not to_case_scope(s.key, v):
                    problems.append(f"scope {s.key}: needs an id")
                continue
            if not _scalar_ok(s.key, v):
                problems.append(f"scope {s.key}={v!r}: wrong value type")
                continue
            phrase = verbatim(s.phrase, text)
            if phrase and _states_number(s.key, v, phrase):
                scope[s.key] = v
                grounding[grounding_key(s.key, v)] = phrase
            elif not to_case_scope(s.key, v):
                problems.append(f"scope {s.key}={v!r}: numeric context is not copied from the case")
        action = RuleAction(draft.action)
        act_phrase = verbatim(draft.action_phrase, text)
        if act_phrase:
            grounding[f"action={action.value}"] = act_phrase
        else:
            ungrounded.append(f"action {action.value}")
        arg = draft.action_arg if action == RuleAction.ROUTE_TO else None
        if action == RuleAction.ROUTE_TO and arg is None:
            problems.append("route_to without an internal role")
        role = ruling.author_role
        title = _ws(ruling.decision)
        rule = Rule(
            id=rid, version=1, kind=KIND_OF_ACTION[action],  # type: ignore[arg-type]
            scope=dict(sorted(scope.items())), condition={draft.match: clauses}, action=action, action_arg=arg,
            tier=TIER_OF_ROLE[role], authority_required=role,  # type: ignore[arg-type]
            origin_ruling_id=ruling.id, origin_example=question.case_refs[0] if question.case_refs else None,
            grounding=grounding, valid_from=ruling.at if role == Role.CONTROLLER else None,
            recorded_at=ruling.at, status="proposed",
            title=title if len(title) <= 240 else title[:237].rsplit(" ", 1)[0] + "…")
        return RuleDraftResult(rule, rec, draft, case_scoped, ungrounded, problems)

    # -- DrafterAPI: challenges
    def challenge_source(self, decision: FlightDecision, text: str, received_at: datetime | None = None) -> Source:
        """The tier-4 ``Source`` a challenge's facts point at."""
        return Source(id=f"SRC-CHALLENGE-{decision.flight_id}-{_h(text)}", kind=SourceKind.CHALLENGE,
                      title=f"Challenge to {_num(decision.flight_id)}", text=text,
                      sha256=hashlib.sha256(text.encode()).hexdigest(), received_at=received_at or self._now(),
                      trust_tier=CHALLENGE_TIER, acl_tags=[])

    def classify_challenge(self, decision: FlightDecision, text: str) -> tuple[str, list[Fact]]:
        res = self.classify_challenge_detailed(decision, text)
        return res.classification, res.facts

    def classify_challenge_detailed(self, decision: FlightDecision, text: str) -> ChallengeResult:
        now = self._now()
        src = self.challenge_source(decision, text, now)
        h = _h(text)
        sent, n = redact(text)
        self.stats["pii_redacted"] += n
        dp, k = decision_payload(decision)
        self.stats["pii_redacted"] += k
        compact = {key: dp[key] for key in ("flight", "flight_id", "cause", "extraordinary", "recode_label",
                                            "reason", "evidence", "rules_applied", "legal_basis")}
        allowed = {f: cf.get(f).description for f in CHALLENGE_FIELDS}
        user = _message([("evidence", {"decision": compact, "allowed_fact_fields": allowed}),
                         ("challenge", sent)], "Classify this challenge and list the facts it states.")
        kw = keyword_class(text)
        base = Fact(id=f"F-CH-{decision.flight_id}-{h}-0", source_id=src.id, subject=f"flight:{decision.flight_id}",
                    field="challenge.text", value=text, span=text, extractor="verbatim@1", recorded_at=now)
        facts: list[Fact] = [base]
        dropped = 0
        llm_cls: str | None = None
        reason: str | None = None
        rec: LlmCallRecord | None = None
        try:
            out, rec = self._call("classify", PV_CLASSIFY, user, ChallengeDraft,
                                  [e.fact_id for e in decision.evidence])
            llm_cls, reason = out.classification, out.reason
            extractor = f"llm:{rec.model or MODEL}@{PV_CLASSIFY}"
            for i, fd in enumerate(out.facts, start=1):
                fact = self._challenge_fact(decision, fd.field, fd.value_json, fd.span, sent, text, src, h, i,
                                            extractor, now)
                if fact is None:
                    dropped += 1
                else:
                    facts.append(fact)
        except LLMUnavailable as e:
            rec = e.record
            m = _HIDDEN_DEFECT_SPAN.search(text)
            if m:
                fact = self._challenge_fact(decision, "manufacturer.hidden_defect", "true", m.group(0).strip(), text,
                                            text, src, h, 1, "fallback:keywords@1", now)
                if fact is not None:
                    facts.append(fact)
        cls = max([c for c in (llm_cls, kw) if c in _RANK], key=_RANK.__getitem__)
        return ChallengeResult(cls, facts, src, rec, llm_cls, kw, dropped, reason)

    def _challenge_fact(self, d: FlightDecision, fname: str, value_json: str, span: str, sent: str, original: str,
                        src: Source, h: str, i: int, extractor: str, now: datetime) -> Fact | None:
        try:
            v = json.loads(value_json)
        except json.JSONDecodeError:
            return None
        if not cf.is_registered(fname) or not cf.check_value(fname, v):
            return None
        sp = verbatim(span, sent)
        if sp is None or verbatim(sp, original) is None:
            return None
        spec = cf.get(fname)
        ok, _why = cp.verify(fname, v, sp, _ws(sent), ref=d.known_at)
        if not ok:
            return None
        if spec.parse is None and spec.type == "str" and str(v).lower() not in sp.lower():
            return None
        subject = f"flight:{d.flight_id}"
        if spec.subject == "aircraft" and (tail := _tail_of(d)):
            subject = f"aircraft:{tail}"
        elif spec.subject == "station" and (icao := _station_of(d)):
            subject = f"station:{icao}"
        return Fact(id=f"F-CH-{d.flight_id}-{h}-{i}", source_id=src.id, subject=subject, field=fname, value=v,
                    span=sp, extractor=extractor, recorded_at=now)


# ================================================================ demo scenarios and recordings
@dataclass
class Scenario:
    name: str
    method: str
    args: dict[str, Any]
    response: dict[str, Any]
    note: str = ""


_ARG_TYPES: dict[str, dict[str, Any]] = {
    "explain": {"decision": FlightDecision},
    "rights_notice": {"ent": Entitlement},
    "je_memo": {"je": JournalEntry},
    "challenge_reply": {"decision": FlightDecision, "cited": list[Evidence]},
    "classify_challenge": {"decision": FlightDecision},
    "propose_rule": {"ruling": Ruling, "question": Question, "case_facts": list[Fact]},
}


def load_scenarios(path: Path = SCENARIOS_FILE) -> dict[str, Scenario]:
    """The demo inputs (plan §1.2–1.4) and their hand-written responses, from ``scenarios.json``."""
    from pydantic import TypeAdapter

    data = json.loads(path.read_text(encoding="utf-8"))
    objects = data.get("objects", {})
    out: dict[str, Scenario] = {}
    for name, s in data["scenarios"].items():
        args: dict[str, Any] = {}
        for k, v in s["args"].items():
            if isinstance(v, str) and v.startswith("@"):
                v = objects[v[1:]]
            t = _ARG_TYPES[s["method"]].get(k)
            args[k] = TypeAdapter(t).validate_python(v) if t is not None else v
        out[name] = Scenario(name, s["method"], args, s["response"], s.get("note", ""))
    return out


def run_scenario(drafter: Drafter, s: Scenario) -> Any:
    return getattr(drafter, s.method)(**s.args)


RECORDED_AT = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)


def record_demo(*, live: bool = False, out_dir: Path = DRAFTER_DEMO_DIR, names: Sequence[str] | None = None,
                scenarios: Mapping[str, Scenario] | None = None) -> dict[str, str]:
    """(Re)write the Drafter's demo recordings into ``out_dir`` and return ``{scenario: cache key}``.

    Without ``live`` the responses are the hand-written ones in ``scenarios.json`` (``provenance: hand-written``),
    sent through the real prompt builders so the cache keys are exactly the ones production computes. With ``live``
    (needs ``ANTHROPIC_API_KEY``) the real API answers instead.
    """
    sc = dict(scenarios if scenarios is not None else load_scenarios())
    if names:
        sc = {k: v for k, v in sc.items() if k in names}
    current: dict[str, Any] = {}

    def respond(req: Any) -> RawResponse:
        r = current["response"]
        parsed = r.get("parsed")
        text = r.get("text") if parsed is None else json.dumps(parsed, ensure_ascii=False)
        return RawResponse(model=MODEL, request_id="hand-written", message_id="hand-written",
                           stop_reason="end_turn", stop_details=None, text=text or "", parsed=parsed, usage={})

    backend = AnthropicBackend() if live else ScriptedBackend(respond, provenance="hand-written")
    out_dir.mkdir(parents=True, exist_ok=True)
    keys: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        # live spend is tracked in the persistent cache dir, so the dollar cap holds across runs
        work = DEFAULT_CACHE_DIR if live else Path(tmp)
        client = LlmClient(mode="live", cache_dir=work, read_dirs=[], backend=backend,
                           clock=(lambda: RECORDED_AT) if not live else None)
        drafter = Drafter(client=client, clock=lambda: RECORDED_AT)
        for name, s in sc.items():
            current["response"] = s.response
            n = len(drafter.records)
            try:
                run_scenario(drafter, s)
            except LLMUnavailable:
                pass
            if len(drafter.records) > n:
                keys[name] = drafter.records[-1].prompt_hash
        for name, key in keys.items():
            src = work / f"{key}.json"
            if src.exists():
                shutil.copyfile(src, out_dir / f"{key}.json")
    if names is None:
        for p in out_dir.glob("*.json"):
            if p.name not in (SCENARIOS_FILE.name, MANIFEST_FILE.name) and p.stem not in keys.values():
                p.unlink()
        (out_dir / MANIFEST_FILE.name).write_text(_dump(dict(sorted(keys.items()))) + "\n", encoding="utf-8")
    return keys


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Rewrite the Drafter's demo recordings (data/cache/demo/drafter/).")
    ap.add_argument("--live", action="store_true", help="call the real API (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--out-dir", type=Path, default=DRAFTER_DEMO_DIR,
                    help="write the recordings here instead (e.g. a scratch dir to review live output first)")
    ap.add_argument("names", nargs="*", help="only these scenarios")
    a = ap.parse_args()
    for k, v in record_demo(live=a.live, out_dir=a.out_dir, names=a.names or None).items():
        print(f"{k}: {v}")
