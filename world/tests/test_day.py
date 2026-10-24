"""F3d: `generate_day(icao, local_day, seed)`, the judge's desk world (offline on pinned METAR unless a test fakes IEM)."""
import hashlib
import time
from datetime import UTC, date, datetime, timedelta
from functools import cache

import orjson
import pytest
import time_machine

from contracts.models import World

# (station, local day): pinned at both ends. Isha (storm), Boston's local evening, an EU airport (context
# flight), Dublin's whole hub day, and calm days with nothing natural going wrong.
EGLL_ISHA = ("EGLL", date(2024, 1, 21))
KBOS_EVENING = ("KBOS", date(2024, 1, 10))
LFPG_ISHA = ("LFPG", date(2024, 1, 21))
EIDW_ISHA = ("EIDW", date(2024, 1, 21))
CALM_NON_EU = [("EGLL", date(2024, 5, 15), 7), ("KBOS", date(2024, 5, 14), 0), ("KBOS", date(2023, 10, 15), 5)]
CALM_EU = [("LFPG", date(2024, 5, 15), 0), ("LFPG", date(2025, 3, 24), 2)]
CASES = [(*EGLL_ISHA, 7), (*EGLL_ISHA, 0), (*KBOS_EVENING, 0), (*KBOS_EVENING, 3), (*LFPG_ISHA, 7),
         (*EIDW_ISHA, 0), *CALM_NON_EU, *CALM_EU, ("EHAM", date(2023, 11, 2), 3), ("LEBL", date(2024, 12, 7), 1)]
ALLOWS_CONTRADICTION = [c for c in CASES if c[0] not in ("EHAM", "LEBL")]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")


@cache
def desk(icao: str, day: date, seed: int):
    from world.generate import generate_day_full

    return generate_day_full(icao, day, seed)


def canon(world: World) -> str:
    return hashlib.sha256(orjson.dumps(world.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)).hexdigest()


def near(world: World, icao: str, t: datetime, minutes: int = 60) -> list:
    return [o for key, obs in world.metar.items() if key.split("@")[0] == icao for o in obs
            if abs((o.valid - t).total_seconds()) <= minutes * 60]


# ---------------------------------------------------------------- WorldAPI basics

def test_judge_day_is_a_real_world_on_pinned_weather():
    from world.api import WorldImpl

    world = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)

    assert isinstance(world, World)
    assert any(f.origin == "DUB" and f.dest == "LHR" for f in world.flights)
    assert any(f.origin == "LHR" and f.dest == "DUB" for f in world.flights)
    assert world.metar["EGLL@2024-01-21"]
    assert world.metar["EIDW@2024-01-21"]


@pytest.mark.parametrize("seed", [0, 7, 99])
def test_judge_day_always_contains_unsigned_voucher_scope_controls(seed):
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


def test_intra_eu_judge_route_has_a_labelled_non_eu_control():
    """Between DUB and an EU airport every sector departs the EU, so nothing could 'ask again'. The day's BOS→DUB
    inbound joins as labelled context (golden's Herminia pattern) with compensation owed, and the storm entry lists
    it so a run over the desk's flights reaches it."""
    from world.api import WorldImpl

    api = WorldImpl()
    world = api.generate_day("LFPG", date(2024, 1, 21), seed=7)
    flights = {f.id: f for f in world.flights}
    assert any(f.origin == "DUB" and f.dest == "CDG" for f in world.flights)
    context = world.meta["desk"]["context_flights"]
    assert context == ["NS30@2024-01-20"]
    assert flights[context[0]].origin == "BOS" and flights[context[0]].status == "cancelled"
    assert not api.airport(flights[context[0]].origin).eu
    assert context[0] in world.meta["storms"]["LFPG@2024-01-21"]["flight_ids"]
    assert len(world.meta["days"][0]["judge_unsigned_vouchers"]) == 4


