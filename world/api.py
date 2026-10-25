"""Public WorldAPI used by the server and the judge's desk."""
from __future__ import annotations

import gzip
import io
import os
from pathlib import Path

import orjson

from contracts.models import World
from world.airports import airport, distance_km
from world.events import blackout_world
from world.generate import generate_day
from world.metar import fetch_metar

GZIP_MAGIC = b"\x1f\x8b"


class WorldImpl:
    airport = staticmethod(airport)
    distance_km = staticmethod(distance_km)
    fetch_metar = staticmethod(fetch_metar)
    generate_day = staticmethod(generate_day)
    blackout_world = staticmethod(blackout_world)     # the Iberian blackout scenario (world.events)

    def load(self, path: str | os.PathLike[str]) -> World:
        """A World from `.json` or gzip-compressed `.json.gz` (detected by content, not by name)."""
        raw = Path(path).read_bytes()
        if raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
        return World.model_validate_json(raw)


def write_world(world: World, path: str | os.PathLike[str]) -> Path:
    """Write a World as canonical JSON (sorted keys), gzip-compressed when the name ends in `.gz`. The gzip header
    carries no name or mtime, so the same World always gives the same bytes."""
    p = Path(path)
    data = orjson.dumps(world.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    if p.suffix == ".gz":
        buf = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
            gz.write(data)
        data = buf.getvalue()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p
