"""D8 · Trace: append-only event store, hash chain, blame, replay(known_at), revert, IAS 8.5 class."""
from __future__ import annotations

import hashlib
import itertools
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

import orjson
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from contracts.models import (
    AccessDecision,
    Cause,
    Confidence,
    Entitlement,
    Evidence,
    Extraordinary,
    Fact,
    FlightDecision,
    JournalEntry,
    JournalLine,
    MetarObs,
    Question,
    Role,
    Rule,
    RuleAction,
    Ruling,
    Session,
    Source,
    SourceKind,
)
from engine import dsl, trace
from engine.trace import EvidenceUse, TraceStore, ias8_class

ENGINE = "abc1234"
CAL = "cal-v1"
NS31 = "NS31@2025-01-24"
NS117 = "NS117@2025-01-24"
FLIGHT_DATE = date(2025, 1, 24)

T_FACTS = datetime(2025, 1, 25, 5, 0, tzinfo=UTC)
T_RULE = datetime(2025, 1, 25, 7, 0, tzinfo=UTC)
T_RUN = datetime(2025, 1, 25, 8, 0, tzinfo=UTC)
T_JE = datetime(2025, 1, 25, 8, 5, tzinfo=UTC)
T_LOCK = datetime(2025, 2, 3, 9, 0, tzinfo=UTC)
T_REVERT = datetime(2025, 2, 10, 9, 0, tzinfo=UTC)

TECH_LOG_TEXT = ("23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM "
                 "LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.")
OCC_TEXT = "05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71. NS31 NS116/117. ASM SENT."
METAR_1600 = "EIDW 241600Z 23012G25KT 9999 -RA FEW012 SCT020 BKN050 05/00 Q0990 NOSIG"
METAR_1630 = "EIDW 241630Z 23011G22KT 190V270 9999 -RA FEW012 SCT020 BKN050 05/00 Q0990 NOSIG"
RULING_TEXT = ("A return sector whose outbound was cancelled for the storm is extraordinary: the aircraft never "
               "reached the outstation.")


def store() -> TraceStore:
    return TraceStore(":memory:", engine_sha=ENGINE, cal_version=CAL)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def source(sid: str, kind: SourceKind, text: str, received: datetime, tier: int, tags=None) -> Source:
    return Source(id=sid, kind=kind, title=sid, text=text, sha256=sha(text), received_at=received, trust_tier=tier,
                  acl_tags=tags or [])


def fact(fid: str, subject: str, field: str, value, src: str, span: str | None, recorded=T_FACTS) -> Fact:
    return Fact(id=fid, source_id=src, subject=subject, field=field, value=value, span=span,
                extractor="normalize@1", recorded_at=recorded)


def conf(score: float) -> Confidence:
    return Confidence(score=score, kind="cause", label="cause-finding confidence", features={},
                      calibration_version=CAL)


R_LEG_1 = Rule(id="R-LEG-1", version=1, kind="cause", tier="legal_ruling", authority_required=Role.LEGAL,
               scope={"flight.is_return_sector": True, "rotation.prev_cause": "weather"}, condition={"all": []},
               action=RuleAction.SET_EXTRAORDINARY, origin_ruling_id="RUL-Q2", valid_from=None,
               recorded_at=T_RULE, status="active", title="Knock-on returns of storm-cancelled outbounds")

COUPONS = {NS31: ["1A", "1B", "1C"], NS117: ["1A", "1B", "1C", "1D"]}
BAND = {NS31: 600, NS117: 250}


# ---------- a small pure decide function (stands in for engine.cause + engine.eu261) ----------

def latest(facts: Iterable[Fact]) -> dict[tuple[str, str], Fact]:
    out: dict[tuple[str, str], Fact] = {}
    for f in sorted(facts, key=lambda f: (f.recorded_at, f.id)):
        out[(f.subject, f.field)] = f
    return out


def ev(f: Fact, role="supports", struck=False, tier=1) -> Evidence:
    return Evidence(fact_id=f.id, source_id=f.source_id, field=f.field, value=f.value, quote=f.span, role=role,
                    trust_tier=tier, struck=struck)