@pytest.mark.parametrize("station, day, code", [
    ("ZZZZ", date(2024, 1, 21), "unknown_airport"),
    ("KBOS", date(2099, 1, 1), "future_date"),
    ("EGLL", date(1900, 1, 1), "no_metar"),
    ("LFPG", date(2024, 3, 13), "no_metar"),       # a real day, but LFPG isn't pinned for it (offline)
])
def test_bad_desk_input_has_a_plain_world_error(station, day, code):
    from world.api import WorldImpl
    from world.errors import WorldError

    with pytest.raises(WorldError) as caught:
        WorldImpl().generate_day(station, day)
    assert caught.value.code == code
    assert caught.value.message


def test_judge_world_is_reproducible_fast_and_schema_valid():
    """Under 2 s of CPU (time.process_time: what the spec bounds; wall clock on a loaded box is not), cold METAR."""
    from world import generator, metar
    from world.api import WorldImpl

    for parsed in (metar._daily_rows, metar._bundle_index, generator._pinned_cached):
        parsed.cache_clear()
    start = time.process_time()
    first = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    assert time.process_time() - start < 2
    second = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    first = World.model_validate_json(first.model_dump_json())
    dump = lambda world: orjson.dumps(world.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    assert dump(first) == dump(second)
    assert all(s.sha256 == hashlib.sha256((s.text or "").encode()).hexdigest() for s in first.sources)


def test_calm_weather_can_expose_a_simulated_technical_weather_miscode():
    from world.api import WorldImpl

    world = WorldImpl().generate_day("EGLL", date(2024, 1, 21), seed=7)
    assert any(f.status == "cancelled" and f.ops_cause_code == "71"
               and any(t.aircraft == f.aircraft and t.aog and t.mel_relief is False for t in world.tech_log)
               for f in world.flights)
    assert world.meta["real_vs_simulated"]["real"]


def test_future_day_is_checked_in_the_requested_airports_timezone():
    from world.api import WorldImpl
    from world.errors import WorldError

    # 00:30Z on 24 Oct: already the 24th in Dublin, still the evening of the 23rd in Boston
    with time_machine.travel("2026-10-24T00:30:00Z", tick=False), pytest.raises(WorldError) as caught:
        WorldImpl().generate_day("KBOS", date(2026, 10, 24))
    assert caught.value.code == "future_date"


def test_a_local_day_whose_flights_have_not_landed_yet_is_a_future_date():
    from world.api import WorldImpl
    from world.errors import WorldError

    # 12:00Z on 10 Jan 2024 is 07:00 in Boston: NS31 hasn't left Dublin and NS30 leaves Boston tonight
    with time_machine.travel("2024-01-10T12:00:00Z", tick=False), pytest.raises(WorldError) as caught:
        WorldImpl().generate_day("KBOS", date(2024, 1, 10))
    assert caught.value.code == "future_date" and "landed" in caught.value.message


# ---------------------------------------------------------------- determinism, schema, planted counts

def test_deterministic_hash_per_seed_and_seeds_differ():
    from world.generate import generate_day

    a = canon(generate_day("EGLL", date(2024, 1, 21), 7))
    assert a == canon(generate_day("EGLL", date(2024, 1, 21), 7))
    assert a != canon(generate_day("EGLL", date(2024, 1, 21), 8))


@pytest.mark.parametrize("icao, day, seed", CASES)
def test_schema_valid_and_planted_counts(icao, day, seed):
    from world.airports import airport

    g = desk(icao, day, seed)
    world = g.world
    assert World.model_validate(orjson.loads(orjson.dumps(world.model_dump(mode="json")))) == world
    planted = world.meta["desk"]["planted"]
    flights = {f.id: f for f in world.flights}
    coupons = {c.id: c for c in world.coupons}
    unsigned = {e.coupon_id for e in world.crm if e.kind == "voucher_in_lieu_of_compensation"
                and not e.signed_acceptance_sha256}
    for name, n, eu in (("in_lieu_unsigned_eu_departures", 3, True), ("in_lieu_unsigned_non_eu", 1, False)):
        ids = planted[name]
        assert len(ids) == n == len(set(ids)), name
        for cid in ids:
            flight = flights[coupons[cid].flight_id]
            assert cid in unsigned and flight.status == "cancelled"
            assert airport(flight.origin).eu is eu
            assert coupons[cid].fare_type == "revenue"
            assert "voucher_in_lieu_unsigned" in g.truth.coupons[cid]["planted"]
            assert g.truth.coupons[cid]["handling"] in ("pay_cash_voucher_stays_goodwill", "refund_and_care_only")
    weather_coded_calm = [f.id for f in world.flights if f.status == "cancelled" and f.ops_cause_code in ("71", "72")
                          and g.truth.flights[f.id].latent == "internal_aog"
                          and any(e.station == "DUB" and e.aircraft == f.aircraft and e.aog for e in world.tech_log)
                          and near(world, "EIDW", f.sched_dep) and not any(
                              _storm(o) for o in near(world, "EIDW", f.sched_dep))]
    if (icao, day, seed) in ALLOWS_CONTRADICTION:
        assert planted["contradicted_weather_code"] in weather_coded_calm
    assert world.meta["storms"][f"{airport(icao).icao}@{day.isoformat()}"]["flight_ids"] == list(flights)


def _storm(o) -> bool:
    from world.metar import storm_conditions

    return storm_conditions(o)


@pytest.mark.parametrize("icao, day, seed", [(*KBOS_EVENING, 0), (*EGLL_ISHA, 7), *CALM_NON_EU, *CALM_EU])
def test_vouchers_sit_on_compensation_owed_where_the_day_has_it(icao, day, seed):
    """Both sides owed: 3 EU-departure vouchers settle under R-CL-1 and the non-EU one asks again. On Isha day the
    LHR→DUB legs land in Dublin's storm window (weather, nothing owed), so only the EU side can be."""
    g = desk(icao, day, seed)
    planted = g.world.meta["desk"]["planted"]
    assert all(g.truth.coupons[c]["status"] == "owed" for c in planted["in_lieu_unsigned_eu_departures"])
    non_eu = [g.truth.coupons[c]["status"] for c in planted["in_lieu_unsigned_non_eu"]]
    assert non_eu == (["no_compensation"] if (icao, day) == EGLL_ISHA else ["owed"])


# ---------------------------------------------------------------- the planted fault is consistent evidence

@pytest.mark.parametrize("icao, day, seed", ALLOWS_CONTRADICTION)
def test_planted_fault_evidence_is_consistent(icao, day, seed):
    g = desk(icao, day, seed)
    world, truth = g.world, g.truth
    flights = {f.id: f for f in world.flights}
    root = flights[world.meta["desk"]["planted"]["contradicted_weather_code"]]
    t = truth.flights[root.id]

    # at DUB, cancelled, coded weather, while the METAR at both ends shows no storm conditions
    assert root.origin == "DUB" and root.status == "cancelled" and root.ops_cause_code in ("71", "72")
    assert near(world, "EIDW", root.sched_dep) and not any(_storm(o) for o in near(world, "EIDW", root.sched_dep))
    dest = next(a.icao for a in world.airports if a.iata == root.dest)
    assert near(world, dest, root.sched_arr) and not any(_storm(o) for o in near(world, dest, root.sched_arr))
    # one AOG write-up at DUB before departure, no MEL relief; truth agrees and tags the miscode
    aogs = [e for e in world.tech_log if e.aircraft == root.aircraft and e.aog]
    assert len(aogs) == 1
    aog = aogs[0]
    assert aog.station == "DUB" and aog.logged_at < root.sched_dep and aog.mel_relief is False
    assert aog.rts_est is not None and aog.rts_est > root.sched_dep
    assert (t.latent, t.cause, t.extraordinary) == ("internal_aog", "technical", "not_extraordinary")
    assert "miscoded_technical" in t.planted and t.ops_code == root.ops_cause_code

    # every cancelled flight is in exactly one OCC entry, whose code is the flight's code (batch inbounds: RSN 72)
    for f in world.flights:
        tf = truth.flights[f.id]
        assert tf.status == f.status
        entries = [e for e in world.ops_log if e.kind == "occ" and f.id in e.flight_ids]
        if f.status != "cancelled":
            assert not entries and f.ops_cause_code is None
            continue
        assert len(entries) == 1, (f.id, [e.id for e in entries])
        e = entries[0]
        assert f.ops_cause_code == tf.ops_code
        assert e.code == f.ops_cause_code or (f.ops_cause_code == "72" and "INBD" in e.text and f.number in e.text)
    # the grounded aircraft flies nothing until its return to service; its later sectors trace back to the fault
    for f in world.flights:
        if f.aircraft == root.aircraft and root.sched_dep <= f.sched_dep < aog.rts_est:
            assert f.status == "cancelled", f.id
    for f in world.flights:
        tf = truth.flights[f.id]
        if f.status == "cancelled" and f.id != root.id and tf.root_flight_id == root.id:
            assert tf.latent == "rotation" and f.aircraft == root.aircraft
    # coupons only on cancelled flights, one per passenger; the faulted flight's compensation is owed
    by_flight: dict[str, int] = {}
    for c in world.coupons:
        by_flight[c.flight_id] = by_flight.get(c.flight_id, 0) + 1
    assert set(by_flight) == {f.id for f in world.flights if f.status == "cancelled"}
    assert all(by_flight[fid] == flights[fid].pax for fid in by_flight)
    statuses = {truth.coupons[c.id]["status"] for c in world.coupons if c.flight_id == root.id}
    assert statuses <= {"owed", "staff_ticket"} and "owed" in statuses
    assert world.meta["days"][0]["cancelled"] == sorted(fid for fid, f in flights.items() if f.status == "cancelled")


def test_the_planted_fault_is_at_dublin_on_a_long_haul_day():
    """Boston's day: the AOG is written up at DUB before NS31 (not at the outstation), NS30 knocks on."""
    g = desk(*KBOS_EVENING, 0)
    root = g.world.meta["desk"]["planted"]["contradicted_weather_code"]
    assert root == "NS31@2024-01-10"
    assert [(e.station, e.aircraft) for e in g.world.tech_log if e.aog] == [("DUB", "EI-NSN")]
    knock = g.truth.flights["NS30@2024-01-10"]
    assert (knock.latent, knock.root_flight_id, knock.extraordinary) == ("rotation", root, "not_extraordinary")


@pytest.mark.parametrize("icao, day, seed", CALM_NON_EU)
def test_no_extra_faults_on_a_calm_day(icao, day, seed):
    """One planted fault. Everything cancelled is that aircraft's day; nothing else is made up."""
    g = desk(icao, day, seed)
    world = g.world
    planted = world.meta["desk"]["planted"]
    assert [f["kind"] for f in planted["faults"]] == ["aog_miscoded_weather"]
    root = next(f for f in world.flights if f.id == planted["contradicted_weather_code"])
    assert [e.aircraft for e in world.tech_log if e.aog] == [root.aircraft]
    assert {f.aircraft for f in world.flights if f.status == "cancelled"} == {root.aircraft}
    assert len([e for e in world.ops_log if e.kind == "occ" and e.code in ("71", "72")]) == 1


@pytest.mark.parametrize("icao, day, seed", CALM_EU)
def test_an_eu_airports_calm_day_adds_only_the_honest_context_case(icao, day, seed):
    g = desk(icao, day, seed)
    world = g.world
    planted = world.meta["desk"]["planted"]
    assert [f["kind"] for f in planted["faults"]] == ["aog_miscoded_weather", "aog_context"]
    ctx = next(f for f in world.flights if f.id == planted["context_flights"][0])
    assert ctx.origin == "BOS" and ctx.ops_cause_code == "41"
    assert [(e.station, e.aircraft) for e in world.tech_log if e.aog and e.aircraft == ctx.aircraft] == \
        [("BOS", ctx.aircraft)]
    aog = next(e for e in world.tech_log if e.aog and e.aircraft == ctx.aircraft)
    # written up at BOS after the aircraft got there (NS31 of the evening before, in the network) and by STD.
    # 24 Mar 2025 is in the US/EU daylight-saving gap: NS31 lands as NS30 is due out, so the write-up is on arrival
    from world import network as N

    arrived = next(s.sta for s in N.day_sectors(ctx.date) if s.number == "NS31")
    assert arrived <= aog.logged_at <= ctx.sched_dep
    assert g.truth.flights[ctx.id].extraordinary == "not_extraordinary"
    weather_coded = [e for e in world.ops_log if e.kind == "occ" and e.code in ("71", "72")]
    assert len(weather_coded) == 1 and planted["contradicted_weather_code"] in weather_coded[0].flight_ids


# ---------------------------------------------------------------- the judge's local day and its weather

def test_boston_local_day_and_its_evening_departure_have_metar_at_both_ends():
    """Boston's 10 Jan: NS31 lands that evening and NS30 leaves at 19:10 local = 00:10Z on the 11th. The previous
    evening's NS30 is Boston's 9 Jan, not this day."""
    world = desk(*KBOS_EVENING, 0).world
    ids = {f.id for f in world.flights}
    assert ids == {"NS31@2024-01-10", "NS30@2024-01-10"}
    ns30 = next(f for f in world.flights if f.id == "NS30@2024-01-10")
    assert ns30.sched_dep == datetime(2024, 1, 11, 0, 10, tzinfo=UTC)
    assert near(world, "KBOS", ns30.sched_dep)
    assert near(world, "EIDW", ns30.sched_arr)


def test_live_metar_is_fetched_for_every_hour_the_flights_need(monkeypatch):
    """Nothing pinned (cache mode, IEM faked): each station is fetched across the UTC days its sectors need."""
    from world import metar
    from world.generate import generate_day

    monkeypatch.setenv("STORMCHECK_MODE", "cache")
    real_pinned = metar.pinned_day
    monkeypatch.setattr(metar, "pinned_day", lambda icao, d: None if icao in ("KBOS", "EIDW") else real_pinned(icao, d))
    monkeypatch.setattr(metar, "_MEMO", {})
    calls: list[tuple[str, datetime, datetime]] = []

    def fake_iem(icao, start, end, *, timeout=metar.TIMEOUT_S):
        calls.append((icao, start, end))
        t = start.replace(minute=54, second=0, microsecond=0)
        rows = []
        while t < end:
            if t >= start:
                rows.append(metar.MetarObs(station=icao, valid=t, sknt=8, gust=None, drct=240, vsby_sm=10.0,
                                           wxcodes=None, raw=f"{icao[1:] if icao[0] == 'K' else icao} "
                                                             f"{t:%d%H%M}Z 24008KT 10SM FEW040 05/M02 A3000"))
            t += timedelta(hours=1)
        return rows

    monkeypatch.setattr(metar, "fetch_iem", fake_iem)
    world = generate_day("KBOS", date(2024, 1, 10), seed=0)
    ns30 = next(f for f in world.flights if f.id == "NS30@2024-01-10")
    ns31 = next(f for f in world.flights if f.id == "NS31@2024-01-10")
    assert near(world, "KBOS", ns30.sched_dep) and near(world, "KBOS", ns31.sched_arr)
    assert near(world, "EIDW", ns31.sched_dep) and near(world, "EIDW", ns30.sched_arr)
    spans = {icao: (s, e) for icao, s, e in calls}
    assert set(spans) == {"KBOS", "EIDW"} and len(calls) == 2           # one request per station
    assert spans["KBOS"][0] <= ns31.sched_arr and spans["KBOS"][1] >= ns30.sched_dep
    assert spans["EIDW"][0] <= ns31.sched_dep and spans["EIDW"][1] >= ns30.sched_arr
    assert world.meta["desk"]["metar"] == {"EIDW": "retrieved", "KBOS": "retrieved"}


# ---------------------------------------------------------------- the hub day and loading

def test_dublin_is_the_whole_network_day():
    from world import network as N

    world = desk(*EIDW_ISHA, 0).world
    assert [f.id for f in world.flights] == [s.id for s in N.day_sectors(date(2024, 1, 21))]
    assert world.meta["desk"]["hub_day"] is True


@pytest.mark.parametrize("name", ["world.json", "world.json.gz"])
def test_load_reads_json_and_json_gz(tmp_path, name):
    from world.api import WorldImpl, write_world

    world = desk(*EGLL_ISHA, 7).world
    path = write_world(world, tmp_path / name)
    assert canon(WorldImpl().load(str(path))) == canon(world)
    assert path.read_bytes() == write_world(world, tmp_path / ("again-" + name)).read_bytes()
    if name.endswith(".gz"):
        assert path.read_bytes()[:2] == b"\x1f\x8b"
