"""The Iberian blackout scenario (world.events): pinned event, real METAR, planted cases, determinism, timing."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime

import pytest

from contracts.models import ExternalEvent, Source, SourceKind, World
from contracts.normalize import event_fact_id, world_to_facts
from world import events as E
from world import metar as M
from world.generate import generate_day, generate_day_full
from world.golden import canonical_hash

DAY = date(2025, 4, 28)


@pytest.fixture(scope="module")
def world() -> World:
    return E.blackout_world()


@pytest.fixture(scope="module")
def key() -> dict:
    return E.answer_key()


def _windows() -> dict[str, tuple[datetime, datetime]]:
    ev, _ = E.load_event()
    return {w.icao: (w.start, w.end) for w in ev.airports}


def _in(t: datetime, w: tuple[datetime, datetime]) -> bool:
    return w[0] <= t <= w[1]


# ---------------------------------------------------------------- the pinned event
def test_event_json_validates_and_its_sources_are_verbatim_notices_with_urls():
    doc = json.loads(E.EVENT_PATH.read_text(encoding="utf-8"))
    ev = ExternalEvent.model_validate(doc["event"])
    sources = [Source.model_validate(s) for s in doc["sources"]]
    assert ev.id == E.EVENT_ID and ev.kind == "grid_outage" and ev.title == "Iberian Peninsula blackout"
    assert {w.icao for w in ev.airports} == set(E.STATIONS)
    by_id = {s.id: s for s in sources}
    assert set(ev.source_ids) == set(by_id) and ev.source_ids[0] == "SRC-EVT-ENTSOE-BLACKOUT"
    for s in sources:
        assert s.kind == SourceKind.EXTERNAL_EVENT
        assert s.sha256 == hashlib.sha256((s.text or "").encode("utf-8")).hexdigest()
        assert s.uri and s.uri.startswith("https://") and s.uri in (s.text or "")
        assert s.trust_tier in (1, 2)
    tier1 = {s.id for s in sources if s.trust_tier == 1}
    assert {"SRC-EVT-ENTSOE-BLACKOUT", "SRC-EVT-ENTSOE-RESTORATION", "SRC-EVT-REE-RESTORATION",
            "SRC-EVT-IAA-ADVICE"} == tier1
    assert "at 12:33 CEST, the power systems of continental Spain and Portugal experienced a total blackout" in \
        by_id["SRC-EVT-ENTSOE-BLACKOUT"].text


def test_every_window_starts_at_the_entsoe_onset_and_every_end_says_it_is_approximate():
    ev, _ = E.load_event()
    for w in ev.airports:
        assert w.start == datetime(2025, 4, 28, 10, 33, tzinfo=UTC)     # 12:33 CEST
        assert w.start < w.end <= datetime(2025, 4, 29, 6, tzinfo=UTC)
        assert w.note and w.note.startswith("approximate:"), w.icao
    assert E.event_window("LPPT")[1] == datetime(2025, 4, 28, 21, 0, tzinfo=UTC)   # ANA: no departures until 10 pm
    assert E.event_window("EIDW") is None


def test_real_metar_is_pinned_and_calm_at_all_three_airports():
    for icao in E.STATIONS:
        for d in (date(2025, 4, 28), date(2025, 4, 29)):
            assert M.daily_pin_path(icao, d).exists(), (icao, d)
            obs = M.pinned_day(icao, d)
            assert obs and len(obs) >= 40 and all(o.station == icao for o in obs)
            assert not any(M.storm_conditions(o) for o in obs), (icao, d)


# ---------------------------------------------------------------- the scenario world
def test_world_carries_the_event_its_sources_and_validates(world: World):
    back = World.model_validate_json(world.model_dump_json())
    assert back.events and back.events[0].id == E.EVENT_ID
    assert canonical_hash(back) == canonical_hash(world)
    src = {s.id for s in world.sources}
    assert set(world.events[0].source_ids) <= src
    assert {a.iata for a in world.airports} == {"DUB", "LIS", "MAD", "BCN"}
    assert {"EIDW@2025-04-28", "LPPT@2025-04-28", "LEMD@2025-04-28", "LEBL@2025-04-28"} <= set(world.metar)
    assert world.meta["scenario"]["run_id"] == E.RUN_ID and world.meta["storms"][E.RUN_ID]["event_id"] == E.EVENT_ID
    ids = {f.id for f in world.flights}
    assert set(world.meta["storms"][E.RUN_ID]["flight_ids"]) == ids
    assert all(f.origin == "DUB" or f.dest == "DUB" for f in world.flights)


def test_most_cancellations_are_inside_the_outage_window(world: World, key: dict):
    win = _windows()
    icao = {"LIS": "LPPT", "MAD": "LEMD", "BCN": "LEBL"}
    cancelled = [f for f in world.flights if f.status == "cancelled"]
    inside = [f for f in cancelled if (f.origin in icao and _in(f.sched_dep, win[icao[f.origin]]))
              or (f.dest in icao and _in(f.sched_arr, win[icao[f.dest]]))]
    assert {f.id for f in inside} == set(E.EVENT_WINDOW_FLIGHTS)
    assert len(inside) == 8 and len(inside) > len(cancelled) - len(inside)
    for fid in E.EVENT_WINDOW_FLIGHTS:
        t = key["flights"][fid]
        assert (t["cause"], t["extraordinary"], t["owed"]) == ("external_event", "extraordinary", 0)
        f = next(x for x in world.flights if x.id == fid)
        assert f.ops_cause_code == "87"
        assert any(fid in e.flight_ids and "IBERIAN GRID OUTAGE" in e.text for e in world.ops_log)


def test_post_restoration_cancellations_are_internal_logged_and_owed(world: World, key: dict):
    win = _windows()
    by_id = {f.id: f for f in world.flights}
    ns128, ns129 = (by_id[f] for f in E.POST_RESTORATION_FLIGHTS)
    mad_end = win["LEMD"][1]
    assert ns128.sched_arr > mad_end and ns129.sched_dep > mad_end         # both ends outside every window
    assert ns128.origin == "DUB" and ns129.origin == "MAD"
    logs = {fid: [e for e in world.ops_log if fid in e.flight_ids] for fid in E.POST_RESTORATION_FLIGHTS}
    assert any("A/C EI-NSH OUT OF POSITION" in e.text and e.code == "93" for e in logs[ns128.id])
    assert any(e.kind == "spares" and "STD+0h00" in e.text and "EI-NTB" in e.text for e in logs[ns128.id])
    crew = [e for e in logs[ns129.id] if "CREW OUT OF FDP" in e.text]
    assert crew and crew[0].code == "64" and crew[0].author == "Crew control" and crew[0].at > mad_end
    for fid, cause in zip(E.POST_RESTORATION_FLIGHTS, ("knock_on", "crew")):
        t = key["flights"][fid]
        assert (t["cause"], t["extraordinary"]) == (cause, "not_extraordinary")
        assert t["owed"] > 100 and t["compensation_cents"] > 0
        assert "post_restoration_internal" in t["planted"]


def test_care_is_booked_for_every_cancelled_flight(world: World, key: dict):
    cancelled = {f.id for f in world.flights if f.status == "cancelled"}
    accrued = {c.flight_id for c in world.care if not c.invoiced}
    kinds = {(c.flight_id, c.kind) for c in world.care if not c.invoiced}
    assert accrued == cancelled
    assert all((fid, k) in kinds for fid in cancelled for k in ("hotel", "meal"))
    assert key["care_accrued_cents"] == sum(c.amount_cents for c in world.care if not c.invoiced) > 0


def test_normalize_emits_the_event_facts(world: World):
    facts = {f.id: f for f in world_to_facts(world, flight_ids=[])}
    for icao in E.STATIONS:
        start = facts[event_fact_id(E.EVENT_ID, "event.window_start", icao)]
        assert start.value == "2025-04-28T10:33:00Z" and start.source_id == "SRC-EVT-ENTSOE-BLACKOUT"
    assert facts[event_fact_id(E.EVENT_ID, "event.kind")].value == "grid_outage"


# ---------------------------------------------------------------- generate_day, determinism, timing
@pytest.mark.parametrize("icao", E.STATIONS)
def test_generate_day_serves_the_scenario_at_each_iberian_airport(icao: str):
    w = generate_day(icao, DAY)
    assert [e.id for e in w.events] == [E.EVENT_ID]
    sid = f"{icao}@{DAY.isoformat()}"
    assert w.meta["desk"]["storm_id"] == sid and w.meta["judge_station"] == icao
    st = w.meta["storms"][sid]
    assert st["station"] == icao and st["flight_ids"] and st["event_id"] == E.EVENT_ID
    assert set(E.POST_RESTORATION_FLIGHTS) <= {f.id for f in w.flights}
    assert set(w.meta["desk"]["planted"]["post_restoration_internal"]) == set(E.POST_RESTORATION_FLIGHTS)


def test_generate_day_lppt_contains_the_event_and_planted_cases_with_truth():
    g = generate_day_full("LPPT", DAY)
    lis = {f.id for f in g.world.flights if "LIS" in (f.origin, f.dest)}
    assert {"NS112@2025-04-28", "NS113@2025-04-28", "NS170@2025-04-28", "NS171@2025-04-28"} == lis
    assert g.truth.flights["NS113@2025-04-28"].extraordinary == "extraordinary"
    assert g.truth.flights["NS129@2025-04-28"].extraordinary == "not_extraordinary"
    assert g.world.events[0].airports[0].icao == "LPPT"


def test_other_days_and_dublin_are_not_the_scenario():
    assert not E.is_event_day("LPPT", date(2025, 4, 27)) and not E.is_event_day("EIDW", DAY)
    assert E.is_event_day("LEBL", DAY)


def test_deterministic_per_seed():
    a = E._generated.__wrapped__(0).world
    b = E._generated.__wrapped__(0).world
    c = E._generated.__wrapped__(1).world
    assert canonical_hash(a) == canonical_hash(b)
    assert [(f.id, f.status) for f in a.flights] == [(f.id, f.status) for f in c.flights]
    assert canonical_hash(a) != canonical_hash(c)


def test_blackout_world_builds_in_under_two_seconds_of_cpu():
    E.load_event()                                    # parsed once per process, like the pinned METAR
    t0 = time.process_time()
    g = E._generated.__wrapped__(7)
    cpu = time.process_time() - t0
    assert g.world.events and cpu < 2.0, cpu