def make_decide(use_tech_log: bool = True):
    def decide(facts: list[Fact], rules: list[Rule], known_at: datetime):
        v = latest(facts)
        out: list = []
        # NS31: the tech log (tier 1) beats the OCC code 71 (tier 3) when it is used
        tl = v.get((f"flight:{NS31}", "aog.mel_relief"))
        occ = v.get((f"flight:{NS31}", "flight.ops_cause_code"))
        wx = v.get((f"flight:{NS31}", "flight.in_window_dep"))
        if use_tech_log and tl is not None and tl.value is False:
            d31 = FlightDecision(
                flight_id=NS31, cause=Cause.TECHNICAL, extraordinary=Extraordinary.NO, ops_cause_code="71",
                recoded=True, recode_label="71 → 41", in_window_dep="out", in_window_arr="out",
                confidence=conf(0.91), reason="AOG before the window, no MEL relief",
                evidence=[ev(tl)] + ([ev(wx)] if wx else []) + (
                    [ev(occ, role="contradicts", struck=True, tier=3)] if occ else []),
                rules_applied=[], legal_basis=["EU261 Art.5(3)", "CJEU C-549/07"], outcome="auto", known_at=known_at)
        else:
            d31 = FlightDecision(
                flight_id=NS31, cause=Cause.WEATHER, extraordinary=Extraordinary.YES, ops_cause_code="71",
                recoded=False, in_window_dep="out", in_window_arr="out", confidence=conf(0.62),
                reason="OCC code 71", evidence=[ev(occ, tier=3)] if occ else [], rules_applied=[],
                legal_basis=["EU261 Art.5(3)"],
                outcome="auto", known_at=known_at)
        out.append(d31)
        # NS117: knock-on return; extraordinary only under an active legal rule
        feats = {"flight.is_return_sector": True, "rotation.prev_cause": "weather"}
        hits = dsl.matching(rules, feats, actions={RuleAction.SET_EXTRAORDINARY}, known_at=known_at,
                            flight_date=FLIGHT_DATE)
        ko = v.get((f"flight:{NS117}", "rotation.prev_cause"))
        arr = v.get((f"flight:{NS117}", "flight.in_window_arr"))
        evidence = [ev(f) for f in (ko, arr) if f is not None]
        if hits:
            d117 = FlightDecision(
                flight_id=NS117, cause=Cause.KNOCK_ON, extraordinary=Extraordinary.YES, ops_cause_code="71",
                recoded=False, in_window_dep="out", in_window_arr="out", confidence=conf(0.93),
                reason="knock-on return, ruled extraordinary", evidence=evidence,
                rules_applied=[dsl.ref(hits[0])], legal_basis=["EU261 Art.5(3)"], outcome="auto", known_at=known_at)
        else:
            d117 = FlightDecision(
                flight_id=NS117, cause=Cause.KNOCK_ON, extraordinary=Extraordinary.NEEDS_LEGAL, ops_cause_code="71",
                recoded=False, in_window_dep="out", in_window_arr="out", confidence=conf(0.47),
                reason="knock-on return, no precedent", evidence=evidence, rules_applied=[],
                legal_basis=["EU261 Art.5(3)"], outcome="escalated", routed_to=Role.LEGAL, known_at=known_at)
        out.append(d117)
        for d in (d31, d117):
            for seat in COUPONS[d.flight_id]:
                comp = 0 if d.extraordinary == Extraordinary.YES else BAND[d.flight_id] * 100
                status = {Extraordinary.YES: "no_compensation", Extraordinary.NO: "owed",
                          Extraordinary.NEEDS_LEGAL: "held"}[d.extraordinary]
                out.append(Entitlement(coupon_id=f"{d.flight_id}:{seat}", flight_id=d.flight_id, distance_km=1000.0,
                                       band_eur=BAND[d.flight_id], band_margin_km=10.0, compensation_cents=comp,
                                       status=status, article="Art. 7(1)", reason="test",
                                       rules_applied=list(d.rules_applied)))
        return out
    return decide


