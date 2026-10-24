"""Rulings → rules → replay, on the real engine modules and Books ("never ask twice", plan §1.4, THREAD D5).

Until `engine.lifecycle` lands, the server orchestrates it:
1. `answer` records a `Ruling` (append-only doc + commit) and drafts a `RuleProposal`: the Drafter's
   `propose_rule` when one exists, else the scripted proposal for the known patterns (R-CL-1 / R-LEG-1 / R-CTL-1,
   the stub's), else none (the ruling is applied to its cases directly as an override).
2. `would_flip` is a real replay: re-decide the affected flights with the candidate rule set (flight-level rules
   flip `needs_legal` decisions on the rule's cases or wherever the DSL matches), recompute entitlements with
   `engine.eu261` (coupon-level rules such as R-CL-1 go through the engine's own DSL), price the change with
   `Books.preview`.
3. `confirm` activates the rule, writes the new decisions/entitlements, posts `Books.post_recode` and updates the
   storm run and flight files. `revert` retires it and replays back. `widen` drops one `case:` scope key.
The engine decides; the server never computes an amount (Books does) and never pre-answers a question.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable

from contracts.models import (
    Entitlement, Extraordinary, FlightDecision, FlightFile, Question, ReplayDiff, ReplayFlip, Role, Rule,
    RuleAction, RuleProposal, Ruling, StormRun, World,
)

from . import compose
from .impls import _module, call

if TYPE_CHECKING:
    from .runtime import Runtime

FLIGHT_ACTIONS = {RuleAction.SET_EXTRAORDINARY: Extraordinary.YES,
                  RuleAction.SET_NOT_EXTRAORDINARY: Extraordinary.NO}
COHORT_ACTIONS = {RuleAction.KEEP_TAIL, RuleAction.DENY_RELEASE}
PATTERN_TO_CANNED = {"voucher_in_lieu_unsigned": "Q-1", "knock_on_return": "Q-2", "cohort_release": "Q-3"}
AUTHORITY = {  # THREAD D4: who may author what
    Role.CLAIMS_LEAD: {"voucher", "entitlement", "routing"},
    Role.LEGAL: {"cause", "entitlement", "regime", "routing"},
    Role.CONTROLLER: {"release", "routing"},
}
TIER_FOR_ROLE = {Role.CLAIMS_LEAD: "claims_lead_ruling", Role.LEGAL: "legal_ruling",
                 Role.CONTROLLER: "controller_ruling"}


class LifecycleError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def base_id(rule_id: str) -> str:
    return rule_id.split("@", 1)[0]


def ref(rule: Rule) -> str:
    return f"{rule.id}@{rule.version}"


# ---------------------------------------------------------------- features (until engine.cause exposes them)
_SPARE = re.compile(r"STD\s*\+\s*(\d+)\s*h\s*(\d+)?", re.I)


def flight_features(world: World, d: FlightDecision, ents: list[Entitlement],
                    decisions: dict[str, FlightDecision]) -> dict[str, Any]:
    f = next((x for x in world.flights if x.id == d.flight_id), None)
    if f is None:
        return {"flight": d.flight_id}
    o, a = compose.airport_by(world, f.origin), compose.airport_by(world, f.dest)
    feats: dict[str, Any] = {
        "flight": f.id, "flight.in_window_dep": d.in_window_dep, "flight.in_window_arr": d.in_window_arr,
        "flight.window_margin_min": d.window_margin_min, "flight.ops_cause_code": f.ops_cause_code,
        "flight.operating_carrier_eu": f.operating_carrier_eu, "flight.is_return_sector": f.outbound_pair_id is not None,
        "flight.departs_eu": o.eu if o else None, "flight.arrives_eu": a.eu if a else None,
    }
    if ents:
        feats["flight.distance_km"] = ents[0].distance_km
        feats["flight.band_eur"] = ents[0].band_eur
    geo = _module("engine.geo")
    if geo is not None and o and a:
        try:
            feats["flight.route_region"] = geo.route_region(o, a)
        except Exception:
            pass
    prev_id = f.outbound_pair_id or f.inbound_flight_id
    if prev_id:
        prev = next((x for x in world.flights if x.id == prev_id), None)
        feats["rotation.prev_cancelled"] = prev is not None and prev.status == "cancelled"
        pd = decisions.get(prev_id)
        if pd is not None:
            feats["rotation.prev_cause"] = pd.cause.value
    for e in world.ops_log:
        if f.id in e.flight_ids and e.kind == "spares":
            m = _SPARE.search(e.text)
            if m:
                feats["spare.available_within_h"] = round(int(m.group(1)) + int(m.group(2) or 0) / 60, 2)
            elif re.search(r"\bno (long-range )?tail\b", e.text, re.I):
                feats.setdefault("spare.available_within_h", None)
        if f.id in e.flight_ids and re.search(r"earliest (re-?route|reroute)", e.text, re.I):
            feats["pax.reroute_earliest_offered"] = True
    for s in world.sources:
        if s.text and f.number in s.text and re.search(r"earliest re-?route", s.text, re.I):
            feats.setdefault("pax.reroute_earliest_offered", True)
    return feats


def rule_applies(rule: Rule, feats: dict[str, Any], cases: Iterable[str], known_at: datetime,
                 flight_date: Any = None) -> bool:
    """A flight-level rule applies to its own cases (the ruling was about them) or wherever its DSL matches."""
    if rule.status != "active" or rule.recorded_at > known_at:
        return False
    if feats.get("flight") in set(cases):
        return True
    dsl = _module("engine.dsl")
    if dsl is None:
        return False
    try:
        return bool(dsl.applies(rule, feats, known_at, flight_date))
    except Exception:
        return False


# ---------------------------------------------------------------- lifecycle
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

    def cases(self, rule_id: str) -> list[str]:
        return list(self.rt.store.get("rule_cases", base_id(rule_id)) or [])

    def decisions(self) -> dict[str, FlightDecision]:
        return {k: FlightDecision.model_validate(self.rt.store.get("decision", k))
                for k in self.rt.store.keys("decision")}

    def ents(self, fid: str) -> list[Entitlement]:
        return [Entitlement.model_validate(e) for e in (self.rt.store.get("entitlements", fid) or [])]

    def original(self, fid: str) -> FlightDecision:
        """The engine's own decision for the flight (first version), before any ruling or rule."""
        hist = self.rt.store.history("decision", fid)
        return FlightDecision.model_validate(hist[0][1])

    # ---- re-decide -------------------------------------------------------
    def redecide(self, fid: str, rules: list[Rule], decisions: dict[str, FlightDecision],
                 known_at: datetime) -> FlightDecision:
        base = self.original(fid)
        cur = decisions.get(fid, base)
        if cur.outcome == "human" and not any(r for r in cur.rules_applied if base_id(r) in {x.id for x in rules}):
            return cur          # a person ruled on this case directly (override): rules never undo that
        if base.extraordinary != Extraordinary.NEEDS_LEGAL or self.world is None:
            return base
        feats = flight_features(self.world, base, self.ents(fid), decisions)
        cands = [r for r in rules if r.action in FLIGHT_ACTIONS and not r.static_card]
        dsl = _module("engine.dsl")
        if dsl is not None:
            cands.sort(key=dsl.precedence_key, reverse=True)
        flight = next((f for f in self.world.flights if f.id == fid), None)
        for r in cands:
            if rule_applies(r, feats, self.cases(r.id), known_at, flight.date if flight else None):
                return flipped(base, r, known_at)
        return base

    def replay(self, rules_after: list[Rule], *, flights: Iterable[str] | None = None,
               rule_ref: str = "replay") -> tuple[ReplayDiff, list[tuple]]:
        """Re-decide + re-entitle; price with Books.preview. Writes nothing. Returns (diff, changes)."""
        rt = self.rt
        now = rt.now
        decs = self.decisions()
        targets = list(flights) if flights is not None else list(decs)
        changes = []
        all_before: list[Entitlement] = []
        all_after: list[Entitlement] = []
        for fid in targets:
            if fid not in decs or self.world is None:
                continue
            before_d, before_e = decs[fid], self.ents(fid)
            after_d = self.redecide(fid, rules_after, decs, now)
            after_e = compose.entitlements_for(after_d, self.world, rules_after, now, rt.impls.engine)
            sig = lambda es: [(e.coupon_id, e.status, e.compensation_cents, e.voucher_offset_cents, e.reduction,
                               tuple(e.rules_applied)) for e in es]
            d_changed = (before_d.extraordinary, before_d.rules_applied) != (after_d.extraordinary,
                                                                          after_d.rules_applied)
            if d_changed or sig(before_e) != sig(after_e):
                changes.append((fid, before_d, after_d, before_e, after_e))
                all_before += before_e
                all_after += after_e
        preview = None
        if rt.books is not None and changes:
            try:
                preview = rt.books.preview(all_before, all_after)
            except Exception:
                preview = None
        delta_by = {f.entity_id: f.delta_cents for f in (preview.flips if preview else [])}
        flips: list[ReplayFlip] = []
        for fid, bd, ad, be, ae in changes:
            if bd.extraordinary != ad.extraordinary:
                flips.append(ReplayFlip(entity_id=fid, field="extraordinary", before=bd.extraordinary.value,
                                        after=ad.extraordinary.value, delta_cents=delta_by.get(fid, 0)))
            else:
                bmap = {e.coupon_id: e for e in be}
                n = 0
                for e in ae:
                    b = bmap.get(e.coupon_id)
                    if b is not None and b.status != e.status:
                        flips.append(ReplayFlip(entity_id=e.coupon_id, field="status", before=b.status,
                                                after=e.status, delta_cents=0))
                        n += 1
                if not n and delta_by.get(fid):
                    flips.append(ReplayFlip(entity_id=fid, field="eu261_liability_cents", before=None, after=None,
                                            delta_cents=delta_by[fid]))
        locked = rt.books.locked_periods() if rt.books is not None and hasattr(rt.books, "locked_periods") else []
        diff = ReplayDiff(rule_ref=rule_ref, known_at=now, flips=flips,
                          total_delta_cents=preview.total_delta_cents if preview else 0,
                          locked_periods_untouched=list(locked))
        return diff, changes

    def apply(self, changes: list[tuple], *, reason: str, rule_ref: str | None) -> list[str]:
        """Write re-decided flights: decision + entitlement commits, Books recode, flight files, storm runs."""
        rt = self.rt
        now = rt.now
        if not changes:
            return []
        before_all, after_all = [], []
        for fid, bd, ad, be, ae in changes:
            c = rt.store.commit(kind="decision", actor="agent.engine", at=now, payload=ad, payload_ref=fid,
                                inputs=rt.inputs(*(x for x in [bd.commit, rule_ref] if x)),
                                message=f"{fid.split('@')[0]} · {ad.extraordinary.value} · {reason}")
            ad = ad.model_copy(update={"commit": c.hash})
            rt.store.put("decision", fid, ad, now)
            rt.store.put("entitlements", fid, ae, now)
            rt.store.commit(kind="entitlement", actor="agent.engine", at=now, payload=ae, payload_ref=fid,
                            inputs=rt.inputs(c.hash), message=f"{fid.split('@')[0]} · {len(ae)} entitlements · "
                            f"{reason}")
            before_all += be
            after_all += ae
        je_ids: list[str] = []
        if rt.books is not None:
            try:
                jes = call(rt.books.post_recode, before_all, after_all, now, rule_ref=rule_ref)
            except Exception:
                jes = []
            for je in jes:
                rt.store.commit(kind="journal_event", actor="agent.books", at=now, payload=je, payload_ref=je.id,
                                inputs=rt.inputs(*(x for x in [rule_ref] if x)),
                                message=f"{je.id} drafted · {je.kind} · {reason}")
                je_ids.append(je.id)
                amt = sum(line.cr_cents - line.dr_cents for line in je.lines if line.account == "2140")
                rt.emit("journal", "agent.books", f"Drafted {je.id} · {je.kind.replace('_', ' ')} · "
                        f"{'+' if amt >= 0 else '−'}{compose.eur(abs(amt))} EU261 compensation liability · "
                        "drafted, pending approval", "DRAFTED", je.id, amt)
        for fid, *_ in changes:
            self._refresh_flight(fid, None, None)     # journal preview now includes the recode
        self.refresh_runs({fid for fid, *_ in changes})
        return je_ids

    def _refresh_flight(self, fid: str, d: FlightDecision | None, ents: list[Entitlement] | None) -> None:
        rt = self.rt
        data = rt.store.get("flight_file", fid)
        if data is None or self.world is None:
            return
        ff = FlightFile.model_validate(data)
        d = d or FlightDecision.model_validate(rt.store.get("decision", fid))
        ents = ents if ents is not None else self.ents(fid)
        journal = list(rt.books.journal()) if rt.books is not None else ff.journal_preview
        run = self._run_of(fid)
        obs = run.metar if run else []
        windows = run.windows if run else []
        new = compose.flight_file(self.world, ff.flight, d, ents, journal, obs, windows,
                                  ff.explanation if ff.decision.reason == d.reason else
                                  compose.template_explanation(d))
        rt.store.put("flight_file", fid, new, rt.now)

    def _run_of(self, fid: str) -> StormRun | None:
        for key in self.rt.store.keys("storm_run"):
            data = self.rt.store.get("storm_run", key)
            if any(r["flight"]["id"] == fid for r in data["flights"]):
                return StormRun.model_validate(data)
        return None

    def refresh_runs(self, fids: set[str] | None = None) -> None:
        rt = self.rt
        decs = self.decisions()
        for key in rt.store.keys("storm_run"):
            run = StormRun.model_validate(rt.store.get("storm_run", key))
            ids = {r.flight.id for r in run.flights}
            if fids is not None and not ids & fids:
                continue
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
    def next_id(self, kind: str, prefix: str) -> str:
        return f"{prefix}-{len(self.rt.store.keys(kind)) + 1:04d}"

    def record_ruling(self, *, question_id: str | None, role: Role, author: str, kind: str, decision: str,
                      explanation: str) -> Ruling:
        rt = self.rt
        ruling = Ruling(id=self.next_id("ruling", "RUL"), question_id=question_id, author_role=role, author=author,
                        kind=kind, decision=decision, explanation=explanation, at=rt.now)
        rt.store.put("ruling", ruling.id, ruling, rt.now)
        if question_id:
            rt.store.put("ruling_for", question_id, {"ruling_id": ruling.id}, rt.now)
        rt.store.commit(kind="ruling", actor=f"{role.value}:{author}", at=rt.now, payload=ruling,
                        payload_ref=ruling.id, inputs=rt.inputs(*(x for x in [question_id] if x)),
                        message=f"{ruling.id} · {kind} by {compose.label(role)} · {decision[:80]}")
        return ruling

    def answer(self, q: Question, role: Role, author: str, principal: str, decision: str,
               explanation: str) -> tuple[Ruling, RuleProposal | None]:
        rt = self.rt
        lowered = decision.lower().strip()
        kind = "rejection" if q.pattern in ("cohort_release",) or lowered.startswith(("reject", "keep", "never")) \
            else "answer"
        ruling = self.record_ruling(question_id=q.id, role=role, author=author, kind=kind, decision=decision,
                                    explanation=explanation)
        proposal = self.draft_proposal(q, ruling)
        if proposal is not None:
            self.store_proposal(proposal, cases=q.case_refs)
            rt.emit("ruling", principal, f"{compose.label(role)} ruled on {q.id} · rule {ref(proposal.rule)} proposed"
                    f" · would flip {len(proposal.would_flip.flips)}", "RULED", q.id,
                    proposal.would_flip.total_delta_cents or q.holds_cents or None)
        else:
            settled = self.override(q, ruling)
            rt.emit("ruling", principal, f"{compose.label(role)} ruled on {q.id} · {settled} case(s) updated",
                    "RULED", q.id, q.holds_cents or None)
        return ruling, proposal

    def draft_proposal(self, q: Question, ruling: Ruling) -> RuleProposal | None:
        rt = self.rt
        rule: Rule | None = None
        drafter = rt.impls.drafter
        canned = PATTERN_TO_CANNED.get(q.pattern)
        if canned is None and drafter is not None and hasattr(drafter, "propose_rule"):
            try:
                rule = drafter.propose_rule(ruling, q, [])
            except Exception:
                rule = None
        if rule is None and canned is not None:
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
                rt.store.put("rule_cases", rule.id, list(q.case_refs), rt.now)
                return base.model_copy(update={"rule": rule})
        else:
            widen_next = None
        if rule is None:
            return None
        if rule.recorded_at < rt.now:
            rule = rule.model_copy(update={"recorded_at": rt.now})
        return self.build_proposal(rule, cases=q.case_refs, author_role=ruling.author_role, widen_next=widen_next)

    def build_proposal(self, rule: Rule, *, cases: list[str], author_role: Role,
                       widen_next: dict[str, Any] | None = None) -> RuleProposal:
        active = rule.model_copy(update={"status": "active"})
        others = [r for r in self.rt.rules() if r.id != rule.id and r.status == "active"]
        diff, changes = self.replay([*others, active], rule_ref=ref(rule), flights=None) \
            if rule.action not in COHORT_ACTIONS else (self.cohort_preview(rule), [])
        self.rt.store.put("rule_cases", rule.id, list(cases), self.rt.now)
        checks = self.checks(rule, cases, changes, author_role, others)
        if widen_next is None:
            keys = [k for k, v in rule.scope.items() if isinstance(v, str) and v.startswith("case:")]
            widen_next = {"remove": keys[0]} if keys else None
        return RuleProposal(rule=rule, checks=checks, would_flip=diff, widen_next=widen_next)

    def cohort_preview(self, rule: Rule) -> ReplayDiff:
        cohort = rule.scope.get("cohort")
        cohort = compose_strip(cohort) if cohort else None
        flips = []
        if cohort and self.rt.books is not None:
            try:
                bal = int(self.rt.books.gl_balance("2140", cohort=cohort))
                flips = [ReplayFlip(entity_id=cohort, field="release_proposed_cents", before=bal, after=0)]
            except Exception:
                flips = []
        return ReplayDiff(rule_ref=ref(rule), known_at=self.rt.now, flips=flips, total_delta_cents=0)

    def checks(self, rule: Rule, cases: list[str], changes: list[tuple], author_role: Role,
               others: list[Rule]) -> dict[str, bool]:
        dsl = _module("engine.dsl")
        compiles = True
        if dsl is not None:
            try:
                compiles = not dsl.validate(rule.condition) and not dsl.validate_scope(rule.scope)
            except Exception:
                compiles = False
        changed = {fid for fid, *_ in changes} | {e.coupon_id for *_, ae in changes for e in ae}
        reproduces = rule.action in COHORT_ACTIONS or bool(set(cases) & changed) or not cases
        grounded = bool(rule.grounding) or all(isinstance(v, str) and v.startswith("case:")
                                               for v in rule.scope.values())
        authority = rule.kind in AUTHORITY.get(author_role, set()) and rule.authority_required == author_role
        conflict = any(o.kind == rule.kind and o.tier == rule.tier and o.action != rule.action
                       and set(o.scope) == set(rule.scope) for o in others)
        return {"compiles": compiles, "reproduces_case": reproduces, "no_hard_control": rule.tier != "hard_control",
                "grounded": grounded, "author_has_authority": authority, "no_conflict": not conflict}

    def store_proposal(self, p: RuleProposal, cases: list[str] | None = None) -> None:
        self.rt.store.put("proposal", p.rule.id, p, self.rt.now)
        if cases is not None:
            self.rt.store.put("rule_cases", p.rule.id, list(cases), self.rt.now)

    # ---- override (no rule: the ruling is applied to its own cases) ---------
    def override(self, q: Question, ruling: Ruling) -> int:
        text = f"{ruling.decision} {ruling.explanation}".lower()
        if "not extraordinary" in text or "technical" in text or "owed" in text:
            target = Extraordinary.NO
        elif "extraordinary" in text or "weather" in text:
            target = Extraordinary.YES
        else:
            return 0
        decs = self.decisions()
        changes = []
        now = self.rt.now
        for fid in q.case_refs:
            if fid not in decs or self.world is None:
                continue
            bd = decs[fid]
            ad = bd.model_copy(update={"extraordinary": target, "outcome": "human", "routed_to": None,
                                       "question_id": None, "known_at": now, "commit": None,
                                       "reason": f"Ruled by {compose.label(ruling.author_role)} ({ruling.id}): "
                                                 f"{ruling.decision[:120]}"})
            rules = self.rt.rules()
            ae = compose.entitlements_for(ad, self.world, rules, now, self.rt.impls.engine)
            changes.append((fid, bd, ad, self.ents(fid), ae))
        self.apply(changes, reason=f"ruling {ruling.id}", rule_ref=None)
        return len(changes)

    # ---- confirm / reject / widen / revert ----------------------------------
    def confirm(self, rule_id: str, principal: str) -> tuple[Rule, ReplayDiff]:
        rt = self.rt
        rid = base_id(rule_id)
        p = self.proposal(rid)
        if p is None:
            p = self.canned_for(rid)
        if p is None:
            existing = self.rules().get(rid)
            if existing is None:
                raise LifecycleError(404, "not_found", f"No proposal {rule_id}.")
            return existing, ReplayDiff(rule_ref=ref(existing), known_at=rt.now, flips=[], total_delta_cents=0)
        rule = p.rule.model_copy(update={"status": "active", "recorded_at": rt.now})
        others = [r for r in rt.rules() if r.id != rid and r.status == "active"]
        cases = self.cases(rid)
        if rule.action in COHORT_ACTIONS:
            diff = self.cohort_preview(rule)
            if rt.books is not None and hasattr(rt.books, "keep_tail"):
                cohort = rule.scope.get("cohort")
                try:
                    rt.books.keep_tail(ref(rule), [compose_strip(cohort)] if cohort else None, rt.now)
                except Exception:
                    pass
            je_ids: list[str] = []
            settled = len(diff.flips)
        else:
            rt.store.put("rule", rid, rule, rt.now)     # active before replay so the engine sees it
            diff, changes = (self.replay([*others, rule], rule_ref=ref(rule)) if self.world is not None
                             else (p.would_flip, []))
            je_ids = self.apply(changes, reason=f"rule {ref(rule)}", rule_ref=ref(rule))
            settled = len(changes)
            diff = diff.model_copy(update={"adjustment_je_ids": je_ids})
        rt.store.put("rule", rid, rule, rt.now)
        rt.store.commit(kind="rule_event", actor=principal, at=rt.now, payload=rule, payload_ref=ref(rule),
                        inputs=rt.inputs(*(x for x in [rule.origin_ruling_id] if x)),
                        message=f"{ref(rule)} active · {settled} settled")
        rt.store.put("proposal_state", rid, {"state": "confirmed", "rule_ref": ref(rule)}, rt.now)
        cited = self.times_cited().get(ref(rule), 0)
        rt.emit("rule", principal, f"Saved as policy {ref(rule)} · never asked again · {settled} settled · cited "
                f"{cited}×", "LEARNED", ref(rule), diff.total_delta_cents or None)
        return self.with_views(rule), diff

    def canned_for(self, rid: str) -> RuleProposal | None:
        """Screens can be built in any order: the scripted rules confirm even before their question is answered."""
        from contracts import stub_app as stub
        qid = stub.RULE_TO_QUESTION.get(rid)
        if qid is None:
            return None
        q = next((Question.model_validate(x) for x in self.rt.store.all("question") if x["id"] == qid), None)
        if q is None:
            return None
        r = Ruling(id=f"RUL-{qid}", question_id=qid, author_role=q.routed_to, author="(as recommended)",
                   kind="rejection" if qid == "Q-3" else "answer", decision=q.recommended_option, explanation="",
                   at=self.rt.now)
        p = self.draft_proposal(q, r)
        if p is not None:
            self.store_proposal(p, cases=q.case_refs)
        return p

    def revert(self, rule_id: str, principal: str, *, status: str = "retired") -> ReplayDiff:
        rt = self.rt
        rid = base_id(rule_id)
        rule = self.rules().get(rid)
        if rule is None:
            raise LifecycleError(404, "not_found", f"No rule {rule_id}.")
        if rule.tier in ("hard_control", "regulation") or rule.static_card:
            raise LifecycleError(403, "forbidden", f"{rid} is a {rule.tier.replace('_', ' ')}: hard controls are "
                                                   "code and regulation versions are not reverted.")
        retired = rule.model_copy(update={"status": status})
        rt.store.put("rule", rid, retired, rt.now)
        others = [r for r in rt.rules() if r.status == "active"]
        diff, changes = self.replay(others, rule_ref=ref(rule))
        je_ids = self.apply(changes, reason=f"revert {ref(rule)}", rule_ref=ref(rule))
        rt.store.commit(kind="revert", actor=principal, at=rt.now, payload=retired, payload_ref=ref(rule),
                        inputs=rt.inputs(), message=f"{ref(rule)} {status} · {len(changes)} flipped back")
        locked = ", ".join(diff.locked_periods_untouched)
        rt.emit("replay", principal, f"Reverted {ref(rule)} · flips {len(diff.flips)}"
                + (f" · {locked} locked, untouched" if locked else ""), "INFO", ref(rule),
                diff.total_delta_cents or None)
        return diff.model_copy(update={"adjustment_je_ids": je_ids})

    def widen(self, rule_id: str) -> RuleProposal:
        rt = self.rt
        rid = base_id(rule_id)
        p = self.proposal(rid)
        rule = self.rules().get(rid) or (p.rule if p else None)
        if rule is None:
            p = self.canned_for(rid)
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
                            "until the six-year limitation"}.get(rid, latest.title)
        wider = latest.model_copy(update={"version": latest.version + 1, "scope": scope, "condition": cond,
                                          "status": "proposed", "supersedes": ref(latest), "recorded_at": rt.now,
                                          "title": title})
        cases = self.cases(rid)
        prop = self.build_proposal(wider, cases=cases, author_role=wider.authority_required)
        rest = [k for k in case_keys if k != key]
        prop = prop.model_copy(update={"widen_next": {"remove": rest[0]} if rest else None})
        self.store_proposal(prop)
        rt.emit("rule", "agent.engine", f"Proposed widening {rid} to v{wider.version} (drops {key}) · would flip "
                f"{len(prop.would_flip.flips)}", "INFO", ref(wider), prop.would_flip.total_delta_cents or None)
        return prop

    def reject(self, rule_id: str, role: Role, author: str, principal: str,
               explanation: str) -> tuple[Ruling, RuleProposal | None]:
        rt = self.rt
        rid = base_id(rule_id)
        rule = self.rules().get(rid)
        p = self.proposal(rid) or (None if rule else self.canned_for(rid))
        target = rule or (p.rule if p else None)
        if target is None:
            raise LifecycleError(404, "not_found", f"No rule or proposal {rule_id}.")
        if target.tier in ("hard_control", "regulation") or target.static_card:
            raise LifecycleError(403, "forbidden", f"{rid} is a {target.tier.replace('_', ' ')}; it cannot be "
                                                   "rejected (hard controls are code).")
        from contracts import stub_app as stub
        qid = stub.RULE_TO_QUESTION.get(rid)
        ruling = self.record_ruling(question_id=None, role=role, author=author, kind="rejection", decision="reject",
                                    explanation=explanation)
        if rule is not None and rule.status == "active" and rule.kind != "release":
            self.revert(rid, principal)
        else:
            rt.store.put("proposal_state", rid, {"state": "rejected", "ruling": ruling.id}, rt.now)
        proposal = None
        if target.kind == "release" or rid == "R-CTL-1":
            q = next((Question.model_validate(x) for x in rt.store.all("question") if x["pattern"] == "cohort_release"),
                     None)
            if q is not None:
                r2 = ruling.model_copy(update={"question_id": qid or q.id})
                proposal = self.draft_proposal(q, r2)
                if proposal is not None:
                    self.store_proposal(proposal, cases=q.case_refs)
        rt.emit("ruling", principal, f"{compose.label(role)} rejected {rid}"
                + (f" · rule {ref(proposal.rule)} proposed" if proposal else ""), "RULED", rid)
        return ruling, proposal

    # ---- views ------------------------------------------------------------------
    def times_cited(self) -> dict[str, int]:
        """Citations as a view: flight-level rules once per decision, coupon-level rules once per coupon."""
        counts: dict[str, int] = {}
        for fid, d in self.decisions().items():
            flight_level = set(d.rules_applied)
            for r in flight_level:
                counts[r] = counts.get(r, 0) + 1
            for e in self.ents(fid):
                for r in set(e.rules_applied) - flight_level:
                    counts[r] = counts.get(r, 0) + 1
        return counts

    def with_views(self, rule: Rule) -> Rule:
        return rule.model_copy(update={"times_cited": self.times_cited().get(ref(rule), 0)})

    def rules_view(self) -> list[Rule]:
        cited = self.times_cited()
        return [r.model_copy(update={"times_cited": cited.get(ref(r), r.times_cited)}) for r in self.rt.rules()]


def flipped(base: FlightDecision, rule: Rule, known_at: datetime) -> FlightDecision:
    target = FLIGHT_ACTIONS[rule.action]
    why = rule.title or f"{rule.id} applies"
    return base.model_copy(update={
        "extraordinary": target, "outcome": "auto", "routed_to": None, "question_id": None, "known_at": known_at,
        "commit": None, "rules_applied": [*base.rules_applied, ref(rule)],
        "legal_basis": list(dict.fromkeys([*base.legal_basis, "CJEU C-74/19"] if rule.kind == "cause"
                                          else base.legal_basis)),
        "reason": f"{'Extraordinary' if target == Extraordinary.YES else 'Not extraordinary'} under {ref(rule)}: "
                  f"{why[:160]}"})


def compose_strip(v: Any) -> Any:
    if isinstance(v, str) and v.startswith("case:"):
        return v[len("case:"):]
    return v
