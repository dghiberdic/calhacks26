"""D7 · Miner: conditional-majority mining over ``world.history_cases`` (frequency mining only).

- **Candidates.** Within each case ``kind`` (e.g. ``reroute_reduction``), a candidate condition is one clause over an
  allowlisted DSL feature (CONTRACTS §4), either ``f eq v`` or ``f in [values whose cases mostly decided D]``, or a
  conjunction of two clauses on different features. Its decision is the majority decision of the cases it covers.
  Features outside the allowlist, and numeric features with no finite domain, are never split.
- **Thresholds.** A candidate is kept only with support ≥ 8 (cases covered AND decided the majority way) and
  purity ≥ 95% (support / cases covered). Tautologies (a clause admitting the feature's whole domain) are dropped.
- **Choice.** Per (kind, decision), the most general survivor wins: most cases covered, then most support, then
  fewest clauses, then selectivity against the feature's domain (``pax.election`` in 2 of 5 values beats
  ``flight.departs_eu`` in 1 of 2), then canonical JSON.
- **Only policy is mined.** A decision that settles law (extraordinary circumstances, an offset below the
  statutory floor) is never proposed, whatever its support: Legal rules on law.
- **Output.** Each survivor is a ``RuleProposal`` in ``shadow``, ``tier="mined"``, ``support="41 of 42"``, grounded
  in the case ids it was mined from. ``would_flip`` replays the rule against the history it came from, so the
  exceptions it would overturn are shown with their Δ€.
- **Written policy vs practice.** A written policy (``world.meta["written_policies"]`` or ``written=``) that an
  established practice (same thresholds) contradicts becomes one Controller question; the mined rule it contradicts
  stays ``proposed`` (``checks.no_conflict = False``) and is never auto-activated.
- ``learned_items`` feeds the Storm Run "Learns" strip (history read, claim rate from the curve, mined policy).

Pure: no LLM, no wall clock, no randomness. The result never depends on the order of ``history_cases``.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from contracts import fields
from contracts.models import (
    Cause,
    ClaimCurve,
    Confidence,
    Coupon,
    Entitlement,
    Evidence,
    FlightDecision,
    HistoryCase,
    LearnedItem,
    Question,
    ReplayDiff,
    ReplayFlip,
    Role,
    Rule,
    RuleAction,
    RuleProposal,
    World,
)
from engine import dsl
from engine import rules as rulebook
from engine.eu261 import REDUCTION_LIMIT_MIN, REROUTE_KINDS
from engine.questions import remind_at

MIN_SUPPORT = 8
MIN_PURITY = Fraction(95, 100)
MAX_CLAUSES = 2

ROOT = Path(__file__).resolve().parent.parent
CURVES_JSON = ROOT / "contracts" / "fixtures" / "golden" / "curves.json"
LONG_HAUL = "long_haul_gt3500"

CurveLookup = Callable[[str], ClaimCurve | Mapping[str, Any] | None]


# ---------- what a decision means ----------

@dataclass(frozen=True)
class Policy:
    action: RuleAction
    slug: str            # R-MINED-<slug>
    title: str           # the rule card (grounds the action: engine.rules.ACTION_LEXICON)
    learned: str         # the Learns strip line


POLICIES: dict[str, Policy] = {
    "apply_7_2_reduction": Policy(
        RuleAction.APPLY_7_2_REDUCTION, "REDUCE",
        "Take the 50% reroute cut (Art. 7(2)) when the reroute arrives within the band's limit",
        "Takes the 50% reroute cut (Art. 7(2)) when a reroute arrives within the band's limit"),
    "deny_offset": Policy(
        RuleAction.DENY_OFFSET, "NO-OFFSET",
        "No offset for an unsigned voucher in lieu of compensation: pay cash",
        "Pays cash when a voucher in lieu of compensation is unsigned"),
}
POLICY_BY_ACTION = {p.action: p for p in POLICIES.values()}

# decisions that settle law: only Legal rules on them (plan §2 rules 3-4, the statutory floor)
LAW = frozenset({"extraordinary", "not_extraordinary", "set_extraordinary", "set_not_extraordinary",
                 "allow_offset"})

ACTION_DECISION: dict[RuleAction, str] = {
    RuleAction.APPLY_7_2_REDUCTION: "apply_7_2_reduction",
    RuleAction.SET_EXTRAORDINARY: "extraordinary", RuleAction.SET_NOT_EXTRAORDINARY: "not_extraordinary",
    RuleAction.DENY_OFFSET: "deny_offset", RuleAction.ALLOW_OFFSET: "allow_offset",
    RuleAction.KEEP_TAIL: "keep_tail", RuleAction.DENY_RELEASE: "deny_release",
}
# the other answers to the same question (which kinds of case a written policy speaks to)
OPPOSITES: dict[str, tuple[str, ...]] = {
    "apply_7_2_reduction": ("no_reduction",), "no_reduction": ("apply_7_2_reduction",),
    "extraordinary": ("not_extraordinary",), "not_extraordinary": ("extraordinary",),
    "deny_offset": ("allow_offset",), "allow_offset": ("deny_offset",),
}
PHRASE = {
    "apply_7_2_reduction": "took the 50% reroute cut", "no_reduction": "paid in full (no reroute cut)",
    "extraordinary": "were found extraordinary", "not_extraordinary": "were found not extraordinary",
    "deny_offset": "paid cash (no voucher offset)", "allow_offset": "offset the voucher",
}


# ---------- feature domains (selectivity) ----------

def _args(model: Any, name: str) -> tuple[Any, ...]:
    out: list[Any] = []
    for a in get_args(model.model_fields[name].annotation):
        out += list(get_args(a)) if get_args(a) else ([] if a is type(None) else [a])
    return tuple(out)


DOMAINS: dict[str, tuple[Any, ...]] = {
    f: s.enum for f in dsl.FEATURES if (s := fields.REGISTRY.get(f)) is not None and s.enum
}
DOMAINS.update({
    "pax.fare_type": _args(Coupon, "fare_type"),
    "flight.band_eur": _args(Entitlement, "band_eur"),
    "flight.in_window_dep": _args(FlightDecision, "in_window_dep"),
    "flight.in_window_arr": _args(FlightDecision, "in_window_arr"),
    "flight.route_region": ("EU", "EU_US", "EU_UK", "OTHER"),          # CONTRACTS §4
    "rotation.prev_cause": tuple(c.value for c in Cause),
})


def _key(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def _scalar(v: Any) -> bool:
    return isinstance(v, str | bool | int | float)


def domain_size(feature: str, seen: Iterable[Any]) -> int | None:
    """How many values ``feature`` can take (None: numeric with no finite domain, so it is never split)."""
    seen = list(seen)
    seen_keys = {_key(v) for v in seen}
    known = DOMAINS.get(feature)
    if known is None and seen_keys and all(isinstance(v, bool) for v in seen):
        known = (False, True)
    if known is not None:
        return len({_key(v) for v in known} | seen_keys)
    if seen_keys and all(isinstance(v, str) for v in seen):
        return len(seen_keys) + 1                      # open vocabulary: room for one value never seen
    return None


# ---------- candidates ----------

@dataclass(frozen=True)
class Atom:
    clause: dict[str, Any]
    share: Fraction                                   # fraction of the domain the clause admits

    @property
    def feature(self) -> str:
        return self.clause["f"]


@dataclass(frozen=True)
class Candidate:
    kind: str
    decision: str
    condition: dict[str, Any]
    covered: tuple[str, ...]                          # ruling ids the condition matches (sorted)
    support_ids: tuple[str, ...]                      # ... of which decided ``decision``
    selectivity: Fraction
    reason: str | None = None                         # None = kept

    @property
    def kept(self) -> bool:
        return self.reason is None

    @property
    def support(self) -> int:
        return len(self.support_ids)

    @property
    def coverage(self) -> int:
        return len(self.covered)

    @property
    def purity(self) -> Fraction:
        return Fraction(self.support, self.coverage) if self.coverage else Fraction(0)

    @property
    def support_text(self) -> str:
        return f"{self.support} of {self.coverage}"

    @property
    def exceptions(self) -> tuple[str, ...]:
        s = set(self.support_ids)
        return tuple(i for i in self.covered if i not in s)

    @property
    def clauses(self) -> list[dict[str, Any]]:
        return list(self.condition.get("all", []))

    def rank(self) -> tuple:
        """Ascending = better (most general first)."""
        return (-self.coverage, -self.support, len(self.clauses), -self.selectivity,
                json.dumps(self.condition, sort_keys=True))


def features_of(case: HistoryCase) -> dict[str, Any]:
    """The case's allowlisted, scalar features (anything else is never mined)."""
    return {f: v for f, v in case.features.items() if f in dsl.FEATURES and _scalar(v)}


