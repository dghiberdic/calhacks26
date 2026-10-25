"""The trust tier of documents injected after the world was built (rehearsed injection 01's regression).

An injected document is not in the base world: it is registered in the trace (``TraceStore.record_source``) or handed
to ``Engine.decide(..., sources=...)``. Its kind caps the tier it may claim, so a tech-log/MCC line is tier 1 and an
e-mail stays tier 4 whatever it declares. A source registered nowhere is tier 4 (fail closed).
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.fakes import FakeReader
from contracts.models import Cause, Extraordinary, Fact, Injection, Role, Source, SourceKind, World
from engine.case import overlay_facts, stations_for
from engine.confidence import default_calibration
from engine.engine import Engine
from engine.trace import TraceStore

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts" / "fixtures" / "golden" / "world.json"
NS110 = "NS110@2025-01-24"
RECEIVED = datetime(2025, 1, 25, 9, 0, tzinfo=UTC)
KNOWN = datetime(2025, 1, 25, 9, 30, tzinfo=UTC)
# inside the 02:30Z-15:00Z DUB window and before the 05:12Z OCC weather batch that cancelled NS110
TECH_LOG = "24JAN 04:05Z EI-NSH DUB N/S. BIRD STRIKE ENG 1 ON TAXI-IN. BORESCOPE REQD. NO MEL RELIEF. A/C AOG."
CONCURRENT_TO_LEGAL = (Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, Role.LEGAL)


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json(GOLDEN.read_bytes())


@pytest.fixture(scope="module")
def engine(world) -> Engine:
    return Engine(world, calibration=default_calibration())


def injected(text: str = TECH_LOG, kind: SourceKind = SourceKind.TECH_LOG, tier: int = 1,
             sid: str = "SRC-INJ-0001") -> Source:
    return Source(id=sid, kind=kind, title=f"Injected {kind.value}", text=text,
                  sha256=hashlib.sha256(text.encode()).hexdigest(), received_at=RECEIVED, trust_tier=tier,
                  acl_tags=["maintenance"])


def read(src: Source) -> list[Fact]:
    facts, dropped = FakeReader().extract(src)
    assert dropped == 0 and {f.field for f in facts} >= {"aog.logged_at", "aog.mel_relief", "aog.aog"}
    return facts


def sig(d) -> tuple:
    return d.cause, d.extraordinary, d.routed_to


def test_a_tech_log_source_registered_in_the_trace_counts_as_tier_1(world, engine):
    """The server's path: its decide_fn overlays the trace's facts on the base world without naming any source."""
    trace = TraceStore(":memory:", engine_sha="x", cal_version="c")
    src = injected()
    trace.record_source(src, "agent.reader", RECEIVED)
    trace.record_facts(read(src), "agent.reader", RECEIVED)

    def decide_fn(facts, rules, known_at):
        w = overlay_facts(world, facts, known_at)
        yield engine.decide_in(w, NS110, rules, known_at, stations=stations_for(w, known_at))

    d = trace.replay_run(KNOWN, decide_fn, rules_override=[]).after[NS110]
    assert sig(d) == CONCURRENT_TO_LEGAL and d.outcome == "escalated"
    assert any(e.source_id == src.id and e.trust_tier == 1 for e in d.evidence)   # blame reaches the injection


def test_engine_decide_takes_the_injected_document(engine):
    src = injected()
    d = engine.decide(NS110, read(src), [], KNOWN, sources=[src])
    assert sig(d) == CONCURRENT_TO_LEGAL and d.outcome == "escalated"


def test_a_source_registered_nowhere_is_tier_4_and_only_a_claim(engine):
    d = engine.decide(NS110, read(injected()), [], KNOWN)
    assert d.cause != Cause.CONCURRENT and d.routed_to == Role.OPS and d.outcome != "auto"


@pytest.mark.parametrize("kind", [SourceKind.EMAIL, SourceKind.CLAIM, SourceKind.CHALLENGE, SourceKind.CRM,
                                  SourceKind.OCC_LOG])
def test_a_registered_document_cannot_claim_a_better_tier_than_its_kind(engine, kind):
    """A tier-4 e-mail (or any document that isn't a tech log / MCC) declaring tier 1 never grounds a flight and never
    flips it automatically."""
    src = injected(kind=kind, tier=1)
    facts = [f.model_copy(update={"source_id": src.id}) for f in read(injected())]
    d = engine.decide(NS110, facts, [], KNOWN, sources=[src])
    assert d.cause != Cause.CONCURRENT and d.routed_to == Role.OPS and d.outcome != "auto"
    cited = [e for e in d.evidence if e.source_id == src.id]
    assert cited and all(e.trust_tier >= 3 for e in cited)


def test_a_tech_log_source_declaring_a_worse_tier_keeps_it(engine):
    src = injected(tier=4)
    d = engine.decide(NS110, read(src), [], KNOWN, sources=[src])
    assert d.cause != Cause.CONCURRENT and d.routed_to == Role.OPS


def test_the_world_source_wins_over_a_registered_one_with_the_same_id(world, engine):
    """The curated world is never overridden: a document reusing a world e-mail's id keeps that e-mail's tier."""
    email = next(s for s in world.sources if s.kind == SourceKind.EMAIL and s.trust_tier == 4)
    fake = injected(sid=email.id)
    d = engine.decide(NS110, read(fake), [], KNOWN, sources=[fake])
    assert d.cause != Cause.CONCURRENT and d.routed_to == Role.OPS


# ---------- the rehearsed fixture itself ----------

INJ01 = Injection.model_validate_json((ROOT / "contracts" / "fixtures" / "injections" /
                                       "01_aog_inside_window.json").read_bytes())


def test_rehearsed_injection_01_redecides_ns110_concurrent_to_legal(engine):
    assert INJ01.request.kind == "tech_log" and INJ01.request.flight_id == NS110
    src = injected(INJ01.request.text)
    d = engine.decide(NS110, read(src), [], KNOWN, sources=[src])
    assert sig(d) == CONCURRENT_TO_LEGAL and d.outcome == "escalated"


def test_injection_01_is_logged_inside_the_window_and_before_the_occ_cancellation(engine, world):
    """The fixture's AOG must be able to have caused the cancellation: inside the 02:30Z-15:00Z DUB window and
    before the 05:12Z OCC weather batch that cancelled NS110 (E3: a later AOG is not the cause)."""
    (logged,) = [f.value for f in read(injected(INJ01.request.text)) if f.field == "aog.logged_at"]
    at = datetime.fromisoformat(logged.replace("Z", "+00:00"))
    case = engine.evaluate(world, NS110, [], KNOWN).case
    assert case.window is not None and case.window.start <= at <= case.window.end
    assert at < case.decided_at == datetime(2025, 1, 24, 5, 12, tzinfo=UTC)


def test_an_aog_logged_after_the_occ_cancellation_does_not_flip_ns110_even_at_tier_1(engine):
    """E3: the OCC cancelled NS110 for weather at 05:12Z; a bird strike logged at 08:05Z cannot have caused that."""
    src = injected(TECH_LOG.replace("04:05Z", "08:05Z"))
    d = engine.decide(NS110, read(src), [], KNOWN, sources=[src])
    assert (d.cause, d.extraordinary, d.outcome) == (Cause.WEATHER, Extraordinary.YES, "auto")
