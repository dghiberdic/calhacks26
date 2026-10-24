"""D5 · Never ask twice: ruling → rule → verified → previewed → confirmed → re-decided → cited.

1. ``answer`` turns a person's answer into a ``Ruling`` (only the role the question was routed to may answer).
2. ``DrafterAPI.propose_rule`` drafts the rule (an injected drafter; without one, a deterministic template per
   pattern). The engine, not the drafter, sets id, version, tier, authority and timestamps.
3. Verify (``engine.rules.checks``): compiles · reproduces the case · grounded (condition AND scope) · author has
   authority · no hard control · no conflict.
4. Preview: ``engine.trace.TraceStore.replay`` with the rule active, priced by ``BooksAPI.preview`` → the
   ``RuleProposal.would_flip``.
5. ``confirm`` activates it, re-decides the open items, posts the recode to Books and records a citation event per
   case it settles. ``times_cited`` is a view over those events.

Also ``reject`` (a rejection ruling becomes a rule proposal: the Q3 path) and ``widen`` (exactly one rung: drop one
``case:``-scoped key). Pure apart from the injected trace store / books: no wall clock (``at`` is passed in), no
randomness, no LLM unless a drafter is injected (and its output is only ever a draft).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from contracts.models import (
    AnswerResponse,
    Entitlement,
    Fact,
    FlightDecision,
    Question,
    ReplayDiff,
    ReplayFlip,
    Role,
    Rule,
    RuleAction,
    RuleProposal,
    Ruling,
    Session,
    World,
)
from engine import controls, dsl, eu261
from engine import rules as rb
from engine.case import overlay_facts, stations_for
from engine.engine import Engine
from engine.questions import cohort_age_months, cohort_event_date
from engine.trace import TraceStore

PREFIX = {Role.CLAIMS_LEAD: "R-CL", Role.LEGAL: "R-LEG", Role.CONTROLLER: "R-CTL"}
NO_RULE_PATTERNS = frozenset({"window_unknown", "weather_code_contradicted", "cause_unknown", "technical_unverified",
                              "crew", "atc", "challenge_new_fact", "unresolved_subject"})
WIDEN_QUESTION = {
    "cohort": "All storm cohorts?",
    "flight.departs_eu": "Also flights arriving into the EU (e.g. BOS→DUB)?",
    "rotation.prev_cause": "Any cancelled previous rotation, not only weather?",
    "storm": "Every storm, not only this one?",
}


class LifecycleError(Exception):
    def __init__(self, code: str, message: str, **detail: Any):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


@dataclass
class Confirmed:
    rule: Rule
    replay: ReplayDiff
    decisions: list[FlightDecision] = field(default_factory=list)
    entitlements: list[Entitlement] = field(default_factory=list)
    cited: int = 0


# ---------- the deterministic drafter fallback ----------

def _num(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else None


def _says_not_extraordinary(text: str) -> bool:
    return bool(re.search(r"\bnot extraordinary\b|\bis not\b[^.]{0,30}extraordinary|\bcompensation owed\b", text, re.I))


def template_rule(ruling: Ruling, question: Question, case: Mapping[str, Any]) -> Rule | None:
    """A rule draft from the ruling's own words, for the patterns the demo and generator produce."""
    text = f"{ruling.decision} {ruling.explanation}"
    p = question.pattern
    base = dict(id="R-DRAFT", version=1, valid_from=None, recorded_at=ruling.at, status="proposed",
                authority_required=ruling.author_role, tier=rb.TIER_OF_ROLE.get(ruling.author_role, "mined"),
                origin_ruling_id=ruling.id, origin_example=question.case_refs[0] if question.case_refs else None,
                title=ruling.decision.strip().rstrip(".")[:240] or None)
    if p == "voucher_in_lieu_unsigned":
        allow = bool(re.search(r"\boffset the voucher\b|\bmay offset\b|\bpay the balance\b", text, re.I)) and not \
            re.search(r"\bno offset\b", text, re.I)
        return Rule(**base, kind="voucher",
                    scope={"flight.departs_eu": case.get("flight.departs_eu", True)},
                    condition={"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True},
                                       {"f": "voucher.signed", "op": "eq", "v": False}]},
                    action=RuleAction.ALLOW_OFFSET if allow else RuleAction.DENY_OFFSET)
    if p == "knock_on_return":
        clauses: list[dict[str, Any]] = [{"f": "flight.is_return_sector", "op": "eq", "v": True},
                                         {"f": "rotation.prev_cancelled", "op": "eq", "v": True}]
        h = _num(text, r"within\s+(\d+(?:\.\d+)?)\s*h")
        if h is not None:
            clauses.append({"f": "spare.available_within_h", "op": "gt", "v": int(h) if h.is_integer() else h})
        if re.search(r"earliest re-?route", text, re.I):
            clauses.append({"f": "pax.reroute_earliest_offered", "op": "eq", "v": True})
        return Rule(**base, kind="cause", scope={"rotation.prev_cause": case.get("rotation.prev_cause", "weather")},
                    condition={"all": clauses},
                    action=RuleAction.SET_NOT_EXTRAORDINARY if _says_not_extraordinary(text)
                    else RuleAction.SET_EXTRAORDINARY)
    if p == "cohort_release":
        clauses = []
        m = _num(text, r"\bM(\d+)\b")
        clauses.append({"f": "cohort.age_months", "op": "ge", "v": int(m) if m is not None else 12})
        if re.search(r"limitation", text, re.I):
            clauses.append({"f": "cohort.limitation_expired", "op": "eq", "v": False})
        keep = bool(re.search(r"\btail\b|\bkeep\b", text, re.I))
        return Rule(**{**base, "valid_from": ruling.at}, kind="release", scope={"cohort": case.get("cohort")},
                    condition={"all": clauses}, action=RuleAction.KEEP_TAIL if keep else RuleAction.DENY_RELEASE)
    if p in ("concurrent_causes", "external_event", "new_legal_pattern", "rule_conflict"):
        keys = {"concurrent_causes": ["aog.inside_window", "aog.root_cause_internal"],
                "external_event": ["aog.root_cause_internal", "aog.before_window"],
                "new_legal_pattern": ["aog.root_cause_internal"], "rule_conflict": ["flight.is_return_sector"]}[p]
        clauses = [{"f": k, "op": "eq", "v": case[k]} for k in keys if case.get(k) is not None]
        return Rule(**base, kind="cause", scope={"flight": case.get("flight")}, condition={"all": clauses},
                    action=RuleAction.SET_NOT_EXTRAORDINARY if _says_not_extraordinary(text)
                    else RuleAction.SET_EXTRAORDINARY)
    return None


