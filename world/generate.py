"""F3d · `generate_day(icao, local_day, seed)`: the judge's desk world. Real METAR, no LLM, under 2 s on pinned data.

**Which flights.** Northstar's flights between Dublin and the judge's airport, both directions, on the judge's
**local** calendar day at that airport: every sector whose airport-side time (STA there for an arrival, STD there for
a departure) falls inside that local day. This is the engine's own `storm_flights` rule, so a Boston local-evening
departure that leaves after 00:00Z belongs to the Boston day it leaves on. A short-haul outbound and its return
always travel together. EIDW (DUB) gives Dublin's whole world day, exactly as `generate_world` lays it out. An
airport outside the network gets a hypothetical Northstar rotation (`network.adhoc_pair`). Only flights that have
landed by now are included.

**Which weather.** Each station's METAR over every hour its sectors need (±4 h around its departures and arrivals),
at both ends, through `world.metar.fetch_metar` (pinned → IEM → AWC): one request per station, across UTC days. On
an EU airport's day the context station (BOS) is fetched too, but its absence is not an error. On the hub day,
outstations use pinned METAR only.

**Planted cases** (`world.desk_cases`): one OCC weather code the METAR contradicts (when the day allows it), 3
unsigned vouchers in lieu on EU departures and 1 on a non-EU departure. All of them are latent events re-simulated
through `DaySim`, so the evidence agrees.

**Errors:** `WorldError("unknown_airport" | "future_date" | "no_metar")` with a plain message (the server's 422).
`future_date` is judged in the airport's own timezone.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from contracts.models import Airport, MetarObs, World
from world import causes as C
from world import desk_cases as K
from world import events as E
from world import metar as M
from world import network as N
from world.airports import airport
from world.days import WorldDay, split_of
from world.errors import WorldError
from world.generator import (
    STORM_NAMES,
    DayOutput,
    DayPlan,
    DaySim,
    Generated,
    Truth,
    assemble,
    midnight,
    pinned_loader,
    populate_pax,
)

DESK_VERSION = "desk@2"
FETCH_PAD = timedelta(hours=4)       # METAR fetched around each station's movements
OBS_PAD = timedelta(hours=3)         # and kept in the world around them (DaySim's outstation convention)
STORM_HOURS = 2                      # distinct clock hours with storm conditions at one station → an OCC storm day
CONTEXT_PAIR = next(p for p in N.LONG_HAUL if p.dest == "BOS")


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_days(lo: datetime, hi: datetime) -> list[date]:
    d, out = lo.astimezone(UTC).date(), []
    while d <= hi.astimezone(UTC).date():
        out.append(d)
        d += timedelta(days=1)
    return out


def local_span(ap: Airport, day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of the airport's local calendar day."""
    tz = ZoneInfo(ap.tz)
    return (datetime.combine(day, datetime.min.time(), tz).astimezone(UTC),
            datetime.combine(day + timedelta(days=1), datetime.min.time(), tz).astimezone(UTC))


# ---------------------------------------------------------------- which sectors

def desk_sectors(ap: Airport, day: date) -> tuple[list[N.Sector], list[str]]:
    """(sectors, context flight ids) for the airport's local day. See the module docstring."""
    if ap.icao == N.HUB_ICAO:
        return N.day_sectors(day), []
    pairs = N.pair_for_dest(ap.iata) or [N.adhoc_pair(ap.iata)]
    lo, hi = local_span(ap, day)
    chosen: dict[str, N.Sector] = {}
    for k in (-1, 0, 1):
        secs = N.day_sectors(day + timedelta(days=k), pairs)
        for s in secs:
            t = s.sta if s.dest == ap.iata else s.std
            if lo <= t < hi:
                chosen[s.id] = s
        for s in secs:                       # short haul: an outbound and its return travel together
            if s.pair.long_haul or s.id in chosen:
                continue
            mate = next(x for x in secs if x.pair is s.pair and x.is_return != s.is_return)
            if mate.id in chosen:
                chosen[s.id] = s
    sectors = sorted(chosen.values(), key=lambda s: (s.std, s.number))
    context: list[str] = []
    if ap.eu and all(airport(s.origin).eu for s in sectors):
        # every sector departs the EU: add the BOS→DUB inbound landing in Dublin that day (golden's Herminia pattern)
        inbound = next(s for s in N.day_sectors(day, [CONTEXT_PAIR]) if s.is_return)
        sectors = sorted([*sectors, inbound], key=lambda s: (s.std, s.number))
        context.append(inbound.id)
    return sectors, context


def _span(sectors: Iterable[N.Sector], code: str, pad: timedelta) -> tuple[datetime, datetime]:
    times = [s.std for s in sectors if s.origin == code] + [s.sta for s in sectors if s.dest == code]
    return min(times) - pad, max(times) + pad


