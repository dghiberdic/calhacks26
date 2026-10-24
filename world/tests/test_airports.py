"""F2: airports, EU261 territory flag, timezones and great-circle distances (all offline, from data/pinned/airports.csv)."""
from __future__ import annotations

import csv

import pytest

from contracts.models import Airport
from world import airports
from world.airports import airport, distance_km, is_eu_country
from world.errors import WorldError

# IMPLEMENTATION_PLAN.md §1.1 (km, great circle, R = 6371)
PLAN_DISTANCES = {"BOS": 4804, "JFK": 5103, "ORD": 5896, "YYZ": 5261, "CDG": 786, "FRA": 1086, "BCN": 1486,
                  "MAD": 1452, "LIS": 1643, "FCO": 1886, "ATH": 2876, "MUC": 1381, "AMS": 750, "LHR": 449}


@pytest.mark.parametrize("dest,km", sorted(PLAN_DISTANCES.items()))
def test_plan_distance_list_within_5km(dest, km):
    assert abs(distance_km("DUB", dest) - km) <= 5


def test_distance_accepts_icao_and_iata_and_is_symmetric():
    assert distance_km("EIDW", "KBOS") == distance_km("DUB", "BOS") == distance_km("BOS", "DUB")
    assert distance_km("dub", "dub") == 0.0


def test_eidw_is_dublin():
    a = airport("EIDW")
    assert isinstance(a, Airport)
    assert (a.icao, a.iata, a.country, a.tz, a.eu) == ("EIDW", "DUB", "IE", "Europe/Dublin", True)
    assert airport("DUB") == a == airport(" eidw ")


@pytest.mark.parametrize("code,tz", [("KBOS", "America/New_York"), ("KORD", "America/Chicago"),
                                     ("CYYZ", "America/Toronto"), ("EGLL", "Europe/London"),
                                     ("LEBL", "Europe/Madrid"), ("LGAV", "Europe/Athens"), ("LFPG", "Europe/Paris")])
def test_timezones_from_airportsdata(code, tz):
    assert airport(code).tz == tz


@pytest.mark.parametrize("code,eu", [
    ("EIDW", True), ("LFPG", True), ("EDDF", True), ("LGAV", True),     # EU27
    ("BIKF", True), ("ENGM", True),                                      # EEA (Iceland, Norway)
    ("LSZH", True),                                                      # Switzerland
    ("GCLP", True), ("LPMA", True),                                      # outermost regions (Canaries, Madeira)
    ("EGLL", False), ("EGCC", False),                                    # UK: not EU261 territory since 2021
    ("KBOS", False), ("CYYZ", False), ("LTFM", False),
])
def test_eu261_territory_flag(code, eu):
    assert airport(code).eu is eu


# EU261 territory is decided per airport, not only per country code: the outermost regions with their own ISO codes
# are in; northern Cyprus (Protocol 10), RAF Akrotiri (Protocol 3) and Svalbard (EEA Protocol 40) are out.
TERRITORY = [("TFFR", True), ("TFFF", True), ("SOCA", True), ("FMEE", True), ("FMCZ", True), ("TFFG", True),
             ("LCEN", False), ("LCGK", False), ("LCRA", False), ("ENSB", False),
             ("LCLK", True), ("LCPH", True), ("ENGM", True), ("EIDW", True), ("LFPG", True), ("GCLP", True),
             ("EGLL", False), ("KBOS", False), ("LTFM", False), ("BGGH", False), ("EKVG", False)]


@pytest.mark.parametrize("code,eu", TERRITORY)
def test_territory_edge_cases(code, eu):
    assert airport(code).eu is eu
    assert airport(airport(code).iata).eu is eu          # the same answer by IATA


@pytest.mark.parametrize("code", [c for c, _ in TERRITORY])
def test_world_and_engine_agree_on_eu261_territory(code):
    """world.airports (the generator's answer key) and engine.geo (the engine's decisions) must not disagree."""
    from engine import geo

    a = airport(code)
    assert a.eu is geo.in_eu261_territory(a.country, a.iata, a.icao)
    try:
        engine_view = geo.airport(None, code)        # the engine's own fallback table (airportsdata)
    except geo.UnknownAirport:                       # e.g. Geçitkale is only in our pinned OurAirports subset
        return
    assert a.eu is engine_view.eu


def test_no_excluded_airport_is_in_the_generated_network():
    from world import network as N
    from world.airports import NOT_EU261_AIRPORTS

    assert not {airport(c).icao for c in N.network_airports()} & NOT_EU261_AIRPORTS
    assert not set(N.network_airports()) & NOT_EU261_AIRPORTS


def test_eu_country_set_is_eu27_eea_ch():
    eu27 = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
            "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
    assert all(is_eu_country(c) for c in eu27 | {"IS", "LI", "NO", "CH"})
    assert not any(is_eu_country(c) for c in ("GB", "US", "CA", "TR", "UA", "RS", "FO", "GL", ""))


def test_unknown_airport_raises_world_error():
    for bad in ("ZZZZ", "QQQ", "", "12", "EIDWX"):
        with pytest.raises(WorldError) as ei:
            airport(bad)
        assert ei.value.code == "unknown_airport"
        assert ei.value.message  # plain English for the desk 422


def test_airport_outside_pinned_subset_falls_back_to_airportsdata():
    # Tokyo Haneda is not in the EU/NA subset, but a judge may still type it at the desk.
    a = airport("RJTT")
    assert (a.iata, a.tz, a.eu) == ("HND", "Asia/Tokyo", False)


def test_pinned_subset_is_large_and_medium_in_europe_and_north_america():
    rows = list(csv.DictReader(airports.PINNED_CSV.open(encoding="utf-8")))
    assert 1500 < len(rows) < 4000
    assert {r["type"] for r in rows} <= {"large_airport", "medium_airport"}
    assert all(r["tz"] for r in rows)
    icaos = [r["icao"] for r in rows]
    assert icaos == sorted(icaos) and len(set(icaos)) == len(icaos)
    assert airports.PINNED_CSV.stat().st_size < 400_000


def test_band_helper_matches_art7():
    # Art. 7(1): <=1500 km €250; intra-EU >1500 or 1500–3500 €400; else €600.
    assert airports.band_eur("DUB", "LHR") == 250
    assert airports.band_eur("DUB", "BCN") == 250          # 1,486 km, 14 km under the €400 band
    assert airports.band_eur("DUB", "LIS") == 400
    assert airports.band_eur("DUB", "ATH") == 400
    assert airports.band_eur("DUB", "BOS") == 600
    assert airports.band_eur("DUB", "KEF") == 250          # 1,497 km
    assert airports.band_eur("LHR", "IST") == 400          # non-EU, 1,500–3,500 km
    assert airports.band_eur("CDG", "FDF") == 400          # intra-EU (Martinique) > 3,500 km stays €400
    assert airports.band_margin_km("DUB", "BCN") == pytest.approx(14, abs=1)
