"""D4 · Rules: precedence, conflicts, authority, hard-control screening, grounding, immutable versions.

Rules come only from mined history, rulings, rejections and regulation versions; there is no rule editor.
- **Precedence:** hard_control > regulation > legal > controller > claims_lead > mined, then specificity
  (constrained scope keys + condition clauses), then ``recorded_at`` (``engine.dsl.precedence_key``).
- **Conflicts:** two applicable rules of equal tier and specificity with opposite actions are a conflict: nothing
  is applied and the case is escalated (``checks.no_conflict = False`` on a proposal that would create one).
- **Authority:** claims_lead → voucher/claim rules · legal → cause/extraordinary rules · controller →
  release/estimate rules · nobody → a rule that touches a hard control. Statutory floor: only Legal may lower
  EU261 compensation below the Regulation's own amount (e.g. an offset without Art. 7(3) signed acceptance).
- **Grounding:** every literal in ``condition`` AND ``scope`` must map to a phrase in the ruling. Ungrounded scope
  keys are copied from the case as ``case:<v>``; an ungrounded condition literal is flagged.
- **Versions** are immutable; status and ``times_cited`` are views over events (``RuleBook``).
Pure: no wall clock, no randomness.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from contracts.models import Role, Rule, RuleAction, Ruling
from engine import dsl
from engine.controls import hard_controls_touched

# ---------- authority ----------

ACTION_AUTHORITY: dict[RuleAction, Role | None] = {
    RuleAction.SET_EXTRAORDINARY: Role.LEGAL,
    RuleAction.SET_NOT_EXTRAORDINARY: Role.LEGAL,
    RuleAction.ALLOW_OFFSET: Role.LEGAL,             # statutory floor: offsets compensation without Art. 7(3) consent
    RuleAction.DENY_OFFSET: Role.CLAIMS_LEAD,
    RuleAction.DENY_RELEASE: Role.CONTROLLER,
    RuleAction.KEEP_TAIL: Role.CONTROLLER,
    RuleAction.APPLY_7_2_REDUCTION: Role.CLAIMS_LEAD,  # within the statute (the engine enforces the 7(2) limits)
    RuleAction.ROUTE_TO: None,                       # by kind
}
KIND_AUTHORITY: dict[str, Role] = {
    "cause": Role.LEGAL, "entitlement": Role.LEGAL, "regime": Role.LEGAL, "voucher": Role.CLAIMS_LEAD,
    "release": Role.CONTROLLER, "routing": Role.CONTROLLER, "mined_policy": Role.CLAIMS_LEAD,
}
TIER_OF_ROLE = {Role.LEGAL: "legal_ruling", Role.CONTROLLER: "controller_ruling",
                Role.CLAIMS_LEAD: "claims_lead_ruling"}
RULE_AUTHORS = frozenset(TIER_OF_ROLE)
LOWERS_COMPENSATION = frozenset({RuleAction.SET_EXTRAORDINARY, RuleAction.ALLOW_OFFSET})
OPPOSITE = {
    RuleAction.SET_EXTRAORDINARY: RuleAction.SET_NOT_EXTRAORDINARY,
    RuleAction.SET_NOT_EXTRAORDINARY: RuleAction.SET_EXTRAORDINARY,
    RuleAction.ALLOW_OFFSET: RuleAction.DENY_OFFSET,
    RuleAction.DENY_OFFSET: RuleAction.ALLOW_OFFSET,
}
INTERNAL_ROUTES = frozenset({"claims_lead", "legal", "controller", "ops"})


def required_role(rule: Rule) -> Role:
    return ACTION_AUTHORITY.get(rule.action) or KIND_AUTHORITY.get(rule.kind, Role.LEGAL)


def authority_problems(rule: Rule, author_role: Role | None) -> list[str]:
    """Why ``author_role`` may not author ``rule`` (empty = allowed). Mined rules have no human author."""
    if rule.tier == "mined":
        return [] if rule.action == RuleAction.APPLY_7_2_REDUCTION or rule.kind == "mined_policy" else [
            "mined rules may only carry mined policy"]
    if rule.tier in ("hard_control", "regulation"):
        return [f"no ruling can author a {rule.tier} rule (code / regulation versions only)"]
    if author_role not in RULE_AUTHORS:
        return [f"{getattr(author_role, 'value', author_role)} may not author rules"]
    need = required_role(rule)
    probs = []
    if author_role != need:
        probs.append(f"{rule.action.value} needs {need.value}, not {author_role.value}")
    if TIER_OF_ROLE[author_role] != rule.tier:
        probs.append(f"tier {rule.tier} does not match the author's tier {TIER_OF_ROLE[author_role]}")
    if rule.action in LOWERS_COMPENSATION and author_role != Role.LEGAL:
        probs.append("statutory floor: only Legal may lower EU261 compensation")
    return probs


def hard_control_problems(rule: Rule, ruling: Ruling | None = None) -> list[str]:
    """A rule may never touch a hard control (SoD, payouts, locked periods, materiality, external approvals)."""
    probs = []
    if rule.tier == "hard_control":
        probs.append("hard controls are code, not rules")
    if rule.action == RuleAction.ROUTE_TO and (rule.action_arg or "") not in INTERNAL_ROUTES:
        probs.append(f"routes to {rule.action_arg!r}: external parties never satisfy an internal approval")
    texts = [rule.title or "", json.dumps(rule.scope, default=str), json.dumps(rule.condition, default=str)]
    if ruling is not None:
        texts += [ruling.decision, ruling.explanation]
    for c in hard_controls_touched(" ".join(texts)):
        probs.append(f"touches hard control {c}")
    return list(dict.fromkeys(probs))


# ---------- conflicts ----------

def scopes_overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    for k in set(a) & set(b):
        va, vb = dsl.strip_case(a[k]), dsl.strip_case(b[k])
        if not isinstance(va, list) and not isinstance(vb, list) and va != vb:
            return False
    return True


def conflicts_with(rule: Rule, rules: Iterable[Rule]) -> list[Rule]:
    """Active rules of the same tier with the opposite action whose scopes can overlap."""
    opp = OPPOSITE.get(rule.action)
    if opp is None:
        return []
    return sorted((r for r in rules if r.id != rule.id and r.status == "active" and not r.static_card
                   and r.tier == rule.tier and r.action == opp and scopes_overlap(rule.scope, r.scope)),
                  key=lambda r: (r.id, r.version))


@dataclass(frozen=True)
class Resolution:
    rule: Rule | None                 # the rule to apply (None when nothing applies or on conflict)
    hits: tuple[Rule, ...]            # every applicable rule, strongest first
    conflict: tuple[Rule, ...] = ()   # equal-tier, equal-specificity rules with opposite actions

    @property
    def conflicted(self) -> bool:
        return bool(self.conflict)


def resolve(rules: Iterable[Rule], feats: Mapping[str, Any], *, actions: Iterable[RuleAction] | None = None,
            tiers: Iterable[str] | None = None, known_at: datetime | None = None,
            flight_date: date | None = None) -> Resolution:
    """The strongest applicable rule, or a conflict. Independent of the order of ``rules``."""
    allowed = None if tiers is None else set(tiers)
    hits = [r for r in dsl.matching(rules, feats, actions=actions, known_at=known_at, flight_date=flight_date)
            if allowed is None or r.tier in allowed]
    if not hits:
        return Resolution(None, ())
    top = hits[0]
    rank = (dsl.TIER_RANK.get(top.tier, 0), dsl.specificity(top))
    rivals = tuple(r for r in hits[1:] if (dsl.TIER_RANK.get(r.tier, 0), dsl.specificity(r)) == rank
                   and OPPOSITE.get(r.action) == top.action)
    if rivals:
        return Resolution(None, tuple(hits), (top, *rivals))
    return Resolution(top, tuple(hits))


# ---------- grounding ----------

_NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
              10: "ten", 12: "twelve", 14: "fourteen", 18: "eighteen", 24: "twenty-four"}

_INSIDE_EVENT = (r"\binside (?:the |its )?(?:[\w-]+ )?(?:outage |event )?window\b|"
                 r"\bin the (?:[\w-]+ )?(?:outage|event) window\b|\bduring the (?:outage|blackout)\b")
LEXICON: dict[tuple[str, Any], str] = {
    ("voucher.signed", False): r"\bno signed acceptance\b|\bunsigned\b|\bnot signed\b|\bno signature\b|"
                               r"\bwithout (?:a )?signature\b|\bwithout signed acceptance\b|\bno signed\b",
    ("voucher.signed", True): r"\bsigned acceptance\b|\bsigned\b",
    ("voucher.in_lieu", True): r"\bin lieu(?: of compensation)?\b|\bthe voucher\b|\bvouchers?\b",
    ("flight.departs_eu", True): r"\bleaving the EU\b|\bdepart(?:s|ing|ures?)? (?:from )?the EU\b|"
                                 r"\bEU departures?\b|\bfrom the EU\b|\bout of the EU\b",
    ("flight.departs_eu", False): r"\bnot (?:depart|leav)\w* the EU\b|\boutside the EU\b|\binto the EU\b",
    ("flight.arrives_eu", True): r"\b(?:arriv\w*|into) (?:in(?:to)? )?the EU\b",
    ("flight.is_return_sector", True): r"\breturn sectors?\b|\breturn legs?\b|\breturns?\b",
    ("rotation.prev_cancelled", True): r"\b(?:storm-)?cancelled rotation\b|\bcancelled (?:outbound|rotation)\b|"
                                       r"\bprevious rotation\b|\boutbound (?:was )?cancelled\b",
    ("rotation.prev_cause", "weather"): r"\bstorm\b|\bweather\b",
    ("pax.reroute_earliest_offered", True): r"\b(?:offered )?(?:the )?earliest re-?route[\w ]*?\b",
    ("cohort.limitation_expired", False): r"\buntil the (?:six-year |6-year )?limitation\b|"
                                          r"\bbefore (?:the )?limitation\b",
    ("cohort.limitation_expired", True): r"\b(?:after|at) (?:the )?limitation\b|\blimitation (?:has )?expired\b",
    ("sources.disagree", True): r"\bsources disagree\b|\bdisagree\b",
    ("aog.root_cause_internal", True): r"\binternal\b|\bown aircraft\b",
    ("aog.root_cause_internal", False): r"\bexternal\b|\boutside (?:the carrier'?s|its) control\b",
    ("event.kind", "grid_outage"): r"\bgrid outage\b|\bblackout\b|\bpower (?:cut|outage|failure)\b|\boutage\b",
    ("flight.in_event_window_dep", "in"): _INSIDE_EVENT,
    ("flight.in_event_window_arr", "in"): _INSIDE_EVENT,
}
NUMERIC_UNITS: dict[str, str] = {
    "spare.available_within_h": r"(?:within )?{n} ?h(?:ours?)?(?: of STD)?|{w} hours?",
    "cohort.age_months": r"\bM{n}\b|{n} months?|{w} months?",
    "cohort.months_since_last_claim": r"{n} months?|{w} months?",
    "pax.notice_days": r"{n} days?|{w} days?",
    "pax.arrival_delay_min": r"{n} ?min(?:utes)?|{h} ?h(?:ours?)?",
    "flight.distance_km": r"{n:,} ?km|{n} ?km",
    "flight.window_margin_min": r"{n} ?min(?:utes)?",
    "flight.band_eur": r"€ ?{n}\b|{n} ?(?:EUR|euros?)",
    "voucher.amount_cents": r"€ ?{e}\b",
    "claim.age_months": r"{n} months?",
}
ACTION_LEXICON: dict[RuleAction, str] = {
    RuleAction.DENY_OFFSET: r"\bno offset\b|\bnot offset\b|\bdo not offset\b|\bpay (?:the )?(?:€ ?\d+ )?cash\b",
    RuleAction.ALLOW_OFFSET: r"\boffset (?:the voucher|it)\b|\bmay offset\b|\bcounts? (?:as|towards)\b",
    RuleAction.SET_EXTRAORDINARY: r"\bis extraordinary\b|\bextraordinary\b",
    RuleAction.SET_NOT_EXTRAORDINARY: r"\bnot extraordinary\b|\bis not extraordinary\b",
    RuleAction.KEEP_TAIL: r"\bnever release the tail\b|\bkeep (?:the )?(?:expected )?tail\b|\bkeep\b",
    RuleAction.DENY_RELEASE: r"\bnever release\b|\bdo not release\b|\bno release\b",
    RuleAction.APPLY_7_2_REDUCTION: r"\b50 ?%|\breduc\w+\b|\bhalf\b",
    RuleAction.ROUTE_TO: r"\broute\w*\b|\bsend\b|\bask\b",
}


def _num_pattern(feature: str, n: float) -> str:
    ni = int(n) if float(n).is_integer() else n
    tmpl = NUMERIC_UNITS.get(feature, r"\b{n}\b")
    h = (n / 60) if feature == "pax.arrival_delay_min" else n
    hi = int(h) if float(h).is_integer() else round(h, 2)
    e = int(n // 100) if feature == "voucher.amount_cents" else ni
    w = _NUM_WORDS.get(int(n), str(ni)) if float(n).is_integer() else str(ni)
    try:
        return tmpl.format(n=ni, w=w, h=hi, e=e)
    except (ValueError, TypeError):
        return rf"\b{re.escape(str(ni))}\b"


def find_phrase(feature: str, value: Any, text: str) -> str | None:
    """The verbatim phrase of ``text`` that states ``feature = value``, if any."""
    pat = LEXICON.get((feature, value))
    if pat is None and isinstance(value, bool):
        leaf = feature.split(".")[-1].replace("_", " ")
        pat = (r"\bnot? " if value is False else r"\b") + re.escape(leaf) + r"\b"
    if pat is None and isinstance(value, int | float) and not isinstance(value, bool):
        pat = _num_pattern(feature, value)
    if pat is None and isinstance(value, str):
        alts = {value, value.replace("_", " ")}
        pat = "|".join(rf"\b{re.escape(a)}\b" for a in sorted(alts))
    if pat is None and isinstance(value, list):
        hits = [find_phrase(feature, v, text) for v in value]
        return "; ".join(h for h in hits if h) if all(hits) else None
    if pat is None:
        return None
    m = re.search(pat, text, re.I)
    return m.group(0).strip() if m else None


def grounding_key(feature: str, value: Any) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(int(value) if float(value).is_integer() else value)
    return f"{feature}={json.dumps(value)}" if not isinstance(value, str) else f"{feature}={value}"


@dataclass
class Grounded:
    rule: Rule                                   # with ungrounded scope keys rewritten to case:<v>
    grounding: dict[str, str] = field(default_factory=dict)
    ungrounded_condition: list[str] = field(default_factory=list)
    case_scoped: list[str] = field(default_factory=list)
    action_grounded: bool = True

    @property
    def grounded(self) -> bool:
        return not self.ungrounded_condition and self.action_grounded


def ground(rule: Rule, ruling_text: str, case_feats: Mapping[str, Any] | None = None) -> Grounded:
    case_feats = case_feats or {}
    grounding: dict[str, str] = dict(rule.grounding)
    ungrounded: list[str] = []
    scope: dict[str, Any] = {}
    case_scoped: list[str] = []
    for k, v in rule.scope.items():
        if isinstance(v, str) and v.startswith(dsl.CASE_PREFIX):
            scope[k] = v
            case_scoped.append(k)
            continue
        phrase = find_phrase(k, v, ruling_text) if k in dsl.FEATURES else None
        if phrase:
            grounding[grounding_key(k, v)] = phrase
            scope[k] = v
        else:
            cv = case_feats.get(k, v)
            scope[k] = f"{dsl.CASE_PREFIX}{json.dumps(cv) if isinstance(cv, bool) else cv}"
            case_scoped.append(k)
    for c in dsl.clauses(rule.condition):
        if c.get("op") == "exists":
            continue
        f, v = c["f"], c.get("v")
        key = grounding_key(f, v)
        if key in grounding:
            continue
        phrase = find_phrase(f, v, ruling_text)
        if phrase:
            grounding[key] = phrase
        else:
            ungrounded.append(f"{f} {c['op']} {json.dumps(v)}")
    act = re.search(ACTION_LEXICON.get(rule.action, r"$^"), ruling_text, re.I)
    if act:
        grounding[f"action={rule.action.value}"] = act.group(0).strip()
    new = rule.model_copy(update={"scope": scope, "grounding": grounding})
    return Grounded(new, grounding, ungrounded, case_scoped, act is not None)


# ---------- checks for a proposal ----------

def compile_problems(rule: Rule) -> list[str]:
    return dsl.validate(rule.condition) + dsl.validate_scope(rule.scope)


def reproduces(rule: Rule, case_feats: Mapping[str, Any]) -> bool:
    """The rule fires on the case it came from (scope incl. case: values, and condition)."""
    if compile_problems(rule):
        return False
    return dsl.scope_matches(rule.scope, case_feats) and dsl.evaluate(rule.condition, case_feats)


def checks(rule: Rule, *, author_role: Role | None, ruling: Ruling | None, case_feats: Mapping[str, Any] | None,
           existing: Sequence[Rule] = ()) -> tuple[Rule, dict[str, bool], list[str]]:
    """Ground the rule and run every proposal check. Returns (grounded rule, checks, problems)."""
    text = " ".join(x for x in [ruling.decision if ruling else "", ruling.explanation if ruling else "",
                                rule.title or ""] if x)
    g = ground(rule, text, case_feats)
    comp = compile_problems(g.rule)
    auth = authority_problems(g.rule, author_role)
    hc = hard_control_problems(g.rule, ruling)
    conf = conflicts_with(g.rule, existing)
    rep = reproduces(g.rule, case_feats) if case_feats is not None else True
    problems = comp + auth + hc + [f"ungrounded: {u}" for u in g.ungrounded_condition]
    if not g.action_grounded:
        problems.append(f"ungrounded action {rule.action.value}")
    problems += [f"conflicts with {dsl.ref(r)}" for r in conf]
    if not rep:
        problems.append("does not reproduce the case it came from")
    return g.rule, {
        "compiles": not comp, "reproduces_case": rep, "no_hard_control": not hc, "grounded": g.grounded,
        "author_has_authority": not auth, "no_conflict": not conf,
    }, problems


# ---------- immutable versions + status/citation views ----------

@dataclass(frozen=True)
class RuleEvent:
    seq: int
    at: datetime
    kind: str                         # "version" | "status" | "cite"
    rule_id: str
    version: int
    status: str | None = None
    rule: Rule | None = None
    count: int = 0


class RuleBook:
    """Append-only rule history. ``rules_known_at(K)`` is the bitemporal view (plan §2 rule 7)."""

    def __init__(self, events: Iterable[RuleEvent] = ()):
        self.events: list[RuleEvent] = list(events)

    def _next(self) -> int:
        return len(self.events) + 1

    def add(self, rule: Rule, at: datetime | None = None) -> Rule:
        """Record ``rule`` as a new immutable version (its version number is assigned here)."""
        at = at or rule.recorded_at
        prev = [e.version for e in self.events if e.kind == "version" and e.rule_id == rule.id]
        version = max(prev, default=0) + 1
        sup = rule.supersedes if rule.supersedes else (f"{rule.id}@{version - 1}" if prev else None)
        frozen = rule.model_copy(update={"version": version, "recorded_at": at, "supersedes": sup,
                                         "times_cited": 0})
        self.events.append(RuleEvent(self._next(), at, "version", rule.id, version, rule.status, frozen))
        return frozen

    def set_status(self, ref: str, status: str, at: datetime) -> None:
        rid, v = split_ref(ref)
        if v is None:
            v = self.latest_version(rid)
        if v is None:
            raise KeyError(ref)
        self.events.append(RuleEvent(self._next(), at, "status", rid, v, status))

    def cite(self, ref: str, at: datetime, n: int = 1) -> None:
        rid, v = split_ref(ref)
        v = v if v is not None else self.latest_version(rid)
        if v is None or n <= 0:
            return
        self.events.append(RuleEvent(self._next(), at, "cite", rid, v, count=n))

    def latest_version(self, rid: str, known_at: datetime | None = None) -> int | None:
        vs = [e.version for e in self.events if e.kind == "version" and e.rule_id == rid
              and (known_at is None or e.at <= known_at)]
        return max(vs) if vs else None

    def get(self, ref: str, known_at: datetime | None = None) -> Rule | None:
        rid, v = split_ref(ref)
        v = v if v is not None else self.latest_version(rid, known_at)
        base = next((e.rule for e in self.events if e.kind == "version" and e.rule_id == rid and e.version == v),
                    None)
        if base is None:
            return None
        return self._view(base, known_at)

    def _view(self, base: Rule, known_at: datetime | None) -> Rule:
        status = base.status
        cited = 0
        for e in self.events:
            if e.rule_id != base.id or (known_at is not None and e.at > known_at):
                continue
            if e.kind == "status" and e.version == base.version:
                status = e.status or status
            if e.kind == "cite" and e.version == base.version:
                cited += e.count
        # a newer active version supersedes the older one
        if status == "active":
            newer = [e for e in self.events if e.kind == "version" and e.rule_id == base.id
                     and e.version > base.version and (known_at is None or e.at <= known_at)]
            if any(self._status_of(e.rule_id, e.version, known_at) == "active" for e in newer):
                status = "retired"
        return base.model_copy(update={"status": status, "times_cited": cited})

    def _status_of(self, rid: str, version: int, known_at: datetime | None) -> str | None:
        st = next((e.status for e in self.events if e.kind == "version" and e.rule_id == rid
                   and e.version == version), None)
        for e in self.events:
            if (e.kind == "status" and e.rule_id == rid and e.version == version
                    and (known_at is None or e.at <= known_at)):
                st = e.status
        return st

    def rules_known_at(self, known_at: datetime | None = None) -> list[Rule]:
        """Every version recorded by ``known_at``, with status and citations as of ``known_at``."""
        out = [self._view(e.rule, known_at) for e in self.events
               if e.kind == "version" and e.rule is not None and (known_at is None or e.at <= known_at)]
        return sorted(out, key=lambda r: (r.id, r.version))

    def active_at(self, known_at: datetime | None = None) -> list[Rule]:
        return [r for r in self.rules_known_at(known_at) if r.status == "active"]


def split_ref(ref: str) -> tuple[str, int | None]:
    if "@" in ref:
        rid, _, v = ref.rpartition("@")
        if v.isdigit():
            return rid, int(v)
    return ref, None