# ---------------------------------------------------------------- METAR

class DeskMetar:
    """Each needed station's METAR, fetched once over the span its sectors need; serves `DaySim` per UTC day."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.by_station: dict[str, dict[date, list[MetarObs]]] = {}
        self.spans: dict[str, tuple[datetime, datetime]] = {}
        self.provenance: dict[str, str] = {}

    def fetch(self, icao: str, lo: datetime, hi: datetime, *, required: bool, label: str) -> None:
        hi = min(hi, self.now)
        obs: list[MetarObs] = []
        if hi > lo:
            try:
                obs = M.fetch_metar(icao, lo, hi)
            except WorldError as exc:
                if exc.code != "no_metar":
                    raise
        if not obs:
            if required:
                raise WorldError("no_metar", f"No METAR reports for {label} ({icao}) between {lo:%Y-%m-%d %H:%MZ} "
                                             f"and {hi:%Y-%m-%d %H:%MZ}, so this day can't be run on real weather. "
                                             "Try another date.")
            self.provenance[icao] = "none"
            return
        days: dict[date, list[MetarObs]] = {}
        for o in obs:
            days.setdefault(o.valid.date(), []).append(o)
        self.by_station[icao] = days
        self.spans[icao] = (lo, hi)
        pinned = all(M.pinned_day(icao, d) is not None for d in _utc_days(lo, hi - timedelta(microseconds=1)))
        self.provenance[icao] = "pinned" if pinned else "retrieved"

    def __call__(self, icao: str, utc_day: date) -> list[MetarObs]:
        if icao in self.by_station:
            return list(self.by_station[icao].get(utc_day, []))
        return pinned_loader(icao, utc_day)      # hub-day outstations: pinned only, never the network

    def obs(self, icao: str) -> list[MetarObs]:
        return [o for d in sorted(self.by_station.get(icao, {})) for o in self.by_station[icao][d]]


class DeskSim(DaySim):
    """`DaySim` over a station's local day: METAR from `DeskMetar` around each station's own movements, and DUB
    standby spares of a blocked class unavailable all day (the planted fault, `world.desk_cases`)."""

    def __init__(self, *args: Any, hub_day: bool, blocked: frozenset[str] = frozenset(), **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.hub_day = hub_day
        self.blocked = blocked

    def load_metar(self, sectors: list[N.Sector]) -> dict[str, C.ObsIndex]:
        if self.hub_day:                     # Dublin's world day: exactly generate_world's windows
            return super().load_metar(sectors)
        idx: dict[str, C.ObsIndex] = {}
        for code in sorted({s.origin for s in sectors} | {s.dest for s in sectors}):
            lo, hi = _span(sectors, code, OBS_PAD)
            obs = [o for o in self._obs(code, _utc_days(lo, hi)) if lo <= o.valid <= hi]
            idx[code] = C.ObsIndex(obs)
            if obs:
                self.out.metar[f"{airport(code).icao}@{self.day.isoformat()}"] = idx[code].obs
        return idx

    def _free(self, spare_free: dict[str, datetime | None]) -> dict[str, datetime | None]:
        return {k: (None if k in self.blocked else v) for k, v in spare_free.items()} if self.blocked else spare_free

    def _spare(self, s: N.Sector, spare_free: dict[str, datetime | None], at: datetime) -> str | None:
        return super()._spare(s, self._free(spare_free), at)

    def _ferry(self, s: N.Sector, spare_free: dict[str, datetime | None],
               idx: dict[str, C.ObsIndex]) -> dict[str, Any]:
        return super()._ferry(s, self._free(spare_free), idx)


def _stormy(obs: Iterable[MetarObs]) -> bool:
    return len({o.valid.replace(minute=0, second=0, microsecond=0) for o in obs if M.storm_conditions(o)}) \
        >= STORM_HOURS


# ---------------------------------------------------------------- the desk day

def _known_at(day: date, sectors: Sequence[N.Sector]) -> datetime:
    """The morning after (06:00Z, golden's convention), or 30 min after the last landing if that is later."""
    last = max(s.sta for s in sectors) + timedelta(minutes=30)
    last = last.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if last.minute else timedelta())
    return max(midnight(day + timedelta(days=1)) + timedelta(hours=6), last)