def seed(s: TraceStore, *, decide=None, with_tech_log: bool = True) -> dict:
    """Sources → METAR obs → facts → question → ruling → rule → decisions → entitlements → JE."""
    metar_src = source("SRC-METAR-EIDW", SourceKind.METAR, f"{METAR_1600}\n{METAR_1630}",
                       datetime(2025, 1, 25, 0, 0, tzinfo=UTC), 1, ["ops"])
    tl_src = source("SRC-TECHLOG-EI-NSB", SourceKind.TECH_LOG, TECH_LOG_TEXT,
                    datetime(2025, 1, 23, 21, 40, tzinfo=UTC), 1, ["maintenance"])
    occ_src = source("SRC-OCC-0512", SourceKind.OCC_LOG, OCC_TEXT, datetime(2025, 1, 24, 5, 12, tzinfo=UTC), 3, ["ops"])
    for src in (metar_src, tl_src, occ_src):
        s.record_source(src, "agent.engine", T_FACTS)
    obs = [MetarObs(station="EIDW", valid=datetime(2025, 1, 24, 16, 0, tzinfo=UTC), sknt=12, gust=25, raw=METAR_1600),
           MetarObs(station="EIDW", valid=datetime(2025, 1, 24, 16, 30, tzinfo=UTC), sknt=11, gust=22, raw=METAR_1630)]
    s.record_metar(obs, "agent.engine", T_FACTS, source_id=metar_src.id)
    facts = [
        fact("F-TL-1", f"flight:{NS31}", "aog.mel_relief", False, tl_src.id, "NO MEL RELIEF. A/C AOG."),
        fact("F-WX-31", f"flight:{NS31}", "flight.in_window_dep", "out", metar_src.id, METAR_1630),
        fact("F-OCC-31", f"flight:{NS31}", "flight.ops_cause_code", "71", occ_src.id, "RSN 71"),
        fact("F-KO-117", f"flight:{NS117}", "rotation.prev_cause", "weather", occ_src.id, "NS116/117"),
        fact("F-WX-117", f"flight:{NS117}", "flight.in_window_arr", "out", metar_src.id, METAR_1600),
    ]
    if not with_tech_log:
        facts = facts[1:]
    s.record_facts(facts, "agent.reader", T_FACTS)
    q = Question(id="Q-2", case_refs=[NS117], pattern="knock_on_return", routed_to=Role.LEGAL, asked_at=T_FACTS,
                 title="Knock-on return", found="f", why_flagged="w", recommends="r", recommended_option="extraordinary",
                 options=["extraordinary", "not_extraordinary"], evidence=[ev(facts[-2])], confidence=conf(0.47),
                 reason_tag="no-precedent", remind_at=T_FACTS + timedelta(hours=3))
    s.record_question(q, "agent.engine", T_FACTS + timedelta(minutes=1))
    ruling = Ruling(id="RUL-Q2", question_id="Q-2", author_role=Role.LEGAL, author="legal:aoife-byrne", kind="answer",
                    decision="extraordinary", explanation=RULING_TEXT, at=T_RULE - timedelta(minutes=5))
    s.record_ruling(ruling, "legal:aoife-byrne", T_RULE - timedelta(minutes=5))
    s.record_question(q, "agent.engine", T_RULE - timedelta(minutes=5), event="answered")
    s.record_rule(R_LEG_1, "agent.engine", T_RULE)
    out = list((decide or make_decide())(s.facts_known_at(T_RUN), s.rules_known_at(T_RUN), T_RUN))
    for d in out:
        if isinstance(d, FlightDecision):
            s.record_decision(d, "agent.engine", T_RUN)
    s.record_entitlements([e for e in out if isinstance(e, Entitlement)], "agent.engine", T_RUN)
    je = JournalEntry(id="JE-000101", event_date=FLIGHT_DATE, period="2025-01", kind="compensation_estimate",
                      memo="NS31 EU261 compensation liability", status="draft", preparer="agent.engine",
                      source_decision_id=NS31,
                      lines=[JournalLine(account="4090", account_name="EU261 compensation (reduction of passenger "
                                         "revenue)", dr_cents=63_000, dims={"flight": NS31}),
                             JournalLine(account="2140", account_name="EU261 compensation liability (estimated)",
                                         cr_cents=63_000, dims={"flight": NS31})])
    s.record_journal(je, "agent.books", T_JE)
    return {"facts": facts, "out": out, "je": je}


# ---------- append-only storage ----------

def test_update_and_delete_abort_on_every_table():
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    s.cite_rule("R-LEG-1@1", NS117, "agent.engine", T_RUN)
    for table in trace.TABLES:
        n = s.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n > 0, f"{table} has no rows, so its UPDATE trigger is not exercised"
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            s.conn.execute(f"UPDATE {table} SET seq = seq")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            s.conn.execute(f"DELETE FROM {table}")
    assert s.verify().ok


