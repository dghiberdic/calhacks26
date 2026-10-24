"""F3a: network, world days, latent causes, flights and ops logs (offline, from pinned METAR)."""
from __future__ import annotations

import ast
import hashlib
import re
from datetime import date, timedelta
from pathlib import Path

import orjson
import pytest

from contracts.models import Cause, Extraordinary, World
from world import days as D
from world import network as N
from world.generator import DaySim, generate_world

ID_RE = re.compile(r"^[A-Za-z0-9@.:_-]+$")
SAMPLE = [date(2024, 1, 21), date(2024, 4, 6), date(2024, 9, 17), date(2025, 2, 26), date(2025, 3, 24)]


def canon(model) -> str:
    return hashlib.sha256(orjson.dumps(model.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)).hexdigest()


def sample_days():
    by_day = {w.day: w for w in D.world_days()}
    return [by_day[d] for d in SAMPLE]


@pytest.fixture(scope="module")
def gen():
    return generate_world(0, sample_days())


# ---------------------------------------------------------------- network

def test_network_has_about_35_routes_eu_uk_and_north_america():
    assert 30 <= len(N.ROUTES) <= 40
    lh = {p.dest for p in N.LONG_HAUL}
    assert {"JFK", "BOS", "ORD", "YYZ"} <= lh
    assert {"LHR", "MAN", "EDI"} <= set(N.ROUTES)        # UK
    assert all(N.FLEET[p.tail].code in ("A21X", "A333") for p in N.LONG_HAUL)


def test_tails_follow_the_plan_naming():
    assert all(re.match(r"^EI-N[SLWT][A-Z]$", t) for t in N.FLEET)
    assert N.FLEET["EI-NSB"].code == "A21X" and N.FLEET["EI-NSN"].code == "A21X"


@pytest.mark.parametrize("day", [date(2025, 1, 24), date(2024, 7, 16)])    # winter and summer time
def test_daily_rotations_are_feasible(day):
    secs = N.day_sectors(day)
    assert len(secs) == 2 * len(N.PAIRS)
    for tail, ss in N.tail_rotation(secs).items():
        for a, b in zip(ss, ss[1:]):
            assert a.dest == b.origin, (tail, a.id, b.id)
            assert b.std - a.sta >= timedelta(minutes=30), (tail, a.id, b.id)


def test_plan_numbers_and_times_on_eowyn_day():
    secs = {s.number: s for s in N.day_sectors(date(2025, 1, 24))}
    assert secs["NS31"].std.strftime("%H:%M") == "16:30" and secs["NS31"].dest == "BOS"
    assert secs["NS117"].std.strftime("%H:%M") == "14:05" and secs["NS117"].sta.strftime("%H:%M") == "16:20"
    assert secs["NS101"].std.strftime("%H:%M") == "08:00" and secs["NS101"].sta.strftime("%H:%M") == "09:15"
    # overnight inbounds carry their local departure date (CONTRACTS: NS20@2025-01-23)
    assert secs["NS20"].id == "NS20@2025-01-23" and secs["NS30"].id == "NS30@2025-01-23"
    assert secs["NS120"].std.strftime("%H:%M") == "15:30"


def test_summer_schedule_keeps_dublin_local_times():
    s = {x.number: x for x in N.day_sectors(date(2024, 7, 16))}["NS100"]
    assert s.std.strftime("%H:%M") == "05:10"       # 06:10 IST = 05:10Z


# ---------------------------------------------------------------- days

def test_storm_days_come_from_data_with_the_plan_rule():
    storms = D.storm_days()
    assert len(storms) == 26
    assert {date(2025, 1, 24), date(2025, 1, 26), date(2024, 1, 21), date(2024, 12, 7)} <= set(storms)
    assert date(2023, 11, 1) not in storms          # Ciarán: one hour of G37 at EIDW (world/DECISIONS F1.10)
    for d in storms:
        assert D.eidw_summaries()[d].hours_gust_ge >= 3


def test_background_days_are_deterministic_and_split():
    bg = D.background_days()
    assert len(bg) == 40 and bg == D.background_days()
    assert sum(d < D.SCORE_START for d in bg) == 28 and sum(d >= D.SCORE_START for d in bg) == 12
    assert not set(bg) & set(D.storm_days()) and not set(bg) & D.GOLDEN_DAYS
    wd = D.world_days()
    assert len(wd) == 66 and [w.day for w in wd] == sorted(w.day for w in wd)
    assert {w.split for w in wd if w.day.year == 2025} == {"test"}


# ---------------------------------------------------------------- generated flights

def test_world_is_schema_valid_and_ids_are_clean(gen):
    w = gen.world
    World.model_validate(w.model_dump(mode="json"))
    ids = [f.id for f in w.flights] + [e.id for e in w.tech_log] + [e.id for e in w.ops_log] + [s.id for s in w.sources]
    assert len(set(ids)) == len(ids)
    assert all(ID_RE.match(i) for i in ids)
    assert all(f.id == f"{f.number}@{f.date.isoformat()}" for f in w.flights)


