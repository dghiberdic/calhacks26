"""Airports, EU261 territory, timezones and Art. 7(4) great-circle distances (F2).

Data: `data/pinned/airports.csv`, an OurAirports subset (large + medium airports in Europe and North America, see
`world/pin_airports.py`) with an IANA `tz` column from `airportsdata`. Codes outside the subset (a judge may type
any station at the desk) fall back to `airportsdata` itself. Lookups accept ICAO or IATA, case-insensitive.

`eu` means EU261 territory: EU27 + EEA (IS, LI, NO) + CH, including the EU outermost regions (Canaries, Madeira,
Azores via ES/PT; Guadeloupe, Martinique, French Guiana, Réunion, Mayotte, Saint-Martin by their own ISO codes),
except northern Cyprus, RAF Akrotiri and Svalbard (`NOT_EU261_AIRPORTS`; the same rule as `engine/geo.py`).
The UK is not EU261 territory (UK261 is a separate regime).
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

from contracts.models import Airport
from world.errors import WorldError

ROOT = Path(__file__).resolve().parent.parent
PINNED_CSV = ROOT / "data" / "pinned" / "airports.csv"
PINNED_COLUMNS = ["icao", "iata", "name", "lat", "lon", "country", "continent", "type", "municipality", "tz"]
EARTH_RADIUS_KM = 6371.0

EU27 = frozenset({"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
                  "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"})
EEA_CH = frozenset({"IS", "LI", "NO", "CH"})
OUTERMOST = frozenset({"GP", "MQ", "GF", "RE", "YT", "MF"})   # French outermost regions with their own ISO codes
EU261_COUNTRIES = EU27 | EEA_CH | OUTERMOST
# Airports inside an EU261 country code where the Regulation does not apply (IATA and ICAO), as in engine/geo.py:
# northern Cyprus, Ercan and Geçitkale (acquis suspended, Protocol 10 to the 2003 Act of Accession); RAF Akrotiri
# (UK Sovereign Base Area, Protocol 3); Svalbard, Longyearbyen (outside the EEA Agreement, Protocol 40).
NOT_EU261_AIRPORTS = frozenset({"ECN", "LCEN", "GEC", "LCGK", "AKT", "LCRA", "LYR", "ENSB"})


def is_eu_country(iso2: str) -> bool:
    return (iso2 or "").strip().upper() in EU261_COUNTRIES


def in_eu261_territory(country: str, *codes: str) -> bool:
    """Art. 3(1) territory: an EU261 country code, unless the airport is one of `NOT_EU261_AIRPORTS`."""
    return is_eu_country(country) and not any((c or "").upper() in NOT_EU261_AIRPORTS for c in codes)


def _airport(icao: str, iata: str, name: str, lat: float, lon: float, country: str, tz: str) -> Airport:
    return Airport(icao=icao, iata=iata or icao, name=name, lat=round(lat, 6), lon=round(lon, 6), country=country,
                   eu=in_eu261_territory(country, icao, iata), tz=tz)


@lru_cache(maxsize=1)
def _pinned() -> tuple[dict[str, Airport], dict[str, str]]:
    by_icao: dict[str, Airport] = {}
    iata_to_icao: dict[str, str] = {}
    with PINNED_CSV.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            a = _airport(r["icao"], r["iata"], r["name"], float(r["lat"]), float(r["lon"]), r["country"], r["tz"])
            by_icao[a.icao] = a
            if r["iata"]:
                # a large airport wins an IATA collision (rows are sorted by ICAO, so this is deterministic)
                prev = iata_to_icao.get(r["iata"])
                if prev is None or r["type"] == "large_airport":
                    iata_to_icao[r["iata"]] = a.icao
    return by_icao, iata_to_icao


@lru_cache(maxsize=1)
def _airportsdata() -> tuple[dict, dict]:
    import airportsdata  # lazy: ~28k rows, only needed for codes outside the pinned subset

    return airportsdata.load("ICAO"), airportsdata.load("IATA")


@lru_cache(maxsize=4096)
def airport(code: str) -> Airport:
    """Look up an airport by ICAO (4 letters) or IATA (3 letters). Raises WorldError("unknown_airport")."""
    c = (code or "").strip().upper()
    if len(c) not in (3, 4) or not c.isalnum():
        raise WorldError("unknown_airport", f"'{code}' is not an airport code (use ICAO like EIDW or IATA like DUB).")
    by_icao, iata_to_icao = _pinned()
    if len(c) == 4 and c in by_icao:
        return by_icao[c]
    if len(c) == 3 and c in iata_to_icao:
        return by_icao[iata_to_icao[c]]
    ad_icao, ad_iata = _airportsdata()
    rec = ad_icao.get(c) if len(c) == 4 else ad_iata.get(c)
    if rec and rec.get("tz") and (rec.get("icao") or len(c) == 4):
        return _airport(rec.get("icao") or c, rec.get("iata") or "", rec["name"], float(rec["lat"]),
                        float(rec["lon"]), rec["country"], rec["tz"])
    raise WorldError("unknown_airport", f"Airport '{c}' was not found in the airport database.")


def known(code: str) -> bool:
    try:
        airport(code)
    except WorldError:
        return False
    return True


def all_airports() -> list[Airport]:
    """The pinned subset, sorted by ICAO."""
    return list(_pinned()[0].values())


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


@lru_cache(maxsize=4096)
def _distance(a: str, b: str) -> float:
    x, y = airport(a), airport(b)
    if x.icao == y.icao:
        return 0.0
    return round(great_circle_km(x.lat, x.lon, y.lat, y.lon), 1)


def distance_km(a: str, b: str) -> float:
    """Great-circle distance (Art. 7(4), R = 6371 km), rounded to 0.1 km. Symmetric; ICAO or IATA."""
    x, y = airport(a).icao, airport(b).icao
    return _distance(*sorted((x, y)))


def band_eur(a: str, b: str) -> int:
    """EU261 Art. 7(1) band: ≤1500 km €250; intra-EU >1500 km or 1500–3500 km €400; otherwise €600."""
    d = distance_km(a, b)
    if d <= 1500:
        return 250
    if (airport(a).eu and airport(b).eu) or d <= 3500:
        return 400
    return 600


def band_margin_km(a: str, b: str) -> float:
    """Distance to the nearest band edge that would change the band (the UI's "14 km under the €400 band")."""
    d = distance_km(a, b)
    intra = airport(a).eu and airport(b).eu
    if d <= 1500:
        return round(1500 - d, 1)
    if intra:
        return round(d - 1500, 1)
    if d <= 3500:
        return round(min(d - 1500, 3500 - d), 1)
    return round(d - 3500, 1)
