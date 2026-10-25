"""D2 · Everything the cause logic may look at for one flight, gathered from the World as known at ``known_at``.

Bitemporal: METAR obs with ``valid > known_at``, tech/ops log lines with ``logged_at/at > known_at`` and CRM events
after ``known_at`` do not exist yet. Facts (Reader output, injections) can be overlaid with ``overlay_facts``.

Which AOG grounds a flight: one logged on its tail before the cancellation decision (the OCC cancel entry when there
is one, else STD) and not returned to service by STD (an RTS estimate at or before STD, a later RTS / MEL-deferral
entry, or the tail operating a flight in between). No fixed lookback: an aircraft still AOG is still AOG.

Trust tiers decide what an overlaid fact may become: only a tier-1 tech-log/MCC fact becomes a tech-log line; any
other AOG claim stays a claim (``FlightCase.aog_claims``, routed to Ops). The earliest-reroute verdict comes only
from tier ≤ 2 statements, best tier then latest. Overlaid lines carry their fact ids, source and tier
(``world.meta["_overlay"]``) so evidence and blame reach the fact itself.

A fact's source is looked up in the world, then among the documents registered outside it (``sources=`` or the
trace's registry while it replays, ``registered_sources``). A registered document's kind caps the tier it may
claim (``KIND_TIER``); a source found nowhere is tier 4 (fail closed).

External events (``World.events``, e.g. a grid outage) add their airport windows to the station (``StationView.events``)
once an operator notice (tier ≤ 2) is on file. The flight's positions against them are ``dep_event`` / ``arr_event``;
``event`` is the window it sits in (``event_in``) or closed less than 24 h before it (``after_event``).

Pure: no wall clock, no randomness.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from contracts.models import (
    Airport,
    EventAirportWindow,
    ExternalEvent,
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

OVERLAY = "_overlay"                   # world.meta key of an overlaid copy: provenance of the synthetic lines
REROUTE_MAX_TIER = 2                   # PSS/schedule or better: the earliest-reroute verdict is a fact about the offer
SPARES_MAX_TIER = 2
CLAIM_WINDOW = timedelta(hours=48)     # an unverified AOG claim counts only this close before the decision
FAIL_CLOSED_TIER = 4                   # a source the world doesn't know is treated as a passenger e-mail
LOG_TIER = {"mcc": 1, "spares": 2, "occ": 3}
# the best tier a document registered outside the world may claim, by kind (CONTRACTS Source.trust_tier); unlisted
# kinds fail closed. The curated base world keeps its own tiers.
KIND_TIER = {SourceKind.TECH_LOG: 1, SourceKind.MCC_LOG: 1, SourceKind.METAR: 1, SourceKind.SCHEDULE: 2,
             SourceKind.MANIFEST: 2, SourceKind.PSS: 2, SourceKind.BSP: 2, SourceKind.SPARES: 2,
             SourceKind.MANUFACTURER: 2, SourceKind.OCC_LOG: 3, SourceKind.CRM: 3, SourceKind.CLAIM: 4,
             SourceKind.EMAIL: 4, SourceKind.CHALLENGE: 4}
_REGISTERED: ContextVar[Mapping[str, Source] | None] = ContextVar("engine_registered_sources", default=None)
EVENT_MAX_TIER = 2                     # an external event counts only on an operator notice (tier 1-2), never hearsay
POST_EVENT = timedelta(hours=24)       # a flight this soon after an event window closed is judged "after the event"
EVENT_KIND_LABEL = {"grid_outage": "Grid outage"}
_CNL = re.compile(r"\bCNL\b|\bCANCEL", re.I)
_RTS = re.compile(r"\bRTS\b|\bRETURNED TO SERVICE\b|\bA/C S/S\b|\bRELEASED TO SERVICE\b", re.I)


@dataclass(frozen=True)
class Aog:
    entry: TechLogEntry
    cls: AtaClass
    inside_window: bool               # logged while a storm window was open at its station
    before_window: bool               # logged before the flight's storm window starts (or no storm at all)
    window: StormWindow | None        # the station window it relates to (inside, or the next one after it)
    station: str | None = None        # ICAO of the station it was logged at

    @property
    def decisive(self) -> bool:
        """No-go: AOG without MEL relief (None = not stated; an AOG is no-go unless relief is logged)."""
        return self.entry.aog and self.entry.mel_relief is not True


@dataclass(frozen=True)
class AogClaim:
    """An AOG asserted by a source below tier 1 (or not from a tech log / MCC): evidence for Ops, never a cause."""
    aircraft: str
    logged_at: datetime
    source_id: str
    tier: int
    facts: dict[str, str]             # field -> fact id
    text: str


@dataclass(frozen=True)
class EventWindow:
    """One airport window of an external event (a grid outage), as a ``StormWindow`` of that kind."""
    window: StormWindow
    event: ExternalEvent
    airport: EventAirportWindow

    @property
    def approximate(self) -> bool:
        return (self.airport.note or "").strip().lower().startswith("approx")


@dataclass
class StationView:
    icao: str
    obs: list[MetarObs]
    windows: list[StormWindow]                                # METAR storm windows
    events: list[EventWindow] = field(default_factory=list)   # external-event windows at this station

    @property
    def event_windows(self) -> list[StormWindow]:
        return [e.window for e in self.events]

    def event_at(self, t: datetime) -> EventWindow | None:
        return next((e for e in self.events if e.window.start <= t <= e.window.end), None)


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
    window: StormWindow | None = None   # the storm window the flight relates to (in it, or nearest)
    aog_claims: list[AogClaim] = field(default_factory=list)
    overlay: dict[str, Any] = field(default_factory=dict)   # provenance of overlaid lines (see OVERLAY)
    decided_at: datetime | None = None  # when the flight was cancelled: OCC cancel entry, else STD
    # external events (blackout v1): positions against the event windows at each end, and the event the flight sits
    # in (``event_in``) or was cancelled soon after (``after_event``)
    dep_event: EndPosition | None = None
    arr_event: EndPosition | None = None
    event: EventWindow | None = None
    event_in: bool = False
    after_event: bool = False
    occ_lines: list[OpsLogEntry] = field(default_factory=list)

    @property
    def ops_code(self) -> str | None:
        return self.flight.ops_cause_code or (self.occ.code if self.occ else None)

    @property
    def positions(self) -> tuple[str, str]:
        return self.dep.position, self.arr.position

    def any_position(self, end: str) -> str:
        """``in`` if that end sits in a storm or an event window, else its storm-window position (the decision's
        ``in_window_*``)."""
        weather, event = (self.dep, self.dep_event) if end == "dep" else (self.arr, self.arr_event)
        return "in" if event is not None and event.position == "in" else weather.position


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


def event_label(event: ExternalEvent) -> str:
    """'Grid outage (Iberian Peninsula blackout)'."""
    kind = EVENT_KIND_LABEL.get(event.kind, event.kind.replace("_", " ").capitalize())
    return f"{kind} ({event.title})"


def event_known(world: World, event: ExternalEvent, known_at: datetime | None) -> bool:
    """An event counts once an operator notice (a source of tier ≤ 2 in the world) was received by ``known_at``.
    Hearsay (a passenger saying the power went out) or an event with no notice on file never opens a window."""
    srcs = {s.id: s for s in world.sources}
    return any((s := srcs.get(sid)) is not None and s.trust_tier <= EVENT_MAX_TIER
               and (known_at is None or s.received_at <= known_at) for sid in event.source_ids)


def event_windows(world: World, icao: str, known_at: datetime | None) -> list[EventWindow]:
    """The airport windows of every known external event at ``icao``, sorted by start."""
    out = []
    for ev in world.events:
        if not event_known(world, ev, known_at):
            continue
        for a in ev.airports:
            if a.icao != icao:
                continue
            definition = f"{event_label(ev)} from the operator notice" + (f"; end {a.note}" if a.note else "")
            out.append(EventWindow(StormWindow(station=icao, start=a.start, end=a.end, peak_gust_kt=0,
                                               definition=definition, obs_count=0, kind=ev.kind,
                                               label=event_label(ev)), ev, a))
    return sorted(out, key=lambda e: (e.window.start, e.event.id))


class _StationCache:
    def __init__(self, world: World, known_at: datetime | None):
        self.world, self.known_at = world, known_at
        self._c: dict[str, StationView] = {}

    def get(self, icao: str) -> StationView:
        if icao not in self._c:
            obs = station_obs(self.world, icao, self.known_at)
            self._c[icao] = StationView(icao, obs, storm_windows(obs), event_windows(self.world, icao, self.known_at))
        return self._c[icao]


# ---------- logs ----------

def decision_time(world: World, flight: Flight, known_at: datetime) -> datetime:
    """When the flight was cancelled: the earliest OCC cancel entry naming it (as known at ``known_at``), else STD.
    Nothing logged after that moment can have caused the cancellation."""
    cnl = [e.at for e in world.ops_log if e.kind == "occ" and flight.id in e.flight_ids and e.at <= known_at
           and (e.code or _CNL.search(e.text))]
    return min([*cnl, flight.sched_dep])


def returned_to_service(world: World, aircraft: str, logged_at: datetime, rts_est: datetime | None, ata: str,
                        by: datetime, known_at: datetime) -> bool:
    """Back in service by ``by``: its RTS estimate, a later RTS / MEL-deferral line for the same ATA chapter, or the
    tail operating a flight in between (all as known at ``known_at``)."""
    if rts_est is not None and rts_est <= by:
        return True
    for u in world.tech_log:
        if (u.aircraft == aircraft and logged_at < u.logged_at <= min(by, known_at) and not u.aog
                and (_RTS.search(u.text) or (u.mel_relief is True and ata and u.ata[:2] == ata[:2]))):
            return True
    return any(f.aircraft == aircraft and f.status in ("operated", "delayed") and logged_at < f.sched_dep < by
               and f.sched_dep <= known_at for f in world.flights)


def _icao(world: World, station: str | None) -> str | None:
    if not station:
        return None
    try:
        return airport(world, station).icao
    except UnknownAirport:
        return station


def _aog_for(world: World, flight: Flight, known_at: datetime, stations: _StationCache,
             relevant: StormWindow | None, decided: datetime) -> Aog | None:
    """The tech-log AOG that grounds this flight, if any. ``relevant`` = the storm window the flight relates to."""
    cut = min(decided, known_at)
    cands = [t for t in world.tech_log
             if t.aircraft == flight.aircraft and t.aog and t.logged_at <= cut
             and not returned_to_service(world, t.aircraft, t.logged_at, t.rts_est, t.ata, flight.sched_dep, known_at)]
    if not cands:
        return None
    # a no-go entry wins over one with MEL relief; then the latest
    t = sorted(cands, key=lambda t: (t.mel_relief is not True, t.logged_at, t.id))[-1]
    icao = _icao(world, t.station) or t.station
    inside = window_at(t.logged_at, stations.get(icao).windows)
    if inside is None and relevant is not None and relevant.start <= t.logged_at <= relevant.end:
        inside = relevant
    before = inside is None and (relevant is None or t.logged_at < relevant.start)
    return Aog(entry=t, cls=classify(t.ata, t.text), inside_window=inside is not None, before_window=before,
               window=inside or relevant, station=icao)


def _aog_claims(world: World, flight: Flight, known_at: datetime, decided: datetime,
                overlay: Mapping[str, Any]) -> list[AogClaim]:
    cut = min(decided, known_at)
    out = []
    for c in overlay.get("aog_claims", []):
        at = c["logged_at"]
        if (c["aircraft"] == flight.aircraft and cut - CLAIM_WINDOW <= at <= cut
                and not returned_to_service(world, flight.aircraft, at, c.get("rts_est"), c.get("ata") or "",
                                            flight.sched_dep, known_at)):
            out.append(AogClaim(c["aircraft"], at, c["source_id"], c["tier"], dict(c["facts"]), c["text"]))
    return sorted(out, key=lambda c: (c.logged_at, c.source_id))


def relevant_window(dep: EndPosition, arr: EndPosition, dep_st: StationView,
                    arr_st: StationView) -> StormWindow | None:
    """The window a flight relates to: one it sits in at either end, else the nearest to either end."""
    best: tuple[float, StormWindow] | None = None
    for end, st in ((dep, dep_st), (arr, arr_st)):
        for w in st.windows:
            if w.start <= end.at <= w.end:
                return w
            d = min(abs((w.start - end.at).total_seconds()), abs((end.at - w.end).total_seconds()))
            if best is None or d < best[0]:
                best = (d, w)
    return best[1] if best else None


_STD_PLUS = re.compile(r"STD\s*\+\s*(\d+)\s*h\s*(\d{1,2})?", re.I)
_WITHIN = re.compile(r"(?:spare|tail|aircraft)[^.]*?(?:available|within)\s*(\d+(?:\.\d+)?)\s*h", re.I)
_EARLIEST = re.compile(r"earliest\s+(?:re-?route|reroute|rerouting)", re.I)
# only an explicit "not offered" / "no reroute": a stray "no" ("no hotel needed; earliest reroute offered") is not one
_NOT_OFFERED = re.compile(r"\b(?:not|never)\s+(?:been\s+|yet\s+)?(?:offered|proposed)\b|"
                          r"\bno\s+(?:earliest\s+)?re-?rout(?:e|ing)\b|\bre-?route\s+not\s+offered\b", re.I)


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


def log_tier(world: World, entry: OpsLogEntry) -> int:
    """An ops-log line's trust tier: its own source's tier, an overlaid fact's tier, else by kind (MCC 1, spares 2,
    OCC 3); unknown kinds fail closed."""
    prov = (world.meta.get(OVERLAY) or {}).get("ops", {}).get(entry.id)
    if prov is not None:
        return int(prov["tier"])
    src = next((s for s in world.sources if s.id == f"SRC-{entry.id}"), None)
    return src.trust_tier if src is not None else LOG_TIER.get(entry.kind, FAIL_CLOSED_TIER)


def reroute_statements(world: World, flight: Flight, known_at: datetime
                       ) -> list[tuple[int, datetime, str, bool, bool]]:
    """(tier, at, where, offered?, from OCC?) for every line that states whether the earliest reroute was offered."""
    num = re.compile(rf"\b{re.escape(flight.number)}\b")
    ops_prov = (world.meta.get(OVERLAY) or {}).get("ops", {})
    out = []
    for e in world.ops_log:
        if flight.id in e.flight_ids and e.at <= known_at:
            # a genuine OCC / IROPS-desk line, or an overlaid fact read from an OCC-log source
            occ = (e.kind == "occ" and e.id not in ops_prov) or bool(ops_prov.get(e.id, {}).get("occ"))
            for ln in e.text.splitlines():
                if _EARLIEST.search(ln):
                    out.append((log_tier(world, e), e.at, e.id, not _NOT_OFFERED.search(ln), occ))
    for s in world.sources:
        if s.text and s.received_at <= known_at:
            for ln in s.text.splitlines():
                if num.search(ln) and _EARLIEST.search(ln):
                    out.append((s.trust_tier, s.received_at, s.id, not _NOT_OFFERED.search(ln),
                                s.kind == SourceKind.OCC_LOG))
    return out


def _reroute_offered(world: World, flight: Flight, known_at: datetime) -> bool | None:
    """Was the earliest reroute offered? Only the carrier's own records decide: tier ≤ 2 (PSS, schedule, spares) or
    the OCC log. A passenger, agency or CRM line saying so is a claim, not the offer. Best tier wins, then the
    latest, then the source id."""
    st = [x for x in reroute_statements(world, flight, known_at) if x[0] <= REROUTE_MAX_TIER or x[4]]
    if not st:
        return None
    best = min(st, key=lambda x: (x[0], -x[1].timestamp(), x[2]))
    return bool(best[3])


def _prev(world: World, flight: Flight) -> Flight | None:
    pid = flight.outbound_pair_id or flight.inbound_flight_id
    if pid is None:
        return None
    return next((f for f in world.flights if f.id == pid), None)


# ---------- facts overlay ----------

@contextmanager
def registered_sources(sources: Iterable[Source]) -> Iterator[None]:
    """Make documents registered outside the world (the trace's injected sources) known to ``overlay_facts`` inside
    the block. ``TraceStore`` binds its registry while a replay runs, so a ``decide_fn`` that overlays the trace's
    facts resolves their sources without having to name them."""
    token = _REGISTERED.set({**(_REGISTERED.get() or {}), **{s.id: s for s in sources}})
    try:
        yield
    finally:
        _REGISTERED.reset(token)


SourceIndex = Mapping[str, tuple[Source, int]]


def source_index(world: World, sources: Iterable[Source] = ()) -> dict[str, tuple[Source, int]]:
    """source id -> (source, trust tier). A registered document (bound by ``registered_sources``, or in ``sources``)
    may not claim a better tier than its kind allows; a world source of the same id wins, at its own tier."""
    out: dict[str, tuple[Source, int]] = {}
    for s in [*(_REGISTERED.get() or {}).values(), *sources]:
        out[s.id] = (s, max(int(s.trust_tier), KIND_TIER.get(s.kind, FAIL_CLOSED_TIER)))
    out.update({s.id: (s, s.trust_tier) for s in world.sources})
    return out


def _source_of(index: SourceIndex, fact: Fact) -> Source | None:
    hit = index.get(fact.source_id)
    return hit[0] if hit is not None else None


def _tier(index: SourceIndex, fact: Fact) -> int:
    hit = index.get(fact.source_id)
    return hit[1] if hit is not None else FAIL_CLOSED_TIER


def resolve_facts(world: World, facts: Iterable[Fact], known_at: datetime,
                  sources: Iterable[Source] = ()) -> dict[tuple[str, str], Fact]:
    """Per (subject, field): facts recorded by ``known_at``, best trust tier, then latest (plan §2 rule 7)."""
    index = source_index(world, sources)
    best: dict[tuple[str, str], tuple[tuple[int, float], Fact]] = {}
    for f in facts:
        if f.recorded_at > known_at:
            continue
        key = (f.subject, f.field)
        rank = (-_tier(index, f), f.recorded_at.timestamp())
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


def overlay_facts(world: World, facts: Sequence[Fact], known_at: datetime, sources: Iterable[Source] = ()) -> World:
    """Fold extracted facts into a copy of the world, so the cause logic has one input shape.

    Understood: ``flight:<id>`` · ``flight.ops_cause_code`` / ``spare.available_within_h`` /
    ``pax.reroute_earliest_offered`` / ``flight.notified_at``; ``aircraft:<tail>`` · ``aog.logged_at`` (+ optional
    ``aog.ata_chapter``, ``aog.mel_relief``, ``aog.station``, ``aog.defect_text``/``aog.text``, ``aog.rts_est``,
    ``aog.aog``). Anything else is evidence only.

    What a fact may become depends on its source's trust tier (``source_index``: the world's sources, then the
    documents registered in ``sources`` or by ``registered_sources``, capped by kind; a source found nowhere is
    tier 4):
    - ``aog.*`` from a tier-1 tech-log or MCC source becomes a tech-log line; from anything else it stays an AOG
      claim (``FlightCase.aog_claims``: Ops verifies it, it never grounds the flight).
    - spare hours from tier ≤ 2 become a spares line; a lower tier is evidence only.
    - a reroute verdict becomes a statement at the fact's own tier (only tier ≤ 2 statements decide).
    Every synthetic line carries its fact ids, source and tier in ``meta["_overlay"]`` so evidence cites the fact.

    Facts that only restate the base world (``contracts.normalize.world_to_facts`` output: the same tech-log line,
    the same spare hours, the same reroute verdict) change nothing, so replaying stored facts over the world is
    idempotent.
    """
    if not facts:
        return world
    sources = list(sources)
    resolved = resolve_facts(world, facts, known_at, sources)
    if not resolved:
        return world
    index = source_index(world, sources)
    w = world.model_copy(deep=True)
    prov: dict[str, Any] = {"techlog": {}, "ops": {}, "aog_claims": []}
    flights = {f.id: f for f in w.flights}
    by_subject: dict[str, dict[str, Fact]] = {}
    for (subj, fld), f in resolved.items():
        by_subject.setdefault(subj, {})[fld] = f
    for subj, fields in sorted(by_subject.items()):
        kind, _, ident = subj.partition(":")
        if kind == "flight" and ident in flights:
            fl = flights[ident]
            if "flight.ops_cause_code" in fields and fields["flight.ops_cause_code"].value is not None:
                fl.ops_cause_code = str(fields["flight.ops_cause_code"].value)
            if "flight.notified_at" in fields and _as_dt(fields["flight.notified_at"].value):
                fl.notified_at = _as_dt(fields["flight.notified_at"].value)
            if "spare.available_within_h" in fields:
                f = fields["spare.available_within_h"]
                known = [parse_spare_hours(e.text) for e in w.ops_log
                         if e.kind == "spares" and ident in e.flight_ids and e.at <= known_at]
                if (isinstance(f.value, int | float) and not isinstance(f.value, bool)
                        and _tier(index, f) <= SPARES_MAX_TIER
                        and float(f.value) not in [k for k in known if k is not None]):
                    eid = f"FACT-{f.id}"
                    w.ops_log.append(OpsLogEntry(id=eid, at=f.recorded_at, kind="spares", flight_ids=[ident],
                                                 text=f"spare available within {float(f.value)} h",
                                                 author=f.extractor))
                    prov["ops"][eid] = {"source_id": f.source_id, "tier": _tier(index, f),
                                        "facts": {"spare.available_within_h": f.id}}
            if "pax.reroute_earliest_offered" in fields:
                f = fields["pax.reroute_earliest_offered"]
                if isinstance(f.value, bool) and _reroute_offered(w, fl, known_at) != f.value:
                    eid = f"FACT-{f.id}"
                    txt = "earliest reroute offered" if f.value else "earliest reroute not offered"
                    w.ops_log.append(OpsLogEntry(id=eid, at=f.recorded_at, kind="occ", flight_ids=[ident],
                                                 text=txt, author=f.extractor))
                    src = _source_of(index, f)
                    prov["ops"][eid] = {"source_id": f.source_id, "tier": _tier(index, f),
                                        "facts": {"pax.reroute_earliest_offered": f.id},
                                        "occ": src is not None and src.kind == SourceKind.OCC_LOG}
                    w.meta = {**w.meta, OVERLAY: prov}           # the resolver must see this line's tier now
        elif kind == "aircraft" and "aog.logged_at" in fields:
            f = fields["aog.logged_at"]
            at = _as_dt(f.value)
            if at is None or any(t.aircraft == ident and t.logged_at == at for t in w.tech_log):
                continue
            val = {k: v.value for k, v in fields.items()}
            text = str(val.get("aog.defect_text") or val.get("aog.text") or f.span or "")
            src = _source_of(index, f)
            tier = _tier(index, f)
            fact_ids = {k: v.id for k, v in fields.items()}
            if src is None or tier != 1 or src.kind not in (SourceKind.TECH_LOG, SourceKind.MCC_LOG):
                prov["aog_claims"].append({"aircraft": ident, "logged_at": at, "source_id": f.source_id, "tier": tier,
                                           "facts": fact_ids, "text": text,
                                           "ata": str(val.get("aog.ata_chapter") or ""),
                                           "rts_est": _as_dt(val.get("aog.rts_est"))})
                continue
            eid = f"FACT-{f.id}"
            w.tech_log.append(TechLogEntry(                       # station "" = not stated (never assumed)
                id=eid, aircraft=ident, logged_at=at, station=str(val.get("aog.station") or ""),
                ata=str(val.get("aog.ata_chapter") or ""), text=text,
                mel_relief=val.get("aog.mel_relief") if isinstance(val.get("aog.mel_relief"), bool) else None,
                aog=bool(val.get("aog.aog", True)), rts_est=_as_dt(val.get("aog.rts_est"))))
            prov["techlog"][eid] = {"source_id": f.source_id, "tier": tier, "facts": fact_ids}
    if any(prov.values()):
        w.meta = {**w.meta, OVERLAY: prov}
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
    dep = departure_position(flight, dep_st.obs, dep_st.windows)
    arr = arrival_position(flight, arr_st.obs, arr_st.windows)
    relevant = relevant_window(dep, arr, dep_st, arr_st)
    decided = decision_time(world, flight, known_at)
    overlay = dict(world.meta.get(OVERLAY) or {})
    dep_ev = departure_position(flight, dep_st.obs, dep_st.event_windows)
    arr_ev = arrival_position(flight, arr_st.obs, arr_st.event_windows)
    event, event_in, after_event = _event_for(dep_ev, arr_ev, dep_st, arr_st)
    return FlightCase(
        flight=flight, origin=origin, dest=dest, dep_station=dep_st, arr_station=arr_st, dep=dep, arr=arr,
        aog=_aog_for(world, flight, known_at, stations, relevant, decided),
        occ=occ_coded[0] if occ_coded else None,
        mcc=_flight_log(world, flight, "mcc", known_at),
        spares=spares, spare_within_h=spare_h,
        reroute_earliest_offered=_reroute_offered(world, flight, known_at),
        prev=_prev(world, flight), known_at=known_at,
        sources={s.id: s for s in world.sources},
        window=relevant,
        aog_claims=_aog_claims(world, flight, known_at, decided, overlay),
        overlay=overlay, decided_at=decided,
        dep_event=dep_ev, arr_event=arr_ev, event=event, event_in=event_in, after_event=after_event, occ_lines=occ,
    )


def _event_for(dep: EndPosition, arr: EndPosition, dep_st: StationView, arr_st: StationView
               ) -> tuple[EventWindow | None, bool, bool]:
    """(event window, in it?, after it?): the window the flight sits in at either end, else the latest one that
    closed at its origin or destination less than ``POST_EVENT`` before that end's time."""
    for end, st in ((dep, dep_st), (arr, arr_st)):
        if end.position == "in":
            hit = st.event_at(end.at)
            if hit is not None:
                return hit, True, False
    closed = [(end.at - e.window.end, e) for end, st in ((dep, dep_st), (arr, arr_st)) for e in st.events
              if e.window.end <= end.at and end.at - e.window.end < POST_EVENT]
    if closed:
        return min(closed, key=lambda x: (x[0], x[1].event.id))[1], False, True
    return None, False, False