def test_status_fields_are_views_over_events():
    s = store()
    views = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
    assert {"rule_status", "question_status", "current_decisions", "period_status"} <= views
    rule = R_LEG_1.model_copy(update={"status": "proposed"})
    s.record_rule(rule, "agent.engine", T_RULE)
    assert s.rule("R-LEG-1@1").status == "proposed"
    s.record_rule(rule, "legal:aoife-byrne", T_RULE + timedelta(minutes=1), event="active")
    s.cite_rule("R-LEG-1@1", "NS113@2025-01-24", "agent.engine", T_RUN)
    s.cite_rule("R-LEG-1", "NS115@2025-01-24", "agent.engine", T_RUN)
    row = s.conn.execute("SELECT status, times_cited FROM rule_status WHERE rule_id = 'R-LEG-1'").fetchone()
    assert tuple(row) == ("active", 2)
    assert s.rule("R-LEG-1@1").times_cited == 2
    s.record_rule(rule, "controller:ana", T_REVERT, event="retired")
    assert s.rule("R-LEG-1").status == "retired"
    # bitemporal: as known before the retirement the rule was still active
    assert {r.id: r.status for r in s.rules_known_at(T_RUN)} == {"R-LEG-1": "active"}
    assert s.rules_known_at(T_RULE - timedelta(hours=1)) == []

    q = Question(id="Q-9", case_refs=[NS117], pattern="knock_on_return", routed_to=Role.LEGAL, asked_at=T_FACTS,
                 title="t", found="f", why_flagged="w", recommends="r", recommended_option="a", options=["a"],
                 evidence=[], confidence=conf(0.4), reason_tag="no-precedent")
    s.record_question(q, "agent.engine", T_FACTS)
    assert s.question("Q-9").status == "open"
    s.record_question(q, "agent.engine", T_FACTS + timedelta(hours=3), event="reminded")
    assert s.question("Q-9").status == "reminded"
    s.record_question(q, "agent.engine", T_FACTS + timedelta(hours=4), event="answered")
    assert s.question("Q-9").status == "answered"
    assert [x.id for x in s.questions(status="answered")] == ["Q-9"]

    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    assert s.locked_periods() == {"2025-01": T_LOCK}


# ---------- commits & the chain ----------

def test_commit_hash_is_sha256_of_canonical_fields():
    s = store()
    c = s.commit("fact", {"b": 2, "a": [1, "x"]}, "agent.engine", [], T_RUN, ref="X-1", message="m")
    ph = hashlib.sha256(orjson.dumps({"a": [1, "x"], "b": 2}, option=orjson.OPT_SORT_KEYS)).hexdigest()
    assert c.payload_hash == ph
    expected = hashlib.sha256(orjson.dumps(
        {"kind": "fact", "parent": None, "payload_hash": ph, "inputs": ["engine@abc1234", "cal@cal-v1"],
         "at": "2025-01-25T08:00:00Z", "actor": "agent.engine"}, option=orjson.OPT_SORT_KEYS)).hexdigest()
    assert c.hash == expected == trace.commit_hash(c)
    assert c.parent is None and c.payload_ref == "X-1"


def test_inputs_carry_passed_in_engine_sha_and_calibration_version():
    s = store()
    a = s.commit("fact", {"i": 1}, "agent.engine", [], T_RUN, ref="A")
    b = s.commit("decision", {"i": 2}, "agent.engine", [a.hash, "engine@abc1234"], T_RUN, ref="B")
    assert b.inputs == [a.hash, "engine@abc1234", "cal@cal-v1"]   # deduped; links first, then engine@, cal@
    assert b.parent == a.hash and s.head() == b.hash
    with pytest.raises(ValueError):
        TraceStore(":memory:", engine_sha="", cal_version=CAL)
    with pytest.raises(ValueError):
        TraceStore(":memory:", engine_sha=ENGINE, cal_version="")
    with pytest.raises(ValueError):
        s.commit("fact", {}, "agent.engine", [], datetime(2025, 1, 25, 8, 0), ref="naive")   # naive time
    assert TraceStore(":memory:", engine_sha="engine@abc1234", cal_version="cal@cal-v1").base_inputs == (
        "engine@abc1234", "cal@cal-v1")


def test_chain_links_every_commit_to_its_parent_and_verifies():
    s = store()
    seed(s)
    commits = s.all_commits()
    assert len(commits) == len(s) == 19
    assert commits[0].parent is None
    assert all(c.parent == p.hash for p, c in itertools.pairwise(commits))
    v = s.verify()
    assert v.ok and v.checked == len(commits) and v.broken == ()
    assert v.summary() == f"{len(commits)} commits verified · chain intact"
    assert s.log(limit=3)[0].hash == s.head()          # newest first


TAMPER_COLUMNS = ["payload", "kind", "actor", "at", "inputs", "parent", "payload_hash", "hash"]


