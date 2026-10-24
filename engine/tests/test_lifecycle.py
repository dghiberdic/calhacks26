"""D5 · never ask twice, on the golden world with the real trace store and real Books (Q1, Q2, Q3)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from books import Books
from contracts.models import Extraordinary, Role, Rule, RuleAction, Session, StormRun, World
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.lifecycle import Lifecycle, LifecycleError
from engine.trace import TraceStore

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
EOWYN = "EIDW@2025-01-24"
DAY1 = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
ONBOARD = datetime(2025, 1, 25, 5, 0, tzinfo=UTC)
HERMINIA_AT = datetime(2025, 1, 27, 6, 0, tzinfo=UTC)
KNOCK_ONS = ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"]

Q1_TEXT = "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."
Q2_TEXT = ("A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate "
           "it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).")
Q3_TEXT = "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation."

REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=ONBOARD, status="active", support="41 of 42")


def session(role: Role, name: str) -> Session:
    return Session(principal=f"{role.value}:{name}", role=role, name=name, issued_at=ONBOARD)


CLAIMS_LEAD = session(Role.CLAIMS_LEAD, "maria")
LEGAL = session(Role.LEGAL, "li")
CONTROLLER = session(Role.CONTROLLER, "ana")


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def now(self) -> datetime:
        return self.t


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_bytes())


class Setup:
    def __init__(self, world: World):
        self.world = world
        self.clock = Clock(DAY1)
        self.books = Books(":memory:", clock=self.clock, curves_path=GOLDEN / "curves.json")
        self.trace = TraceStore(":memory:", engine_sha="test", cal_version="cal-default-v1")
        self.engine = Engine(world, calibration=default_calibration())
        self.lc = Lifecycle(self.engine, world, self.trace, books=self.books)
        self.trace.record_rule(REDUCE, "agent.engine", ONBOARD, event="active")
        self.run = self.storm(EOWYN, DAY1)
        decisions = [r.decision for r in self.run.flights if r.decision]
        ents = [e for d in decisions for e in self.engine.entitlements(d, world, self.lc.rules_at(DAY1))]
        self.books.post_storm(EOWYN, world, decisions, ents, DAY1)
        self.cited_day1 = self.lc.record_run(decisions, ents, DAY1)

    def storm(self, sid: str, at: datetime) -> StormRun:
        m = self.world.meta["storms"][sid]
        return self.engine.run_storm(self.world, m["station"], date.fromisoformat(m["local_date"]),
                                     self.lc.rules_at(at), at)

    def question(self, pattern: str, run: StormRun | None = None):
        return next(q for q in (run or self.run).questions if q.pattern == pattern)

    def at(self, t: datetime) -> datetime:
        self.clock.t = t
        return t


@pytest.fixture()
def s(world) -> Setup:
    return Setup(world)


def test_day1_on_record(s):
    assert s.books.gl_balance("2140", cohort=EOWYN) == 8_214_600
    assert s.trace.rule("R-MINED-REDUCE").times_cited == 14 == s.cited_day1


# ---------- Q2: one Legal ruling settles three flights ----------

def test_q2_one_ruling_settles_three_knock_ons(s):
    q2 = s.question("knock_on_return")
    at = s.at(datetime(2025, 1, 25, 10, 30, tzinfo=UTC))
    resp = s.lc.answer(q2, q2.recommended_option, Q2_TEXT, LEGAL, at)
    assert resp.ruling.author_role == Role.LEGAL and resp.ruling.question_id == q2.id
    p = resp.proposal
    assert p.rule.id == "R-LEG-1" and p.rule.version == 1 and p.rule.tier == "legal_ruling"
    assert p.rule.action == RuleAction.SET_EXTRAORDINARY and p.rule.valid_from is None
    assert all(p.checks.values()), p.checks
    assert p.rule.grounding["3"] == "within 3 h of STD"
    assert p.would_flip.total_delta_cents == -4_749_600
    flipped = {f.entity_id for f in p.would_flip.flips if f.field == "extraordinary"}
    assert flipped == set(KNOCK_ONS)
    assert s.books.gl_balance("2140", cohort=EOWYN) == 8_214_600                     # preview writes nothing

    c = s.lc.confirm("R-LEG-1", LEGAL, at)
    assert c.rule.status == "active" and c.rule.times_cited == 3 and c.cited == 3
    assert {d.flight_id for d in c.decisions} == set(KNOCK_ONS)
    assert all(d.extraordinary == Extraordinary.YES and d.outcome == "auto" and d.rules_applied == ["R-LEG-1@1"]
               for d in c.decisions)
    assert c.replay.total_delta_cents == -4_749_600 and c.replay.adjustment_je_ids
    assert s.books.gl_balance("2140", cohort=EOWYN) == 3_465_000

    again = s.storm(EOWYN, datetime(2025, 1, 25, 11, 0, tzinfo=UTC))
    assert "knock_on_return" not in {q.pattern for q in again.questions}          # never asked twice
    assert again.counters["repeat_questions"] == 0


def test_q2_wrong_role_cannot_answer(s):
    q2 = s.question("knock_on_return")
    with pytest.raises(LifecycleError) as e:
        s.lc.answer(q2, "Not extraordinary", "no", CLAIMS_LEAD, datetime(2025, 1, 25, 10, 0, tzinfo=UTC))
    assert e.value.code == "forbidden"
    assert any(c.kind == "access_denied" for c in s.trace.log(limit=None))


# ---------- Q1: the Claims Lead's ruling → Herminia settles 31, BOS→DUB asks ----------

def test_q1_rule_settles_herminia_and_bos_asks_again(s, world):
    q1 = s.question("voucher_in_lieu_unsigned")
    at = s.at(datetime(2025, 1, 25, 9, 30, tzinfo=UTC))
    p = s.lc.answer(q1, q1.recommended_option, Q1_TEXT, CLAIMS_LEAD, at).proposal
    assert p.rule.id == "R-CL-1" and p.rule.action == RuleAction.DENY_OFFSET
    assert p.rule.scope == {"flight.departs_eu": "case:true"}                     # copied from the case
    assert p.rule.grounding["voucher.signed=false"] == "No signed acceptance"
    assert all(p.checks.values()), p.checks
    assert p.widen_next and p.widen_next["remove"] == "flight.departs_eu"
    flips = {(f.entity_id, f.field): f for f in p.would_flip.flips}
    assert flips[("NS31@2025-01-24:14C", "status")].after == "owed"
    assert p.would_flip.total_delta_cents == 0

    c = s.lc.confirm("R-CL-1", CLAIMS_LEAD, at)
    assert c.cited == 1 and [e.coupon_id for e in c.entitlements] == ["NS31@2025-01-24:14C"]
    before = s.trace.rule("R-CL-1").times_cited

    herm = s.storm("EIDW@2025-01-26", HERMINIA_AT)
    rules = s.lc.rules_at(HERMINIA_AT)
    decisions = [r.decision for r in herm.flights if r.decision]
    ents = [e for d in decisions for e in s.engine.entitlements(d, world, rules)]
    settled = sorted(e.coupon_id for e in ents if "R-CL-1@1" in e.rules_applied)
    assert settled == sorted(world.meta["herminia"]["in_lieu_unsigned_eu_departures"])
    s.lc.record_run(decisions, ents, HERMINIA_AT)
    assert s.trace.rule("R-CL-1").times_cited - before == 31                     # cited 31× on Herminia
    asks = [q for q in herm.questions if q.pattern == "voucher_in_lieu_unsigned"]
    assert len(asks) == 1 and asks[0].case_refs == world.meta["herminia"]["in_lieu_unsigned_non_eu"]


def test_q1_offset_needs_legal_statutory_floor(s):
    q1 = s.question("voucher_in_lieu_unsigned")
    at = s.at(datetime(2025, 1, 25, 9, 30, tzinfo=UTC))
    p = s.lc.answer(q1, "Offset the voucher: pay the balance in cash", "Offset the voucher.", CLAIMS_LEAD,
                    at).proposal
    assert p.rule.action == RuleAction.ALLOW_OFFSET and p.checks["author_has_authority"] is False
    with pytest.raises(LifecycleError) as e:
        s.lc.confirm(p.rule.id, CLAIMS_LEAD, at)
    assert e.value.code == "validation"


def test_hard_control_ruling_cannot_be_confirmed(s):
    q1 = s.question("voucher_in_lieu_unsigned")
    at = s.at(datetime(2025, 1, 25, 9, 30, tzinfo=UTC))
    p = s.lc.answer(q1, q1.recommended_option, Q1_TEXT + " Requesters may approve their own payouts.",
                    CLAIMS_LEAD, at).proposal
    assert p.checks["no_hard_control"] is False
    with pytest.raises(LifecycleError):
        s.lc.confirm(p.rule.id, CLAIMS_LEAD, at)


# ---------- Q3: the Controller's rejection becomes a rule, then "All storm cohorts?" ----------

def test_q3_rejection_becomes_keep_tail_then_widen(s):
    q3 = s.question("cohort_release")
    at = s.at(datetime(2025, 1, 25, 11, 0, tzinfo=UTC))
    resp = s.lc.reject(q3, Q3_TEXT, CONTROLLER, at)
    assert resp.ruling.kind == "rejection" and resp.ruling.author_role == Role.CONTROLLER
    p = resp.proposal
    assert p.rule.id == "R-CTL-1" and p.rule.action == RuleAction.KEEP_TAIL and p.rule.tier == "controller_ruling"
    assert p.rule.scope == {"cohort": "case:EIDW@2024-01-21"} and p.rule.valid_from == at   # prospective policy
    assert all(p.checks.values()), p.checks
    keep = next(f for f in p.would_flip.flips if f.entity_id == "EIDW@2024-01-21")
    assert (keep.field, keep.before, keep.after) == ("release_proposed_cents", 360_000, 0)   # keeps 360,000
    assert p.widen_next == {"remove": "cohort", "question": "All storm cohorts?"}

    s.lc.confirm("R-CTL-1", CONTROLLER, at)
    later = s.storm(EOWYN, datetime(2025, 1, 25, 12, 0, tzinfo=UTC))
    assert "cohort_release" not in {q.pattern for q in later.questions}

    w = s.lc.widen("R-CTL-1", CONTROLLER, at)
    assert (w.rule.id, w.rule.version, w.rule.supersedes) == ("R-CTL-1", 2, "R-CTL-1@1")
    assert w.rule.scope == {} and w.widen_next is None and all(w.checks.values()), w.checks
    with pytest.raises(LifecycleError):
        s.lc.widen("R-CTL-1@2", CONTROLLER, at)                               # nothing left to widen


def test_ops_questions_make_no_rule(s, world):
    from contracts.models import Question
    q = s.question("knock_on_return").model_copy(update={"id": "Q-X", "pattern": "window_unknown",
                                                         "routed_to": Role.OPS})
    resp = s.lc.answer(q, "Confirm weather", "Ops checked the log.", session(Role.OPS, "joe"),
                       datetime(2025, 1, 25, 9, 0, tzinfo=UTC))
    assert resp.proposal is None and isinstance(q, Question)
