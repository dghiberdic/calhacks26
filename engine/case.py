"""D2 · Everything the cause logic may look at for one flight, gathered from the World as known at ``known_at``.

Bitemporal: METAR obs with ``valid > known_at``, tech/ops log lines with ``logged_at/at > known_at`` and CRM events
after ``known_at`` do not exist yet. Facts (Reader output, injections) can be overlaid with ``overlay_facts``.

Pure: no wall clock, no randomness.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from contracts.models import (
    Airport,
    Fact,
    Flight,
    MetarObs,
    OpsLogEntry,
    Source,
    SourceKind,
    StormWindow,
    TechLogEntry,
    World,
)
from engine.ata_table import AtaClass, classify
from engine.geo import UnknownAirport, airport
from engine.timeline import EndPosition, arrival_position, departure_position, storm_windows, window_at

AOG_LOOKBACK = timedelta(hours=36)     # an AOG logged this long before STD can still ground the flight


@dataclass(frozen=True)
class Aog:
    entry: TechLogEntry
    cls: AtaClass
    inside_window: bool               # logged while a storm window was open at its station
    before_window: bool               # logged before any storm window that reaches the flight (or no storm at all)
    window: StormWindow | None        # the station window it relates to (inside, or the next one after it)

    @property
    def decisive(self) -> bool:
        """No-go: AOG without MEL relief (None = not stated; an AOG is no-go unless relief is logged)."""
        return self.entry.aog and self.entry.mel_relief is not True


@dataclass
class StationView:
    icao: str
    obs: list[MetarObs]
    windows: list[StormWindow]


@dataclass
class FlightCase:
    flight: Flight
    origin: Airport
    dest: Airport
    dep_station: StationView
    arr_station: StationView
    dep: EndPosition
    arr: EndPosition
    aog: Aog | None
    occ: OpsLogEntry | None
    mcc: list[OpsLogEntry]
    spares: list[OpsLogEntry]
    spare_within_h: float | None
    reroute_earliest_offered: bool | None
    prev: Flight | None                # previous rotation of the tail (outbound pair first)
    known_at: datetime
    sources: dict[str, Source] = field(default_factory=dict)

    @property
    def ops_code(self) -> str | None:
        return self.flight.ops_cause_code or (self.occ.code if self.occ else None)

    @property
    def positions(self) -> tuple[str, str]:
        return self.dep.position, self.arr.position


# ---------- METAR per station ----------

def station_obs(world: World, icao: str, known_at: datetime | None) -> list[MetarObs]:
    seen: dict[tuple[datetime, str], MetarObs] = {}
    for key, obs in world.metar.items():
        key_station = key.split("@", 1)[0]
        for o in obs:
            if o.station != icao and key_station != icao:
                continue
            if known_at is not None and o.valid > known_at:
                continue
            seen[(o.valid, o.raw)] = o
    return [seen[k] for k in sorted(seen)]


class _StationCache:
    def __init__(self, world: World, known_at: datetime | None):
        self.world, self.known_at = world, known_at
        self._c: dict[str, StationView] = {}

    def get(self, icao: str) -> StationView:
        if icao not in self._c:
            obs = station_obs(self.world, icao, self.known_at)
            self._c[icao] = StationView(icao, obs, storm_windows(obs))
        return self._c[icao]


# ---------- logs ----------

def _aog_for(world: World, flight: Flight, known_at: datetime, stations: _StationCache) -> Aog | None:
    cands = [t for t in world.tech_log
             if t.aircraft == flight.aircraft and t.aog and t.logged_at <= known_at
             and flight.sched_dep - AOG_LOOKBACK <= t.logged_at <= flight.sched_dep
             and (t.rts_est is None or t.rts_est > flight.sched_dep)]
    if not cands:
        return None
    # a no-go entry wins over one with MEL relief; then the latest
    t = sorted(cands, key=lambda t: (t.mel_relief is not True, t.logged_at, t.id))[-1]
    try:
        icao = airport(world, t.station).icao
    except UnknownAirport:
        icao = t.station
    wins = stations.get(icao).windows
    inside = window_at(t.logged_at, wins)
    reach = [w for w in wins if w.end >= t.logged_at and w.start <= flight.sched_arr]
    after_one = any(w.end < t.logged_at and w.end >= t.logged_at - AOG_LOOKBACK for w in wins)
    nxt = min(reach, key=lambda w: w.start) if reach else None
    return Aog(entry=t, cls=classify(t.ata, t.text), inside_window=inside is not None,
               before_window=inside is None and not after_one, window=inside or nxt)


_STD_PLUS = re.compile(r"STD\s*\+\s*(\d+)\s*h\s*(\d{1,2})?", re.I)
_WITHIN = re.compile(r"(?:spare|tail|aircraft)[^.]*?(?:available|within)\s*(\d+(?:\.\d+)?)\s*h", re.I)
_EARLIEST = re.compile(r"earliest\s+(?:re-?route|reroute|rerouting)", re.I)
_NOT_OFFERED = re.compile(r"\b(?:not|never|no)\b[^.]{0,30}\b(?:offered|reroute)", re.I)


def parse_spare_hours(text: str) -> float | None:
    """'Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20' -> 4.33 (hours after STD a tail could operate)."""
    m = _STD_PLUS.search(text)
    if m:
        return round(int(m.group(1)) + int(m.group(2) or 0) / 60, 2)
    m = _WITHIN.search(text)
    if m:
        return float(m.group(1))
    return None


def _flight_log(world: World, flight: Flight, kind: str, known_at: datetime) -> list[OpsLogEntry]:
    return sorted((e for e in world.ops_log if e.kind == kind and flight.id in e.flight_ids and e.at <= known_at),
                  key=lambda e: (e.at, e.id))


def _reroute_offered(world: World, flight: Flight, known_at: datetime) -> bool | None:
    """Was the earliest reroute offered? From the flight's own log lines, or source lines naming the flight."""
    num = re.compile(rf"\b{re.escape(flight.number)}\b")
    lines = [ln for e in world.ops_log if flight.id in e.flight_ids and e.at <= known_at for ln in e.text.splitlines()]
    lines += [ln for s in world.sources if s.text and s.received_at <= known_at
              for ln in s.text.splitlines() if num.search(ln)]
    verdict: bool | None = None
    for line in lines:
        if _EARLIEST.search(line):
            verdict = not bool(_NOT_OFFERED.search(line))
    return verdict


