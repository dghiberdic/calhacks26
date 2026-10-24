"""Every JSON file in contracts/fixtures/api validates against its model, and the hero numbers match the plan."""
from __future__ import annotations

import csv
import fnmatch
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from contracts.models import (
    AccessDecision, AccessMatrix, Blame, CfoMetrics, ClaimCurve, Commit, ControlMapping, EstimateCard, EvalReport,
    FlightFile, Health, Injection, InvariantResult, JournalEntry, Question, Rollforward, Rule, StormRun, StormSummary,
    TraceEvent,
)

API = Path(__file__).resolve().parent.parent / "fixtures" / "api"
GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"

# filename pattern -> model. A new fixture file without an entry here fails test_every_fixture_has_a_model.
FIXTURE_MODELS: dict[str, Any] = {
    "health.json": Health,
    "storms.json": list[StormSummary],
    "storm_*.json": StormRun,
    "flight_*.json": FlightFile,
    "questions.json": list[Question],
    "trace.json": list[TraceEvent],
    "rules.json": list[Rule],
    "commits.json": list[Commit],
    "blame.json": Blame,
    "audit.json": dict[str, Any],
    "rollforward_*.json": Rollforward,
    "estimate.json": EstimateCard,
    "journal.json": list[JournalEntry],
    "month_end_je.json": JournalEntry,
    "curve_*.json": ClaimCurve,
    "cfo.json": CfoMetrics,
    "invariants.json": list[InvariantResult],
    "access_matrix.json": AccessMatrix,
    "access_log.json": list[AccessDecision],
    "controls.json": list[ControlMapping],
    "injections.json": list[Injection],
    "eval.json": EvalReport,
}
FILES = sorted(p.name for p in API.glob("*.json"))
ID_RE = re.compile(r"^[A-Za-z0-9@.:_-]+$")


def model_for(name: str) -> Any:
    hits = [m for pat, m in FIXTURE_MODELS.items() if fnmatch.fnmatch(name, pat)]
    assert len(hits) == 1, f"{name}: expected exactly one model pattern, got {len(hits)}"
    return hits[0]


def load(name: str) -> Any:
    return TypeAdapter(model_for(name)).validate_json((API / name).read_bytes())


def test_fixture_dir_is_populated():
    assert len(FILES) >= len(FIXTURE_MODELS)
    for pat in FIXTURE_MODELS:
        assert fnmatch.filter(FILES, pat), f"no fixture for {pat}"


@pytest.mark.parametrize("name", FILES)
def test_every_fixture_has_a_model(name):
    model_for(name)


@pytest.mark.parametrize("name", FILES)
def test_fixture_validates_and_round_trips(name):
    """Validation alone ignores unknown keys; the round trip catches typos and stale field names."""
    raw = json.loads((API / name).read_text())
    adapter = TypeAdapter(model_for(name))
    assert adapter.dump_python(adapter.validate_python(raw), mode="json") == raw


# ---------------------------------------------------------------- the hero storm (plan §1.2–1.4, CONTRACTS §5)
@pytest.fixture(scope="module")
def storm() -> StormRun:
    return load("storm_EIDW@2025-01-24.json")


def row(storm: StormRun, number: str):
    return next(r for r in storm.flights if r.flight.number == number)


def test_storm_counts(storm):
    cancelled = [r for r in storm.flights if r.flight.status == "cancelled"]
    operated = [r for r in storm.flights if r.flight.status == "operated"]
    assert len(cancelled) == 27 and len(operated) == 11
    assert sum(r.flight.pax for r in cancelled) == 5292 == storm.counters["passengers"]
    assert storm.counters["cancelled"] == 27 and storm.counters["questions"] == 3
    assert storm.liability_drafted_cents == 8214600 and storm.entitlement_cents == 9900000
    assert all(r.decision is None for r in operated)
    assert all(15 * 60 + 30 <= r.flight.sched_dep.hour * 60 + r.flight.sched_dep.minute <= 17 * 60 + 30
               for r in operated)


