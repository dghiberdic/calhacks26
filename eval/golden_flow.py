"""Measured replay through the real engine, trace and books, with simulated human rulings.

The historical reduction policy is a supplied fixture, not a claim that the miner ran.
No LLM is involved in this accounting/control regression.
"""
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import orjson

from books import Books
from contracts.models import Role, Rule, RuleAction, Session, World
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.lifecycle import Lifecycle
from engine.trace import TraceStore

GOLDEN = Path(__file__).resolve().parents[1] / "contracts/fixtures/golden"
DAY1 = datetime(2025, 1, 25, 6, tzinfo=UTC)


def historical_reduction(at: datetime) -> Rule:
    return Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
                condition={"all": [{"f": "pax.election", "op": "in",
                                     "v": ["reroute_partner", "reaccommodated_own"]}]},
                action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
                valid_from=None, recorded_at=at, status="active", support="41 of 42; supplied fixture policy")


class Clock:
    def now(self):
        return DAY1


def replay_once():
    world = World.model_validate_json((GOLDEN / "world.json").read_bytes())
    engine = Engine(world, calibration=default_calibration())
    books = Books(":memory:", clock=Clock(), curves_path=GOLDEN / "curves.json")
    trace = TraceStore(":memory:", engine_sha="eval-v1", cal_version="cal-default-v1")
    lifecycle = Lifecycle(engine, world, trace, books=books)
    trace.record_rule(historical_reduction(DAY1), "agent.engine", DAY1, event="active")
    run = engine.run_storm(world, "EIDW", date(2025, 1, 24), lifecycle.rules_at(DAY1), DAY1)
    decisions = [r.decision for r in run.flights if r.decision]
    ents = [e for d in decisions for e in engine.entitlements(d, world, lifecycle.rules_at(DAY1))]
    books.post_storm(run.id, world, decisions, ents, DAY1)
    lifecycle.record_run(decisions, ents, DAY1)
    before = books.gl_balance("2140", cohort=run.id)
    texts = {
        "voucher_in_lieu_unsigned": (Role.CLAIMS_LEAD, "R-CL-1",
            "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."),
        "knock_on_return": (Role.LEGAL, "R-LEG-1",
            ("A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could "
             "operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).")),
    }
    for i, (pattern, (role, rid, text)) in enumerate(texts.items()):
        at = datetime(2025, 1, 25, 9 + i, 30, tzinfo=UTC)
        session = Session(principal=f"{role.value}:eval", role=role, name="eval", issued_at=DAY1)
        question = next(q for q in run.questions if q.pattern == pattern)
        lifecycle.answer(question, question.recommended_option, text, session, at)
        lifecycle.confirm(rid, session, at)
    after = books.gl_balance("2140", cohort=run.id)
    later_at = datetime(2025, 1, 25, 12, tzinfo=UTC)
    later = engine.run_storm(world, "EIDW", date(2025, 1, 24), lifecycle.rules_at(later_at), later_at)
    resolved = {"voucher_in_lieu_unsigned", "knock_on_return"}
    repeat = sum(q.pattern in resolved for q in later.questions)
    herm_at = datetime(2025, 1, 27, 6, tzinfo=UTC)
    herm_rules = lifecycle.rules_at(herm_at)
    herm = engine.run_storm(world, "EIDW", date(2025, 1, 26), herm_rules, herm_at)
    herm_ents = [e for r in herm.flights if r.decision
                 for e in engine.entitlements(r.decision, world, herm_rules)]
    applied = {e.coupon_id for e in herm_ents if "R-CL-1@1" in e.rules_applied}
    outside = set(world.meta["herminia"]["in_lieu_unsigned_non_eu"])
    controls = {"repeat_questions": repeat, "out_of_scope_auto": len(applied & outside),
                "in_scope_coupons": len(applied),
                "out_of_scope_questions": sum(q.pattern == "voucher_in_lieu_unsigned" and
                                               bool(set(q.case_refs) & outside) for q in herm.questions)}
    payload = {"before_cents": before, "after_cents": after,
               "decisions": [d.model_dump(mode="json") for d in decisions],
               "settled_coupons": sorted(applied), "controls": controls}
    digest = sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()
    return before, after, digest, controls


def replay_three():
    runs = [replay_once() for _ in range(3)]
    hashes = [r[2] for r in runs]
    return {"runs": 3, "liability_eur": [r[1] / 100 for r in runs],
            "pre_legal_liability_eur": [r[0] / 100 for r in runs], "hashes": hashes,
            "hash_identical": len(set(hashes)) == 1,
            "phase": "after simulated Claims Lead and Legal rulings; real engine/trace/books",
            "policy_source": "supplied historical reduction fixture; no miner or LLM benchmark"}, runs[0][3]
