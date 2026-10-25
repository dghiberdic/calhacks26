"""Run a ruling-owned test pack against the existing Engine, without activating rules.

The oracle below describes the Q1 ruling's permitted scope. It is fixed independently
of the candidate: changing a draft can never rewrite its expected results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import orjson

from books import Books
from books.errors import SoDViolation
from contracts.models import Role, Rule, RuleAction, Session, World
from engine import dsl, eu261
from engine import rules as rulebook
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.geo import airport, distance_km
from engine.lifecycle import Lifecycle
from engine.trace import TraceStore
from eval.rule_lab.oracle import PROTECTED_RESULTS

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts/fixtures/golden"
DAY1 = datetime(2025, 1, 25, 6, tzinfo=UTC)
ONBOARD = datetime(2025, 1, 25, 5, tzinfo=UTC)
Q1_AT = datetime(2025, 1, 25, 9, 30, tzinfo=UTC)
HERMINIA_AT = datetime(2025, 1, 27, 6, tzinfo=UTC)
Q1_TEXT = "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."
ORIGINAL = "NS31@2025-01-24:14C"
EOWYN = "EIDW@2025-01-24"
PRESETS = {
    "scoped": {"title": "Respect the ruling", "description": "EU departures, unsigned compensation vouchers only."},
    "wrong_authority": {
        "title": "Agent claims rule authority",
        "description": "Test mutation: submit the policy with an agent as its author.",
    },
    "missing_guard": {
        "title": "Drop the consent condition",
        "description": "Test mutation: remove the unsigned-consent condition from the draft.",
    },
    "broader_scope": {
        "title": "Remove the EU boundary",
        "description": "Test mutation: apply the same ruling to non-EU departures, without reauthorization.",
    },
}


def digest(value: Any) -> str:
    return sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()


@dataclass
class Clock:
    at: datetime = DAY1

    def now(self) -> datetime:
        return self.at


def reduction_rule() -> Rule:
    return Rule(
        id="R-MINED-REDUCE",
        version=1,
        kind="mined_policy",
        scope={},
        condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
        action=RuleAction.APPLY_7_2_REDUCTION,
        tier="mined",
        authority_required=Role.CLAIMS_LEAD,
        valid_from=None,
        recorded_at=ONBOARD,
        status="active",
        support="41 of 42",
    )


def snapshot(ent) -> dict[str, Any]:
    return {
        "status": ent.status,
        "compensation_cents": ent.compensation_cents,
        "voucher_offset_cents": ent.voucher_offset_cents,
        "cash_cents": ent.compensation_cents - ent.voucher_offset_cents,
        "refund_due_cents": ent.refund_due_cents,
        "rules_applied": ent.rules_applied,
    }


def run_lab(preset: str = "scoped") -> dict[str, Any]:
    """Return deterministic evidence. This function has no network or persistent writes."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown scenario: {preset}. Choose one of: {', '.join(PRESETS)}.")
    raw = (GOLDEN / "world.json").read_bytes()
    world = World.model_validate_json(raw)
    engine = Engine(world, calibration=default_calibration())
    trace = TraceStore(":memory:", engine_sha="rule-lab", cal_version="cal-default-v1")
    books = Books(":memory:", clock=Clock(), curves_path=GOLDEN / "curves.json")
    try:
        reduce = reduction_rule()
        trace.record_rule(reduce, "agent.engine", ONBOARD, event="active")
        lifecycle = Lifecycle(engine, world, trace, books=books)
        initial = engine.run_storm(world, "EIDW", date(2025, 1, 24), [reduce], DAY1)
        decisions = [f.decision for f in initial.flights if f.decision]
        ents = [e for d in decisions for e in engine.entitlements(d, world, [reduce])]
        books.post_storm(EOWYN, world, decisions, ents, DAY1)
        lifecycle.record_run(decisions, ents, DAY1)
        question = next(q for q in initial.questions if q.pattern == "voucher_in_lieu_unsigned")
        author = Session(
            principal="claims_lead:lab-reviewer", role=Role.CLAIMS_LEAD, name="Lab reviewer", issued_at=ONBOARD
        )
        response = lifecycle.answer(question, question.recommended_option, Q1_TEXT, author, Q1_AT)
        proposal = response.proposal
        assert proposal is not None
        candidate = proposal.rule.model_copy(deep=True)
        if preset == "broader_scope":
            candidate.scope = {}
        if preset == "missing_guard":
            candidate.condition = {"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True}]}
        candidate, core_checks, core_problems = rulebook.checks(
            candidate,
            author_role=Role.ENGINE if preset == "wrong_authority" else author.role,
            ruling=response.ruling,
            case_feats=lifecycle.case_features(question, Q1_AT),
            existing=[reduce],
        )
        # Simulate an active copy in this call only. The proposal and trace remain proposed.
        active = candidate.model_copy(deep=True, update={"status": "active"})
        cases: list[dict[str, Any]] = []
        cache: dict[tuple[str, datetime], tuple[dict, dict, dict]] = {}

        def evaluate(w: World, coupon: str, at: datetime, *, cached: bool = True):
            fid = coupon.split(":")[0]
            key = (fid, at)
            if cached and key in cache:
                return cache[key]
            before_d = engine.decide_in(w, fid, [reduce], at)
            after_d = engine.decide_in(w, fid, [reduce, active], at)
            before = {e.coupon_id: e for e in eu261.entitlements(before_d, w, [reduce], at)}
            after = {e.coupon_id: e for e in eu261.entitlements(after_d, w, [reduce, active], at)}
            flight = next(f for f in w.flights if f.id == fid)
            o, dest = airport(w, flight.origin), airport(w, flight.dest)
            dist = distance_km(w, flight.origin, flight.dest)
            features = {
                v.coupon.id: eu261.coupon_features(
                    flight,
                    v,
                    eu261.band_for(dist, o.eu and dest.eu),
                    dist,
                    o,
                    dest,
                    after_d,
                )
                for v in eu261.coupon_views(w, fid, at)
            }
            result = (before, after, features)
            if cached:
                cache[key] = result
            return result

        def add_case(
            case_id: str,
            label: str,
            coupon: str,
            at: datetime,
            *,
            intended: bool,
            w: World = world,
            synthetic: bool = False,
            expected_cash: int = 25_000,
            expected_match: bool | None = None,
        ):
            before, after, features = evaluate(w, coupon, at, cached=not synthetic)
            b, a = snapshot(before[coupon]), snapshot(after[coupon])
            if intended:
                expected_result = {"status": "owed", "cash_cents": expected_cash, "voucher_offset_cents": 0}
                passed = (
                    b["status"] == "needs_ruling"
                    and a["status"] == "owed"
                    and "R-CL-1@1" in a["rules_applied"]
                    and a["cash_cents"] == expected_cash
                    and a["voucher_offset_cents"] == 0
                )
                expected = f"Resolve this unsigned EU-departure voucher; €{expected_cash // 100} cash, no offset."
            else:
                expected_result = PROTECTED_RESULTS[case_id]
                passed = b == a and "R-CL-1@1" not in a["rules_applied"]
                expected = "Preserve the existing result; this ruling gives no new authority here."
            passed = passed and all(a[key] == value for key, value in expected_result.items())
            flight = next(f for f in w.flights if f.id == coupon.split(":")[0])
            matches = bool(dsl.matching([active], features[coupon], known_at=at, flight_date=flight.date))
            if intended:
                expected_match = True
            if expected_match is not None:
                passed = passed and matches == expected_match
            if case_id == "signed-consent":
                expected = (
                    "Do not match signed vouchers; preserve €300 signed offset and €300 residual cash. "
                    "The engine already protects the amount even if this draft matches too broadly."
                )
            cases.append(
                {
                    "id": case_id,
                    "label": label,
                    "coupon_id": coupon,
                    "group": "intended" if intended else "protected",
                    "source": "synthetic counterexample" if synthetic else "golden demo fixture",
                    "expected": expected,
                    "expected_result": expected_result,
                    "before": b,
                    "after": a,
                    "passed": passed,
                    "candidate_matches": matches,
                    "expected_match": expected_match,
                }
            )

        if all(core_checks.values()):
            add_case(
                "original-ruling",
                "Original ruling · unsigned voucher",
                ORIGINAL,
                Q1_AT,
                intended=True,
                expected_cash=60_000,
            )
            for index, coupon in enumerate(world.meta["herminia"]["in_lieu_unsigned_eu_departures"], 1):
                add_case(
                    f"future-{index:02d}", f"Next storm · eligible case {index:02d}", coupon, HERMINIA_AT, intended=True
                )
            for coupon in world.meta["herminia"]["in_lieu_unsigned_non_eu"]:
                add_case(
                    "non-eu-boundary",
                    "Non-EU departure · needs its own ruling",
                    coupon,
                    HERMINIA_AT,
                    intended=False,
                    expected_match=False,
                )
            signed = world.model_copy(deep=True)
            for event in signed.crm:
                if event.coupon_id == ORIGINAL and event.kind == "voucher_in_lieu_of_compensation":
                    event.signed_acceptance_sha256 = "a" * 64
                    event.text = "Simulated signed acceptance of a €300 compensation voucher."
            add_case(
                "signed-consent",
                "Signed acceptance · preserve the €300 offset",
                ORIGINAL,
                Q1_AT,
                intended=False,
                w=signed,
                synthetic=True,
                expected_match=False,
            )
            ordinary = world.model_copy(deep=True)
            ordinary.crm = [
                e for e in ordinary.crm if not (e.coupon_id == ORIGINAL and e.kind == "voucher_in_lieu_of_compensation")
            ]
            add_case(
                "no-voucher",
                "No compensation voucher · unchanged",
                ORIGINAL,
                Q1_AT,
                intended=False,
                w=ordinary,
                synthetic=True,
                expected_match=False,
            )
            staff = world.model_copy(deep=True)
            next(c for c in staff.coupons if c.id == ORIGINAL).fare_type = "staff_id90"
            add_case(
                "staff-fare",
                "Staff fare · retain the existing exclusion",
                ORIGINAL,
                Q1_AT,
                intended=False,
                w=staff,
                synthetic=True,
            )
            notice = world.model_copy(deep=True)
            f = next(f for f in notice.flights if f.id == ORIGINAL.split(":")[0])
            f.notified_at = f.sched_dep - timedelta(days=15)
            add_case(
                "early-notice",
                "15 days notice · retain the existing exemption",
                ORIGINAL,
                Q1_AT,
                intended=False,
                w=notice,
                synthetic=True,
            )
            weather_d = next(d for d in decisions if d.extraordinary.value == "extraordinary" and d.outcome == "auto")
            weather_coupon = next(c.id for c in world.coupons if c.flight_id == weather_d.flight_id)
            add_case("weather", "Weather cancellation · unchanged", weather_coupon, Q1_AT, intended=False)
        liability_before = books.gl_balance("2140", cohort=EOWYN)
        accounting = None
        if all(core_checks.values()):
            after_run = engine.run_storm(world, "EIDW", date(2025, 1, 24), [reduce, active], Q1_AT)
            after_decisions = [f.decision for f in after_run.flights if f.decision]
            after_ents = [e for d in after_decisions for e in eu261.entitlements(d, world, [reduce, active], Q1_AT)]
            books.clock.at = Q1_AT
            books.post_storm(EOWYN, world, after_decisions, after_ents, Q1_AT)
            once = books.journal()
            books.post_storm(EOWYN, world, after_decisions, after_ents, Q1_AT)
            twice = books.journal()
            agent = Session(principal="agent.engine", role=Role.ENGINE, name="Engine", issued_at=ONBOARD)
            entry = next(j for j in twice if j.status == "draft" and j.kind == "compensation_estimate")
            blocked = False
            try:
                books.approve(entry.id, agent)
            except SoDViolation:
                blocked = True
            accounting = {
                "liability_before_cents": liability_before,
                "liability_after_cents": books.gl_balance("2140", cohort=EOWYN),
                "new_entries_on_retry": len(twice) - len(once),
                "unbalanced_entries": sum(sum(line.dr_cents - line.cr_cents for line in j.lines) != 0 for j in twice),
                "agent_approval_blocked": blocked,
                "approved_entries": sum(j.status == "approved" for j in books.journal()),
                "journal_entries": len(twice),
            }
        checks = [
            {
                "id": f"engine:{key}",
                "label": key.replace("_", " ").capitalize(),
                "group": "existing_engine",
                "passed": value,
                "detail": "Existing StormCheck proposal gate.",
            }
            for key, value in core_checks.items()
        ]
        checks += [
            {
                "id": f"case:{c['id']}",
                "label": c["label"],
                "group": c["group"],
                "passed": c["passed"],
                "detail": c["expected"],
            }
            for c in cases
        ]
        if accounting is not None:
            for key, label, passed, detail in [
                (
                    "liability",
                    "Liability estimate unchanged",
                    accounting["liability_before_cents"] == accounting["liability_after_cents"] == 8_214_600,
                    "Q1 changes voucher handling, not the €82,146 whole-storm estimate.",
                ),
                (
                    "retry",
                    "Retry creates no duplicate entries",
                    accounting["new_entries_on_retry"] == 0,
                    "Run the same accounting work twice in the scratch ledger.",
                ),
                (
                    "balance",
                    "Every journal entry balances",
                    accounting["unbalanced_entries"] == 0,
                    "Sum of debits equals sum of credits for each entry.",
                ),
                (
                    "approval",
                    "Agent cannot approve a journal",
                    accounting["agent_approval_blocked"],
                    "The real Books approval gate rejects the agent session.",
                ),
                (
                    "unapproved",
                    "No journal approval from testing",
                    accounting["approved_entries"] == 0,
                    "All lab-created proposals remain unapproved.",
                ),
            ]:
                checks.append(
                    {
                        "id": f"accounting:{key}",
                        "label": label,
                        "group": "accounting",
                        "passed": passed,
                        "detail": detail,
                    }
                )
        unchanged = sha256((GOLDEN / "world.json").read_bytes()).hexdigest() == sha256(raw).hexdigest()
        checks.append(
            {
                "id": "isolation:fixture",
                "label": "Golden inputs unchanged",
                "group": "isolation",
                "passed": unchanged,
                "detail": "Read-only source fixture.",
            }
        )
        proposal_status = trace.rule(candidate.id).status
        activated = sum(r.id == candidate.id and r.status == "active" for r in trace.rules_known_at(None))
        checks.append(
            {
                "id": "isolation:proposal",
                "label": "Candidate remains a proposal",
                "group": "isolation",
                "passed": proposal_status == candidate.status == "proposed" and activated == 0,
                "detail": "No confirmation event is written, even to the temporary rule store.",
            }
        )
        failed = sum(not c["passed"] for c in checks)
        report = {
            "schema": "stormcheck-rule-lab-v1",
            "preset": preset,
            "scenario": PRESETS[preset],
            "verdict": "blocked" if failed else "ready_for_review",
            "simulation_ran": all(core_checks.values()),
            "submitted_author_role": (Role.ENGINE if preset == "wrong_authority" else author.role).value,
            "label": "StormCheck simulated demo · regression evidence, not approval or certification",
            "ruling": response.ruling.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "existing_gate_problems": core_problems,
            "summary": {
                "intended_cases": sum(c["group"] == "intended" for c in cases),
                "protected_cases": sum(c["group"] == "protected" for c in cases),
                "passed_checks": len(checks) - failed,
                "failed_checks": failed,
                "total_checks": len(checks),
            },
            "cases": cases,
            "checks": checks,
            "accounting": accounting,
            "isolation": {
                "storage": ":memory:",
                "activated_rules": activated,
                "stored_candidate_status": proposal_status,
                "persistent_writes": 0,
                "fixture_unchanged": unchanged,
                "model_calls": 0,
            },
            "fingerprints": {
                "candidate_sha256": digest(candidate.model_dump(mode="json")),
                "world_sha256": sha256(raw).hexdigest(),
                "curves_sha256": sha256((GOLDEN / "curves.json").read_bytes()).hexdigest(),
                "test_pack_sha256": digest(
                    {
                        p.name: sha256(p.read_bytes()).hexdigest()
                        for p in (Path(__file__), Path(__file__).with_name("oracle.py"))
                    }
                ),
                "implementation_sha256": digest(
                    {
                        str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                        for folder in ("engine", "books", "contracts")
                        for p in sorted((ROOT / folder).rglob("*.py"))
                        if "tests" not in p.relative_to(ROOT / folder).parts
                    }
                ),
            },
            "limitations": [
                "Supports the Q1 unsigned-voucher rule family only.",
                "Fixed simulated cases cannot establish correctness on unseen production data.",
                "Passing only produces evidence for a human reviewer; it never confirms a rule.",
            ],
        }
        report["fingerprints"]["report_sha256"] = digest(report)
        return report
    finally:
        books.close()
        trace.close()