def _prev(world: World, flight: Flight) -> Flight | None:
    pid = flight.outbound_pair_id or flight.inbound_flight_id
    if pid is None:
        return None
    return next((f for f in world.flights if f.id == pid), None)


# ---------- facts overlay ----------

def _tier(world: World, fact: Fact) -> int:
    for s in world.sources:
        if s.id == fact.source_id:
            return s.trust_tier
    return 4


def resolve_facts(world: World, facts: Iterable[Fact], known_at: datetime) -> dict[tuple[str, str], Fact]:
    """Per (subject, field): facts recorded by ``known_at``, best trust tier, then latest (plan §2 rule 7)."""
    best: dict[tuple[str, str], tuple[tuple[int, float], Fact]] = {}
    for f in facts:
        if f.recorded_at > known_at:
            continue
        key = (f.subject, f.field)
        rank = (-_tier(world, f), f.recorded_at.timestamp())
        if key not in best or rank > best[key][0]:
            best[key] = (rank, f)
    return {k: v[1] for k, v in best.items()}


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def overlay_facts(world: World, facts: Sequence[Fact], known_at: datetime) -> World:
    """Fold extracted facts into a copy of the world, so the cause logic has one input shape.

    Understood: ``flight:<id>`` · ``flight.ops_cause_code`` / ``spare.available_within_h`` /
    ``pax.reroute_earliest_offered`` / ``flight.notified_at``; ``aircraft:<tail>`` · ``aog.logged_at`` (+ optional
    ``aog.ata_chapter``, ``aog.mel_relief``, ``aog.station``, ``aog.text``, ``aog.rts_est``) becomes a tech-log line.
    Anything else is evidence only.
    """
    if not facts:
        return world
    resolved = resolve_facts(world, facts, known_at)
    if not resolved:
        return world
    w = world.model_copy(deep=True)
    flights = {f.id: f for f in w.flights}
    by_subject: dict[str, dict[str, Fact]] = {}
    for (subj, fld), f in resolved.items():
        by_subject.setdefault(subj, {})[fld] = f
    for subj, fields in sorted(by_subject.items()):
        kind, _, ident = subj.partition(":")
        if kind == "flight" and ident in flights:
            fl = flights[ident]
            if "flight.ops_cause_code" in fields:
                fl.ops_cause_code = str(fields["flight.ops_cause_code"].value)
            if "flight.notified_at" in fields and _as_dt(fields["flight.notified_at"].value):
                fl.notified_at = _as_dt(fields["flight.notified_at"].value)
            if "spare.available_within_h" in fields:
                f = fields["spare.available_within_h"]
                w.ops_log.append(OpsLogEntry(id=f"FACT-{f.id}", at=f.recorded_at, kind="spares", flight_ids=[ident],
                                             text=f"spare available within {float(f.value)} h", author=f.extractor))
            if "pax.reroute_earliest_offered" in fields:
                f = fields["pax.reroute_earliest_offered"]
                txt = "earliest reroute offered" if f.value else "earliest reroute not offered"
                w.ops_log.append(OpsLogEntry(id=f"FACT-{f.id}", at=f.recorded_at, kind="occ", flight_ids=[ident],
                                             text=txt, author=f.extractor))
        elif kind == "aircraft" and "aog.logged_at" in fields:
            f = fields["aog.logged_at"]
            at = _as_dt(f.value)
            if at is None:
                continue
            val = {k: v.value for k, v in fields.items()}
            text = str(val.get("aog.text") or f.span or "")
            w.tech_log.append(TechLogEntry(
                id=f"FACT-{f.id}", aircraft=ident, logged_at=at, station=str(val.get("aog.station") or "DUB"),
                ata=str(val.get("aog.ata_chapter") or ""), text=text,
                mel_relief=val.get("aog.mel_relief") if isinstance(val.get("aog.mel_relief"), bool) else None,
                aog=bool(val.get("aog.aog", True)), rts_est=_as_dt(val.get("aog.rts_est"))))
    return w


