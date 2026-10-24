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
# The plan §1.4 rulings, word for word: (role, rule id, explanation, ruling kind). The held-out replay in
# eval/evaluate.py applies the same words from the morning each pattern is first asked.
SCRIPTED_RULINGS = {
    "voucher_in_lieu_unsigned": (Role.CLAIMS_LEAD, "R-CL-1",
        "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.", "answer"),
    "knock_on_return": (Role.LEGAL, "R-LEG-1",
        ("A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could "
         "operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19)."),
        "answer"),
    "cohort_release": (Role.CONTROLLER, "R-CTL-1",
        "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.",
        "rejection"),
}


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
    texts = {p: SCRIPTED_RULINGS[p][:3] for p in ("voucher_in_lieu_unsigned", "knock_on_return")}
    for i, (pattern, (role, rid, text)) in enumerate(texts.items()):
        at = datetime(2025, 1, 25, 9 + i, 30, tzinfo=UTC)
        session = Session(principal=f"{role.value}:eval", role=role, name="eval", issued_at=DAY1)
        question = next(q for q in run.questions if q.pattern == pattern)
        lifecycle.answer(question, question.recommended_option, text, session, at)
        lifecycle.confirm(rid, session, at)
    ctl_at = datetime(2025, 1, 25, 11, tzinfo=UTC)
    controller = Session(principal="controller:eval", role=Role.CONTROLLER, name="eval", issued_at=DAY1)
    release = next(q for q in run.questions if q.pattern == "cohort_release")
    lifecycle.reject(release, SCRIPTED_RULINGS["cohort_release"][2], controller, ctl_at)
    lifecycle.confirm("R-CTL-1", controller, ctl_at)
    tail = books.gl_balance("2140", cohort="EIDW@2024-01-21")
    # Proposing a broader rule must not activate it; the controller still needs to confirm the proposal.
    lifecycle.widen("R-CTL-1", controller, ctl_at)
    broadened = any(r.id == "R-CTL-1" and not r.scope for r in lifecycle.rules_at(ctl_at))
    after = books.gl_balance("2140", cohort=run.id)
    later_at = datetime(2025, 1, 25, 12, tzinfo=UTC)
    later = engine.run_storm(world, "EIDW", date(2025, 1, 24), lifecycle.rules_at(later_at), later_at)
    resolved = {"voucher_in_lieu_unsigned", "knock_on_return", "cohort_release"}
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
    payload = {"before_cents": before, "after_cents": after, "tail_cents": tail, "widen_active": broadened,
               "decisions": [d.model_dump(mode="json") for d in decisions],
               "settled_coupons": sorted(applied), "controls": controls}
    digest = sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()
    return before, after, digest, controls, tail, broadened


def replay_three():
    runs = [replay_once() for _ in range(3)]
    hashes = [r[2] for r in runs]
    return {"runs": 3, "liability_eur": [r[1] / 100 for r in runs],
            "pre_legal_liability_eur": [r[0] / 100 for r in runs], "hashes": hashes,
            "hash_identical": len(set(hashes)) == 1,
            "tail_kept_eur": [r[4] / 100 for r in runs],
            "unconfirmed_widen_applied": any(r[5] for r in runs),
            "phase": "after simulated Claims Lead, Legal and Controller rulings; real engine/trace/books",
            "policy_source": "supplied historical reduction fixture; no miner or LLM benchmark"}, runs[0][3]


# ---------------------------------------------------------------- StormCheck ×3 on held-out storms, fresh processes

STORM_DAYS = ("2025-01-24", "2025-01-26", "2025-02-26")      # Éowyn, Herminia and a generated held-out storm


def storm_runs(days=STORM_DAYS, seed: int = 0, world: World | None = None) -> dict[str, dict]:
    """The real engine's StormRun on each storm, as the held-out eval runs it (the morning after, supplied policy,
    before any ruling): drafted liability and the canonical sha256 of the whole StormRun."""
    from eval.evaluate import day_world, known_at_for

    if world is None:
        from world.generator import generate_world

        world = generate_world(seed=seed).world
    out = {}
    for text in days:
        day = date.fromisoformat(text)
        sample = day_world(world, day)
        run = Engine(sample, calibration=default_calibration()).run_storm(
            sample, "EIDW", day, [historical_reduction(datetime(2023, 7, 1, tzinfo=UTC))], known_at_for(day))
        out[text] = {"liability_cents": run.liability_drafted_cents, "cancelled": run.counters.get("cancelled", 0),
                     "questions": len(run.questions),
                     "hash": sha256(orjson.dumps(run.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)).hexdigest()}
    return out


def fresh_process_runs(days=STORM_DAYS, runs: int = 3) -> dict:
    """``runs`` separate interpreters (PYTHONHASHSEED 1..runs), each regenerating the world from the seed."""
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    results = []
    for i in range(runs):
        env = dict(os.environ, PYTHONHASHSEED=str(i + 1), LLM_MODE="offline")
        p = subprocess.run([sys.executable, "-m", "eval.golden_flow", "--storm-runs", ",".join(days)], cwd=root,
                           env=env, capture_output=True, text=True, timeout=900, check=True)
        results.append(orjson.loads(p.stdout.strip().splitlines()[-1]))
    storms = {}
    for text in days:
        hashes = [r[text]["hash"] for r in results]
        storms[text] = {"liability_eur": [r[text]["liability_cents"] / 100 for r in results], "hashes": hashes,
                        "hash_identical": len(set(hashes)) == 1, "cancelled": results[0][text]["cancelled"],
                        "questions": results[0][text]["questions"]}
    return {"runs": runs, "processes": f"a fresh interpreter per run, PYTHONHASHSEED 1..{runs}",
            "phase": "initial engine estimate before any ruling (the baseline's phase)", "storms": storms,
            "hash_identical": all(s["hash_identical"] for s in storms.values())}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="StormCheck held-out storm runs in this process")
    parser.add_argument("--storm-runs", default=",".join(STORM_DAYS))
    args = parser.parse_args()
    print(orjson.dumps(storm_runs(tuple(args.storm_runs.split(",")))).decode())