def test_storm_window_and_metar_are_real(storm):
    rows = list(csv.DictReader((GOLDEN / "eidw_2025-01-23_25.csv").open()))
    assert [o.raw for o in storm.metar] == [r["metar"] for r in rows]
    main = max(storm.windows, key=lambda w: w.end - w.start)
    assert (main.start.isoformat(), main.end.isoformat(), main.peak_gust_kt) == (
        "2025-01-24T02:30:00+00:00", "2025-01-24T15:00:00+00:00", 56)


def test_ns31_hero(storm):
    r = row(storm, "NS31")
    d = r.decision
    assert r.flight.pax == 172 and r.flight.aircraft == "EI-NSB"
    assert (d.cause, d.extraordinary, d.recoded, d.recode_label, d.outcome) == (
        "technical", "not_extraordinary", True, "71 → 41", "auto")
    assert d.confidence.score == 0.91 and d.confidence.label == "cause-finding confidence"
    assert d.in_window_dep == d.in_window_arr == "out" and d.window_margin_min >= 60
    assert any(e.struck and e.value == "71" for e in d.evidence)
    assert not any(e.field.startswith("spare") for e in d.evidence), "spares are never a feature for NS31"
    ff: FlightFile = load("flight_NS31@2025-01-24.json")
    assert ff.entitlements_summary["compensation_cents"] == 9900000
    assert ff.journal_preview[0].lines[1].account == "2140"
    assert ff.journal_preview[0].lines[1].cr_cents == 3465000
    c14 = next(e for e in ff.sample_entitlements if e.coupon_id.endswith(":14C"))
    assert (c14.status, c14.compensation_cents, c14.voucher_offset_cents) == ("needs_ruling", 60000, 0)


def test_weather_and_knock_on(storm):
    weather = [r for r in storm.flights if r.decision and r.decision.cause == "weather"]
    assert len(weather) == 23 and all(r.decision.extraordinary == "extraordinary" for r in weather)
    ns117 = row(storm, "NS117").decision
    assert (ns117.cause, ns117.extraordinary, ns117.routed_to, ns117.question_id) == (
        "knock_on", "needs_legal", "legal", "Q-2")
    assert ns117.confidence.score < 0.60
    bcn = load("flight_NS108@2025-01-24.json").sample_entitlements[0]
    assert (bcn.band_eur, bcn.band_margin_km) == (250, 14)


def test_questions():
    qs = {q.id: q for q in load("questions.json")}
    q1, q2 = qs["Q-1"], qs["Q-2"]
    assert (q1.routed_to, q1.confidence.score, q1.reason_tag) == ("claims_lead", 0.39, "sources-disagree")
    assert (q2.routed_to, q2.confidence.score, q2.reason_tag) == ("legal", 0.47, "no-precedent")
    assert q2.case_refs == ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"]
    assert q2.holds_cents == 1922400 + 1987200 + 840000
    assert q1.recommended_option in q1.options and q2.recommended_option in q2.options


def test_books_numbers():
    feb: Rollforward = load("rollforward_2025-02.json")
    ns31 = next(r for r in feb.rows if r.cohort == "EIDW@2025-01-24")
    assert (ns31.opening_cents, ns31.claims_approved_cents, ns31.change_in_estimate_cents, ns31.closing_cents) == (
        3105000, 930000, 399000, 2574000)
    assert feb.ties_to_gl and feb.closing_total_cents == feb.gl_balance_cents
    est: EstimateCard = load("estimate.json")
    assert (est.bf_cents, est.selected, est.sensitivity_5pp_cents, est.actual_vs_expected) == (
        2574000, "bf", 495000, 1.448)
    for je in load("journal.json"):
        assert sum(x.dr_cents for x in je.lines) == sum(x.cr_cents for x in je.lines), je.id


def test_ids_use_the_allowed_alphabet(storm):
    ids = [r.flight.id for r in storm.flights] + [q.id for q in storm.questions] + [e.ref for e in storm.feed if e.ref]
    ids += [j.id for j in load("journal.json")] + [r.id for r in load("rules.json")]
    ids += [e.coupon_id for p in API.glob("flight_*.json") for e in load(p.name).sample_entitlements]
    bad = [i for i in ids if not ID_RE.match(i)]
    assert not bad, bad


def test_trace_seq_is_monotonic():
    seqs = [e.seq for e in load("trace.json")]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs) and seqs[0] == 1