def _tampered(col: str, row: sqlite3.Row):
    if col == "payload":
        return orjson.dumps({**orjson.loads(row["payload"]), "tampered": True})
    if col == "kind":
        return "decision" if row["kind"] != "decision" else "fact"
    if col == "actor":
        return row["actor"] + "x"
    if col == "at":
        return "2030-01-01T00:00:00Z"
    if col == "inputs":
        return orjson.dumps([*orjson.loads(row["inputs"]), "f" * 64]).decode()
    if col == "parent":
        return "0" * 64
    if col == "payload_hash":
        return "0" * 64
    return "e" * 64


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(min_value=2, max_value=9), data=st.data())
def test_tampering_any_commit_breaks_it_and_every_descendant(n, data):
    s = store()
    kinds = ["fact", "decision", "entitlement", "rule_event", "journal_event"]
    for i in range(n):
        s.commit(kinds[i % len(kinds)], {"i": i, "v": data.draw(st.integers(-10**6, 10**6))}, f"agent.{i}",
                 [s.head()] if s.head() else [], T_RUN + timedelta(seconds=i), ref=f"X-{i}")
    assert s.verify().ok
    target = data.draw(st.integers(min_value=0, max_value=n - 1))
    col = data.draw(st.sampled_from(TAMPER_COLUMNS))
    row = s.conn.execute("SELECT * FROM commits ORDER BY seq LIMIT 1 OFFSET ?", (target,)).fetchone()
    s.conn.execute("DROP TRIGGER commits_no_update")      # an attacker with raw DB access
    s.conn.execute(f"UPDATE commits SET {col} = ? WHERE seq = ?", (_tampered(col, row), row["seq"]))
    v = s.verify()
    assert not v.ok
    assert v.broken == tuple(range(target, n)), (col, target, v.reasons)


def test_verify_chain_on_commit_objects():
    s = store()
    for i in range(4):
        s.commit("fact", {"i": i}, "agent.engine", [], T_RUN, ref=f"X-{i}")
    commits = s.all_commits()
    assert trace.verify_chain(commits).ok
    bad = list(commits)
    bad[1] = bad[1].model_copy(update={"actor": "mallory"})
    assert trace.verify_chain(bad).broken == (1, 2, 3)
    payloads = [{"i": i} for i in range(4)]
    assert trace.verify_chain(commits, payloads).ok
    payloads[2] = {"i": 99}
    assert trace.verify_chain(commits, payloads).broken == (2, 3)


# ---------- replay ----------

def test_replay_is_hash_identical_when_run_twice_and_writes_nothing():
    s = store()
    seed(s)
    n = len(s)
    a = s.replay_run(T_REVERT, make_decide())
    b = s.replay_run(T_REVERT, make_decide())
    assert trace.model_hash(a.diff) == trace.model_hash(b.diff)
    assert a.output_hash == b.output_hash
    assert s.replay(T_REVERT, make_decide()) == a.diff
    assert a.diff.flips == [] and a.diff.total_delta_cents == 0     # same facts, same rules: nothing flips
    assert len(s) == n and s.verify().ok                              # replay is read-only (no llm_call either)


def test_replay_uses_facts_as_known_at_and_rules_override():
    s = store()
    seed(s)
    # before the facts were recorded, NS31 has no tech-log evidence: the toy decide falls back to the OCC code
    early = s.replay_run(T_FACTS - timedelta(minutes=1), make_decide())
    assert early.after[NS31].cause == Cause.WEATHER
    assert s.facts_known_at(T_FACTS - timedelta(minutes=1)) == []
    # rules_override: without R-LEG-1, NS117 is held for Legal again
    diff = s.replay(T_REVERT, make_decide(), rules_override=[], )
    flips = {(f.entity_id, f.field): (f.before, f.after) for f in diff.flips}
    assert flips[(NS117, "extraordinary")] == ("extraordinary", "needs_legal")
    assert flips[(NS117, "outcome")] == ("auto", "escalated")
    assert flips[(f"{NS117}:1A", "status")] == ("no_compensation", "held")
    assert flips[(f"{NS117}:1A", "compensation_cents")] == (0, 25_000)
    assert flips[(NS117, "entitlement_cents")] == (0, 100_000)
    assert diff.total_delta_cents == 100_000 == sum(f.delta_cents for f in diff.flips)
    assert [f.entity_id for f in diff.flips] == sorted(f.entity_id for f in diff.flips)


