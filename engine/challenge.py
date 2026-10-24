"""D6 · A challenge to a decision routes; it never flips it (plan §1.4).

The Drafter classifies the text (``assertion`` | ``new_fact`` | ``new_legal_pattern``) and returns its facts at
trust tier 4. The engine then decides:
- ``assertion`` -> "Decision stands.", citing the decision's tier-1/2 evidence plus the flights that operated
  after the window ("everyone else flew").
- ``new_fact`` -> the decision stands until Ops verifies the fact (an Ops question).
- ``new_legal_pattern`` -> the decision stands; Legal is asked (e.g. a hidden manufacturing defect, C-549/07 ¶26).
Pure: no wall clock, no randomness.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from contracts.models import Evidence, Fact, FlightDecision, Question, Role, World
from engine import confidence as conf
from engine.questions import remind_at

OPERATED_HORIZON = timedelta(hours=2)
CHALLENGE_TIER = 4


@dataclass
class ChallengeVerdict:
    classification: str
    decision_stands: bool
    cited: list[Evidence]
    question: Question | None = None
    routed_to: Role | None = None
    facts: list[Fact] = field(default_factory=list)


def operated_evidence(world: World, decision: FlightDecision) -> Evidence | None:
    """Departures from the same origin that operated between the window's end and STD + 2 h."""
    flight = next((f for f in world.flights if f.id == decision.flight_id), None)
    win = next((e.value for e in decision.evidence if e.field == "storm.window" and isinstance(e.value, dict)), None)
    if flight is None or win is None:
        return None
    end = datetime.fromisoformat(str(win["end"]).replace("Z", "+00:00"))
    if end > flight.sched_dep:
        return None
    ops = sorted((f for f in world.flights if f.status == "operated" and f.origin == flight.origin
                  and end <= f.sched_dep <= flight.sched_dep + OPERATED_HORIZON), key=lambda f: f.sched_dep)
    if not ops:
        return None
    span = f"{ops[0].sched_dep:%H:%M}–{ops[-1].sched_dep:%H:%M}Z"
    return Evidence(fact_id=f"F-OPS-{flight.origin}-{end:%Y%m%dT%H%MZ}-operated", source_id=f"SRC-SCHEDULE-{flight.origin}",
                    field="flight.operated_after_window", value=len(ops),
                    quote=f"{len(ops)} {flight.origin} departures operated {span}: "
                          + " ".join(f.number for f in ops),
                    role="supports", trust_tier=2)


def challenge(world: World, decision: FlightDecision, classification: str, facts: Sequence[Fact],
              asked_at: datetime, calibration: dict[str, Any] | None = None) -> ChallengeVerdict:
    cal = calibration if calibration is not None else conf.load_calibration()
    strong = [e for e in decision.evidence if e.trust_tier <= 2 and e.role in ("supports", "context")
              and not e.struck]
    ops = operated_evidence(world, decision)
    cited = strong + ([ops] if ops else [])
    tier4 = list(facts)
    if classification == "assertion":
        return ChallengeVerdict("assertion", True, cited, facts=tier4)

    if classification == "new_legal_pattern":
        pattern, role, tag = "new_legal_pattern", Role.LEGAL, "new-legal-pattern"
        title = f"Does the challenge to {decision.flight_id.split('@')[0]} raise a new legal pattern?"
        recommends = ("Ask Legal whether the notice shows a hidden manufacturing defect (C-549/07 ¶26). The "
                      "decision stands meanwhile.")
        options = ["Decision stands: not extraordinary", "Extraordinary: hidden defect (C-549/07 ¶26)",
                   "Request the manufacturer's notice first"]
    else:
        classification = "new_fact"
        pattern, role, tag = "challenge_new_fact", Role.OPS, "sources-disagree"
        title = f"Verify the new fact raised against {decision.flight_id.split('@')[0]}?"
        recommends = "Ops to verify the fact against tier-1 logs; the decision stands meanwhile."
        options = ["Fact not supported: decision stands", "Fact verified: re-decide", "Need more information"]

    feats = dict(decision.confidence.features)
    feats["sources_disagree"] = 1.0
    c = conf.score(decision.confidence.kind, feats, cal, caps=[*decision.confidence.caps, "capped:challenge-tier-4"])
    challenge_ev = [Evidence(fact_id=f.id, source_id=f.source_id, field=f.field, value=f.value, quote=f.span,
                             role="contradicts", trust_tier=CHALLENGE_TIER) for f in facts]
    q = Question(
        id=f"Q-{decision.flight_id}:{pattern}", case_refs=[decision.flight_id], pattern=pattern, routed_to=role,
        asked_at=asked_at, title=title,
        found=f"A tier-4 challenge to {decision.flight_id.split('@')[0]} ({decision.cause.value}, "
              f"{decision.extraordinary.value}): " + "; ".join(str(f.span or f.value) for f in facts)[:400],
        why_flagged="Challenge facts are tier 4: they route, they never flip a decision.",
        recommends=recommends, recommended_option=options[0], options=options,
        evidence=challenge_ev + cited[:8], confidence=c, reason_tag=tag, holds=[], holds_cents=0,
        remind_at=remind_at(asked_at))
    return ChallengeVerdict(classification, True, cited, question=q, routed_to=role, facts=tier4)
