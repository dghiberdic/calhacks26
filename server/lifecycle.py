"""Rulings → rules → replay ("never ask twice", plan §1.4, THREAD D5), on the real engine, trace and Books.

Until `engine.lifecycle` lands, the server orchestrates it:
1. `answer` records a `Ruling` (trace `ruling` commit; the question gets an `answered` event) and drafts a
   `RuleProposal`: the scripted rule for the known patterns (R-CL-1 / R-LEG-1 / R-CTL-1, the stub's bodies with
   the question's cases), else the Drafter's `propose_rule` when one exists, else none (the ruling is then applied
   to its own cases as a human override).
2. `would_flip` is `TraceStore.replay_run`: the real `Engine` re-decides every decided flight with the candidate
   rule set (its DSL decides where a cause rule applies), `engine.eu261` recomputes entitlements (coupon-level rules
   such as R-CL-1), and `Books.preview` prices the change. Replay writes nothing.
3. `confirm` records the rule `active`, replays, records the changed decisions and entitlements, posts
   `Books.post_recode` and refreshes the storm runs and flight files. `revert` is `TraceStore.revert` (retire →
   replay → `Books.post_recode` → revert commit, never into a locked period). `widen` drops one `case:` scope key.
The engine decides; the server never computes an amount (Books does) and never pre-answers a question.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator

from contracts.models import (
    AskedAgain, Entitlement, Extraordinary, FlightDecision, FlightFile, JournalEntry, Question, ReplayDiff, ReplayFlip, Role,
    Rule, RuleAction, RuleProposal, Ruling, StormRun, WidenOffer, World,
)

from . import compose
from .impls import _module, call

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger("stormcheck.server")
FLIGHT_ACTIONS = {RuleAction.SET_EXTRAORDINARY: Extraordinary.YES,
                  RuleAction.SET_NOT_EXTRAORDINARY: Extraordinary.NO}
COHORT_ACTIONS = {RuleAction.KEEP_TAIL, RuleAction.DENY_RELEASE}
BASE_EXTRACTORS = frozenset({"normalize@1", "engine:evidence@1"})   # facts that restate the base world
TEMPLATE_ONLY = frozenset({"external_event_window"})   # engine.lifecycle.TEMPLATE_ONLY when importable
PATTERN_TO_CANNED = {"voucher_in_lieu_unsigned": "Q-1", "knock_on_return": "Q-2", "cohort_release": "Q-3"}
# asked-again-v1: a case-scoped key in plain words: what the rule covers, what a case outside it is, what one rung
# wider would also cover
SCOPE_WORDS: dict[str, dict[Any, tuple[str, str, str]]] = {
    "flight.departs_eu": {True: ("flights leaving the EU", "arrives into the EU", "flights arriving into the EU"),
                          False: ("flights that do not leave the EU", "leaves the EU", "flights leaving the EU")},
    "flight.arrives_eu": {True: ("flights arriving into the EU", "does not arrive into the EU",
                                 "flights leaving the EU"),
                          False: ("flights that do not arrive into the EU", "arrives into the EU",
                                  "flights arriving into the EU")},
}
AUTHORITY = {  # THREAD D4: who may author what
    Role.CLAIMS_LEAD: {"voucher", "entitlement", "routing"},
    Role.LEGAL: {"cause", "entitlement", "regime", "routing"},
    Role.CONTROLLER: {"release", "routing"},
}


class LifecycleError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def base_id(rule_id: str) -> str:
    return rule_id.split("@", 1)[0]


def ref(rule: Rule) -> str:
    return f"{rule.id}@{rule.version}"


def flight_level(rule: Rule) -> bool:
    """Rules that can change a flight decision (cause and routing); the rest only change entitlements."""
    return rule.action in FLIGHT_ACTIONS or rule.action == RuleAction.ROUTE_TO or rule.kind == "cause"


def strip_case(v: Any) -> Any:
    return v[len("case:"):] if isinstance(v, str) and v.startswith("case:") else v


class Lifecycle:
    def __init__(self, rt: "Runtime"):
        self.rt = rt

    # ---- state views ---------------------------------------------------
    @property
    def world(self) -> World | None:
        return self.rt.world

    def rules(self) -> dict[str, Rule]:
        return {r.id: r for r in self.rt.rules()}

    def proposal(self, rule_id: str) -> RuleProposal | None:
        data = self.rt.store.get("proposal", base_id(rule_id))
        return RuleProposal.model_validate(data) if data else None

    def decisions(self) -> dict[str, FlightDecision]:
        return {k: FlightDecision.model_validate(self.rt.store.get("decision", k))
                for k in self.rt.store.keys("decision")}

    def ents(self, fid: str) -> list[Entitlement]:
        return [Entitlement.model_validate(e) for e in (self.rt.store.get("entitlements", fid) or [])]

    def run_of(self, fid: str) -> str | None:
        doc = self.rt.store.get("flight_run", fid)
        return doc["run"] if doc else None

    # ---- the pure decide function replay runs -----------------------------
    def decide_fn(self, fids: Iterable[str] | None = None, *, redecide: bool = True
                  ) -> Callable[[list, list, datetime], Iterator[Any]]:
        """`decide_fn(facts, rules, known_at)` for `TraceStore.replay_run` / `revert`: the real Engine over the base
        world with the injected facts overlaid; entitlements from the engine. Never calls an LLM.

        `redecide=False` keeps each flight's decision and recomputes only its entitlements: a coupon-level rule
        (voucher offset, Art. 7(2) reduction) never changes a flight decision."""
        rt = self.rt
        targets = list(fids) if fids is not None else list(rt.store.keys("decision"))
        current = self.decisions()

        def fn(facts: list, rules: list, known_at: datetime) -> Iterator[Any]:
            world = rt.world
            if world is None:
                return
            eng = rt.impls.engine
            er = rt.engine_rules(list(rules))
            case = _module("engine.case")
            w = world
            new = [f for f in facts if f.extractor not in BASE_EXTRACTORS]   # already in the base world otherwise
            if new and case is not None and hasattr(eng, "evaluate"):
                w = case.overlay_facts(world, new, known_at)
            stations = case.stations_for(w, known_at) if case is not None and hasattr(eng, "evaluate") else None
            for fid in targets:
                if redecide or new:
                    d = self._decide_one(eng, w, fid, er, known_at, stations, current.get(fid))
                else:
                    d = current[fid].model_copy(update={"known_at": known_at}) if fid in current else None
                if d is None:
                    continue
                yield d
                yield from compose.entitlements_for(d, w, er, known_at, eng)

        return fn

    def _decide_one(self, eng: Any, w: World, fid: str, rules: list[Rule], known_at: datetime, stations: Any,
                    cur: FlightDecision | None) -> FlightDecision | None:
        if cur is not None and cur.outcome == "human" and cur.reason.startswith("Ruled by"):
            return cur                    # a person ruled on this case directly: replay never undoes that
        try:
            if eng is not None and hasattr(eng, "evaluate") and hasattr(eng, "to_decision"):
                ev = eng.evaluate(w, fid, rules, known_at, stations)
                return eng.to_decision(w, ev, rules, known_at, self.run_of(fid))
            if eng is not None and hasattr(eng, "decide"):
                return call(eng.decide, fid, [], rules, known_at, compose.CAL_VERSION)
        except Exception:
            return cur
        if cur is None:
            return None
        # no engine on this checkout: flip a needs_legal decision on the rule's own cases
        for r in rules:
            if r.action in FLIGHT_ACTIONS and r.status == "active" and fid in (self.rt.store.get("rule_cases", r.id)
                                                                              or []):
                if cur.extraordinary == Extraordinary.NEEDS_LEGAL:
                    return cur.model_copy(update={"extraordinary": FLIGHT_ACTIONS[r.action], "outcome": "auto",
                                                  "routed_to": None, "question_id": None, "known_at": known_at,
                                                  "rules_applied": [*cur.rules_applied, ref(r)]})
        return cur.model_copy(update={"known_at": known_at})

    def replay(self, rules_after: list[Rule], *, rule_ref: str, fids: Iterable[str] | None = None,
               flight_level: bool = True) -> Any:
        """`TraceStore.replay_run` with the candidate rule set; None when there is nothing to replay over."""
        rt = self.rt
        if rt.world is None or not hasattr(rt.trace, "replay_run"):
            return None
        preview = rt.books.preview if rt.books is not None else None
        locks = rt.books.locked_periods() if rt.books is not None and hasattr(rt.books, "locked_periods") else None
        return rt.trace.replay_run(rt.now, self.decide_fn(fids, redecide=flight_level), rules_override=rules_after,
                                   preview_fn=preview, rule_ref=rule_ref, locks=locks)

    def features(self) -> dict[str, dict[str, Any]]:
        """The engine's DSL features per decided flight at the current clock (cached until the clock or the facts
        change). Features do not depend on the rule set: rules only adjust a finding after it is made."""
        rt = self.rt
        eng = rt.impls.engine
        key = (rt.now, len(rt.store.keys("injected_fact")), id(rt.world))
        cache = getattr(self, "_feat_cache", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        feats: dict[str, dict[str, Any]] = {}
        case = _module("engine.case")
        if rt.world is not None and eng is not None and hasattr(eng, "evaluate") and case is not None:
            stations = case.stations_for(rt.world, rt.now)
            for fid in rt.store.keys("decision"):
                try:
                    feats[fid] = dict(eng.evaluate(rt.world, fid, [], rt.now, stations).features)
                except Exception:
                    continue
        self._feat_cache = (key, feats)
        return feats

    def candidates(self, rule: Rule) -> list[str] | None:
        """Flights a flight-level rule could change: where its DSL matches the engine's features, that cite it, or
        that are its own cases. None = every decided flight (no features to filter on)."""
        dsl = _module("engine.dsl")
        feats = self.features()
        if dsl is None or not feats:
            return None
        active = rule.model_copy(update={"status": "active", "recorded_at": min(rule.recorded_at, self.rt.now)})
        cases = set(self.rt.store.get("rule_cases", rule.id) or [])
        flights = {f.id: f for f in (self.rt.world.flights if self.rt.world else [])}
        out = set(self.citing(ref(rule))) | (cases & set(feats))
        for fid, f in feats.items():
            fl = flights.get(fid)
            try:
                if dsl.applies(active, f, self.rt.now, fl.date if fl else None):
                    out.add(fid)
            except Exception:
                out.add(fid)
        return sorted(out)

    def citing(self, rule_ref: str) -> list[str]:
        """Flights whose decision or entitlements cite `rule_ref` (all a revert of it can change)."""
        out = []
        for fid, d in self.decisions().items():
            if rule_ref in d.rules_applied or any(rule_ref in e.rules_applied for e in self.ents(fid)):
                out.append(fid)
        return out

    def with_rule(self, rule: Rule) -> list[Rule]:
        return [*(r for r in self.rt.rules() if r.id != rule.id), rule]

    # ---- writing a replay ------------------------------------------------------
    def apply(self, run: Any, *, actor: str, link: str | None, rule_ref: str | None, reason: str,
              persisted: bool = False, jes: list | None = None) -> list[str]:
        """Write a replay's changed flights and coupons: trace (unless already persisted by revert), docs, Books."""
        rt = self.rt
        now = rt.now
        fids = run.changed_flights()
        coupons = run.changed_coupons()
        if not fids and not coupons:
            return []
        links = [link] if link else []
        decided: list[FlightDecision] = []
        for fid in fids:
            d = run.after[fid]
            if not persisted:
                d = rt.commit_decision(d, actor, now, inputs=links)
            elif rt.trace is not None and hasattr(rt.trace, "decision"):
                stored = rt.trace.decision(fid)
                d = stored if stored is not None else d
            rt.store.put("decision", fid, d, now)
            decided.append(d)
        by_flight: dict[str, list[Entitlement]] = defaultdict(list)
        for c in coupons:
            by_flight[run.after_entitlements[c].flight_id].append(run.after_entitlements[c])
        if coupons and not persisted:
            rt.record("record_entitlements", [run.after_entitlements[c] for c in coupons], actor, now, inputs=links)
        for fid, changed in by_flight.items():
            cur = {e.coupon_id: e for e in self.ents(fid)}
            cur.update({e.coupon_id: e for e in changed})
            rt.store.put("entitlements", fid, [cur[k] for k in sorted(cur)], now)
        recoded = set(coupons)
        if jes is None:
            before = [run.before_entitlements[c] for c in coupons if c in run.before_entitlements]
            before += [e for d in decided for e in self.ents(d.flight_id) if e.coupon_id not in recoded]
            jes = self.post_recode(before, [run.after_entitlements[c] for c in coupons], decided, rule_ref=rule_ref)
            rt.commit_journal(jes, "agent.books", now, inputs=links)
        elif decided:
            # revert: TraceStore.revert posted its recode before these decisions had commits; pass them on now
            self.post_recode([e for d in decided for e in self.ents(d.flight_id)], [], decided, rule_ref=rule_ref)
        for je in jes:
            amt = sum(line.cr_cents - line.dr_cents for line in je.lines if line.account == "2140")
            rt.emit("journal", "agent.books", f"Drafted {je.id} · {je.kind.replace('_', ' ')} · "
                    f"{'+' if amt >= 0 else '−'}{compose.eur(abs(amt))} EU261 compensation liability · drafted, "
                    "pending approval", "DRAFTED", je.id, amt)
        touched = set(fids) | set(by_flight)
        for fid in touched:
            self.refresh_flight(fid)
        self.refresh_runs(touched)
        return [je.id for je in jes]

    def post_recode(self, before: list[Entitlement], after: list[Entitlement], decisions: list[FlightDecision], *,
                    rule_ref: str | None) -> list[JournalEntry]:
        """`Books.post_recode` with the re-decided flights' decisions, so Books' decision view (INV-7: extraordinary
        → no compensation) and the register's cause / decision-commit provenance follow them. A coupon in `before`
        but not in `after` is unchanged: it only names its flight for that provenance update."""
        rt = self.rt
        if rt.books is None or not (after or decisions):
            return []
        try:
            return list(call(rt.books.post_recode, before, after, rt.now, rule_ref=rule_ref, decisions=decisions))
        except Exception as exc:
            log.warning("books.post_recode (%s) failed: %s", rule_ref, exc)
            return []

    def refresh_flight(self, fid: str) -> None:
        rt = self.rt
        data = rt.store.get("flight_file", fid)
        if data is None or self.world is None:
            return
        ff = FlightFile.model_validate(data)
        d = FlightDecision.model_validate(rt.store.get("decision", fid))
        journal = list(rt.books.journal()) if rt.books is not None else ff.journal_preview
        run = self._run(fid)
        new = compose.flight_file(self.world, ff.flight, d, self.ents(fid), journal, run.metar if run else [],
                                  run.windows if run else [],
                                  ff.explanation if ff.decision.reason == d.reason else compose.template_explanation(d))
        rt.store.put("flight_file", fid, new, rt.now)

    def _run(self, fid: str) -> StormRun | None:
        rid = self.run_of(fid)
        data = self.rt.store.get("storm_run", rid) if rid else None
        return StormRun.model_validate(data) if data else None

    def refresh_runs(self, fids: set[str] | None = None) -> None:
        rt = self.rt
        decs = self.decisions()
        for key in rt.store.keys("storm_run"):
            run = StormRun.model_validate(rt.store.get("storm_run", key))
            ids = {r.flight.id for r in run.flights}
            if run.real_context.get("desk") or (fids is not None and not ids & fids):
                continue                            # desk days are priced in their own scratch ledger
            rows = [r.model_copy(update={"decision": decs.get(r.flight.id, r.decision)}) for r in run.flights]
            ds = [r.decision for r in rows if r.decision is not None]
            ents = {d.flight_id: self.ents(d.flight_id) for d in ds}
            counters = {**run.counters, **compose.counters([r.flight for r in rows], ds, ents, run.questions)}
            owed = sum(e.compensation_cents for es in ents.values() for e in es if e.status in ("owed", "needs_ruling"))
            liability = run.liability_drafted_cents
            if rt.books is not None and hasattr(rt.books, "gl_balance"):
                try:
                    liability = int(rt.books.gl_balance("2140", cohort=run.id))
                except Exception:
                    pass
            rt.store.put("storm_run", run.id, run.model_copy(update={
                "flights": rows, "counters": counters, "entitlement_cents": owed,
                "liability_drafted_cents": liability}), rt.now)

    # ---- answer ------------------------------------------------------------
    def record_ruling(self, *, question: Question | None, role: Role, author: str, principal: str, kind: str,
                      decision: str, explanation: str) -> Ruling:
        rt = self.rt
        ruling = Ruling(id=f"RUL-{len(rt.store.keys('ruling')) + 1:04d}", question_id=question.id if question else None,
                        author_role=role, author=author, kind=kind, decision=decision, explanation=explanation,
                        at=rt.now)
        rt.store.put("ruling", ruling.id, ruling, rt.now)
        rt.record("record_ruling", ruling, principal, rt.now)
        if question is not None:
            rt.store.put("ruling_for", question.id, {"ruling_id": ruling.id}, rt.now)
            rt.record("record_question", question, principal, rt.now, event="answered")
        return ruling

    def answer(self, q: Question, role: Role, author: str, principal: str, decision: str,
               explanation: str) -> tuple[Ruling, RuleProposal | None]:
        rt = self.rt
        lowered = decision.lower().strip()
        kind = "rejection" if q.pattern == "cohort_release" or lowered.startswith(("reject", "keep", "never")) \
            else "answer"
        ruling = self.record_ruling(question=q, role=role, author=author, principal=principal, kind=kind,
                                    decision=decision, explanation=explanation)
        proposal = self.draft_proposal(q, ruling, principal)
        if proposal is not None:
            rt.emit("ruling", principal, f"{compose.label(role)} ruled on {q.id} · rule {ref(proposal.rule)} proposed"
                    f" · would flip {len({f.entity_id for f in proposal.would_flip.flips})}", "RULED", q.id,
                    proposal.would_flip.total_delta_cents or q.holds_cents or None)
        else:
            settled = self.override(q, ruling, principal)
            rt.emit("ruling", principal, f"{compose.label(role)} ruled on {q.id} · {settled} case(s) updated",
                    "RULED", q.id, q.holds_cents or None)
        return ruling, proposal

    def drafted_rule(self, q: Question, ruling: Ruling, rule_id: str | None) -> Rule | None:
        """The Drafter's rule draft (`llm.drafter.Drafter.propose_rule`), committed as an `llm_call`, then verified
        by the engine (`engine.rules.checks`: allowlist, grounding in condition and scope, authority, hard
        controls, reproduces the case). Anything that fails, raises or times out returns None."""
        rt = self.rt
        drafter = rt.impls.drafter
        if drafter is None or not hasattr(drafter, "propose_rule"):
            return None
        from .live import timed
        before = len(getattr(drafter, "records", None) or [])
        try:
            rule = timed(call, rt.settings.reader_timeout_s, drafter.propose_rule, ruling, q, [], rule_id=rule_id,
                         existing_ids=[r.id for r in rt.rules()])
        except Exception as exc:
            rt.store.put("draft_failure", f"{q.id}:{ruling.id}", {"error": type(exc).__name__}, rt.now)
            return None
        recs = getattr(drafter, "records", None) or []
        rt.commit_llm(recs[-1] if len(recs) > before else None)
        if not isinstance(rule, Rule):
            return None
        rb = _module("engine.rules")
        if rb is not None:
            feats = self.features().get(q.case_refs[0]) if q.case_refs else None
            active = [r for r in rt.rules() if r.status == "active" and r.id != rule.id]
            try:
                rule, chk, problems = rb.checks(rule, author_role=ruling.author_role, ruling=ruling,
                                                case_feats=feats, existing=active)
            except Exception:
                return None
            if not all(chk.values()):
                rt.store.put("draft_rejected", f"{q.id}:{ruling.id}", {"problems": problems[:10]}, rt.now)
                return None
        return rule.model_copy(update={"status": "proposed", "origin_ruling_id": rule.origin_ruling_id or ruling.id,
                                       "recorded_at": max(rule.recorded_at, rt.now)})

    def templated_proposal(self, q: Question, ruling: Ruling, principal: str, elc: Any) -> RuleProposal | None:
        """Patterns the engine templates from the ruling's chosen option and never sends to the Drafter (its schema
        cannot express the event features; the blackout's Legal question): `engine.lifecycle.template_rule`, then
        `engine.rules.checks` (grounding, authority), then the same replay as any proposal. "Decide flight by flight"
        templates no rule, so the ruling is applied to its own cases instead."""
        rt = self.rt
        rb = _module("engine.rules")
        fn = getattr(elc, "template_rule", None)
        feats = dict(self.features().get(q.case_refs[0], {})) if q.case_refs else {}
        draft = fn(ruling, q, feats) if fn is not None else None
        if draft is None or rb is None:
            return None
        from contracts import stub_app as stub
        prefix = getattr(elc, "PREFIX", {}).get(ruling.author_role, "R-X")
        taken = {r.id for r in rt.rules()} | set(rt.store.keys("proposal")) | set(stub.RULE_TO_QUESTION)
        rid = next(f"{prefix}-{n}" for n in range(1, 1000) if f"{prefix}-{n}" not in taken)
        rule = draft.model_copy(update={
            "id": rid, "version": 1, "tier": rb.TIER_OF_ROLE.get(ruling.author_role, draft.tier),
            "authority_required": rb.required_role(draft), "origin_ruling_id": ruling.id,
            "origin_example": q.case_refs[0] if q.case_refs else None, "recorded_at": rt.now, "status": "proposed",
            "origin_quote": (ruling.explanation or "").strip() or (ruling.decision or "").strip() or None})
        active = [r for r in rt.rules() if r.status == "active" and r.id != rule.id]
        rule, _, _ = rb.checks(rule, author_role=ruling.author_role, ruling=ruling, case_feats=feats, existing=active)
        rule = rule.model_copy(update={"status": "proposed"})
        p = self.build_proposal(rule, cases=q.case_refs, author_role=ruling.author_role, actor=principal)
        self.store_proposal(p, cases=q.case_refs)
        return p

    def no_wider(self, drafted: Rule, scripted: Rule, q: Question, ruling: Ruling) -> Rule | None:
        """A draft keeps every case-scoped key of its pattern's scripted rule (in its scope or its condition): it is
        never wider than the case that was ruled on, because widening is explicit (`widen`, "All storm cohorts?").
        A wider draft is recorded as rejected and the scripted rule stands."""
        keys = [k for k, v in scripted.scope.items() if isinstance(v, str) and v.startswith("case:")]
        have = set(drafted.scope) | {c.get("f") for c in drafted.condition.get("all", []) if isinstance(c, dict)}
        dropped = [k for k in keys if k not in have]
        if not dropped:
            return drafted
        self.rt.store.put("draft_rejected", f"{q.id}:{ruling.id}", {"problems": [
            f"wider than the ruled case: drops {k} (widening is explicit)" for k in dropped]}, self.rt.now)
        return None

    def draft_proposal(self, q: Question, ruling: Ruling, principal: str) -> RuleProposal | None:
        """Drafter's rule → engine checks → replay. If the draft fails any check (or there is none), the scripted
        rule for the known patterns stands in; for other patterns the ruling is applied to its cases directly."""
        rt = self.rt
        canned = PATTERN_TO_CANNED.get(q.pattern)
        from contracts import stub_app as stub
        canned_id = next((rid for rid, qid in stub.RULE_TO_QUESTION.items() if qid == canned), None)
        elc = _module("engine.lifecycle")
        if self.world is not None and q.pattern in getattr(elc, "TEMPLATE_ONLY", TEMPLATE_ONLY):
            return self.templated_proposal(q, ruling, principal, elc)
        if self.world is not None:
            drafted = self.drafted_rule(q, ruling, canned_id)
            if drafted is not None and canned is not None:
                drafted = self.no_wider(drafted, stub.canned_proposal(canned, ruling, rt.now).rule, q, ruling)
            if drafted is not None:
                p = self.build_proposal(drafted, cases=q.case_refs, author_role=ruling.author_role, actor=principal)
                if all(p.checks.values()):
                    self.store_proposal(p, cases=q.case_refs)
                    return p
        rule: Rule | None = None
        widen_next = None
        if canned is not None:
            from contracts import stub_app as stub
            base = stub.canned_proposal(canned, ruling, rt.now)
            rule = base.rule
            if canned == "Q-1" and q.case_refs:
                rule = rule.model_copy(update={"origin_example": q.case_refs[0]})
            elif canned == "Q-2" and q.case_refs:
                rule = rule.model_copy(update={"origin_example": q.case_refs[-1]})
            elif canned == "Q-3" and q.case_refs:
                rule = rule.model_copy(update={"scope": {"cohort": f"case:{q.case_refs[0]}"},
                                               "origin_example": q.case_refs[0]})
            widen_next = base.widen_next
            if self.world is None:        # stub pipeline: nothing to replay over, keep the scripted diff
                p = base.model_copy(update={"rule": rule})
                self.store_proposal(p, cases=q.case_refs)
                return p
        if rule is None:
            return None
        rule = rule.model_copy(update={"recorded_at": max(rule.recorded_at, rt.now), "status": "proposed",
                                       "origin_ruling_id": rule.origin_ruling_id or ruling.id})
        p = self.build_proposal(rule, cases=q.case_refs, author_role=ruling.author_role, widen_next=widen_next,
                                actor=principal)
        self.store_proposal(p, cases=q.case_refs)
        return p

    def build_proposal(self, rule: Rule, *, cases: list[str], author_role: Role,
                       widen_next: dict[str, Any] | None = None, actor: str = "agent.engine") -> RuleProposal:
        rt = self.rt
        rt.store.put("rule_cases", rule.id, list(cases), rt.now)
        rt.record("record_rule", rule, actor, rt.now, event="proposed", reason="drafted from the ruling")
        active = rule.model_copy(update={"status": "active"})
        if rule.action in COHORT_ACTIONS:
            diff, run = self.cohort_preview(rule), None
        else:
            run = self.replay(self.with_rule(active), rule_ref=ref(rule), flight_level=flight_level(rule),
                              fids=self.candidates(rule) if flight_level(rule) else None)
            diff = run.diff if run is not None else ReplayDiff(rule_ref=ref(rule), known_at=rt.now, flips=[],
                                                               total_delta_cents=0)
        checks = self.checks(rule, cases, run, author_role)
        if widen_next is None:
            keys = [k for k, v in rule.scope.items() if isinstance(v, str) and v.startswith("case:")]
            widen_next = {"remove": keys[0]} if keys else None
        return RuleProposal(rule=rule, checks=checks, would_flip=diff, widen_next=widen_next)

    def cohort_preview(self, rule: Rule) -> ReplayDiff:
        cohort = strip_case(rule.scope.get("cohort")) if rule.scope.get("cohort") else None
        flips = []
        if cohort and self.rt.books is not None:
            try:
                bal = int(self.rt.books.gl_balance("2140", cohort=cohort))
                flips = [ReplayFlip(entity_id=cohort, field="release_proposed_cents", before=bal, after=0)]
            except Exception:
                flips = []
        return ReplayDiff(rule_ref=ref(rule), known_at=self.rt.now, flips=flips, total_delta_cents=0)

    def checks(self, rule: Rule, cases: list[str], run: Any, author_role: Role) -> dict[str, bool]:
        dsl = _module("engine.dsl")
        compiles = True
        if dsl is not None:
            try:
                compiles = not dsl.validate(rule.condition) and not dsl.validate_scope(rule.scope)
            except Exception:
                compiles = False
        changed = set(run.changed_flights()) | set(run.changed_coupons()) if run is not None else set()
        reproduces = rule.action in COHORT_ACTIONS or not cases or bool(set(cases) & changed) or run is None
        grounded = bool(rule.grounding) or all(isinstance(v, str) and v.startswith("case:")
                                               for v in rule.scope.values())
        authority = rule.kind in AUTHORITY.get(author_role, set()) and rule.authority_required == author_role
        others = [o for o in self.rt.rules() if o.id != rule.id and o.status == "active"]
        conflict = any(o.kind == rule.kind and o.tier == rule.tier and o.action != rule.action
                       and set(o.scope) == set(rule.scope) for o in others)
        return {"compiles": compiles, "reproduces_case": reproduces, "no_hard_control": rule.tier != "hard_control",
                "grounded": grounded, "author_has_authority": authority, "no_conflict": not conflict}

    def store_proposal(self, p: RuleProposal, cases: list[str] | None = None) -> None:
        self.rt.store.put("proposal", p.rule.id, p, self.rt.now)
        if cases is not None:
            self.rt.store.put("rule_cases", p.rule.id, list(cases), self.rt.now)

    # ---- override (no rule: the ruling is applied to its own cases) ---------
    def override(self, q: Question, ruling: Ruling, principal: str) -> int:
        text = f"{ruling.decision} {ruling.explanation}".lower()
        if "not extraordinary" in text or "technical" in text or "owed" in text:
            target = Extraordinary.NO
        elif "extraordinary" in text or "weather" in text:
            target = Extraordinary.YES
        else:
            return 0
        rt = self.rt
        decs = self.decisions()
        now = rt.now
        before_all, after_all = [], []
        decided: list[FlightDecision] = []
        for fid in q.case_refs:
            if fid not in decs or self.world is None:
                continue
            bd = decs[fid]
            ad = bd.model_copy(update={"extraordinary": target, "outcome": "human", "routed_to": None,
                                       "question_id": None, "known_at": now, "commit": None,
                                       "reason": f"Ruled by {compose.label(ruling.author_role)} ({ruling.id}): "
                                                 f"{ruling.decision[:120]}"})
            ad = rt.commit_decision(ad, principal, now)
            ae = rt.entitlements(ad, self.world, rt.rules(), now)
            rt.record("record_entitlements", ae, principal, now)
            before_all += self.ents(fid)
            after_all += ae
            rt.store.put("decision", fid, ad, now)
            rt.store.put("entitlements", fid, ae, now)
            decided.append(ad)
        jes = self.post_recode(before_all, after_all, decided, rule_ref=ruling.id)
        rt.commit_journal(jes, "agent.books", now)
        for fid in q.case_refs:
            self.refresh_flight(fid)
        self.refresh_runs(set(q.case_refs))
        return len(decided)

    # ---- confirm / reject / widen / revert ----------------------------------
    def confirm(self, rule_id: str, principal: str) -> tuple[Rule, ReplayDiff]:
        rt = self.rt
        rid = base_id(rule_id)
        p = self.proposal(rid) or self.canned_for(rid, principal)
        if p is None:
            existing = self.rules().get(rid)
            if existing is None:
                raise LifecycleError(404, "not_found", f"No proposal {rule_id}.")
            return self.with_views(existing), ReplayDiff(rule_ref=ref(existing), known_at=rt.now, flips=[],
                                                         total_delta_cents=0)
        rule = p.rule.model_copy(update={"status": "active", "recorded_at": rt.now})
        rt.store.put("rule", rid, rule, rt.now)
        rc = rt.record("record_rule", rule, principal, rt.now, event="active", reason=f"confirmed by {principal}")
        link = rc.hash if rc is not None else None
        if rule.action in COHORT_ACTIONS:
            diff = self.cohort_preview(rule)
            if rt.books is not None and hasattr(rt.books, "keep_tail"):
                cohort = rule.scope.get("cohort")
                try:
                    rt.books.keep_tail(ref(rule), [strip_case(cohort)] if cohort else None, rt.now)
                except Exception:
                    pass
            settled = len(diff.flips)
        elif self.world is None:
            diff, settled = p.would_flip, len(p.would_flip.flips)
        else:
            run = self.replay(self.with_rule(rule), rule_ref=ref(rule), flight_level=flight_level(rule),
                              fids=self.candidates(rule) if flight_level(rule) else None)
            je_ids = self.apply(run, actor=principal, link=link, rule_ref=ref(rule), reason=f"rule {ref(rule)}") \
                if run is not None else []
            settled = len(set(run.changed_flights()) | set(run.changed_coupons())) if run is not None else 0
            diff = (run.diff if run is not None else p.would_flip).model_copy(update={"adjustment_je_ids": je_ids})
        rt.store.put("proposal_state", rid, {"state": "confirmed", "rule_ref": ref(rule)}, rt.now)
        cited = self.times_cited().get(ref(rule), 0)
        rt.emit("rule", principal, f"Saved as policy {ref(rule)} · never asked again · {settled} settled · cited "
                f"{cited}×", "LEARNED", ref(rule), diff.total_delta_cents or None)
        return self.with_views(rule), diff

    def canned_for(self, rid: str, principal: str = "agent.engine") -> RuleProposal | None:
        """Screens can be built in any order: the scripted rules confirm even before their question is answered."""
        from contracts import stub_app as stub
        qid = stub.RULE_TO_QUESTION.get(rid)
        if qid is None:
            return None
        q = next((Question.model_validate(x) for x in self.rt.store.all("question")
                  if PATTERN_TO_CANNED.get(x["pattern"]) == qid), None)
        if q is None:
            return None
        r = Ruling(id=f"RUL-{qid}", question_id=q.id, author_role=q.routed_to, author="(as recommended)",
                   kind="rejection" if qid == "Q-3" else "answer", decision=q.recommended_option, explanation="",
                   at=self.rt.now)
        return self.draft_proposal(q, r, principal)

    def revert(self, rule_id: str, principal: str, *, reason: str = "reverted") -> ReplayDiff:
        rt = self.rt
        rid = base_id(rule_id)
        rule = self.rules().get(rid)
        if rule is None:
            raise LifecycleError(404, "not_found", f"No rule {rule_id}.")
        if rule.tier in ("hard_control", "regulation") or rule.static_card:
            raise LifecycleError(403, "forbidden", f"{rid} is a {rule.tier.replace('_', ' ')}: hard controls are "
                                                   "code and regulation versions are not reverted.")
        rt.store.put("rule", rid, rule.model_copy(update={"status": "retired"}), rt.now)
        tr = _module("engine.trace")
        if self.world is None or not hasattr(rt.trace, "revert"):
            rt.emit("replay", principal, f"Reverted {ref(rule)} · flips 0", "INFO", ref(rule))
            return ReplayDiff(rule_ref=ref(rule), known_at=rt.now, flips=[], total_delta_cents=0)
        locks = rt.books.locked_periods() if rt.books is not None and hasattr(rt.books, "locked_periods") else None
        try:
            out = rt.trace.revert(ref(rule), actor=principal, at=rt.now,
                                  decide_fn=self.decide_fn(self.citing(ref(rule)), redecide=flight_level(rule)),
                                  preview_fn=rt.books.preview if rt.books is not None else None,
                                  post_recode_fn=rt.books.post_recode if rt.books is not None else None,
                                  locks=locks, reason=reason)
        except Exception as exc:
            if tr is not None and isinstance(exc, getattr(tr, "LockedPeriodWrite", ())):
                raise LifecycleError(403, "forbidden", str(exc)) from exc
            if tr is not None and isinstance(exc, getattr(tr, "TraceError", ())):
                raise LifecycleError(422, "validation", str(exc)) from exc
            raise
        self.apply(out.run, actor=principal, link=out.commit.hash, rule_ref=ref(rule), reason=f"revert {ref(rule)}",
                   persisted=True, jes=list(out.journal))
        locked = ", ".join(out.diff.locked_periods_untouched)
        rt.emit("replay", principal, f"Reverted {ref(rule)} · flips {len({f.entity_id for f in out.diff.flips})}"
                + (f" · {locked} locked, untouched" if locked else "") + f" · adjustment in {out.adjustment_period}",
                "INFO", ref(rule), out.diff.total_delta_cents or None)
        return out.diff

    def widen(self, rule_id: str, principal: str = "agent.engine") -> RuleProposal:
        rt = self.rt
        rid = base_id(rule_id)
        p = self.proposal(rid)
        rule = self.rules().get(rid) or (p.rule if p else None)
        if rule is None:
            p = self.canned_for(rid, principal)
            rule = p.rule if p else None
        if rule is None:
            raise LifecycleError(404, "not_found", f"No rule {rule_id}.")
        latest = p.rule if p and p.rule.version > rule.version else rule
        case_keys = [k for k, v in latest.scope.items() if isinstance(v, str) and v.startswith("case:")]
        if not case_keys:
            raise LifecycleError(422, "validation", f"{rid} has no case-scoped key left to widen.")
        key = case_keys[0]
        scope = {k: v for k, v in latest.scope.items() if k != key}
        cond = latest.condition
        if "all" in cond:
            cond = {**cond, "all": [c for c in cond["all"] if c.get("f") != key]}
        title = {"R-CTL-1": "Never release the tail, for all storm cohorts: keep (ultimate − M12 rate) × entitlement "
                            "until the six-year limitation",
                 "R-CL-1": "No signed acceptance, no offset: pay cash; the voucher stays as goodwill (flights leaving "
                           "or arriving into the EU)"}.get(rid, latest.title)
        wider = latest.model_copy(update={"version": latest.version + 1, "scope": scope, "condition": cond,
                                          "status": "proposed", "supersedes": ref(latest), "recorded_at": rt.now,
                                          "title": title})
        cases = list(rt.store.get("rule_cases", rid) or [])
        prop = self.build_proposal(wider, cases=cases, author_role=wider.authority_required, actor=principal)
        rest = [k for k in case_keys if k != key]
        prop = prop.model_copy(update={"widen_next": {"remove": rest[0]} if rest else None})
        self.store_proposal(prop)
        rt.emit("rule", principal, f"Proposed widening {rid} to v{wider.version} (drops {key}) · would flip "
                f"{len({f.entity_id for f in prop.would_flip.flips})}", "INFO", ref(wider),
                prop.would_flip.total_delta_cents or None)
        return prop

    # ---- asked again (asked-again-v1): a ruled pattern, a case outside the rule's scope -------------------
    def rule_pattern(self, rule: Rule) -> str | None:
        """The question pattern a rule settles: the scripted rules by their canned question, else the pattern of the
        question its origin ruling answered."""
        from contracts import stub_app as stub
        canned = stub.RULE_TO_QUESTION.get(rule.id)
        if canned is not None:
            return next((p for p, c in PATTERN_TO_CANNED.items() if c == canned), None)
        ruling = self.rt.store.get("ruling", rule.origin_ruling_id) if rule.origin_ruling_id else None
        q = self.rt.store.get("question", ruling["question_id"]) if ruling and ruling.get("question_id") else None
        return q["pattern"] if q else None

    @staticmethod
    def _fid(case_ref: str) -> str:
        return case_ref.rsplit(":", 1)[0] if ":" in case_ref.split("@", 1)[-1] else case_ref

    def case_value(self, case_ref: str, key: str) -> Any:
        """A case's value for a scope key: the engine's features for its flight, else the world's airports."""
        fid = self._fid(case_ref)
        feats = self.features().get(fid) or {}
        if key in feats:
            return feats[key]
        fl = next((f for f in (self.world.flights if self.world else []) if f.id == fid), None)
        if fl is None:
            return None
        if key in ("flight.departs_eu", "flight.arrives_eu"):
            ap = compose.airport_by(self.world, fl.origin if key == "flight.departs_eu" else fl.dest)
            return ap.eu if ap else None
        return None

    def _flight_words(self, case_ref: str) -> tuple[str, str, str]:
        """("NS30", "Boston → Dublin", "BOS→DUB") for a case."""
        fid = self._fid(case_ref)
        fl = next((f for f in (self.world.flights if self.world else []) if f.id == fid), None)
        if fl is None:
            return fid.split("@")[0], "", ""

        def city(code: str) -> str:
            ap = compose.airport_by(self.world, code)
            return ap.name.split()[0] if ap and ap.name else code
        return fl.number, f"{city(fl.origin)} → {city(fl.dest)}", f"{fl.origin}→{fl.dest}"

    def asked_again(self, q: Question) -> AskedAgain | None:
        """Why an unanswered question asks again although its pattern has an active rule: its case falls outside
        that rule's case-scoped keys (the rule is never stretched; widening is explicit). A read-time view only."""
        if q.status == "answered" or not q.case_refs:
            return None
        for rule in sorted(self.rt.rules(), key=lambda r: r.id):
            if rule.status != "active" or rule.recorded_at > q.asked_at or self.rule_pattern(rule) != q.pattern:
                continue
            for key, v in rule.scope.items():
                if not (isinstance(v, str) and v.startswith("case:")):
                    continue
                raw = v.split(":", 1)[1]
                want: Any = {"true": True, "false": False}.get(raw.lower(), raw)
                outside = [c for c in q.case_refs if (got := self.case_value(c, key)) is not None and got != want]
                if not outside:
                    continue
                num, route, pair = self._flight_words(outside[0])
                covers, case_is, wider = SCOPE_WORDS.get(key, {}).get(want, (
                    f"cases where {key} is {raw}", f"has {key} = {self.case_value(outside[0], key)}",
                    f"cases where {key} is anything"))
                more = f" (and {len(outside) - 1} more)" if len(outside) > 1 else ""
                subject = f"{num} {route}".strip()
                reason = (f"Your rule {rule.id} covers {covers}. {subject}{more} {case_is}, so it asks instead of "
                          "stretching your ruling.")
                p = self.proposal(rule.id)
                nxt = p.widen_next if p and p.widen_next and p.widen_next.get("remove") == key else None
                if key in SCOPE_WORDS:
                    question = f"Also cover {wider}" + (f" (e.g. {pair})" if pair else "") + "?"
                else:
                    question = (nxt or {}).get("question") or f"Widen {rule.id} (drop {key})?"
                return AskedAgain(rule_ref=ref(rule), rule_title=rule.title, reason=reason,
                                  widen=WidenOffer(rule_id=rule.id, question=question))
        return None

    def asked_again_for(self, rule_id: str) -> list[tuple[Question, AskedAgain]]:
        rid = base_id(rule_id)
        out = []
        for q in self.rt.questions():
            aa = self.asked_again(q)
            if aa is not None and aa.widen is not None and aa.widen.rule_id == rid:
                out.append((q, aa))
        return out

    def widen_and_apply(self, rule_id: str, role: Role, author: str, principal: str) -> RuleProposal:
        """One-click widen from an asked-again question, by the rule's authority: propose one rung wider, confirm
        it (replay re-decides the cases now in scope, recorded like any confirm), then close each asked-again
        question with a ruling that says so."""
        asks = self.asked_again_for(rule_id)
        prop = self.widen(rule_id, principal)
        rule, diff = self.confirm(rule_id, principal)
        for q, aa in asks:
            self.record_ruling(question=q, role=role, author=author, principal=principal, kind="answer",
                               decision=aa.widen.question if aa.widen else f"Widen {rule.id}",
                               explanation=f"Widened {aa.rule_ref} to {ref(rule)}: {rule.title}")
            self.rt.emit("ruling", principal, f"{compose.label(role)} widened {aa.rule_ref} → {ref(rule)} from {q.id}"
                         f" · {len({f.entity_id for f in diff.flips})} settled", "RULED", q.id,
                         diff.total_delta_cents or None)
        return prop.model_copy(update={"rule": rule, "would_flip": diff})

    def reject(self, rule_id: str, role: Role, author: str, principal: str,
               explanation: str) -> tuple[Ruling, RuleProposal | None]:
        rt = self.rt
        rid = base_id(rule_id)
        rule = self.rules().get(rid)
        p = self.proposal(rid) or (None if rule else self.canned_for(rid, principal))
        target = rule or (p.rule if p else None)
        if target is None:
            raise LifecycleError(404, "not_found", f"No rule or proposal {rule_id}.")
        if target.tier in ("hard_control", "regulation") or target.static_card:
            raise LifecycleError(403, "forbidden", f"{rid} is a {target.tier.replace('_', ' ')}; it cannot be "
                                                   "rejected (hard controls are code).")
        ruling = self.record_ruling(question=None, role=role, author=author, principal=principal, kind="rejection",
                                    decision="reject", explanation=explanation)
        if rule is not None and rule.status == "active" and rule.kind != "release":
            self.revert(rid, principal, reason=f"rejected ({ruling.id})")
        else:
            rt.store.put("proposal_state", rid, {"state": "rejected", "ruling": ruling.id}, rt.now)
            if rule is not None:
                rt.store.put("rule", rid, rule.model_copy(update={"status": "retired"}), rt.now)
            rt.record("record_rule", target, principal, rt.now, event="retired", reason=f"rejected ({ruling.id})")
        proposal = None
        if target.kind == "release" or rid == "R-CTL-1":
            q = next((Question.model_validate(x) for x in rt.store.all("question") if x["pattern"] == "cohort_release"),
                     None)
            if q is not None:
                proposal = self.draft_proposal(q, ruling.model_copy(update={"question_id": q.id}), principal)
        rt.emit("ruling", principal, f"{compose.label(role)} rejected {rid}"
                + (f" · rule {ref(proposal.rule)} proposed" if proposal else ""), "RULED", rid)
        return ruling, proposal

    # ---- views ------------------------------------------------------------------
    def citations(self) -> dict[str, dict[str, int]]:
        """Citations as a view, per rule ref and storm run: flight-level rules once per decision, coupon-level
        rules once per coupon."""
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for fid, d in self.decisions().items():
            run = self.run_of(fid) or "unassigned"
            flight_level = set(d.rules_applied)
            for r in flight_level:
                counts[r][run] += 1
            for e in self.ents(fid):
                for r in set(e.rules_applied) - flight_level:
                    counts[r][run] += 1
        return {r: dict(by_run) for r, by_run in counts.items()}

    def times_cited(self) -> dict[str, int]:
        return {r: sum(by_run.values()) for r, by_run in self.citations().items()}

    def with_views(self, rule: Rule) -> Rule:
        by_run = self.citations().get(ref(rule), {})
        return rule.model_copy(update={"times_cited": sum(by_run.values()), "cases_settled_by_storm": by_run})

    def rules_view(self) -> list[Rule]:
        cited = self.citations()
        return [r.model_copy(update={"times_cited": sum(cited[ref(r)].values()) if ref(r) in cited else r.times_cited,
                                     "cases_settled_by_storm": cited.get(ref(r), r.cases_settled_by_storm)})
                for r in self.rt.rules()]

    def reject_target(self, q: Question) -> str | None:
        """Justin #11: the rule a "Reject" on this question targets. Once ruled on, the rule drafted from the
        ruling; before that, only a release proposal has one (its Reject keeps the tail: R-CTL-1)."""
        ruled = self.rt.store.get("ruling_for", q.id)
        if ruled is not None:
            return next((p.rule.id for k in self.rt.store.keys("proposal") if (p := self.proposal(k)) is not None
                         and p.rule.origin_ruling_id == ruled["ruling_id"]), None)
        if q.pattern != "cohort_release":
            return None
        from contracts import stub_app as stub
        canned = PATTERN_TO_CANNED[q.pattern]
        return next((rid for rid, qid in stub.RULE_TO_QUESTION.items() if qid == canned), None)
