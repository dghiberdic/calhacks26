"""`POST /api/desk`: a judge names an airport and a local date; StormCheck runs that day on real METAR.

`WorldAPI.generate_day` (`world.generate_day`, else `FakeWorld.generate_day`) when one exists. Until then the server
adapts `world.generator.generate_world` to one day: the Northstar network day for that date (real EIDW METAR plus
each outstation's), from which the engine's `run_storm` takes the flights touching the named airport.

- Bad input is a 422 `{"error":{"code","message"}}` with a plain message: unknown ICAO (`unknown_airport`), a date
  after today (`future_date`), or a day with no METAR (`no_metar`). A `WorldError` maps to the same codes.
- A day with no storm returns a StormRun with `message="max gust 18 kt · no storm window"` (the engine's).
- A golden storm day (EIDW@2025-01-24 / 2025-01-26) returns the stored run, or runs the pending one in a scratch.
- Desk runs are priced in a **scratch Books** (in memory), so a judge's day never writes the demo ledger. Their
  decisions and entitlements are committed to the trace (blame works) and served at `/storms/{id}` and
  `/flights/{id}`; their questions live in the run only (they never enter the Questions queue).
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from contracts.models import StormRun, World

from . import compose
from .impls import _module, call

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger("stormcheck.server")
_CACHE: "OrderedDict[date, World]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
CACHE_DAYS = 8


class DeskError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def resolve_airport(icao: str) -> Any:
    code = (icao or "").strip().upper()
    airports = _module("world.airports")
    if airports is not None:
        try:
            return airports.airport(code)
        except Exception as exc:
            raise DeskError("unknown_airport", getattr(exc, "message", None) or
                            f"We don't know the airport '{icao}'. Use an ICAO code like EIDW or EGLL.") from exc
    a = compose._airport_from_table(code)
    if a is None:
        raise DeskError("unknown_airport", f"We don't know the airport '{icao}'. Use an ICAO code like EIDW or EGLL.")
    return a


def metar_source(icao: str, day: date) -> str:
    m = _module("world.metar")
    try:
        if m is not None and m.pinned_day(icao, day):
            return "pinned"
    except Exception:
        pass
    return "IEM" if (date.today() - day).days > 30 else "AWC"


def generate_day(rt: "Runtime", icao: str, day: date, seed: int = 0) -> World:
    """WorldAPI.generate_day, or the server's adapter over `world.generator.generate_world` for one day."""
    gen = rt.impls.generate_day
    if gen is not None:
        return call(gen, icao, day, seed=seed)
    with _CACHE_LOCK:
        if day in _CACHE:
            _CACHE.move_to_end(day)
            return _CACHE[day]
    generator = _module("world.generator")
    days = _module("world.days")
    if generator is None or days is None:
        raise DeskError("no_metar", "The world generator is not available on this server.")
    try:
        storm = day in set(days.storm_days())
        summary = days.eidw_summaries().get(day)
        wday = days.WorldDay(day, "storm" if storm else "background", days.split_of(day), summary)
        world = generator.generate_world(seed, [wday]).world
    except Exception as exc:
        err = rt.impls.world_error
        if err is not None and isinstance(exc, err):
            raise DeskError(exc.code, exc.message) from exc
        raise DeskError("no_metar", f"There is no usable weather for {day.isoformat()}: the METAR for that day "
                                    "could not be read.") from exc
    with _CACHE_LOCK:
        _CACHE[day] = world
        while len(_CACHE) > CACHE_DAYS:
            _CACHE.popitem(last=False)
    return world


def add_station_metar(world: World, icao: str, day: date) -> World:
    """Make sure the named station's own METAR for the day is in the world (the engine's windows come from it)."""
    if any(k.split("@", 1)[0] == icao for k in world.metar):
        return world
    m = _module("world.metar")
    if m is None:
        return world
    try:
        obs = m.fetch_day(icao, day)
    except Exception:
        return world
    if not obs:
        return world
    return world.model_copy(update={"metar": {**world.metar, f"{icao}@{day.isoformat()}": list(obs)}})


def run_desk(rt: "Runtime", icao_in: str, day: date) -> StormRun:
    ap = resolve_airport(icao_in)
    icao = ap.icao
    if day > date.today():
        raise DeskError("future_date", f"{day.isoformat()} hasn't happened yet, so there is no weather to read. "
                                       "Pick a past date.")
    run_id = f"{icao}@{day.isoformat()}"
    stored = rt.storm_run(run_id)
    if stored is not None:
        rt.emit("info", "judge", f"Desk opened {run_id} (already run)", "INFO", run_id)
        return stored
    golden = rt.world is not None and run_id in (rt.world.meta.get("storms") or {})
    world = rt.world if golden else generate_day(rt, icao, day)
    world = add_station_metar(world, icao, day)
    if not golden and not any(k.split("@", 1)[0] in (icao, "EIDW") for k in world.metar):
        raise DeskError("no_metar", f"No METAR observations for {icao} on {day.isoformat()}.")
    known_at = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1, hours=6)
    result = rt.run_and_store(world, icao, day, known_at, source="desk", curated=golden, desk=True)
    run = result.run.model_copy(update={"real_context": {**result.run.real_context,
                                                         "metar_source": metar_source(icao, day),
                                                         "generated": not golden, "desk": True}})
    rt.store.put("storm_run", run.id, run, rt.now)
    rt.emit("info", "judge", f"Desk ran {run_id} · {run.counters.get('cancelled', 0)} cancelled · "
            f"{run.message or str(len(run.windows)) + ' storm window(s)'}", "INFO", run_id)
    return rt.storm_run(run.id) or run
