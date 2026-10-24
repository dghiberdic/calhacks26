"""Public WorldAPI used by the server and the judge's desk."""
from __future__ import annotations

from pathlib import Path

from contracts.models import World
from world.airports import airport, distance_km
from world.generate import generate_day
from world.metar import fetch_metar


class WorldImpl:
    airport = staticmethod(airport)
    distance_km = staticmethod(distance_km)
    fetch_metar = staticmethod(fetch_metar)
    generate_day = staticmethod(generate_day)

    def load(self, path: str) -> World:
        return World.model_validate_json(Path(path).read_text(encoding="utf-8"))
