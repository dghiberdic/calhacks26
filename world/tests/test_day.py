import hashlib
import time
from datetime import date

import orjson
import pytest
import time_machine

from contracts.models import World


def test_judge_day_is_a_real_world_on_pinned_weather(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl

    world = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)

    assert isinstance(world, World)
    assert any(f.origin == "DUB" and f.dest == "LHR" for f in world.flights)
    assert any(f.origin == "LHR" and f.dest == "DUB" for f in world.flights)
    assert world.metar["EGLL@2024-01-21"]
    assert world.metar["EIDW@2024-01-21"]


@pytest.mark.parametrize("seed", [0, 7, 99])
def test_judge_day_always_contains_unsigned_voucher_scope_controls(monkeypatch, seed):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl

    api = WorldImpl()
    world = api.generate_day("EGLL", date(2024, 1, 21), seed=seed)
    coupons = {c.id: c for c in world.coupons}
    flights = {f.id: f for f in world.flights}
    eu = non_eu = 0
    for event in world.crm:
        if event.kind != "voucher_in_lieu_of_compensation" or event.signed_acceptance_sha256:
            continue
        flight = flights[coupons[event.coupon_id].flight_id]
        if api.airport(flight.origin).eu:
            eu += 1
        else:
            non_eu += 1
    assert eu >= 3
    assert non_eu >= 1


def test_intra_eu_judge_route_has_a_labelled_non_eu_control(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl

    world = WorldImpl().generate_day("LFPG", date(2024, 1, 21), seed=7)
    assert any(f.origin == "DUB" and f.dest == "CDG" for f in world.flights)
    assert any(f.origin == "LHR" and f.status == "cancelled" for f in world.flights)
    assert len(world.meta["days"][0]["judge_unsigned_vouchers"]) == 4


@pytest.mark.parametrize("station, day, code", [
    ("ZZZZ", date(2024, 1, 21), "unknown_airport"),
    ("KBOS", date(2099, 1, 1), "future_date"),
    ("EGLL", date(1900, 1, 1), "no_metar"),
])
def test_bad_desk_input_has_a_plain_world_error(monkeypatch, station, day, code):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl
    from world.errors import WorldError

    with pytest.raises(WorldError) as caught:
        WorldImpl().generate_day(station, day)
    assert caught.value.code == code
    assert caught.value.message


def test_judge_world_is_reproducible_fast_and_schema_valid(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl

    start = time.perf_counter()
    first = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    assert time.perf_counter() - start < 2
    second = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    first = World.model_validate_json(first.model_dump_json())
    dump = lambda world: orjson.dumps(world.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    assert dump(first) == dump(second)
    assert all(s.sha256 == hashlib.sha256((s.text or "").encode()).hexdigest() for s in first.sources)


def test_calm_weather_can_expose_a_simulated_technical_weather_miscode(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl

    world = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    assert any(f.status == "cancelled" and f.ops_cause_code == "71"
               and any(t.aircraft == f.aircraft and t.aog and t.mel_relief is False for t in world.tech_log)
               for f in world.flights)
    assert world.meta["real_vs_simulated"]["real"]


def test_future_day_is_checked_in_the_requested_airports_timezone(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    from world.api import WorldImpl
    from world.errors import WorldError

    with time_machine.travel("2026-10-24T00:30:00Z", tick=False), pytest.raises(WorldError) as caught:
        WorldImpl().generate_day("KBOS", date(2026, 10, 24))
    assert caught.value.code == "future_date"
