"""Pin the OurAirports subset used by `world/airports.py` (F2).

    uv run python -m world.pin_airports [path/to/airports.csv]

Without a path it downloads https://davidmegginson.github.io/ourairports-data/airports.csv (public domain).
Keeps large and medium airports in Europe and North America (plus EU outermost regions such as the Canaries,
whose OurAirports continent is AF) that have a 4-letter ICAO-style code, and adds an IANA `tz` from `airportsdata`
(by ICAO, then IATA, then the nearest airportsdata station in the same country). Output is sorted by ICAO, so a
re-run on the same input is byte-identical.
"""
from __future__ import annotations

import csv
import io
import math
import re
import sys
from pathlib import Path

import airportsdata
import httpx

from world.airports import PINNED_CSV, PINNED_COLUMNS, is_eu_country

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
TYPES = ("large_airport", "medium_airport")
CONTINENTS = ("EU", "NA")
_ICAO = re.compile(r"^[A-Z]{4}$")


def _icao(row: dict) -> str | None:
    for key in ("icao_code", "gps_code", "ident"):
        v = (row.get(key) or "").strip().upper()
        if _ICAO.match(v):
            return v
    return None


def _nearest_tz(lat: float, lon: float, country: str, by_icao: dict) -> str | None:
    best, best_d = None, math.inf
    for a in by_icao.values():
        if a["country"] != country or not a["tz"]:
            continue
        d = (a["lat"] - lat) ** 2 + ((a["lon"] - lon) * math.cos(math.radians(lat))) ** 2
        if d < best_d:
            best, best_d = a["tz"], d
    return best


def build(text: str) -> list[dict]:
    by_icao = airportsdata.load("ICAO")
    by_iata = airportsdata.load("IATA")
    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r["type"] not in TYPES:
            continue
        if r["continent"] not in CONTINENTS and not is_eu_country(r["iso_country"]):
            continue
        icao = _icao(r)
        if icao is None:
            continue
        iata = (r.get("iata_code") or "").strip().upper()
        lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
        tz = ((by_icao.get(icao) or {}).get("tz") or (by_iata.get(iata) or {}).get("tz")
              or _nearest_tz(lat, lon, r["iso_country"], by_icao))
        if not tz:
            continue
        row = {"icao": icao, "iata": iata, "name": r["name"].strip(), "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
               "country": r["iso_country"], "continent": r["continent"], "type": r["type"],
               "municipality": (r.get("municipality") or "").strip(), "tz": tz}
        prev = out.get(icao)
        if prev is None or (prev["type"] != "large_airport" and row["type"] == "large_airport"):
            out[icao] = row
    return [out[k] for k in sorted(out)]


def write(rows: list[dict], path: Path = PINNED_CSV) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PINNED_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def main(argv: list[str]) -> None:
    if argv:
        text = Path(argv[0]).read_text(encoding="utf-8")
    else:
        resp = httpx.get(OURAIRPORTS_URL, timeout=httpx.Timeout(60.0, connect=8.0), follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
    rows = build(text)
    write(rows)
    print(f"wrote {len(rows)} airports to {PINNED_CSV}")


if __name__ == "__main__":
    main(sys.argv[1:])