def _ordered(cases: Iterable[HistoryCase]) -> list[HistoryCase]:
    return sorted(cases, key=lambda c: (c.ruling_id, c.case_ref, c.kind, c.decision, c.at.isoformat(),
                                        _key(c.features)))


def _majority(decisions: Iterable[str]) -> tuple[str, int] | None:
    cnt = Counter(decisions)
    if not cnt:
        return None
    return min(cnt.items(), key=lambda kv: (-kv[1], kv[0]))


def _atoms(group: Sequence[HistoryCase], seen: Mapping[str, list[Any]]) -> list[Atom]:
    by_feature: dict[str, dict[str, tuple[Any, Counter]]] = {}
    for c in group:
        for f, v in features_of(c).items():
            slot = by_feature.setdefault(f, {}).setdefault(_key(v), (v, Counter()))
            slot[1][c.decision] += 1
    out: list[Atom] = []
    for f in sorted(by_feature):
        size = domain_size(f, seen.get(f, []))
        if not size:
            continue
        vals = by_feature[f]
        for k in sorted(vals):
            out.append(Atom({"f": f, "op": "eq", "v": vals[k][0]}, Fraction(1, size)))
        for d in sorted({c.decision for c in group}):
            mostly_d = []                              # values whose cases mostly decided d, most common first
            for k, (v, cnt) in vals.items():
                top = cnt.most_common()
                if top[0][0] == d and (len(top) == 1 or top[1][1] < top[0][1]):
                    mostly_d.append((-sum(cnt.values()), k, v))
            if len(mostly_d) >= 2:
                out.append(Atom({"f": f, "op": "in", "v": [v for _, _, v in sorted(mostly_d)]},
                                Fraction(len(mostly_d), size)))
    return [a for a in out if a.share < 1]            # a clause admitting the whole domain says nothing


