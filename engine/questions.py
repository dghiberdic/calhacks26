"""D6 · One question per (pattern, storm), to the right person, covering every case of that pattern.

- Flight patterns (knock-on returns, concurrent causes, data gaps...) group escalated decisions by ``question_id``.
- Coupon pattern ``voucher_in_lieu_unsigned`` groups ``needs_ruling`` entitlements per storm (Claims Lead).
- Cohort pattern ``cohort_release`` proposes reducing an opening-balance cohort at M12 (Controller), unless a
  keep-tail / deny-release rule is in force.

Reminders: ``remind_at = asked_at + 3h``; the status view turns ``reminded`` once the Clock passes it.
Pure: no wall clock, no randomness.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from contracts.models import (
    Claim,
    Confidence,
    Entitlement,
    Evidence,
    FlightDecision,
    OpeningBalance,
    Question,
    Role,
    Rule,
    RuleAction,
    World,
)
from engine import confidence as conf
from engine import dsl

REMIND_AFTER = timedelta(hours=3)

REASON_TAG = {
    "knock_on_return": "no-precedent", "external_event": "no-precedent", "concurrent_causes": "concurrent-causes",
    "window_unknown": "out-of-scope", "weather_code_contradicted": "sources-disagree", "cause_unknown": "out-of-scope",
    "technical_unverified": "out-of-scope", "crew": "out-of-scope", "atc": "out-of-scope",
    "new_legal_pattern": "new-legal-pattern", "voucher_in_lieu_unsigned": "no-precedent",
    "cohort_release": "release-proposal",
}

TITLES = {
    "knock_on_return": "Is the return sector of a storm-cancelled rotation extraordinary when both ends were calm?",
    "concurrent_causes": "Which cause governs when the aircraft was AOG while the storm window was open?",
    "external_event": "Is a pre-storm AOG with an external root cause extraordinary?",
    "window_unknown": "No METAR within 60 min: what cancelled these flights?",
    "weather_code_contradicted": "OCC coded weather, but METAR was calm: what cancelled these flights?",
    "cause_unknown": "No cause evidence: what cancelled these flights?",
    "technical_unverified": "OCC coded technical, but there is no tech-log entry: confirm the cause?",
    "crew": "Confirm the crew cause for these cancellations?",
    "atc": "Confirm the ATC restriction for these cancellations?",
}

OPTIONS = {
    "knock_on_return": [
        "Extraordinary if no aircraft within 3 h of STD and the earliest reroute was offered",
        "Not extraordinary: compensation owed on all of them",
        "Decide flight by flight",
    ],
    "concurrent_causes": ["The storm governs: extraordinary", "The defect governs: not extraordinary",
                          "Decide flight by flight"],
    "external_event": ["Extraordinary (outside the carrier's control)", "Not extraordinary", "Decide flight by flight"],
}
OPS_OPTIONS = ["Confirm weather", "Technical: attach the tech-log entry", "Other cause: attach the log"]

RECOMMENDS = {
    "knock_on_return": ("Extraordinary only if no aircraft and crew could operate the return within 3 h of STD and "
                        "passengers were offered the earliest reroute on any carrier (C-74/19)."),
    "concurrent_causes": "Ask Legal which cause governs; hold compensation until then (IFRS 15.56 constraint).",
    "external_event": "Ask Legal whether the external event is extraordinary (C-549/07).",
}


def remind_at(asked_at: datetime) -> datetime:
    return asked_at + REMIND_AFTER


def status_at(q: Question, now: datetime, answered: bool = False) -> str:
    """The ``Question.status`` view: answered > reminded (Clock past remind_at) > open."""
    if answered:
        return "answered"
    if q.remind_at is not None and now >= q.remind_at:
        return "reminded"
    return "open"


def pattern_of(question_id: str) -> str:
    return question_id.rsplit(":", 1)[-1]


def _numbers(ids: Iterable[str]) -> str:
    nums = [i.split("@", 1)[0] for i in ids]
    return ", ".join(nums[:-1]) + (" and " if len(nums) > 1 else "") + nums[-1] if nums else ""


def _euros(cents: int) -> str:
    return f"€{cents / 100:,.0f}"


def flight_questions(decisions: Sequence[FlightDecision], ents: Sequence[Entitlement], asked_at: datetime,
                     liability_by_flight: dict[str, int]) -> list[Question]:
    groups: dict[str, list[FlightDecision]] = {}
    for d in decisions:
        if d.outcome == "escalated" and d.question_id:
            groups.setdefault(d.question_id, []).append(d)
    out = []
    for qid in sorted(groups):
        ds = sorted(groups[qid], key=lambda d: d.flight_id)
        pattern = pattern_of(qid)
        refs = [d.flight_id for d in ds]
        weakest = min(ds, key=lambda d: (d.confidence.score if d.confidence.score is not None else -1, d.flight_id))
        tag = REASON_TAG.get(pattern, "no-precedent")
        if weakest.confidence.features.get("precedent_count", 0) > 0 and tag == "no-precedent":
            tag = "new-legal-pattern"
        found = " ".join(d.reason for d in ds)
        why = {
            "no-precedent": "No precedent for this pattern; the law needs a ruling (C-74/19: direct causal link and "
                            "reasonable measures).",
            "concurrent-causes": "Two causes overlap: an AOG and an open storm window.",
            "sources-disagree": "The OCC code and the METAR disagree, and no tier-1 source names another cause.",
            "out-of-scope": "The evidence needed to decide is missing.",
            "new-legal-pattern": "A new legal pattern beyond the precedents on file.",
        }[tag]
        options = OPTIONS.get(pattern, OPS_OPTIONS)
        recommends = RECOMMENDS.get(pattern, "Ops to confirm the cause from the logs.")
        out.append(Question(
            id=qid, case_refs=refs, pattern=pattern, routed_to=ds[0].routed_to or Role.OPS, asked_at=asked_at,
            title=TITLES.get(pattern, f"How should {_numbers(refs)} be decided?"),
            found=found, why_flagged=why, recommends=recommends, recommended_option=options[0], options=options,
            evidence=[e for d in ds for e in d.evidence if e.role != "context"][:12],
            confidence=weakest.confidence, reason_tag=tag, holds=refs,
            holds_cents=sum(liability_by_flight.get(r, 0) for r in refs), remind_at=remind_at(asked_at)))
    return out


# ---------- vouchers ----------

_ACCEPTED = re.compile(r"\baccept(ed|s)?\b", re.I)
_DISPUTED = re.compile(r"never (agreed|accepted|signed)|did not (agree|accept|sign)|didn't (agree|accept|sign)|"
                       r"not (agree|accept)", re.I)


def voucher_features(world: World, coupon_id: str, known_at: datetime, rules: Sequence[Rule] = ()) -> tuple[
        dict[str, float], list[Evidence]]:
    evs = sorted((e for e in world.crm if e.coupon_id == coupon_id and e.kind == "voucher_in_lieu_of_compensation"
                  and e.at <= known_at), key=lambda e: (e.at, e.id))
    claims = [c for c in world.claims if c.coupon_id == coupon_id and c.received_at <= known_at]
    v = evs[-1] if evs else None
    crm_says_accepted = bool(v and _ACCEPTED.search(v.text))
    disputed = any(_DISPUTED.search(c.text) for c in claims)
    signed = bool(v and v.signed_acceptance_sha256)
    disagree = (crm_says_accepted and not signed) or (crm_says_accepted and disputed)
    n_hist = sum(1 for h in world.history_cases if h.kind == "voucher_in_lieu_unsigned")
    feats = {"in_lieu": 1.0 if v else 0.0, "signed": 1.0 if signed else 0.0,
             "sources_disagree": 1.0 if disagree else 0.0, "precedent_count": conf.precedents(n_hist)}
    ev: list[Evidence] = []
    if v is not None:
        src = next((s.id for s in world.sources if s.text and v.text and v.text in s.text), f"SRC-CRM-{v.id}")
        ev.append(Evidence(fact_id=f"F-CRM-{v.id}-in_lieu", source_id=src, field="voucher.in_lieu", value=True,
                           quote=v.text, role="supports", trust_tier=3))
        ev.append(Evidence(fact_id=f"F-CRM-{v.id}-signed", source_id=src, field="voucher.signed", value=signed,
                           quote=None, role="supports", trust_tier=3))
        ev.append(Evidence(fact_id=f"F-CRM-{v.id}-amount", source_id=src, field="voucher.amount_cents",
                           value=v.amount_cents, quote=None, role="context", trust_tier=3))
    for c in claims:
        if _DISPUTED.search(c.text):
            m = _DISPUTED.search(c.text)
            quote = c.text[max(0, m.start() - 40): m.end() + 40].strip()
            if quote not in c.text:
                quote = None
            ev.append(Evidence(fact_id=f"F-CLM-{c.id}-disputed", source_id=f"SRC-CLAIM-{c.id}",
                               field="claim.voucher_disputed", value=True, quote=quote, role="contradicts",
                               trust_tier=4))
    return feats, ev


def voucher_questions(world: World, ents: Sequence[Entitlement], storm_id: str, asked_at: datetime,
                      calibration: dict[str, Any], known_at: datetime | None = None) -> list[Question]:
    pending = sorted((e for e in ents if e.status == "needs_ruling"), key=lambda e: e.coupon_id)
    if not pending:
        return []
    known_at = known_at or asked_at
    scored = []
    evidence: list[Evidence] = []
    for e in pending:
        feats, ev = voucher_features(world, e.coupon_id, known_at)
        caps = ["capped:sources-disagree"] if feats["sources_disagree"] else []
        scored.append((conf.score("voucher", feats, calibration, caps), e))
        evidence += ev
    weakest = min(scored, key=lambda x: (x[0].score if x[0].score is not None else -1, x[1].coupon_id))[0]
    tag = "sources-disagree" if any(c.features.get("sources_disagree") for c, _ in scored) else "no-precedent"
    refs = [e.coupon_id for _, e in scored]
    first = pending[0]
    voucher = next((v for v in world.crm if v.coupon_id == first.coupon_id
                    and v.kind == "voucher_in_lieu_of_compensation"), None)
    v_amt = _euros(voucher.amount_cents) if voucher else "the voucher"
    comp = _euros(first.compensation_cents)
    if len(refs) == 1:
        seat = refs[0].rsplit(":", 1)[-1]
        title = f"Does a {v_amt} service-desk voucher 'in lieu of compensation' offset {seat}'s {comp}?"
        found = (f"{seat} ({first.flight_id.split('@')[0]}) holds a {v_amt} service-desk voucher 'in lieu of "
                 f"compensation' with no signed acceptance on file.")
    else:
        title = (f"Do {len(refs)} unsigned service-desk vouchers 'in lieu of compensation' offset the "
                 "compensation owed?")
        found = f"{len(refs)} passengers hold service-desk vouchers 'in lieu of compensation' with no signed acceptance."
    if tag == "sources-disagree":
        found += " CRM records the voucher as accepted; there is no signature hash."
    options = [f"Pay {comp} cash; the voucher stays as goodwill", f"Offset the voucher: pay the balance in cash",
               "Ask the passenger to sign the acceptance first"]
    return [Question(
        id=f"Q-{storm_id}:voucher_in_lieu_unsigned", case_refs=refs, pattern="voucher_in_lieu_unsigned",
        routed_to=Role.CLAIMS_LEAD, asked_at=asked_at, title=title, found=found,
        why_flagged=("Art. 7(3) needs signed acceptance for an offset" + (", and the sources disagree."
                                                                         if tag == "sources-disagree" else ".")
                     + " No precedent for unsigned in-lieu vouchers."),
        recommends="No signed acceptance, no offset: pay cash; the voucher stays as goodwill.",
        recommended_option=options[0], options=options, evidence=evidence[:12], confidence=weakest,
        reason_tag=tag, holds=refs, holds_cents=sum(e.compensation_cents for e in pending),
        remind_at=remind_at(asked_at))]


# ---------- cohort release (Controller) ----------

def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def cohort_event_date(ob: OpeningBalance) -> date:
    m = re.search(r"@(\d{4}-\d{2}-\d{2})", ob.cohort)
    return date.fromisoformat(m.group(1)) if m else ob.as_of.date()


def cohort_age_months(event: date, at: date) -> int:
    """M1 = the month-end of (event + 28 days); age at the close of ``at``'s month."""
    m1 = _month_index(event + timedelta(days=28))
    return max(0, _month_index(at) - m1 + 1)