# ---------- the lifecycle ----------

class Lifecycle:
    """Owns no clock and no LLM. ``trace`` is the event store (rules, rulings, decisions, citations)."""

    def __init__(self, engine: Engine, world: World, trace: TraceStore, *, books: Any = None, drafter: Any = None,
                 actor: str = "agent.engine"):
        self.engine, self.world, self.trace = engine, world, trace
        self.books, self.drafter, self.actor = books, drafter, actor
        self.proposals: dict[str, RuleProposal] = {}
        self.rulings: dict[str, Ruling] = {}
        self.questions: dict[str, Question] = {}
        self._storm_of = self._storm_index(world)

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def _storm_index(world: World) -> dict[str, str]:
        out: dict[str, str] = {}
        storms = world.meta.get("storms") if isinstance(world.meta, dict) else None
        if isinstance(storms, dict):
            for sid, m in storms.items():
                for fid in (m.get("flight_ids") or []) if isinstance(m, dict) else []:
                    out[fid] = sid
        return out

    def rules_at(self, at: datetime) -> list[Rule]:
        """Rules in force at ``at``: the latest active version per rule id."""
        latest: dict[str, Rule] = {}
        for r in self.trace.rules_known_at(at):
            if r.status == "active" and (r.id not in latest or r.version > latest[r.id].version):
                latest[r.id] = r
        return sorted(latest.values(), key=lambda r: (r.id, r.version))

    def decide_fn(self, flight_ids: Iterable[str] | None = None):
        """``engine.trace`` DecideFn: stored facts overlaid on the base world, re-decided with the given rules."""
        world = self.world
        ids = sorted(set(flight_ids)) if flight_ids is not None else sorted(
            f.id for f in world.flights if f.status == "cancelled")

        def decide(facts: list[Fact], rules: list[Rule], known_at: datetime):
            w = overlay_facts(world, facts, known_at)
            stations = stations_for(w, known_at)
            for fid in ids:
                d = self.engine.decide_in(w, fid, rules, known_at, stations=stations, storm_id=self._storm_of.get(fid))
                yield d
                yield from eu261.entitlements(d, w, rules, known_at)
        return decide

    def record_run(self, decisions: Sequence[FlightDecision], ents: Sequence[Entitlement], at: datetime,
                   actor: str | None = None) -> int:
        """Record a run's decisions and entitlements and one citation per case per rule. Returns citations made."""
        actor = actor or self.actor
        known = {(r.id, r.version) for r in self.trace.rules_known_at(at)}
        by_flight: dict[str, list[Entitlement]] = {}
        for e in ents:
            by_flight.setdefault(e.flight_id, []).append(e)
        n = 0
        for d in decisions:
            c = self.trace.record_decision(d, actor, at)
            fe = by_flight.get(d.flight_id, [])
            if fe:
                self.trace.record_entitlements(fe, actor, at, inputs=[c.hash])
            n += self._cite(d, fe, at, actor, known)
        return n

    def _cite(self, d: FlightDecision, ents: Sequence[Entitlement], at: datetime, actor: str,
              known: set[tuple[str, int]]) -> int:
        n = 0
        flight_rules = set(d.rules_applied)
        for ref in d.rules_applied:
            if rb.split_ref(ref) in known:
                self.trace.cite_rule(ref, d.flight_id, actor, at)
                n += 1
        for e in ents:
            for ref in e.rules_applied:
                if ref not in flight_rules and rb.split_ref(ref) in known:
                    self.trace.cite_rule(ref, e.coupon_id, actor, at)
                    n += 1
        return n

    def case_features(self, question: Question, at: datetime) -> dict[str, Any]:
        """The DSL features of the first case a question covers (flight, coupon or cohort)."""
        ref = question.case_refs[0] if question.case_refs else ""
        if question.pattern == "cohort_release" or ref.startswith(tuple(o.cohort for o in self.world.opening_balances)):
            ob = next((o for o in self.world.opening_balances if o.cohort == ref), None)
            if ob is None:
                return {"cohort": ref}
            age = cohort_age_months(cohort_event_date(ob), at.date())
            msl = (at.year * 12 + at.month) - (ob.as_of.year * 12 + ob.as_of.month)
            return {"cohort": ob.cohort, "cohort.age_months": age, "cohort.months_since_last_claim": msl,
                    "cohort.limitation_expired": False}
        flight_id = ref.split(":", 1)[0] if ":" in ref and "@" in ref.split(":", 1)[0] else ref
        flight = next((f for f in self.world.flights if f.id == flight_id), None)
        if flight is None:
            return {}
        rules = self.rules_at(at)
        ev = self.engine.evaluate(self.world, flight_id, rules, at)
        feats = dict(ev.features)
        if ":" in ref and ref != flight_id:
            d = self.engine.to_decision(self.world, ev, rules, at)
            views = {v.coupon.id: v for v in eu261.coupon_views(self.world, flight_id, at)}
            v = views.get(ref)
            if v is not None:
                from engine.geo import airport, distance_km
                o, de = airport(self.world, flight.origin), airport(self.world, flight.dest)
                dist = distance_km(self.world, flight.origin, flight.dest)
                feats.update(eu261.coupon_features(flight, v, eu261.band_for(dist, o.eu and de.eu), dist, o, de, d))
        return feats

    def _next_id(self, role: Role) -> str:
        prefix = PREFIX.get(role, "R-X")
        taken = {r.id for r in self.trace.rules_known_at(None)} | set(self.proposals)
        n = 1
        while f"{prefix}-{n}" in taken:
            n += 1
        return f"{prefix}-{n}"

    # ---- 1. answer ------------------------------------------------------
    def answer(self, question: Question, decision: str, explanation: str, session: Session, at: datetime,
               *, kind: str = "answer") -> AnswerResponse:
        ok = controls.check_answer(principal=session.principal, role=session.role, routed_to=question.routed_to)
        if not ok.allowed:
            self.trace.record_access_denied(ok.access(at=at, principal=session.principal, action="answer_question",
                                                      resource=question.id))
            raise LifecycleError("forbidden", f"{question.id} is routed to {question.routed_to.value}; "
                                 f"{session.role.value} cannot answer it ({ok.reason}).")
        n = sum(1 for r in self.rulings.values() if r.question_id == question.id) + 1
        ruling = Ruling(id=f"RUL-{question.id}-{n}", question_id=question.id, author_role=session.role,
                        author=session.principal, kind=kind, decision=decision.strip(),
                        explanation=explanation.strip(), at=at)
        self.rulings[ruling.id] = ruling
        self.questions[question.id] = question
        try:
            self.trace.question(question.id)
        except KeyError:
            self.trace.record_question(question, self.actor, question.asked_at, event="asked")
        self.trace.record_ruling(ruling, session.principal, at)
        self.trace.record_question(question, session.principal, at, event="answered")
        proposal = None if question.pattern in NO_RULE_PATTERNS else self.propose(ruling, question, at)
        return AnswerResponse(ruling=ruling, proposal=proposal)

    # ---- 2-4. draft, verify, preview -------------------------------------
    def propose(self, ruling: Ruling, question: Question, at: datetime) -> RuleProposal | None:
        case = self.case_features(question, at)
        draft = None
        if self.drafter is not None:
            facts = [f for f in self.trace.facts_known_at(at)
                     if any(f.subject.endswith(r) for r in question.case_refs)]
            try:
                draft = self.drafter.propose_rule(ruling, question, facts)
            except Exception:
                draft = None
            if draft is not None and rb.compile_problems(draft):
                draft = None
        draft = draft or template_rule(ruling, question, case)
        if draft is None:
            return None
        rid = self._next_id(ruling.author_role)
        rule = draft.model_copy(update={
            "id": rid, "version": 1, "tier": rb.TIER_OF_ROLE.get(ruling.author_role, draft.tier),
            "authority_required": rb.required_role(draft), "origin_ruling_id": ruling.id,
            "origin_example": question.case_refs[0] if question.case_refs else None, "recorded_at": at,
            "valid_from": at if draft.kind == "release" else None, "status": "proposed", "times_cited": 0,
            "supersedes": None, "static_card": False})
        return self._propose(rule, ruling, case, at)

    def _propose(self, rule: Rule, ruling: Ruling, case: Mapping[str, Any], at: datetime) -> RuleProposal:
        existing = self.rules_at(at)
        rule, chk, problems = rb.checks(rule, author_role=ruling.author_role, ruling=ruling, case_feats=case,
                                        existing=[r for r in existing if r.id != rule.id])
        diff = self.preview(rule, at, case)
        widen_next = self._widen_next(rule)
        proposal = RuleProposal(rule=rule, checks=chk, would_flip=diff, widen_next=widen_next)
        self.proposals[rule.id] = proposal
        self.rulings.setdefault(ruling.id, ruling)
        self.trace.record_rule(rule, ruling.author, at, event="proposed",
                               reason="; ".join(problems)[:500] if problems else "", case_ref=rule.origin_example)
        return proposal

    @staticmethod
    def _widen_next(rule: Rule) -> dict[str, Any] | None:
        keys = [k for k, v in rule.scope.items() if isinstance(v, str) and v.startswith(dsl.CASE_PREFIX)]
        if not keys:
            return None
        return {"remove": keys[0], "question": WIDEN_QUESTION.get(keys[0], f"Drop the {keys[0]} constraint?")}

    def preview(self, rule: Rule, at: datetime, case: Mapping[str, Any] | None = None) -> ReplayDiff:
        """Replay the open items with ``rule`` active (never calls an LLM; writes nothing)."""
        candidate = rule.model_copy(update={"status": "active"})
        rules = [r for r in self.rules_at(at) if r.id != rule.id] + [candidate]
        ref = dsl.ref(rule)
        if rule.action in (RuleAction.KEEP_TAIL, RuleAction.DENY_RELEASE):
            return self._release_preview(candidate, at, ref)
        on_record = sorted(self.trace.decisions(at))
        if not on_record:
            return ReplayDiff(rule_ref=ref, known_at=at, flips=[], total_delta_cents=0)
        preview_fn = getattr(self.books, "preview", None)
        return self.trace.replay(at, self.decide_fn(on_record), rules_override=rules, preview_fn=preview_fn,
                                 rule_ref=ref)

    def _release_preview(self, rule: Rule, at: datetime, ref: str) -> ReplayDiff:
        flips = []
        for ob in sorted(self.world.opening_balances, key=lambda o: o.cohort):
            age = cohort_age_months(cohort_event_date(ob), at.date())
            feats = {"cohort": ob.cohort, "cohort.age_months": age, "cohort.limitation_expired": False,
                     "cohort.months_since_last_claim": (at.year * 12 + at.month)
                     - (ob.as_of.year * 12 + ob.as_of.month)}
            if ob.balance_cents > 0 and dsl.scope_matches(rule.scope, feats) and dsl.evaluate(rule.condition, feats):
                flips.append(ReplayFlip(entity_id=ob.cohort, field="release_proposed_cents", before=ob.balance_cents,
                                        after=0, delta_cents=0))
        return ReplayDiff(rule_ref=ref, known_at=at, flips=flips, total_delta_cents=0,
                          locked_periods_untouched=sorted(self.trace.locked_periods()))

    # ---- 5. confirm ------------------------------------------------------
    def confirm(self, rule_id: str, session: Session, at: datetime) -> Confirmed:
        rid = rb.split_ref(rule_id)[0]
        proposal = self.proposals.get(rid)
        if proposal is None:
            raise LifecycleError("not_found", f"No proposal {rule_id}.")
        rule = proposal.rule
        failed = [k for k, v in proposal.checks.items() if not v]
        if failed:
            raise LifecycleError("validation", f"{dsl.ref(rule)} failed checks: {', '.join(failed)}.", failed=failed)
        auth = rb.authority_problems(rule, session.role) if rule.tier != "mined" else []
        if auth or controls.is_external(session.principal):
            self.trace.record_access_denied(controls.ControlResult(False, "R-HC-AUTHORITY", "; ".join(auth) or
                                                                   "external party").access(
                at=at, principal=session.principal, action="confirm_rule", resource=dsl.ref(rule)))
            raise LifecycleError("forbidden", f"{session.role.value} cannot confirm {dsl.ref(rule)}: "
                                 + ("; ".join(auth) or "external party") + ".")
        active = rule.model_copy(update={"status": "active", "recorded_at": at})
        rc = self.trace.record_rule(active, session.principal, at, event="active", case_ref=rule.origin_example)
        del self.proposals[rid]
        ref = dsl.ref(active)
        if active.action in (RuleAction.KEEP_TAIL, RuleAction.DENY_RELEASE):
            diff = self._release_preview(active, at, ref)
            return Confirmed(rule=self.trace.rule(ref), replay=diff)
        on_record = sorted(self.trace.decisions(at))
        if not on_record:
            return Confirmed(rule=self.trace.rule(ref), replay=ReplayDiff(rule_ref=ref, known_at=at, flips=[],
                                                                        total_delta_cents=0))
        preview_fn = getattr(self.books, "preview", None)
        run = self.trace.replay_run(at, self.decide_fn(on_record), rules_override=self.rules_at(at),
                                    preview_fn=preview_fn, rule_ref=ref)
        changed_f = run.changed_flights()
        changed_c = run.changed_coupons()
        jes = []
        post = getattr(self.books, "post_recode", None)
        if post is not None and changed_c:
            before = [run.before_entitlements[c] for c in changed_c if c in run.before_entitlements]
            after = [run.after_entitlements[c] for c in changed_c]
            jes = list(post(before, after, at))
        known = {(r.id, r.version) for r in self.trace.rules_known_at(at)}
        decisions = [run.after[f] for f in changed_f]
        touched = set(changed_f) | {run.after_entitlements[c].flight_id for c in changed_c}
        by_flight: dict[str, list[Entitlement]] = {}
        for c in changed_c:
            e = run.after_entitlements[c]
            by_flight.setdefault(e.flight_id, []).append(e)
        cited = 0
        for fid in sorted(touched):
            d = run.after[fid]
            if fid in changed_f:
                dc = self.trace.record_decision(d, session.principal, at, inputs=[rc.hash])
                inputs = [dc.hash]
            else:
                inputs = [rc.hash]
            fe = by_flight.get(fid, [])
            if fe:
                self.trace.record_entitlements(fe, session.principal, at, inputs=inputs)
            cited += self._cite_ref(d if fid in changed_f else None, fe, ref, at)
        for je in jes:
            self.trace.record_journal(je, je.preparer or self.actor, at, inputs=[rc.hash])
        diff = run.diff.model_copy(update={"adjustment_je_ids": [je.id for je in jes]})
        return Confirmed(rule=self.trace.rule(ref), replay=diff, decisions=decisions,
                         entitlements=[e for v in by_flight.values() for e in v], cited=cited)

    def _cite_ref(self, d: FlightDecision | None, ents: Sequence[Entitlement], ref: str, at: datetime) -> int:
        """One citation per re-decided flight that cites ``ref``, else one per coupon that does."""
        n = 0
        if d is not None and ref in d.rules_applied:
            self.trace.cite_rule(ref, d.flight_id, self.actor, at)
            n += 1
        else:
            for e in ents:
                if ref in e.rules_applied:
                    self.trace.cite_rule(ref, e.coupon_id, self.actor, at)
                    n += 1
        return n

    # ---- reject + widen ----------------------------------------------------
    def reject(self, target: Question | str, explanation: str, session: Session, at: datetime) -> AnswerResponse:
        """Reject a question's recommendation or a proposed/active rule; the rejection becomes a rule proposal."""
        if isinstance(target, Question):
            q = target
            decision = f"Rejected: {q.recommended_option}"
            return self.answer(q, decision, explanation, session, at, kind="rejection")
        rid = rb.split_ref(target)[0]
        p = self.proposals.get(rid)
        rule = p.rule if p is not None else self.trace.rule(target)
        ok = controls.check_answer(principal=session.principal, role=session.role, routed_to=rb.required_role(rule))
        if not ok.allowed:
            raise LifecycleError("forbidden", f"{session.role.value} cannot reject {dsl.ref(rule)} ({ok.reason}).")
        ruling = Ruling(id=f"RUL-{rid}-reject-{len(self.rulings) + 1}", question_id=None, author_role=session.role,
                        author=session.principal, kind="rejection", decision=f"Rejected {dsl.ref(rule)}",
                        explanation=explanation.strip(), at=at)
        self.rulings[ruling.id] = ruling
        self.trace.record_ruling(ruling, session.principal, at)
        self.trace.record_rule(rule, session.principal, at, event="retired", reason=f"rejected: {explanation}"[:500])
        self.proposals.pop(rid, None)
        q = next((x for x in self.questions.values() if rule.origin_example in x.case_refs), None)
        proposal = self.propose(ruling, q, at) if q is not None else None
        return AnswerResponse(ruling=ruling, proposal=proposal)

    def widen(self, rule_id: str, session: Session, at: datetime) -> RuleProposal:
        """Exactly one rung: drop the first ``case:`` scope key (and any condition clause on it)."""
        rid = rb.split_ref(rule_id)[0]
        p = self.proposals.get(rid)
        rule = p.rule if p is not None else self.trace.rule(rule_id)
        nxt = self._widen_next(rule)
        if nxt is None:
            raise LifecycleError("validation", f"{dsl.ref(rule)} has no case-scoped key left to widen.")
        key = nxt["remove"]
        scope = {k: v for k, v in rule.scope.items() if k != key}
        cond = rule.condition
        if "all" in cond:
            cond = {"all": [c for c in cond["all"] if c.get("f") != key]}
        version = max([r.version for r in self.trace.rules_known_at(None) if r.id == rule.id] + [rule.version]) + 1
        title = rule.title
        if key == "cohort" and title:
            title = f"{title} (all storm cohorts)"
        wider = rule.model_copy(update={"version": version, "scope": scope, "condition": cond, "status": "proposed",
                                        "supersedes": dsl.ref(rule), "recorded_at": at, "times_cited": 0,
                                        "title": title})
        ruling = self.rulings.get(rule.origin_ruling_id or "") or Ruling(
            id=f"RUL-{rid}-widen", question_id=None, author_role=session.role, author=session.principal,
            kind="answer", decision=rule.title or "", explanation="", at=at)
        widen_ruling = ruling.model_copy(update={"author_role": session.role, "author": session.principal})
        case = {k: dsl.strip_case(v) for k, v in rule.scope.items()}
        q = self.questions.get(ruling.question_id or "")
        if q is not None:
            case = {**self.case_features(q, at), **case}
        return self._propose(wider, widen_ruling, case, at)