def generate_day_full(icao: str, local_day: date, seed: int = 0, *, now: datetime | None = None) -> Generated:
    """The desk World and its ground truth (`Truth`, the answer key; never part of the World)."""
    ap = airport(icao)                                           # WorldError("unknown_airport")
    day = local_day.date() if isinstance(local_day, datetime) else local_day
    now = (now or datetime.now(UTC)).astimezone(UTC)
    local_today = now.astimezone(ZoneInfo(ap.tz)).date()
    if day > local_today:
        raise WorldError("future_date", f"{day.isoformat()} hasn't happened yet at {ap.name} ({ap.icao}); "
                                        f"it is {local_today.isoformat()} there. Choose a past day.")
    if E.is_event_day(ap.icao, day):
        # LPPT / LEMD / LEBL on 28 Apr 2025: the Iberian blackout scenario (World.events + its planted cases)
        return E.desk_world(ap.icao, seed)
    hub = ap.icao == N.HUB_ICAO
    sectors, context = desk_sectors(ap, day)
    pending = [s.id for s in sectors if s.sta > now]
    sectors = [s for s in sectors if s.sta <= now]
    context = [c for c in context if c not in pending]
    if not any(s.id not in context for s in sectors):
        raise WorldError("future_date", f"Northstar's {ap.iata} flights on {day.isoformat()} haven't landed yet. "
                                        "Choose an earlier day.")

    mt = DeskMetar(now)
    own = [s for s in sectors if s.id not in context]
    if not hub:
        lo, hi = _span(own, ap.iata, FETCH_PAD)
        mt.fetch(ap.icao, lo, hi, required=True, label=ap.name)
    lo, hi = _span(sectors, N.HUB, FETCH_PAD)
    if hub:
        lo, hi = min(lo, midnight(day) - timedelta(hours=6)), max(hi, midnight(day) + timedelta(hours=30))
    mt.fetch(N.HUB_ICAO, lo, hi, required=True, label="Dublin")
    by_id = {s.id: s for s in sectors}
    for cid in context:
        s = by_id[cid]
        lo, hi = _span([s], s.origin, FETCH_PAD)
        mt.fetch(airport(s.origin).icao, lo, hi, required=False, label=airport(s.origin).name)

    storm = _stormy(mt.obs(N.HUB_ICAO)) or (not hub and _stormy(mt.obs(ap.icao)))
    wd = WorldDay(day, "storm" if storm else "background", split_of(day), None)
    storm_name = STORM_NAMES.get(day.isoformat(), "") if storm else ""

    def sim(plan: DayPlan, blocked: frozenset[str]) -> DayOutput:
        return DeskSim(wd, seed, sectors=sectors, loader=mt, plan=plan, storm_name=storm_name, hub_day=hub,
                       blocked=blocked).run()

    sid = f"{ap.icao}@{day.isoformat()}"
    out, planted = K.plan_day(sim, sectors, context, seed=seed, key=sid, storm=storm, prefer_non_eu=hub)
    populate_pax(out, seed)
    K.plant_vouchers(out, seed, planted)
    out.meta.update({"storm_id": sid, "station": ap.icao, "desk": True})

    flight_ids = [f.id for f in out.flights]
    cancelled = [f for f in out.flights if f.status == "cancelled"]
    desk_meta = {
        "version": DESK_VERSION, "icao": ap.icao, "iata": ap.iata, "name": ap.name, "local_day": day.isoformat(),
        "storm_id": sid, "hub_day": hub, "kind": wd.kind, "context_flights": context, "not_yet_landed": pending,
        "metar": dict(sorted(mt.provenance.items())), "planted": planted,
        "counts": dict(sorted(Counter(f.status for f in out.flights).items())),
    }
    extra = {
        "judge_station": ap.icao,
        "judge_local_day": day.isoformat(),
        "desk": desk_meta,
        "storms": {sid: {"name": f"{storm_name or ap.name} · {day.isoformat()}", "station": ap.icao,
                         "local_date": day.isoformat(), "known_at": _iso(_known_at(day, sectors)),
                         "flight_ids": flight_ids, "cancelled": len(cancelled),
                         "operated": len(flight_ids) - len(cancelled),
                         "passengers_cancelled": sum(f.pax for f in cancelled), "metar_keys": sorted(out.metar)}},
        "real_vs_simulated": {
            "real": ["METAR (" + ", ".join(f"{k} {v}" for k, v in sorted(mt.provenance.items())) + ")",
                     "airport coordinates and timezones"],
            "simulated": ["Northstar schedules", "operational logs", "passengers", "claims",
                          "planted judge cases (meta.desk.planted)"],
        },
    }
    world = assemble([out], seed, extra_meta=extra)
    truth = Truth(flights=dict(out.truth), coupons=dict(out.pax.coupon_truth), claims=dict(out.pax.claim_truth),
                  planted={"desk": {"contradicted_weather_code": int(bool(planted["contradicted_weather_code"])),
                                    "in_lieu_unsigned_eu_departures": len(planted["in_lieu_unsigned_eu_departures"]),
                                    "in_lieu_unsigned_non_eu": len(planted["in_lieu_unsigned_non_eu"])}})
    return Generated(world, truth)


def generate_day(icao: str, local_day: date, seed: int = 0) -> World:
    """WorldAPI.generate_day: the judge's desk World for one airport and local day (see the module docstring)."""
    return generate_day_full(icao, local_day, seed).world