# ---------- build ----------

def build_case(world: World, flight_id: str, known_at: datetime, stations: _StationCache | None = None) -> FlightCase:
    flight = next((f for f in world.flights if f.id == flight_id), None)
    if flight is None:
        raise KeyError(flight_id)
    stations = stations or _StationCache(world, known_at)
    origin, dest = airport(world, flight.origin), airport(world, flight.dest)
    dep_st, arr_st = stations.get(origin.icao), stations.get(dest.icao)
    spares = _flight_log(world, flight, "spares", known_at)
    spare_h = None
    for e in spares:
        h = parse_spare_hours(e.text)
        if h is not None:
            spare_h = h
    occ = _flight_log(world, flight, "occ", known_at)
    occ_coded = [e for e in occ if e.code] or occ
    return FlightCase(
        flight=flight, origin=origin, dest=dest, dep_station=dep_st, arr_station=arr_st,
        dep=departure_position(flight, dep_st.obs, dep_st.windows),
        arr=arrival_position(flight, arr_st.obs, arr_st.windows),
        aog=_aog_for(world, flight, known_at, stations),
        occ=occ_coded[0] if occ_coded else None,
        mcc=_flight_log(world, flight, "mcc", known_at),
        spares=spares, spare_within_h=spare_h,
        reroute_earliest_offered=_reroute_offered(world, flight, known_at),
        prev=_prev(world, flight), known_at=known_at,
        sources={s.id: s for s in world.sources},
    )


def stations_for(world: World, known_at: datetime | None) -> _StationCache:
    return _StationCache(world, known_at)


def find_source(case: FlightCase, kind: SourceKind, needle: str | None, fallback: str) -> tuple[str, int]:
    """(source id, trust tier) of the source of ``kind`` whose text contains ``needle``."""
    for s in case.sources.values():
        if s.kind == kind and s.text and needle and needle in s.text:
            return s.id, s.trust_tier
    for s in case.sources.values():
        if s.kind == kind and needle is None:
            return s.id, s.trust_tier
    default_tier = {SourceKind.TECH_LOG: 1, SourceKind.MCC_LOG: 1, SourceKind.METAR: 1, SourceKind.SPARES: 2,
                    SourceKind.SCHEDULE: 2, SourceKind.OCC_LOG: 3}.get(kind, 4)
    return fallback, default_tier
