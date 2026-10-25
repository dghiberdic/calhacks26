"""blackout v1: external events are additive. A world without events dumps and hashes exactly as before."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import orjson
import pytest
from pydantic import ValidationError

from contracts import fields
from contracts.models import (Cause, EventAirportWindow, ExternalEvent, Source, SourceKind, StormRun, StormWindow,
                              World)
from contracts.normalize import event_fact_id, world_to_facts

UTC = timezone.utc
GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "world.json"


def _event() -> ExternalEvent:
    return ExternalEvent(id="EVT-IBERIA-BLACKOUT@2025-04-28", kind="grid_outage", title="Iberian Peninsula blackout",
                         airports=[EventAirportWindow(icao="LPPT", start=datetime(2025, 4, 28, 10, 33, tzinfo=UTC),
                                                      end=datetime(2025, 4, 29, 6, 0, tzinfo=UTC),
                                                      note="approximate: test")],
                         source_ids=["SRC-EVT-ENTSOE"])


def test_world_without_events_dumps_without_the_key():
    raw = GOLDEN.read_bytes()
    w = World.model_validate_json(raw)
    assert w.events == []
    dumped = w.model_dump(mode="json")
    assert "events" not in dumped
    assert orjson.dumps(dumped, option=orjson.OPT_INDENT_2) + b"\n" == raw


def test_world_with_events_round_trips_and_normalizes():
    w = World.model_validate_json(GOLDEN.read_bytes())
    src = Source(id="SRC-EVT-ENTSOE", kind=SourceKind.EXTERNAL_EVENT, title="ENTSO-E",
                 text="At 12:33 CEST on 28 April 2025 ... grid_outage window 2025-04-28T10:33:00Z",
                 sha256="0" * 64, received_at=datetime(2025, 4, 28, 11, 0, tzinfo=UTC), trust_tier=1)
    w2 = w.model_copy(update={"events": [_event()], "sources": [*w.sources, src]})
    back = World.model_validate(w2.model_dump(mode="json"))
    assert back.events == [_event()]
    facts = {f.id: f for f in world_to_facts(back, flight_ids=[])}
    start = facts[event_fact_id("EVT-IBERIA-BLACKOUT@2025-04-28", "event.window_start", "LPPT")]
    assert start.value == "2025-04-28T10:33:00Z" and start.span == "2025-04-28T10:33:00Z"
    assert start.subject == "event:EVT-IBERIA-BLACKOUT@2025-04-28" and start.source_id == "SRC-EVT-ENTSOE"
    kind = facts[event_fact_id("EVT-IBERIA-BLACKOUT@2025-04-28", "event.kind")]
    assert kind.value == "grid_outage" and kind.span == "grid_outage"
    end = facts[event_fact_id("EVT-IBERIA-BLACKOUT@2025-04-28", "event.window_end", "LPPT")]
    assert end.value == "2025-04-29T06:00:00Z" and end.span is None


def test_event_ids_and_times_are_strict():
    with pytest.raises(ValidationError):
        ExternalEvent(id="EVT IBERIA", kind="grid_outage", title="x", airports=[], source_ids=[])
    with pytest.raises(ValidationError):
        EventAirportWindow(icao="LPPT", start=datetime(2025, 4, 28, 10, 33), end=datetime(2025, 4, 29))


def test_defaults_keep_storms_weather():
    w = StormWindow(station="EIDW", start=datetime(2025, 1, 24, 6, tzinfo=UTC),
                    end=datetime(2025, 1, 24, 15, tzinfo=UTC), peak_gust_kt=80)
    assert w.kind == "weather" and w.label is None
    assert StormRun.model_fields["event_id"].default is None
    assert Cause.EXTERNAL_EVENT.value == SourceKind.EXTERNAL_EVENT.value == "external_event"


def test_event_fields_and_features_are_registered():
    for name in ("event.kind", "event.window_start", "event.window_end"):
        assert fields.get(name).subject == "event"
    assert set(fields.EVENT_DSL_FEATURES) <= set(fields.ALL_DSL_FEATURES)
    assert {"flight.in_event_window_dep", "flight.in_event_window_arr"} <= fields.ENGINE_DERIVED
    assert fields.EVENT_WINDOW_VALUES == ("in", "out", "unknown")
    assert fields.check_value("event.window_start", "2025-04-28T10:33:00Z")
