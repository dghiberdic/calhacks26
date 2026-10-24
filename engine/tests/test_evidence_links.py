"""Evidence points at the right document and the right normalize fact (golden world).

(1) A window/METAR citation names the METAR source of its own station and date (never the first METAR source in
    the world). (2) Every evidence item that quotes a world record carries the `contracts.normalize` fact id of that
    record, so the trace can link a decision to the facts it used; engine-derived evidence (windows, rotations,
    "everyone else flew", ages) keeps its own id.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from contracts.fields import ENGINE_DERIVED
from contracts.models import Rule, World
from contracts.normalize import world_to_facts
from engine.confidence import default_calibration
from engine.engine import Engine

UTC = timezone.utc
GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
DERIVED = set(ENGINE_DERIVED) | {"storm.window", "flight.operated_after_window"}


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_bytes())


@pytest.fixture(scope="module")
def runs(world: World):
    import json
    rules = [Rule.model_validate(r) for r in json.loads((GOLDEN.parent / "api" / "rules.json").read_text())]
    eng = Engine(world, calibration=default_calibration())
    return [eng.run_storm(world, "EIDW", date(2025, 1, 24), rules, datetime(2025, 1, 25, 6, tzinfo=UTC)),
            eng.run_storm(world, "EIDW", date(2025, 1, 26), rules, datetime(2025, 1, 27, 6, tzinfo=UTC))]


def decisions(runs):
    return {r.flight.id: r.decision for run in runs for r in run.flights if r.decision}


def test_ns31_window_cites_the_eidw_24_jan_metar(runs):
    d = decisions(runs)["NS31@2025-01-24"]
    win = [e for e in d.evidence if e.field == "storm.window"]
    assert win and {e.source_id for e in win} == {"SRC-METAR-EIDW@2025-01-24"}


def test_herminia_windows_cite_their_own_station_and_date(runs):
    ds = decisions(runs)
    for fid in ("NS106@2025-01-26", "NS110@2025-01-26", "NS114@2025-01-26", "NS30@2025-01-25"):
        for e in ds[fid].evidence:
            if e.field == "storm.window":
                assert e.source_id == "SRC-METAR-EIDW@2025-01-26", (fid, e.source_id)


def test_every_window_and_metar_citation_is_in_its_source(world: World, runs):
    src = {s.id: s for s in world.sources}
    n = 0
    for d in decisions(runs).values():
        for e in d.evidence:
            if e.field == "storm.window":
                s = src[e.source_id]
                start = datetime.fromisoformat(e.value["start"].replace("Z", "+00:00"))
                assert start.strftime("%Y-%m-%d %H:%M") in s.text, (d.flight_id, e.source_id)
                n += 1
            if e.field.startswith("metar."):
                s = src[e.source_id]
                assert e.quote and e.quote in s.text, (d.flight_id, e.source_id)
                assert e.source_id.startswith(f"SRC-METAR-{e.quote.split()[0]}@"), (d.flight_id, e.source_id)
                n += 1
    assert n > 30


def test_evidence_links_to_normalize_facts(world: World, runs):
    facts = {f.id: f for f in world_to_facts(world)}
    unlinked = []
    for run in runs:
        items = [(r.flight.id, e) for r in run.flights if r.decision for e in r.decision.evidence]
        items += [(q.id, e) for q in run.questions for e in q.evidence]
        for who, e in items:
            if e.field in DERIVED:
                continue
            f = facts.get(e.fact_id)
            if f is None or f.field != e.field:
                unlinked.append((who, e.field, e.fact_id))
    assert not unlinked, unlinked[:8]