def test_deterministic_per_seed(gen):
    again = generate_world(0, sample_days())
    assert canon(again.world) == canon(gen.world)
    other = generate_world(1, sample_days())
    assert canon(other.world) != canon(gen.world)


def test_same_flight_same_fate_regardless_of_which_days_are_generated(gen):
    one = generate_world(0, [w for w in sample_days() if w.day == date(2024, 1, 21)])
    a = {f.id: f for f in gen.world.flights}
    for f in one.world.flights:
        assert a[f.id] == f


def test_every_cancellation_has_latent_ground_truth(gen):
    w, t = gen.world, gen.truth.flights
    assert set(t) == {f.id for f in w.flights}
    for f in w.flights:
        ft = t[f.id]
        assert ft.status == f.status
        if f.status == "cancelled":
            assert ft.latent != "none"
            assert ft.cause in {c.value for c in Cause}
            assert ft.extraordinary in (Extraordinary.YES.value, Extraordinary.NO.value)
            assert f.ops_cause_code is not None and f.notified_at is not None
        else:
            assert ft.latent == "none" and f.ops_cause_code is None


def test_truth_follows_the_law_for_each_latent_cause(gen):
    for ft in gen.truth.flights.values():
        if ft.status != "cancelled":
            continue
        if ft.latent in ("weather_dep", "weather_arr", "atc", "external_hit"):
            assert ft.extraordinary == "extraordinary"
        if ft.latent in ("internal_aog", "crew", "concurrent"):
            assert ft.extraordinary == "not_extraordinary"
        if ft.latent == "rotation":
            assert ft.cause == "knock_on"
            if ft.root_latent in ("weather_dep", "weather_arr", "atc", "external_hit"):
                assert ft.expected_route == "legal"
                ok = ft.spare_within_3h is False and ft.reroute_earliest_offered
                assert (ft.extraordinary == "extraordinary") == bool(ok)


def test_storm_days_get_one_occ_batch_coded_71(gen):
    w = gen.world
    storm_days = {m["date"] for m in w.meta["days"] if m["kind"] == "storm"}
    for d in storm_days:
        batches = [o for o in w.ops_log if o.kind == "occ" and o.author == "OCC DM" and o.at.date().isoformat() == d]
        assert len(batches) == 1, d
        b = batches[0]
        assert b.code == "71" and "CNL LIST" in b.text and "RSN 71" in b.text
        flights = {f.id: f for f in w.flights}
        assert all(flights[i].ops_cause_code in ("71", "72") for i in b.flight_ids)


def test_weather_truth_needs_real_weather_at_an_end(gen):
    from world import causes as C

    w = gen.world
    flights = {f.id: f for f in w.flights}
    for ft in gen.truth.flights.values():
        if ft.latent not in ("weather_dep", "weather_arr"):
            continue
        f = flights[ft.flight_id]
        sev = max(C.severity(C.ObsIndex(w.metar.get(f"{_icao(f.origin)}@{ft.day}", [])), f.sched_dep),
                  C.severity(C.ObsIndex(w.metar.get(f"{_icao(f.dest)}@{ft.day}", [])), f.sched_arr))
        assert sev > 0, ft.flight_id


def _icao(code: str) -> str:
    from world.airports import airport

    return airport(code).icao


def test_aog_cancellations_have_a_no_go_tech_log_entry(gen):
    w = gen.world
    tl = {e.aircraft: [] for e in w.tech_log}
    for e in w.tech_log:
        tl[e.aircraft].append(e)
    flights = {f.id: f for f in w.flights}
    for ft in gen.truth.flights.values():
        if ft.latent == "internal_aog":
            f = flights[ft.flight_id]
            entries = [e for e in tl.get(f.aircraft, []) if e.aog and e.logged_at <= f.sched_dep + timedelta(hours=1)]
            assert entries and all(e.mel_relief is False for e in entries if e.ata != "0551")


def test_rotation_links(gen):
    flights = {f.id: f for f in gen.world.flights}
    for f in flights.values():
        if f.inbound_flight_id:
            prev = flights[f.inbound_flight_id]
            assert prev.dest == f.origin and prev.sched_arr <= f.sched_dep
        if f.outbound_pair_id:
            out = flights[f.outbound_pair_id]
            assert out.origin == f.dest and out.dest == f.origin


def test_outstation_metar_is_in_the_world(gen):
    keys = set(gen.world.metar)
    assert "EIDW@2024-01-21" in keys and "EGLL@2024-01-21" in keys and "KBOS@2024-01-21" in keys


def test_one_day_simulates_fast():
    import time

    w = next(x for x in D.world_days() if x.day == date(2024, 12, 7))
    # CPU time, not wall clock: the bound is about the simulation's cost, which a loaded machine doesn't change
    t0 = time.process_time()
    DaySim(w, 0).run()
    assert time.process_time() - t0 < 1.5


def test_generator_never_imports_the_engine():
    for p in Path(__file__).resolve().parents[1].glob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("engine"), p
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("engine") for a in node.names), p