def test_replay_uses_books_preview_for_the_euro_delta():
    s = store()
    seed(s)
    seen = {}

    def preview(before, after):
        seen["n"] = (len(before), len(after))
        delta = sum(a.compensation_cents for a in after) - sum(b.compensation_cents for b in before)
        from contracts.models import ReplayDiff, ReplayFlip
        return ReplayDiff(rule_ref="preview", known_at=T_REVERT, total_delta_cents=delta // 2,
                          flips=[ReplayFlip(entity_id=NS117, field="eu261_liability_cents", before=0,
                                            after=delta // 2, delta_cents=delta // 2)])

    diff = s.replay(T_REVERT, make_decide(), rules_override=[], preview_fn=preview)
    assert seen["n"] == (7, 7)
    assert diff.total_delta_cents == 50_000 == sum(f.delta_cents for f in diff.flips)
    assert {f.field for f in diff.flips if f.delta_cents} == {"eu261_liability_cents"}


# ---------- revert ----------

class Recorder:
    """A post_recode stand-in that books in the period the trace asks for (via known_at)."""

    def __init__(self, period: str | None = None):
        self.calls: list[tuple] = []
        self.period = period

    def __call__(self, before, after, known_at):
        self.calls.append((before, after, known_at))
        period = self.period or f"{known_at.year:04d}-{known_at.month:02d}"
        return [JournalEntry(id=f"JE-ADJ-{len(self.calls)}", event_date=known_at.date(), period=period,
                             kind="recode", memo="recode", status="draft", preparer="agent.engine",
                             ias8_class="change_in_estimate",
                             lines=[JournalLine(account="4090", account_name="x", dr_cents=1),
                                    JournalLine(account="2140", account_name="y", cr_cents=1)])]


def test_revert_retires_the_rule_replays_and_never_touches_a_locked_period():
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    rec = Recorder()
    out = s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(), post_recode_fn=rec)
    assert s.rule("R-LEG-1").status == "retired"
    assert out.retired is not None and out.retired.kind == "rule_event"
    d = out.diff
    assert d.rule_ref == "R-LEG-1@1" and d.known_at == T_REVERT
    assert d.locked_periods_untouched == ["2025-01"]
    assert out.adjustment_period == "2025-02"
    assert d.adjustment_je_ids == ["JE-ADJ-1"]
    assert d.total_delta_cents == 100_000
    assert out.ias8_class == "change_in_estimate"            # a ruling withdrawn, no new evidence
    (before, after, known_at), = rec.calls
    assert known_at == T_REVERT and {e.coupon_id for e in after} == {f"{NS117}:{x}" for x in COUPONS[NS117]}
    assert all(e.status == "held" for e in after) and all(e.status == "no_compensation" for e in before)
    # the re-decisions are recorded, linked to the revert commit
    assert s.decision(NS117).extraordinary == Extraordinary.NEEDS_LEGAL
    assert out.commit.hash in s.get(s.decision(NS117).commit).inputs
    assert "2025-01 locked, untouched" in out.commit.message
    assert s.verify().ok
    # a second revert of a retired rule records no second retirement and finds nothing left to flip
    again = s.revert("R-LEG-1", actor="legal:aoife-byrne", at=T_REVERT + timedelta(hours=1),
                     decide_fn=make_decide(), post_recode_fn=rec)
    assert again.retired is None and again.diff.flips == [] and len(rec.calls) == 1


def test_revert_refuses_an_adjustment_booked_into_a_locked_period():
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    with pytest.raises(trace.LockedPeriodWrite, match="2025-01"):
        s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(),
                 post_recode_fn=Recorder(period="2025-01"))
    # the adjustment period skips every locked period, starting from the revert's own period
    assert trace.adjustment_period(datetime(2025, 1, 30, tzinfo=UTC), {"2025-01", "2025-02"}) == "2025-03"
    assert trace.adjustment_period(T_REVERT, {"2025-01"}) == "2025-02"


def test_revert_with_real_books_keeps_january_untouched():
    books = pytest.importorskip("books")

    class Clock:
        def __init__(self, t):
            self.t = t

        def now(self):
            return self.t

    clock = Clock(T_LOCK)
    b = books.Books(":memory:", clock)
    controller = Session(principal="controller:ana", role=Role.CONTROLLER, name="Ana", issued_at=T_LOCK)
    b.lock_period("2025-01", controller)
    s = store()
    seed(s)
    for p in b.locked_periods():
        s.record_period_lock(p, "controller:ana", T_LOCK)
    clock.t = T_REVERT
    out = s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(),
                   preview_fn=b.preview, post_recode_fn=b.post_recode)
    assert out.diff.adjustment_je_ids, "books drafted no adjustment"
    assert all(je.period == "2025-02" for je in out.journal)
    assert b.journal(period="2025-01") == []
    assert out.diff.locked_periods_untouched == ["2025-01"]
    assert out.diff.total_delta_cents > 0


