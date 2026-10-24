"""Small, reproducible judge worlds on real weather; no language-model calls."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from contracts.models import MetarObs, World
from world import metar, network
from world.airports import airport, distance_km
from world.days import WorldDay, split_of
from world.desk_cases import plant_vouchers, prepare_flights
from world.errors import WorldError
from world.generator import STORM_NAMES, DaySim, assemble, populate_pax


def generate_day(icao: str, local_day: date, seed: int = 0) -> World:
    target = airport(icao)
    if local_day > datetime.now(ZoneInfo(target.tz)).date():
        raise WorldError("future_date", f"{local_day.isoformat()} is in the future; choose a past day.")
    cache: dict[tuple[str, date], list[MetarObs]] = {}

    def load(station: str, day: date) -> list[MetarObs]:
        key = (station, day)
        if key not in cache:
            pinned = metar.pinned_day(station, day)
            if pinned is not None:
                cache[key] = pinned
            elif day == local_day and station in {target.icao, network.HUB_ICAO}:
                cache[key] = metar.fetch_day(station, day)
            else:
                cache[key] = []
        return cache[key]

    observations = load(target.icao, local_day)
    if not observations:
        raise WorldError("no_metar", f"No weather observations for {target.icao} on {local_day.isoformat()}.")
    hub_obs = load(network.HUB_ICAO, local_day)
    pairs = network.PAIRS if target.icao == network.HUB_ICAO else [
        p for p in network.PAIRS if p.dest == target.iata
    ]
    if not pairs:
        km = distance_km(network.HUB, target.iata)
        block = max(45, round((km / 14 + 40) / 5) * 5)
        tail = "EI-NWA" if km > network.A20N.range_km else "EI-NSC"
        pairs = [network.Pair("NS900", "NS901", target.iata, time(8), block, 45, block, tail)]
    # A non-EU-origin negative control is required even when the requested route is intra-EU.
    if target.eu and target.icao != network.HUB_ICAO:
        used = {p.tail for p in pairs}
        tail = next(t for t in network.FLEET if t not in used and t not in network.SPARES)
        pairs = [*pairs, replace(network.MORNING[0], out_number="NS980", ret_number="NS981", tail=tail)]
    kind = "storm" if any(metar.storm_conditions(o) for o in observations + hub_obs) else "background"
    day = WorldDay(local_day, kind, split_of(local_day), None)
    output = DaySim(day, seed, pairs=pairs, loader=load, storm_name=STORM_NAMES.get(local_day.isoformat(), "")).run()
    prepare_flights(output, seed)
    populate_pax(output, seed)
    plant_vouchers(output)
    return assemble([output], seed, extra_meta={
        "judge_station": target.icao,
        "judge_local_day": local_day.isoformat(),
        "real_vs_simulated": {
            "real": ["pinned or retrieved METAR", "airport coordinates and timezones"],
            "simulated": ["Northstar schedules", "operational logs", "passengers", "claims"],
        },
    })
