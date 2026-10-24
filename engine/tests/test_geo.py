"""geo: EU261 territory (Art. 3(1), TFEU Art. 355(1)) and Art. 7(4) distances, banded on the unrounded value."""
from __future__ import annotations

import math

import pytest

from contracts.models import Airport, World
from engine import geo
from engine.eu261 import band_for, scope_article


def _pair(km: float, a_eu: bool, b_eu: bool, meta: dict | None = None) -> World:
    lat = math.degrees(km / geo.EARTH_RADIUS_KM)          # due north on a meridian: great circle = km exactly
    a = Airport(icao="XAAA", iata="AAA", name="A", lat=0.0, lon=0.0, country="IE", eu=a_eu, tz="UTC")
    b = Airport(icao="XBBB", iata="BBB", name="B", lat=lat, lon=0.0, country="IE" if b_eu else "US", eu=b_eu,
                tz="UTC")
    return World(meta=meta or {}, airports=[a, b], flights=[], tech_log=[], ops_log=[], coupons=[], elections=[],
                 crm=[], claims=[], metar={}, sources=[])


# ---------- bands on the unrounded distance (review p3_geo) ----------

@pytest.mark.parametrize("km,a_eu,b_eu,eur", [
    (1500.04, True, True, 400),        # intra-EU: > 1,500 km is band (b), not (a)
    (1500.04, True, False, 400),       # other: 1,500-3,500 km is band (b)
    (3500.04, True, False, 600),       # other: > 3,500 km is band (c)
])
def test_band_uses_the_unrounded_distance(km, a_eu, b_eu, eur):
    great_circle = geo.distance_km(_pair(km, a_eu, b_eu), "AAA", "BBB")
    assert band_for(great_circle, a_eu and b_eu).eur == eur
    pinned = _pair(10.0, a_eu, b_eu, meta={"distances_km": {"AAA-BBB": km}})
    assert band_for(geo.distance_km(pinned, "AAA", "BBB"), a_eu and b_eu).eur == eur


@pytest.mark.parametrize("km,a_eu,b_eu,eur", [
    (1500.0, True, True, 250), (1500.0, True, False, 250), (3500.0, True, False, 400), (3500.0, True, True, 400),
])
def test_exact_thresholds_keep_their_band(km, a_eu, b_eu, eur):
    great_circle = geo.distance_km(_pair(km, a_eu, b_eu), "AAA", "BBB")      # float noise must not flip a band
    assert great_circle == km
    assert band_for(great_circle, a_eu and b_eu).eur == eur
    pinned = _pair(10.0, a_eu, b_eu, meta={"distances_km": {"AAA-BBB": km}})
    assert band_for(geo.distance_km(pinned, "AAA", "BBB"), a_eu and b_eu).eur == eur


def test_display_rounds_to_a_tenth():
    assert geo.display_km(1500.04) == 1500.0 and geo.display_km(4804.0) == 4804.0
    assert geo.display_km(1485.2345) == 1485.2


# ---------- EU261 territory (review p3_geo) ----------

@pytest.mark.parametrize("code", [
    "RUN", "PTP", "FDF", "CAY", "DZA", "SFG",       # outermost regions with their own ISO codes: RE GP MQ GF YT MF
    "LPA", "FNC", "PDL", "MHQ",                      # Canaries, Madeira, Azores, Åland
    "LCA", "PFO", "DUB", "ZRH", "OSL", "KEF", "MLN", "BSL",
])
def test_in_eu261_territory(code):
    assert geo.airport(None, code).eu, code


@pytest.mark.parametrize("code", [
    "ECN", "LCEN",                                   # northern Cyprus: acquis suspended (Protocol 10, 2003 Act)
    "AKT",                                           # UK Sovereign Base Area (Protocol 3, 2003 Act)
    "LYR",                                           # Svalbard: outside the EEA Agreement (Protocol 40)
    "GIB", "SBH", "FSP", "PPT", "NOU", "CUR", "SXM", "FAE", "GOH", "LHR", "JER", "BOS",
])
def test_outside_eu261_territory(code):
    assert not geo.airport(None, code).eu, code


def test_outermost_region_departure_is_in_scope():
    run, jfk, cdg = geo.airport(None, "RUN"), geo.airport(None, "JFK"), geo.airport(None, "CDG")
    assert scope_article(run, jfk, operating_carrier_eu=False) == "Art.3(1)(a)"
    assert scope_article(jfk, run, operating_carrier_eu=True) == "Art.3(1)(b)"
    assert band_for(geo.distance_km(None, "RUN", "CDG"), run.eu and cdg.eu).eur == 400     # intra-EU > 1,500 km