def test_hard_control_rules_cannot_be_reverted():
    s = store()
    hc = Rule(id="R-HC-SOD", version=1, kind="routing", tier="hard_control", authority_required=Role.CONTROLLER,
              scope={}, condition={"all": []}, action=RuleAction.ROUTE_TO, action_arg="controller", valid_from=None,
              recorded_at=T_RULE, status="active")
    s.record_rule(hc, "agent.engine", T_RULE)
    with pytest.raises(trace.TraceError, match="hard control"):
        s.revert("R-HC-SOD@1", actor="controller:ana", at=T_REVERT, decide_fn=make_decide())
    with pytest.raises(trace.NotFound):
        s.revert("R-NOPE@1", actor="controller:ana", at=T_REVERT, decide_fn=make_decide())


# ---------- IAS 8.5 ----------

def test_ias8_classifier():
    lock = T_LOCK
    before_lock = datetime(2025, 1, 23, 21, 40, tzinfo=UTC)
    after_lock = datetime(2025, 2, 5, tzinfo=UTC)
    assert ias8_class([EvidenceUse("F-TL-1", before_lock, decisive=True, used=False)], lock) == "prior_period_error"
    assert ias8_class([EvidenceUse("F-TL-1", lock, decisive=True, used=False)], lock) == "prior_period_error"   # ≤
    assert ias8_class([EvidenceUse("F-TL-1", before_lock, decisive=True, used=True)], lock) == "change_in_estimate"
    assert ias8_class([EvidenceUse("F-TL-1", before_lock, decisive=False, used=False)], lock) == "change_in_estimate"
    assert ias8_class([EvidenceUse("F-CLAIM", after_lock, decisive=True, used=False)], lock) == "change_in_estimate"
    assert ias8_class([EvidenceUse("F-TL-1", before_lock, decisive=True, used=False)], None) == "change_in_estimate"
    assert ias8_class([], lock) == "change_in_estimate"


def test_replay_classifies_unused_pre_lock_evidence_as_prior_period_error():
    # January's decision ignored the tech log (received 23 Jan, before the 3 Feb lock): an IAS 8.5 error
    s = store()
    seed(s, decide=make_decide(use_tech_log=False))
    assert s.decision(NS31).cause == Cause.WEATHER
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    run = s.replay_run(T_REVERT, make_decide(use_tech_log=True))
    assert run.after[NS31].cause == Cause.TECHNICAL
    assert run.ias8_class == "prior_period_error"
    # the latest receipt among the unused decisive evidence (tech log 23 Jan 21:40Z, METAR file 25 Jan 00:00Z)
    assert run.decisive_received_at == datetime(2025, 1, 25, 0, 0, tzinfo=UTC)
    # without a lock on January it is an ordinary change in estimate
    s2 = store()
    seed(s2, decide=make_decide(use_tech_log=False))
    assert s2.replay_run(T_REVERT, make_decide(use_tech_log=True)).ias8_class == "change_in_estimate"


def test_new_evidence_after_the_lock_is_a_change_in_estimate():
    # the tech log only arrives on 5 Feb, after January was locked: the information was not available
    s = store()
    seed(s, with_tech_log=False)
    assert s.decision(NS31).cause == Cause.WEATHER
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    late = source("SRC-TECHLOG-LATE", SourceKind.TECH_LOG, "LATE ENTRY. NO MEL RELIEF.",
                  datetime(2025, 2, 5, tzinfo=UTC), 1)
    s.record_source(late, "agent.engine", datetime(2025, 2, 5, tzinfo=UTC))
    s.record_facts([fact("F-TL-1", f"flight:{NS31}", "aog.mel_relief", False, late.id, "NO MEL RELIEF.",
                         recorded=datetime(2025, 2, 5, tzinfo=UTC))], "agent.reader", datetime(2025, 2, 5, tzinfo=UTC))
    run = s.replay_run(T_REVERT, make_decide(use_tech_log=True))
    assert run.after[NS31].cause == Cause.TECHNICAL
    assert run.ias8_class == "change_in_estimate"


