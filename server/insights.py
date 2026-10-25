"""Pitch insights (INSIGHTS_SPEC v1): computed views over the runs' real data. Nothing here is stored, so no doc,
commit, hash or golden file changes.

- `effort(rt, run_id)`: the work one storm run takes by hand and with StormCheck, from the run's own counts and the
  assumptions below (each with its source). An estimate, not a measurement.
- `learning(rt)`: storm by storm, in the order the clock reached them, the questions each run raised, the rules
  first confirmed from them, and the learned rules it reused (`Rule.cases_settled_by_storm`).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from contracts.models import (
    EffortEstimate,
    EffortLine,
    Entitlement,
    LearningStep,
    Question,
    Rule,
    RuleAction,
    RuleReuse,
    StormRun,
)

from . import compose
from .live import INJECTION_RE

if TYPE_CHECKING:
    from .runtime import Runtime

# ---------------------------------------------------------------- assumptions: the only place they live
CLAIM_RATE = 0.18
CLAIM_RATE_SOURCE = "Steer 2020 for the European Commission: 18% of passengers on a cancelled flight claim"
CLAIM_TIME_SOURCE = "a rail delay-repay case study measured 30 min per claim by hand, 5 min automated"
RATE_SOURCE = ("loaded rate: Irish salary surveys (Chartered Accountants Ireland / Barden 2026 for accountants; "
               "recruiter guides for claims handlers) × 1.3 on-cost ÷ 1,700 h")
OPS_ANALYST, CLAIMS_HANDLER, COUNSEL, ACCOUNTANT = (("ops analyst", 45), ("claims handler", 31),
                                                   ("in-house counsel", 100), ("revenue accountant", 61))
CAUSE_H, CAUSE_REVIEW_H = 1.5, 10 / 60            # per cancelled flight; with StormCheck only the escalated ones
CLAIM_H, CLAIM_REVIEW_H = 20 / 60, 2 / 60         # per expected claim; with StormCheck review a drafted decision
QUESTION_H, QUESTION_ANSWER_H = 4.0, 15 / 60      # research + memo; with StormCheck answer one card
ELECTION_H = 3 / 60                               # per refund or voucher election; with StormCheck none
MONTH_ENDS = 18
BOOKS_H = (16.0, 2.0, 16.0)                       # per cohort: initial estimate, per month-end, audit evidence
BOOKS_REVIEW_H = (1.0, 0.5, 1.0)
ASSUMPTIONS_NOTE = "Estimate from the assumptions below; not measured at a real airline."

LEARNED_TIERS = ("mined", "legal_ruling", "controller_ruling", "claims_lead_ruling")
RULE_WORD = {RuleAction.DENY_OFFSET: "voucher rule", RuleAction.ALLOW_OFFSET: "voucher rule",
             RuleAction.SET_EXTRAORDINARY: "cause rule", RuleAction.SET_NOT_EXTRAORDINARY: "cause rule",
             RuleAction.KEEP_TAIL: "tail rule", RuleAction.DENY_RELEASE: "tail rule",
             RuleAction.APPLY_7_2_REDUCTION: "reroute reduction", RuleAction.ROUTE_TO: "routing rule"}
PATTERN_WORD = {"external_event_window": "a new kind of event"}
REASON_WORD = {"new-legal-pattern": "a new legal pattern", "no-precedent": "no precedent",
               "concurrent-causes": "concurrent causes", "sources-disagree": "sources disagree",
               "release-proposal": "a release proposal", "out-of-scope": "outside a rule's scope"}


def round_to(x: float, step: float) -> float:
    return step * round(x / step)


def run_name(run: StormRun) -> str:
    day = f"{run.date.day} {run.date:%b %Y}"
    name = run.name or run.id
    return name if day in name else f"{name} · {day}"


def is_desk(run: StormRun) -> bool:
    return bool(run.real_context.get("desk"))


def entitlements(rt: Runtime, run: StormRun, fid: str) -> list[Entitlement]:
    data = rt.store.get(("desk_" if is_desk(run) else "") + "entitlements", fid) or []
    return [Entitlement.model_validate(e) for e in data]


def run_questions(run: StormRun) -> list[Question]:
    return list({q.id: q for q in run.questions}.values())


# ---------------------------------------------------------------- effort
def effort(rt: Runtime, run_id: str) -> EffortEstimate | None:
    run = rt.storm_run(run_id)
    if run is None:
        return None
    cancelled = [r for r in run.flights if r.flight.status == "cancelled"]
    escalated = sum(1 for r in cancelled if r.decision is not None and r.decision.outcome != "auto")
    fids = {r.flight.id for r in cancelled}
    world = rt.world
    coupons = {c.id for c in (world.coupons if world else []) if c.flight_id in fids}
    pax = sum(r.flight.pax for r in cancelled)
    inputs = {
        "cancelled_flights": len(cancelled), "escalated_flights": escalated, "passengers": pax,
        "expected_claims": round(pax * CLAIM_RATE), "questions": len(run_questions(run)),
        "refunds": sum(1 for e in (world.elections if world else []) if e.coupon_id in coupons
                       and e.kind in ("refund", "voucher")),
        "cohorts": 1 if cancelled else 0, "month_ends": MONTH_ENDS,
    }
    lines = effort_lines(inputs)
    manual = sum(x.manual_hours for x in lines)
    auto = sum(x.with_stormcheck_hours for x in lines)
    manual_c = sum(x.manual_hours * x.rate_eur_per_hour for x in lines)
    auto_c = sum(x.with_stormcheck_hours * x.rate_eur_per_hour for x in lines)
    mh, ah = round_to(manual, 5), round_to(auto, 5)
    mc, ac = int(round_to(manual_c, 100)) * 100, int(round_to(auto_c, 100)) * 100
    return EffortEstimate(run_id=run.id, name=run_name(run), inputs=inputs, lines=lines, manual_hours=mh,
                          with_stormcheck_hours=ah, hours_saved=mh - ah, manual_cost_cents=mc,
                          with_stormcheck_cost_cents=ac, cost_saved_cents=mc - ac,
                          errors_caught=errors_caught(rt, run, cancelled, coupons),
                          assumptions_note=ASSUMPTIONS_NOTE)


def effort_lines(n: dict[str, int]) -> list[EffortLine]:
    def line(task: str, who: tuple[str, int], basis: str, manual: float, auto: float, source: str | None
             ) -> EffortLine:
        return EffortLine(task=task, role=who[0], basis=basis, manual_hours=round(manual, 1),
                          with_stormcheck_hours=round(auto, 1), rate_eur_per_hour=who[1],
                          source="; ".join(s for s in (source, RATE_SOURCE) if s))
    f, e, c, q, r, k, m = (n["cancelled_flights"], n["escalated_flights"], n["expected_claims"], n["questions"],
                           n["refunds"], n["cohorts"], n["month_ends"])
    books = BOOKS_H[0] + BOOKS_H[1] * m + BOOKS_H[2]
    review = BOOKS_REVIEW_H[0] + BOOKS_REVIEW_H[1] * m + BOOKS_REVIEW_H[2]
    return [
        line("Find what really caused each cancellation", OPS_ANALYST,
             f"{f} flights × 1.5 h; with StormCheck a person reads only the {e} escalated, 10 min each",
             f * CAUSE_H, e * CAUSE_REVIEW_H, None),
        line("Decide each compensation claim", CLAIMS_HANDLER,
             f"{n['passengers']:,} passengers × 18% = {c:,} expected claims × 20 min; with StormCheck 2 min each "
             "to review a drafted decision", c * CLAIM_H, c * CLAIM_REVIEW_H,
             f"{CLAIM_RATE_SOURCE}; {CLAIM_TIME_SOURCE}"),
        line("Answer the legal and policy questions", COUNSEL,
             f"{q} questions × 4 h of research and a memo; with StormCheck 15 min each to answer one card",
             q * QUESTION_H, q * QUESTION_ANSWER_H, None),
        line("Reconcile refunds and vouchers", CLAIMS_HANDLER,
             f"{r:,} refund and voucher elections × 3 min; with StormCheck none", r * ELECTION_H, 0.0, None),
        line("Estimate the liability and true it up each month-end", ACCOUNTANT,
             f"{plural(k, 'cohort')} × (16 h first estimate + 2 h × {m} month-ends + 16 h audit evidence); with StormCheck "
             f"1 h review + 0.5 h × {m} month-ends + 1 h audit", k * books, k * review, None),
    ]


def errors_caught(rt: Runtime, run: StormRun, cancelled: list, coupons: set[str]) -> list[dict]:
    """What the run caught, from its own data: recodes (with the entitlement each one turned on), refunds the CRM
    bot had already made (not repeated), claims that duplicate another claim, and claims carrying an instruction
    that was ignored. Nothing is added when the run has none."""
    out: list[dict] = []
    refunds: list[Entitlement] = []
    for r in cancelled:
        ents = entitlements(rt, run, r.flight.id)
        refunds += [e for e in ents if e.refund_already_initiated]
        d = r.decision
        if d is not None and d.recoded:
            owed = sum(e.compensation_cents for e in ents if e.status in ("owed", "needs_ruling", "held"))
            out.append({"label": f"{r.flight.number} recoded {d.recode_label or ''}".strip(),
                        "amount_cents": owed or None,
                        "detail": f"Coded weather by OCC; the evidence says {d.cause.value.replace('_', '-')}. "
                                  f"{compose.eur(owed)} full Art. 7 entitlement that a weather code would have "
                                  "denied." if owed else d.reason})
    if refunds:
        done = {e.coupon_id for e in refunds}
        amount = sum(x.amount_cents for x in (rt.world.crm if rt.world else [])
                     if x.kind == "refund_initiated" and x.coupon_id in done)
        out.append({"label": f"{len(refunds)} refunds the CRM bot had already made, not repeated",
                    "amount_cents": amount or None,
                    "detail": (f"{compose.eur(amount)} " if amount else "") + "already refunded by the CRM bot; "
                              "a second refund run would have paid it twice."})
    claims = [c for c in (rt.world.claims if rt.world else []) if c.coupon_id in coupons]
    seen = Counter(c.coupon_id for c in claims)
    dupes = [c for c in claims if seen[c.coupon_id] > 1]
    if dupes:
        extra = len(dupes) - len({c.coupon_id for c in dupes})
        out.append({"label": f"{extra} claims duplicate another claim", "amount_cents": None,
                    "detail": "The same passenger claimed twice; paid once."})
    hostile = [c for c in claims if INJECTION_RE.search(c.text or "")]
    if hostile:
        out.append({"label": f"{len(hostile)} claims carried instructions, ignored", "amount_cents": None,
                    "detail": "Text inside a claim is evidence, never an instruction; no approval came from it."})
    return out


# ---------------------------------------------------------------- learned and reused
def reached_runs(rt: Runtime) -> list[tuple[datetime, StormRun]]:
    """Every storm or event run the clock has reached (desk days are not the demo's), in the order it ran."""
    out = []
    for key in rt.store.keys("storm_run"):
        run = rt.storm_run(key)
        hist = rt.store.history("storm_run", key)
        if run is not None and hist and not is_desk(run) and hist[0][0] <= rt.now:
            out.append((hist[0][0], run))
    return sorted(out, key=lambda x: x[0])


def confirmations(rt: Runtime) -> dict[str, tuple[datetime, str]]:
    """rule id → (when it was first confirmed, its rule ref), from the confirm events."""
    out = {}
    for rid in rt.store.keys("proposal_state"):
        first = next(((at, s["rule_ref"]) for at, s in rt.store.history("proposal_state", rid)
                      if s.get("state") == "confirmed"), None)
        if first is not None:
            out[rid] = first
    return out


def learning(rt: Runtime) -> list[LearningStep]:
    runs = reached_runs(rt)
    if not runs:
        return []
    rules = {f"{r.id}@{r.version}": r for r in rt.lifecycle.rules_view()}
    confirmed = confirmations(rt)
    origin: dict[str, tuple[str, Question | None]] = {}       # rule id → (run id, the question it came from)
    for _, run in runs:
        for q in run_questions(run):
            rid = q.proposal_rule_id
            if rid in confirmed and rid not in origin:
                origin[rid] = (run.id, q)
    for rid, (at, _) in confirmed.items():                     # confirmed before its question: the run of the day
        if rid not in origin:
            origin[rid] = (next((run.id for t, run in reversed(runs) if t <= at), runs[0][1].id), None)
    names = {run.id: run.name or run.id for _, run in runs}
    steps = []
    patterns: set[str] = set()                                 # patterns an earlier run already asked about
    for t, run in runs:
        new = [confirmed[rid][1] for rid, (rid_run, _) in origin.items() if rid_run == run.id]
        reused = [RuleReuse(rule_ref=rref, title=r.title or r.id, learned_from=learned_from(rt, r, origin, names),
                            cases=r.cases_settled_by_storm[run.id])
                  for rref, r in rules.items() if r.tier in LEARNED_TIERS and rref not in new
                  and r.cases_settled_by_storm.get(run.id, 0) > 0]
        qs = run_questions(run)
        again = [q for q in qs if q.pattern in patterns]
        patterns |= {q.pattern for q in qs}
        steps.append(LearningStep(run_id=run.id, name=run_name(run), known_at=t, questions_asked=len(qs),
                                  cases_settled_by_reused_rules=sum(x.cases for x in reused), reused=reused,
                                  new_rules=new, note=note(rt, qs, again, new, reused, rules)))
    return steps


def history_months(rt: Runtime) -> int:
    ats = [h.at for h in (rt.world.history_cases if rt.world else [])]
    if not ats:
        return 0
    a, b = min(ats), max(ats)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def learned_from(rt: Runtime, rule: Rule, origin: dict[str, tuple[str, Question | None]],
                 names: dict[str, str]) -> str:
    if rule.tier == "mined":
        months = history_months(rt)
        span = f"{months} months of history" if months else "history"
        return f"{span} ({rule.support})" if rule.support else span
    who = f"{compose.label(rule.authority_required)} ruling"
    run_id, q = origin.get(rule.id, (None, None))
    if run_id is None:
        return who
    return f"{who} on {names.get(run_id, run_id)}" + (f" ({q.id})" if q is not None else "")


def describe(rule: Rule) -> str:
    word = RULE_WORD.get(rule.action, "rule")
    if rule.tier == "mined":
        return f"the {word} learned from history"
    return f"the {compose.label(rule.authority_required)}'s {word}"


def route(rt: Runtime, case_ref: str) -> str | None:
    fid = case_ref.rsplit(":", 1)[0] if case_ref.count(":") else case_ref
    f = next((f for f in (rt.world.flights if rt.world else []) if f.id == fid), None)
    return f"{f.origin}→{f.dest}" if f else None


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def note(rt: Runtime, qs: list[Question], again: list[Question], new: list[str], reused: list[RuleReuse],
         rules: dict[str, Rule]) -> str:
    """One or two plain sentences: what was reused and settled, what was asked again (and why), what was new."""
    parts = []
    if reused:
        what = " and ".join(f"{describe(rules[x.rule_ref])} ({plural(x.cases, 'case')})" for x in reused) \
            if len(reused) > 1 else describe(rules[reused[0].rule_ref])
        parts.append(f"Reused {what}: {plural(sum(x.cases for x in reused), 'case')} settled without asking.")
    if again:
        why = ", ".join(r for q in again for r in [route(rt, q.case_refs[0]) if q.case_refs else None] if r)
        parts.append(f"{len(again)} asked again" + (f" ({why} is outside the rule's scope)." if why else "."))
    fresh = [q for q in qs if q not in again]
    if fresh:
        who = ", ".join(dict.fromkeys(compose.label(q.routed_to) for q in fresh))
        whys = {PATTERN_WORD.get(q.pattern) or REASON_WORD.get(q.reason_tag) for q in fresh}
        why = f": {whys.pop()}" if len(whys) == 1 and None not in whys else ""
        parts.append(f"Asked {plural(len(fresh), 'new question')} ({who}{why})"
                     + (f"; the answers became {plural(len(new), 'new rule')}: {', '.join(new)}." if new else "."))
    elif new:
        parts.append(f"Confirmed {plural(len(new), 'new rule')}: {', '.join(new)}.")
    if not qs:
        parts.append("No question asked.")
    return " ".join(parts)
