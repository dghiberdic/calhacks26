"""Airports, EU261 territory and Art. 7(4) great-circle distances.

Airports come from ``World.airports`` first; a code the world does not carry falls back to the bundled
``airportsdata`` table (static data, no network), so a judge's airport still resolves. Distances are great circle
with R = 6,371 km (Art. 7(4)), unless the world pins a distance for the pair in ``meta["distances_km"]``.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from contracts.models import Airport, World

EARTH_RADIUS_KM = 6371.0

# EU261 territory: EU27 + EEA (IS, LI, NO) + CH.
EU261_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
    "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO", "CH",
})


class UnknownAirport(KeyError):
    pass


@lru_cache(maxsize=2)
def _table(key: str) -> dict[str, dict[str, Any]]:
    import airportsdata  # static bundled data

    return airportsdata.load(key)


def _from_table(code: str) -> Airport:
    code = code.upper()
    row = _table("IATA").get(code) if len(code) == 3 else None
    if row is None and len(code) == 4:
        row = _table("ICAO").get(code)
    if row is None:
        raise UnknownAirport(code)
    return Airport(icao=row["icao"], iata=row.get("iata") or code, name=row["name"], lat=float(row["lat"]),
                   lon=float(row["lon"]), country=row["country"], eu=row["country"] in EU261_COUNTRIES, tz=row["tz"])


def airport(world: World | None, code: str) -> Airport:
    """Look up an airport by IATA or ICAO, world first, then the bundled table."""
    if world is not None:
        for a in world.airports:
            if code in (a.iata, a.icao):
                return a
    return _from_table(code)


def haversine_km(a: Airport, b: Airport) -> float:
    p1, l1, p2, l2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def _pinned_distance(world: World | None, a: str, b: str) -> float | None:
    if world is None:
        return None
    table = world.meta.get("distances_km") if isinstance(world.meta, dict) else None
    if not isinstance(table, dict):
        return None
    for k in (f"{a}-{b}", f"{b}-{a}", f"{a}{b}", f"{b}{a}", f"{a}:{b}", f"{b}:{a}"):
        if k in table:
            return float(table[k])
    # a flat {dest: km} table keyed by the non-hub end
    for k in (a, b):
        if k in table and isinstance(table[k], int | float):
            return float(table[k])
    return None


def distance_km(world: World | None, a: str, b: str) -> float:
    """Great-circle distance in km, rounded to 0.1 km so bands are stable across platforms."""
    pinned = _pinned_distance(world, a, b)
    if pinned is not None:
        return round(pinned, 1)
    return round(haversine_km(airport(world, a), airport(world, b)), 1)


def route_region(origin: Airport, dest: Airport) -> str:
    """``EU`` (both ends in EU261 territory) · ``EU_US`` · ``EU_UK`` · ``OTHER``."""
    if origin.eu and dest.eu:
        return "EU"
    pair = {origin.country, dest.country}
    if origin.eu or dest.eu:
        if "US" in pair:
            return "EU_US"
        if "GB" in pair:
            return "EU_UK"
    return "OTHER"