# ---------- blame ----------

def test_blame_je_line_walks_to_metar_in_order():
    s = store()
    seed(s)
    b = s.blame("JE-000101:2")
    assert b.target == "JE-000101:2"
    labels = [st.label for st in b.steps]
    assert labels[0] == ("JE-000101:2 · Cr 2140 EU261 compensation liability (estimated) €630 · "
                         "drafted, pending approval")
    assert labels[1].startswith(f"Entitlements {NS31} · 3 coupons · €1,800")
    assert labels[2] == (f"Decision {NS31} · technical · not extraordinary · recoded 71 → 41 · "
                         "cause-finding confidence 91%")
    kinds = [st.commit.kind for st in b.steps]
    assert kinds[:3] == ["journal_event", "entitlement", "decision"]
    fact_labels = [x for x in labels if x.startswith("Fact")]
    assert len(fact_labels) == 3 and any("aog.mel_relief = false" in x for x in fact_labels)
    assert labels.index(fact_labels[-1]) < labels.index(next(x for x in labels if x.startswith("Source")))
    assert labels[-1].startswith("METAR EIDW 16:30Z") and b.steps[-1].quote == METAR_1630
    by_label = {st.label: st for st in b.steps}
    tl = next(st for st in b.steps if "aog.mel_relief" in st.label)
    assert tl.quote == "NO MEL RELIEF. A/C AOG." and "tier 1" in tl.label
    src = next(st for lab, st in by_label.items() if lab.startswith("Source · tech_log"))
    assert src.quote == "NO MEL RELIEF. A/C AOG."


def test_blame_entitlement_walks_rule_then_ruling_with_author_and_quote():
    s = store()
    seed(s)
    b = s.blame(f"{NS117}:1A")
    labels = [x.label for x in b.steps]
    assert labels[0] == f"Entitlement {NS117}:1A · €0 · no compensation; refunds and care still due · Art. 7(1)"
    assert labels[1].startswith(f"Decision {NS117} · knock_on · extraordinary")
    assert labels[2] == "R-LEG-1@1 · Knock-on returns of storm-cancelled outbounds · legal ruling · active"
    assert labels[3] == "Ruling RUL-Q2 · legal legal:aoife-byrne · answer: extraordinary"
    assert b.steps[3].quote == RULING_TEXT
    assert labels[4].startswith("Q-2 → legal · knock_on_return · no-precedent")
    order = ["Entitlement", "Decision", "R-LEG-1", "Ruling", "Q-2", "Fact", "Source", "METAR"]
    firsts = [next(i for i, x in enumerate(labels) if x.startswith(p)) for p in order]
    assert firsts == sorted(firsts)
    assert [x.commit.kind for x in b.steps[:4]] == ["entitlement", "decision", "rule_event", "ruling"]


def test_blame_other_targets_and_unknown():
    s = store()
    seed(s)
    assert s.blame(NS31).steps[0].label.startswith(f"Decision {NS31}")
    assert s.blame("R-LEG-1@1").steps[1].label.startswith("Ruling RUL-Q2")
    assert s.blame("JE-000101").steps[0].label.startswith("JE-000101 · compensation_estimate · 2025-01")
    h = s.decision(NS31).commit
    assert s.blame(h).steps[0].commit.hash == h
    assert s.blame("F-TL-1").steps[0].quote == "NO MEL RELIEF. A/C AOG."
    with pytest.raises(trace.NotFound):
        s.blame("NS999@2025-01-24")
    with pytest.raises(trace.NotFound):
        s.blame("JE-000101:9")


def test_access_denied_and_llm_call_commits():
    s = store()
    d = AccessDecision(at=T_RUN, principal="agent.drafter", action="approve_payout", resource=NS31, allowed=False,
                       reason="SoD: agents never approve payouts")
    c = s.record_access_denied(d)
    assert c.kind == "access_denied" and c.actor == "agent.drafter"
    assert c.message == "agent.drafter approve_payout → DENIED · SoD"
    assert s.access_log() == [d]
    llm = s.record_llm_call({"model": "claude-opus-5-5", "prompt_sha256": "0" * 64, "request_id": "req_1"},
                            "agent.reader", T_RUN, ref="SRC-TECHLOG-EI-NSB")
    assert llm.kind == "llm_call" and s.payload(llm.hash)["model"] == "claude-opus-5-5"
    assert s.verify().ok
