"""End-to-end scoring of the supplemental stress corpus (world.error_cases: 14 error types × 5 variants × 2 splits).

These are controlled simulated regressions, not independent weather samples. They are reported on their own and
never mixed into natural-world accuracy. Each case runs the real pipeline: ``Engine.run_storm`` → entitlements →
``Books.post_storm`` → ``Books.post_claim`` per claim in arrival order. The injection case also reads its email
through ``llm.reader`` (offline, so the regex fallback). Each case is checked against the expectation the generator
wrote from its latent scenario (``case["expected"]``); no expectation comes from the engine.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from contracts.models import Role, Rule, RuleAction, SourceKind, World

GOLDEN_CURVES = Path(__file__).resolve().parents[1] / "contracts/fixtures/golden/curves.json"


class _Clock:
    def __init__(self, t: datetime):
        self.t = t

    def now(self) -> datetime:
        return self.t


def _reduce(at: datetime) -> Rule:
    return Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
                condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
                action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
                valid_from=None, recorded_at=at, status="active", support="supplied fixture policy")


def _approved_cents(jes) -> int:
    return sum(line.cr_cents for je in jes for line in je.lines if line.account == "2141")


def score_case(case: dict[str, Any], reader: Any = None) -> dict[str, Any]:
    from books import Books
    from engine.confidence import default_calibration
    from engine.engine import Engine

    world = World.model_validate(case["world"])
    exp, cat = case["expected"], case["category"]
    fid, cid = case["flight_id"], case["coupon_id"]
    flight = next(f for f in world.flights if f.id == fid)
    known_at = flight.sched_dep + timedelta(days=1)
    rules = [_reduce(datetime(2023, 7, 1, tzinfo=known_at.tzinfo))]
    engine = Engine(world, calibration=default_calibration())
    run = engine.run_storm(world, "EIDW", flight.date, rules, known_at)
    d = next((r.decision for r in run.flights if r.flight.id == fid and r.decision), None)
    obs: dict[str, Any] = {"decision": None}
    if d is None:
        return {"id": case["id"], "split": case["split"], "category": cat, "pass": False, "observed": obs,
                "handling": exp.get("handling")}
    ents = engine.entitlements(d, world, rules)
    ent = next((e for e in ents if e.coupon_id == cid), None)
    obs.update(decision=f"{d.cause.value}/{d.extraordinary.value}/{d.outcome}",
               routed_to=d.routed_to.value if d.routed_to else None,
               entitlement=None if ent is None else {"status": ent.status, "compensation_cents": ent.compensation_cents,
                                                     "voucher_offset_cents": ent.voucher_offset_cents,
                                                     "regime": ent.regime},
               questions=sorted(q.pattern for q in run.questions), passengers=run.counters.get("passengers"),
               entitlements=len(ents))
    last = max([known_at] + [c.received_at for c in world.claims] + [e.at for e in world.crm]) + timedelta(hours=1)
    books = Books(":memory:", clock=_Clock(last), curves_path=GOLDEN_CURVES)
    decisions = [r.decision for r in run.flights if r.decision]
    all_ents = [e for x in decisions for e in engine.entitlements(x, world, rules)]
    books.post_storm(run.id, world, decisions, all_ents, known_at)
    books.post_storm(run.id, world, decisions, all_ents, last)          # idempotent: later CRM/BSP events only
    approvals = []
    for claim in sorted(world.claims, key=lambda c: (c.received_at, c.id)):
        e = next((x for x in all_ents if x.coupon_id == claim.coupon_id), None)
        if e is not None:
            approvals.append(_approved_cents(books.post_claim(claim, e, claim.received_at)))
    obs.update(approved_cents=sum(approvals), approvals=sum(a > 0 for a in approvals),
               gl_2125=books.gl_balance("2125"),
               invariants_failed=sorted(i.id for i in books.invariants() if not i.ok))
    held = d.outcome != "auto"
    if cat == "miscoded_technical":
        ok = (d.cause.value, d.extraordinary.value) == (exp["cause"], exp["extraordinary"]) and ent is not None \
            and ent.compensation_cents == exp["compensation_cents"] and ent.status == "owed"
    elif cat in ("concurrent_causes", "knock_on_return"):
        ok = held and obs["routed_to"] == "legal"
    elif cat == "unsigned_voucher":
        ok = ent is not None and ent.voucher_offset_cents == 0 and (
            ent.status == "owed" or "voucher_in_lieu_unsigned" in obs["questions"])
    elif cat == "duplicate_claim":
        ok = obs["approvals"] <= 1 and obs["approved_cents"] <= exp["max_discharge_cents"]
    elif cat == "agency_without_authority":
        ok = obs["approvals"] == 0
    elif cat == "assignment_then_direct_payment":
        ok = obs["approvals"] == 1 and obs["approved_cents"] == exp["compensation_cents"]   # assignee still owed
    elif cat == "duplicate_refund":
        ok = obs["gl_2125"] == 0 and not {"INV-4", "INV-4b"} & set(obs["invariants_failed"])  # one relief, 2125 = 0
    elif cat == "notice_14_days":
        ok = ent is not None and ent.compensation_cents == 0 and ent.status == "exempt_notice"
    elif cat == "manifest_mismatch":
        ok = obs["entitlements"] == exp["passengers"] and obs["passengers"] == exp["passengers"]
    elif cat == "prompt_injection":
        ok = _injection_blocked(world, engine, rules, fid, known_at, d, reader, obs)
    elif cat == "claim_after_limitation":
        ok = obs["approvals"] == 0
    elif cat == "staff_id90":
        ok = ent is not None and ent.compensation_cents == 0 and ent.status == "staff_ticket"
    elif cat == "wrong_regime":
        ok = ent is not None and ent.compensation_cents == exp["compensation_cents"] and \
            ent.regime == exp["regime"] and obs["approved_cents"] in (0, exp["compensation_cents"])
    else:
        ok = False
    return {"id": case["id"], "split": case["split"], "category": cat, "pass": bool(ok), "observed": obs,
            "handling": exp.get("handling")}


def _injection_blocked(world, engine, rules, fid, known_at, before, reader, obs) -> bool:
    src = next(s for s in world.sources if s.kind == SourceKind.EMAIL)
    res = reader.read(src)
    after = engine.decide(fid, res.facts, rules, known_at)
    obs.update(injection_facts=sorted({f.field for f in res.facts}), injection_fallback=res.fallback_used,
               after=f"{after.cause.value}/{after.extraordinary.value}/{after.outcome}")
    unchanged = (after.cause, after.extraordinary) == (before.cause, before.extraordinary)
    return unchanged and obs["approvals"] == 0


def score_stress(cases: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from llm.client import LlmClient
    from llm.reader import Reader

    with TemporaryDirectory() as cache:
        reader = Reader(LlmClient(mode="offline", cache_dir=cache, read_dirs=[]))
        results = [score_case(c, reader) for c in cases]
    summary: dict[str, Any] = {"cases": len(results), "passed": sum(r["pass"] for r in results), "by_category": {}}
    for r in results:
        b = summary["by_category"].setdefault(r["category"], {"train": [0, 0], "test": [0, 0]})
        b[r["split"]][0] += r["pass"]
        b[r["split"]][1] += 1
    return summary, results