def _reason(decision: str, support: int, purity: Fraction) -> str | None:
    if support < MIN_SUPPORT:
        return f"support {support} < {MIN_SUPPORT}"
    if purity < MIN_PURITY:
        return f"purity {float(purity):.0%} < {float(MIN_PURITY):.0%}"
    if decision in LAW:
        return "settles law (Legal rules on it); never mined"
    if decision not in POLICIES:
        return f"no rule action for decision {decision!r}"
    return None


def candidates(cases: Iterable[HistoryCase]) -> list[Candidate]:
    """Every scored candidate (kept or not, with the reason), sorted. Independent of the order of ``cases``."""
    ordered = _ordered(cases)
    seen: dict[str, list[Any]] = {}
    for c in ordered:
        for f, v in features_of(c).items():
            seen.setdefault(f, []).append(v)
    out: list[Candidate] = []
    for kind in sorted({c.kind for c in ordered}):
        group = [(c, features_of(c)) for c in ordered if c.kind == kind]
        atoms = _atoms([c for c, _ in group], seen)
        conds: list[tuple[Atom, ...]] = [(a,) for a in atoms]
        if MAX_CLAUSES >= 2:
            conds += [p for p in combinations(atoms, 2) if p[0].feature != p[1].feature]
        for combo in conds:
            cond = {"all": [a.clause for a in combo]}
            hit = [c for c, f in group if dsl.evaluate(cond, f)]
            maj = _majority(c.decision for c in hit)
            if maj is None:
                continue
            decision, _ = maj
            covered = tuple(sorted(c.ruling_id for c in hit))
            support_ids = tuple(sorted(c.ruling_id for c in hit if c.decision == decision))
            share = Fraction(1)
            for a in combo:
                share *= a.share
            purity = Fraction(len(support_ids), len(covered))
            out.append(Candidate(kind, decision, cond, covered, support_ids, 1 - share,
                                 _reason(decision, len(support_ids), purity)))
    return sorted(out, key=lambda c: (c.kind, c.decision, c.rank()))


