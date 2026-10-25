"""Clock marks, and scenarios: a World slice that joins the demo when the clock reaches its mark.

The Iberian blackout (28 Apr 2025, BLACKOUT_SPEC): when the clock reaches 2025-04-29T06:00Z (the morning after, like
Éowyn's 06:00Z run) `world.events.blackout_world()` is merged into the runtime's world and its days are run like the
Herminia storm run (`Runtime.run_and_store`): decisions, entitlements and questions on the trace and in the normal
Questions queue, Books drafts its own cohort (care accrual included), and replay sees the merged world.

- **Which runs:** the slice's `meta.storms` when it lists them, else its hub METAR day(s) with cancellations
  (`compose.storm_days`), else one run per event day at the hub. One hub run asks Legal one question for the event.
- **Event windows:** each run carries the event's id (`StormRun.event_id`) and its outage windows (`kind
  "grid_outage"`, labelled) for the airports its flights touch, beside any METAR storm window. They are display only:
  the engine reads the event from the world when it decides.
- The server never decides here: the engine decides, Books prices, the merge only adds records.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from contracts.models import ClockMark, StormRun, StormWindow, World

from . import compose


@dataclass(frozen=True)
class Scenario:
    id: str                       # the event id, "EVT-IBERIA-BLACKOUT@2025-04-28"
    label: str                    # the clock mark's label
    note: str
    at: datetime                  # the clock mark: reaching it runs the scenario once
    loader: tuple[str, str]       # (module, function) returning the World slice


BLACKOUT = Scenario(id="EVT-IBERIA-BLACKOUT@2025-04-28", label="Iberian blackout · 28 Apr 2025",
                    note="A power cut, not a storm: asks Legal once", at=datetime(2025, 4, 29, 6, 0, tzinfo=UTC),
                    loader=("world.events", "blackout_world"))
SCENARIOS: tuple[Scenario, ...] = (BLACKOUT,)

# the golden demo's moments (Justin #2); the storm runs' own marks come from `meta.storms[].known_at`
GOLDEN_MARKS: tuple[tuple[str, str, str], ...] = (
    ("2025-01-24T05:12:00Z", "OCC cancel list", "All 27 coded weather"),
    ("2025-01-25T09:00:00Z", "The morning after", "Storm run done"),
    ("2025-01-31T23:59:00Z", "January close", "6 claims approved"),
    ("2025-02-28T23:59:00Z", "February month-end", "Bornhuetter-Ferguson true-up"),
)
STORM_MARKS = {"EIDW@2025-01-26": ("Storm Herminia", "Same ruling, next storm")}


def marks(world: World | None, run_at: Any) -> list[ClockMark]:
    """Every named moment of the golden demo, in time order: the fixed ones, each later storm run (`run_at(world,
    station, day)`, so the mark is when the run happens) and each scenario. Other worlds have none."""
    if world is None or not world.meta.get("golden_version"):
        return []
    out = [ClockMark(at=datetime.fromisoformat(at.replace("Z", "+00:00")), label=label, note=note)
           for at, label, note in GOLDEN_MARKS]
    for sid, (label, note) in STORM_MARKS.items():
        info = compose.storm_meta(world, sid)
        if info:
            station, day = sid.split("@", 1)
            out.append(ClockMark(at=run_at(world, station, date.fromisoformat(day)), label=label, note=note))
    out += [ClockMark(at=s.at, label=s.label, note=s.note) for s in SCENARIOS]
    return sorted(out, key=lambda m: m.at)


def _key(x: Any) -> tuple[str, Any]:
    for attr in ("id", "icao", "coupon_id", "ruling_id", "cohort"):
        v = getattr(x, attr, None)
        if v is not None:
            return attr, v
    return "json", x.model_dump_json()


def merge_worlds(base: World, part: World) -> World:
    """`base` plus every record of `part` it does not already hold (lists by id, dicts by key; `meta.storms` and
    `real_context` merged). Nothing in `base` is changed, so every earlier decision replays the same."""
    update: dict[str, Any] = {}
    for name in type(base).model_fields:
        a, b = getattr(base, name), getattr(part, name)
        if isinstance(a, list):
            seen = {_key(x) for x in a}
            update[name] = a + [x for x in b if _key(x) not in seen]
        elif isinstance(a, dict) and name != "meta":
            update[name] = {**{k: v for k, v in b.items() if k not in a}, **a}
    storms = {**(part.meta.get("storms") or {}), **(base.meta.get("storms") or {})}
    update["meta"] = {**{k: v for k, v in part.meta.items() if k not in base.meta}, **base.meta, "storms": storms}
    return base.model_copy(update=update)


def runs(part: World, hub: str, run_id: str | None = None) -> list[tuple[str, date]]:
    """The station-days to run for a slice: the loader's own `RUN_ID` when its module names one (the blackout runs
    Dublin's day; its `meta.storms` also lists each Iberian station's day, for the Desk), else its listed storms,
    its hub METAR days with cancellations, else each event's day at the hub."""
    if run_id and "@" in run_id:
        station, day = run_id.split("@", 1)
        return [(station, date.fromisoformat(day[:10]))]
    listed = compose.storm_days(part, hub)
    if listed:
        return listed
    days = sorted({date.fromisoformat(e.id.rsplit("@", 1)[1][:10]) for e in getattr(part, "events", [])
                   if "@" in e.id})
    return [(hub, d) for d in days]


def event_of(part: World) -> Any:
    events = list(getattr(part, "events", None) or [])
    return events[0] if events else None


def event_windows(event: Any, codes: set[str], world: World) -> list[StormWindow]:
    """The event's outage window at each airport `codes` names (IATA or ICAO), as display windows."""
    out = []
    for w in event.airports:
        ap = compose.airport_by(world, w.icao)
        if w.icao not in codes and not (ap and ap.iata in codes):
            continue
        label = f"Grid outage ({event.title})" + (" · approximate end" if w.note and "approx" in w.note else "")
        out.append(StormWindow(station=w.icao, start=w.start, end=w.end, peak_gust_kt=0, obs_count=0,
                               definition=f"{event.title}: {w.note}" if w.note else event.title,
                               kind=event.kind, label=label))
    return out


def decorate(run: StormRun, part: World, world: World) -> StormRun:
    """An event run carries its event id and the outage windows of the airports its flights touch."""
    event = event_of(part)
    if event is None:
        return run
    codes = {c for r in run.flights for c in (r.flight.origin, r.flight.dest)} | {run.station}
    have = {(w.station, w.start, w.end) for w in run.windows}
    extra = [w for w in event_windows(event, codes, world) if (w.station, w.start, w.end) not in have]
    windows = [*run.windows, *extra]
    message = run.message if not extra or run.windows else None
    return run.model_copy(update={"event_id": run.event_id or event.id, "windows": windows, "message": message,
                                  "name": run.name or event.title})