def release_questions(world: World, rules: Sequence[Rule], known_at: datetime, calibration: dict[str, Any],
                      asked_at: datetime | None = None) -> list[Question]:
    asked_at = asked_at or known_at
    out = []
    for ob in sorted(world.opening_balances, key=lambda o: o.cohort):
        if ob.balance_cents <= 0:
            continue
        age = cohort_age_months(cohort_event_date(ob), known_at.date())
        msl = _month_index(known_at.date()) - _month_index(ob.as_of.date())
        feats_dsl = {"cohort.age_months": age, "cohort.months_since_last_claim": msl,
                     "cohort.limitation_expired": False, "cohort": ob.cohort}
        keep = dsl.matching(rules, feats_dsl, actions=[RuleAction.KEEP_TAIL, RuleAction.DENY_RELEASE],
                            known_at=known_at)
        if age < 12 or msl < 3 or keep:
            continue
        pct = ob.claimed_cents / ob.entitlement_cents if ob.entitlement_cents else 0.0
        c = conf.score("release", {"cohort_age_months": age, "months_since_last_claim": msl,
                                   "precedent_count": 0.0}, calibration)
        out.append(Question(
            id=f"Q-{ob.cohort}:cohort_release", case_refs=[ob.cohort], pattern="cohort_release",
            routed_to=Role.CONTROLLER, asked_at=asked_at,
            title=f"Reduce the {ob.cohort} {ob.curve_segment} cohort to nil at M{age}?",
            found=(f"Cohort {ob.cohort} ({ob.curve_segment}): {_euros(ob.entitlement_cents)} full Art. 7 entitlement, "
                   f"{pct:.0%} claimed, {_euros(ob.balance_cents)} EU261 compensation liability remaining. "
                   f"No new claims in {msl} months."),
            why_flagged="Release proposal: a change in estimate (IAS 8.36) needs the Controller.",
            recommends=(f"Reduce the remaining {_euros(ob.balance_cents)} to nil as a change in estimate "
                        f"(no new claims in {msl} months)."),
            recommended_option="Reduce to nil now",
            options=["Reduce to nil now", "Keep the expected tail until the six-year limitation", "Review again at M18"],
            evidence=[
                Evidence(fact_id=f"F-OB-{ob.cohort}-balance", source_id=f"SRC-OB-{ob.cohort}",
                         field="cohort.balance_cents", value=ob.balance_cents, role="supports", trust_tier=2),
                Evidence(fact_id=f"F-OB-{ob.cohort}-claimed", source_id=f"SRC-OB-{ob.cohort}",
                         field="cohort.claimed_pct", value=round(pct, 4), role="context", trust_tier=2),
                Evidence(fact_id=f"F-OB-{ob.cohort}-msl", source_id=f"SRC-OB-{ob.cohort}",
                         field="cohort.months_since_last_claim", value=msl, role="supports", trust_tier=2),
            ],
            confidence=c, reason_tag="release-proposal", holds=[ob.cohort], holds_cents=ob.balance_cents,
            remind_at=remind_at(asked_at)))
    return out


def claims_for(world: World, coupon_id: str) -> list[Claim]:
    return [c for c in world.claims if c.coupon_id == coupon_id]


def lowest(confs: Iterable[Confidence]) -> Confidence | None:
    cs = list(confs)
    return min(cs, key=lambda c: c.score if c.score is not None else -1) if cs else None