def stations_for(world: World, known_at: datetime | None) -> _StationCache:
    return _StationCache(world, known_at)


def find_source(case: FlightCase, kind: SourceKind, needle: str | None, fallback: str,
                on: datetime | None = None) -> tuple[str, int]:
    """(source id, trust tier) of the source of ``kind`` whose text contains ``needle``.

    With no needle, only sources named like ``fallback`` qualify (``SRC-METAR-EIDW`` matches
    ``SRC-METAR-EIDW@<day>``, never another station's file), and ``on`` picks the one that covers that moment:
    its text holds the ``YYYY-MM-DD HH:MM`` stamp, else its id carries the date, else its text mentions the date.
    """
    if needle:
        for s in case.sources.values():
            if s.kind == kind and s.text and needle in s.text:
                return s.id, s.trust_tier
    else:
        cands = [s for s in case.sources.values()
                 if s.kind == kind and (s.id == fallback or s.id.startswith(fallback + "@"))]
        if cands:
            def rank(s: Any) -> tuple[bool, bool, bool, str]:
                if on is None:
                    return (False, False, False, s.id)
                text = s.text or ""
                day = on.strftime("%Y-%m-%d")
                return (on.strftime("%Y-%m-%d %H:%M") not in text, not s.id.endswith("@" + day), day not in text,
                        s.id)
            best = min(cands, key=rank)
            return best.id, best.trust_tier
    return fallback, FAIL_CLOSED_TIER        # no source on file: the citation can't claim any tier above 4


def provenance(case: FlightCase, entry_id: str, field_: str, default_fact: str, default_src: tuple[str, int]
               ) -> tuple[str, str, int]:
    """(fact id, source id, tier) for one field of an overlaid line, else the defaults (a world record)."""
    p = (case.overlay.get("techlog", {}) or {}).get(entry_id) or (case.overlay.get("ops", {}) or {}).get(entry_id)
    if p is None:
        return default_fact, *default_src
    return p["facts"].get(field_, default_fact), p["source_id"], int(p["tier"])