def best(cands: Iterable[Candidate]) -> list[Candidate]:
    """The most general kept candidate per (kind, decision)."""
    top: dict[tuple[str, str], Candidate] = {}
    for c in cands:
        if not c.kept:
            continue
        k = (c.kind, c.decision)
        if k not in top or c.rank() < top[k].rank():
            top[k] = c
    return [top[k] for k in sorted(top)]


# ---------- written policy ----------

@dataclass(frozen=True)
class WrittenPolicy:
    id: str
    text: str
    decision: str
    condition: dict[str, Any] = field(default_factory=lambda: {"all": []})
    scope: dict[str, Any] = field(default_factory=dict)
    kind: str | None = None


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9@.:_-]", "-", s) or "policy"


def as_policy(x: Any) -> WrittenPolicy | None:
    """A ``Rule``, a ``WrittenPolicy`` or a mapping ``{id, text, decision, condition?, scope?, kind?}``; else None."""
    if isinstance(x, WrittenPolicy):
        p = x
    elif isinstance(x, Rule):
        dec = ACTION_DECISION.get(x.action)
        if dec is None:
            return None
        p = WrittenPolicy(_safe_id(x.id), x.title or dsl.ref(x), dec, dict(x.condition), dict(x.scope))
    elif isinstance(x, Mapping):
        if "action" in x and "tier" in x:
            try:
                return as_policy(Rule.model_validate(x))
            except ValidationError:
                return None
        pid, dec = x.get("id"), x.get("decision")
        if not isinstance(pid, str) or not pid or not isinstance(dec, str) or not dec:
            return None
        cond, scope, kind = x.get("condition") or {"all": []}, x.get("scope") or {}, x.get("kind")
        p = WrittenPolicy(_safe_id(pid), str(x.get("text") or pid), dec, cond, scope,
                          kind if isinstance(kind, str) else None)
    else:
        return None
    if dsl.validate(p.condition) or dsl.validate_scope(p.scope):
        return None                                    # an unreadable policy can't be checked; never raise
    return p


def written_policies(world: World, written: Iterable[Any] | None = None) -> list[WrittenPolicy]:
    raw = list(world.meta.get("written_policies") or [])
    out: dict[str, WrittenPolicy] = {}
    for p in (as_policy(x) for x in [*raw, *(written or [])]):
        if p is not None:
            out.setdefault(p.id, p)
    return [out[k] for k in sorted(out)]


@dataclass(frozen=True)
class Contradiction:
    policy: WrittenPolicy
    practice: str
    covered: tuple[str, ...]
    support_ids: tuple[str, ...]
    case_refs: dict[str, str]                          # ruling id -> case_ref
    decisions: dict[str, str]                          # ruling id -> decision

    @property
    def support_text(self) -> str:
        return f"{len(self.support_ids)} of {len(self.covered)}"


def _contradiction(p: WrittenPolicy, cases: Sequence[HistoryCase]) -> Contradiction | None:
    family = {p.decision, *OPPOSITES.get(p.decision, ())}
    kinds = {p.kind} if p.kind else {c.kind for c in cases if c.decision in family}
    hit = [c for c in cases if c.kind in kinds and dsl.scope_matches(p.scope, features_of(c))
           and dsl.evaluate(p.condition, features_of(c))]
    maj = _majority(c.decision for c in hit)
    if maj is None or maj[0] == p.decision:
        return None
    practice, n = maj
    if n < MIN_SUPPORT or Fraction(n, len(hit)) < MIN_PURITY:
        return None                                    # no established practice: nothing to contradict
    return Contradiction(p, practice, tuple(sorted(c.ruling_id for c in hit)),
                         tuple(sorted(c.ruling_id for c in hit if c.decision == practice)),
                         {c.ruling_id: c.case_ref for c in hit}, {c.ruling_id: c.decision for c in hit})


# ---------- proposals ----------

def _month(t: datetime) -> str:
    return f"{t.year:04d}-{t.month:02d}"


def _exceptions(ids: Sequence[str]) -> str:
    return f"exception{'s' if len(ids) != 1 else ''}: {', '.join(ids)}"


def _flip(c: HistoryCase, decision: str, action: RuleAction) -> ReplayFlip | None:
    """Replay one exception: what the rule would have decided instead (None = the statute would not let it)."""
    delta = 0
    if action == RuleAction.APPLY_7_2_REDUCTION:
        f = c.features
        band, delay, election = f.get("flight.band_eur"), f.get("pax.arrival_delay_min"), f.get("pax.election")
        if band not in REDUCTION_LIMIT_MIN or election not in REROUTE_KINDS or not isinstance(delay, int | float) \
                or isinstance(delay, bool) or delay > REDUCTION_LIMIT_MIN[band]:
            return None                                # Art. 7(2) limits: the engine would not cut this one
        delta = -(int(band) * 100 // 2)
    return ReplayFlip(entity_id=c.case_ref, field="decision", before=c.decision, after=decision, delta_cents=delta)


def _proposal(cand: Candidate, rid: str, by_id: Mapping[str, HistoryCase], horizon: datetime,
              held: bool) -> RuleProposal:
    pol = POLICIES[cand.decision]
    cases = [by_id[i] for i in cand.covered]
    first, last = min(c.at for c in cases), max(c.at for c in cases)
    exc = cand.exceptions
    ids = ", ".join(cand.support_ids)
    grounding = {rulebook.grounding_key(c["f"], c["v"]): f"history {ids}" for c in cand.clauses}
    grounding[f"action={pol.action.value}"] = (f"{cand.support_text} past decisions"
                                               + (f"; {_exceptions(exc)}" if exc else ""))
    rule = Rule(
        id=rid, version=1, kind="mined_policy", scope={}, condition=cand.condition, action=pol.action,
        tier="mined", authority_required=Role.CLAIMS_LEAD, origin_ruling_id=None,
        origin_example=(f"history_cases {_month(first)}..{_month(last)} ({cand.coverage} {cand.kind} decisions"
                        + (f"; {len(exc)} {_exceptions(exc)}" if exc else "") + ")"),
        grounding=grounding, support=cand.support_text, valid_from=None, recorded_at=horizon, status="shadow",
        title=pol.title)
    rule = rule.model_copy(update={"authority_required": rulebook.required_role(rule)})
    origin = features_of(by_id[cand.support_ids[0]])
    _, chk, _ = rulebook.checks(rule, author_role=None, ruling=None, case_feats=origin)
    if held:
        chk["no_conflict"] = False
    status = "shadow" if all(chk.values()) else "proposed"
    rule = rule.model_copy(update={"status": status})
    flips = [f for f in (_flip(by_id[i], cand.decision, pol.action) for i in exc) if f is not None]
    flips.sort(key=lambda f: f.entity_id)
    diff = ReplayDiff(rule_ref=dsl.ref(rule), known_at=horizon, flips=flips,
                      total_delta_cents=sum(f.delta_cents for f in flips))
    return RuleProposal(rule=rule, checks=chk, would_flip=diff, widen_next=None)


@dataclass(frozen=True)
class Mined:
    proposals: list[RuleProposal]
    contradictions: list[Contradiction]
    held: dict[str, list[str]]                         # policy id -> refs of the mined rules it holds
    candidates: list[Candidate]


def mine(world: World, written: Iterable[Any] | None = None) -> Mined:
    cases = _ordered(world.history_cases)
    if not cases:
        return Mined([], [], {}, [])
    by_id = {c.ruling_id: c for c in reversed(cases)}
    horizon = max(c.at for c in cases)
    cands = candidates(cases)
    chosen = best(cands)
    contras = [x for x in (_contradiction(p, cases) for p in written_policies(world, written)) if x is not None]
    taken: Counter[str] = Counter()
    proposals: list[RuleProposal] = []
    held: dict[str, list[str]] = {}
    for cand in chosen:
        slug = POLICIES[cand.decision].slug
        taken[slug] += 1
        rid = f"R-MINED-{slug}" + (f"-{taken[slug]}" if taken[slug] > 1 else "")
        against = [x for x in contras if x.practice == cand.decision and set(x.support_ids) & set(cand.support_ids)]
        p = _proposal(cand, rid, by_id, horizon, held=bool(against))
        for x in against:
            held.setdefault(x.policy.id, []).append(dsl.ref(p.rule))
        proposals.append(p)
    proposals.sort(key=lambda p: p.rule.id)
    return Mined(proposals, contras, {k: sorted(v) for k, v in held.items()}, cands)


def mine_rules(world: World, written: Iterable[Any] | None = None) -> list[RuleProposal]:
    """``EngineAPI.mine_rules``: mined policy proposals (``shadow``; ``proposed`` if a written policy disagrees)."""
    return mine(world, written).proposals


# ---------- the Controller question ----------

def _known_at(world: World) -> datetime | None:
    raw = world.meta.get("known_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, datetime) else None


def _phrase(decision: str) -> str:
    return PHRASE.get(decision, f"were decided {decision.replace('_', ' ')}")


def _question(x: Contradiction, holds: list[str], asked_at: datetime) -> Question:
    p = x.policy
    n = len(x.support_ids)
    options = [f"Keep written policy {p.id}", f"Adopt the practice ({x.support_text}) and update the written policy",
               "Decide case by case"]
    held = ", ".join(holds) if holds else "the mined practice"
    evidence = [Evidence(fact_id=f"F-POLICY-{p.id}", source_id=f"SRC-POLICY-{p.id}", field="policy.decision",
                         value=p.decision, quote=p.text, role="contradicts", trust_tier=2)]
    for rid in sorted(x.covered, key=lambda r: (x.decisions[r] == x.practice, r))[:11]:   # exceptions first
        d = x.decisions[rid]
        evidence.append(Evidence(fact_id=f"F-{rid}-decision", source_id=f"SRC-{rid}", field="history.decision",
                                 value=d, role="supports" if d == x.practice else "context", trust_tier=2))
    return Question(
        id=f"Q-POLICY-{p.id}:policy_contradiction", case_refs=list(x.covered), pattern="policy_contradiction",
        routed_to=Role.CONTROLLER, asked_at=asked_at,
        title=f"Written policy {p.id} and practice disagree: which governs?",
        found=(f"Written policy {p.id}: \"{p.text}\" In practice, {x.support_text} past decisions it covers "
               f"{_phrase(x.practice)}."),
        why_flagged=("Practice contradicts a written policy. A mined practice never overrides written policy on its "
                     "own; the Controller decides which governs."),
        recommends=f"Keep written policy {p.id} until the Controller changes it; {held} stays proposed, not applied.",
        recommended_option=options[0], options=options, evidence=evidence,
        confidence=Confidence(score=None, kind="claim_validity", label="uncalibrated · practice vs written policy",
                              features={"precedent_count": float(min(n, 10))}, caps=["capped:sources-disagree"],
                              calibration_version="uncalibrated"),
        reason_tag="sources-disagree", holds=list(holds), holds_cents=0, remind_at=remind_at(asked_at))


def contradictions(world: World, written: Iterable[Any] | None = None, *, asked_at: datetime | None = None,
                   mined: Mined | None = None) -> list[Question]:
    """One Controller question per written policy that established practice contradicts."""
    m = mined or mine(world, written)
    if not m.contradictions:
        return []
    at = asked_at or _known_at(world) or max(c.at for c in world.history_cases)
    return [_question(x, m.held.get(x.policy.id, []), at) for x in m.contradictions]


# ---------- the Learns strip ----------

@lru_cache(maxsize=1)
def _golden_curves() -> tuple[ClaimCurve, ...]:
    try:
        raw = json.loads(CURVES_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for c in raw.get("curves", []) if isinstance(raw, Mapping) else []:
        try:
            out.append(ClaimCurve.model_validate(c))
        except ValidationError:
            continue
    return tuple(out)


def curve(segment: str, curve_lookup: CurveLookup | None = None) -> ClaimCurve | None:
    """``curve_lookup(segment)`` (e.g. ``BooksAPI.curve``), else ``contracts/fixtures/golden/curves.json``."""
    got = _looked_up(segment, curve_lookup) if curve_lookup is not None else None
    return got or next((c for c in _golden_curves() if c.segment == segment), None)


def _looked_up(segment: str, curve_lookup: CurveLookup) -> ClaimCurve | None:
    try:
        got = curve_lookup(segment)
        return got if got is None or isinstance(got, ClaimCurve) else ClaimCurve.model_validate(got)
    except Exception:  # noqa: BLE001 - the strip never breaks on Books; the caller falls back to the golden curves
        return None


def _span_months(cases: Sequence[HistoryCase]) -> int:
    if not cases:
        return 0
    a, b = min(c.at for c in cases), max(c.at for c in cases)
    return (b.year * 12 + b.month) - (a.year * 12 + a.month) + 1


def learned_items(world: World, curve_lookup: CurveLookup | None = None, *, written: Iterable[Any] | None = None,
                  mined: Mined | None = None) -> list[LearnedItem]:
    """The Storm Run "Learns" strip: history read · claim rate (curve) · each mined policy."""
    m = mined or mine(world, written)
    lh = curve(LONG_HAUL, curve_lookup)
    n = len(world.history_cases)
    items: list[LearnedItem] = []
    months = lh.observed_through_month if lh is not None else _span_months(world.history_cases)
    if months:
        items.append(LearnedItem(text=f"Read {months} months of claims history",
                                 support=f"{n} past decisions" if n else (f"curve {lh.version}" if lh else None)))
    if lh is not None:
        items.append(LearnedItem(
            text=(f"{lh.ultimate:.0%} of owed long-haul passengers claim (expected ultimate claim rate: history to "
                  f"M{lh.observed_through_month} + tail judgment)"),
            support=f"curve {lh.version}"))
    for p in m.proposals:
        pol = POLICY_BY_ACTION.get(p.rule.action)
        text = pol.learned if pol else (p.rule.title or f"Mined policy {p.rule.id}")
        if not p.checks.get("no_conflict", True):
            text += " · written policy disagrees: asked the Controller"
        items.append(LearnedItem(text=text, support=p.rule.support, rule_ref=dsl.ref(p.rule)))
    return items
