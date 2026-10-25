"""The Iberian blackout scenario (28 April 2025): StormCheck's first extraordinary event that is not weather.

    from world.events import blackout_world, blackout_generated, answer_key
    w = blackout_world()          # World slice: World.events + Northstar DUB<->LIS/MAD/BCN + logs, pax, care, METAR

**The event** is pinned in `data/pinned/events/iberian_blackout_2025-04-28.json`: an `ExternalEvent`
(kind `grid_outage`) with one outage window per airport, and its `Source` texts (short verbatim quotes with URLs).
The primary source is ANA's same-day statement (28 Apr 12:55 Lisbon = 11:55Z, via Lusa: emergency generators on,
Lisbon operating with limitations), tier 1 and known before the run. ENTSO-E (9 May), Red Eléctrica and the IAA
(tier 1) and press reports of ANA, Aena and daa statements (tier 2) corroborate it, some only after the run.
Every window starts at ENTSO-E's 12:33 CEST (10:33Z). Every window end is an estimate and its note says so.

**The weather** is the real IEM METAR for LPPT, LEMD, LEBL (28-29 Apr, pinned) and EIDW: calm, so there is no storm
window anywhere. Whatever is extraordinary that day comes from the event.

**The flights** are Northstar's Dublin rotations to Lisbon, Madrid and Barcelona on 28 April: the network's morning
and afternoon waves plus one scenario-only midday rotation per city (NS170/171 LIS, NS172/173 BCN, NS174/175 MAD).
Outcomes are fixed by `PLAN` (deterministic; the seed only drives passengers, claims and care amounts):

- 8 cancellations inside the outage window (OCC RSN 87). Truth: extraordinary once Legal rules (no precedent).
- 2 cancellations after power had returned at Madrid (window end 16:00Z), for internal reasons written in the logs:
  NS128 (DUB 15:10Z, MAD 17:30Z): A/C EI-NSH out of position (night-stopped at MAD since NS111) while the DUB
  spare EI-NTB was serviceable and not assigned (OCC RSN 93 + spares log STD+0h00). NS129 (MAD 18:10Z): CREW OUT OF
  FDP, no reserve crew called (crew control, RSN 64). Truth: not extraordinary, compensation owed.
- 6 operated, including the afternoon Barcelona rotation after power came back ("everyone else flew").
- Care (hotel, meals, transport) for every cancelled flight's passengers, owed either way (`world.pax`).

The run is Dublin's day (`RUN_ID` = "EIDW@2025-04-28", every DUB<->LIS/MAD/BCN sector) as of `KNOWN_AT`
(2025-04-29T06:00Z, the morning after: the demo's clock mark). `meta.storms` also lists each Iberian station's day.
Under 2 s of CPU; nothing here touches the network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from contracts.models import ExternalEvent, OpsLogEntry, SourceKind, Source, World
from world import network as N
from world import texts as T
from world.airports import airport
from world.days import WorldDay, split_of
from world.generator import (
    DayOutput,
    DaySim,
    FlightTruth,
    Generated,
    Truth,
    assemble,
    populate_pax,
    rng_for,
    stamp,
)

ROOT = Path(__file__).resolve().parent.parent
EVENT_PATH = ROOT / "data" / "pinned" / "events" / "iberian_blackout_2025-04-28.json"
EVENT_ID = "EVT-IBERIA-BLACKOUT@2025-04-28"
DAY = date(2025, 4, 28)
STATIONS = ("LPPT", "LEMD", "LEBL")
RUN_ID = f"{N.HUB_ICAO}@{DAY.isoformat()}"
KNOWN_AT = datetime(2025, 4, 29, 6, 0, tzinfo=UTC)          # the morning after (demo clock mark, desk convention)
PRIMARY_SOURCE = "SRC-EVT-ANA-GENERATORS"                     # same-day operator statement, received before KNOWN_AT
NAME = "Iberian blackout · 28 Apr 2025"
VERSION = "blackout@1"
CHAPTER_LABEL = "Grid outage (Iberian blackout)"

# ---------------------------------------------------------------- the schedule

NETWORK_PAIRS = ("NS108", "NS110", "NS112", "NS128", "NS130")      # world.network morning + afternoon waves
# scenario-only midday rotations (numbers unused by the network), block times as the network's for the same city
EXTRA_PAIRS = (
    N.Pair("NS170", "NS171", "LIS", time(12, 30), 160, 60, 155, "EI-NSR", wave="midday"),
    N.Pair("NS172", "NS173", "BCN", time(12, 20), 145, 40, 145, "EI-NSS", wave="midday"),
    N.Pair("NS174", "NS175", "MAD", time(12, 40), 140, 40, 145, "EI-NST", wave="midday"),
)


@dataclass(frozen=True)
class Outcome:
    status: str                        # operated | cancelled
    latent: str = "none"               # external_event | aircraft_out_of_position | crew
    delay_min: int = 0                 # operated flights


OP = Outcome("operated")
EVT = Outcome("cancelled", "external_event")
PLAN: dict[str, Outcome] = {
    "NS108": Outcome("operated", delay_min=6), "NS109": Outcome("operated", delay_min=9),   # left BCN 10:15Z
    "NS110": Outcome("operated", delay_min=4), "NS111": EVT,
    "NS112": Outcome("operated", delay_min=14), "NS113": EVT,      # NS112 landed at LIS on backup power
    "NS170": EVT, "NS171": EVT, "NS172": EVT, "NS173": EVT, "NS174": EVT, "NS175": EVT,
    "NS128": Outcome("cancelled", "aircraft_out_of_position"),
    "NS129": Outcome("cancelled", "crew"),
    "NS130": Outcome("operated", delay_min=11), "NS131": Outcome("operated", delay_min=7),
}
EVENT_WINDOW_FLIGHTS = tuple(f"{n}@{DAY.isoformat()}" for n, o in PLAN.items() if o.latent == "external_event")
POST_RESTORATION_FLIGHTS = (f"NS128@{DAY.isoformat()}", f"NS129@{DAY.isoformat()}")

# OCC / crew-control / spares lines: (at, kind, flights, code, reason or text, author)
_REASON = {
    "LIS": "LIS: IBERIAN GRID OUTAGE FROM 1033Z, TERMINALS WITHOUT POWER, PAX ASKED TO LEAVE",
    "MAD": "MAD: IBERIAN GRID OUTAGE FROM 1033Z, AENA ON BACKUP POWER, TRAFFIC REDUCED",
    "BCN": "BCN: IBERIAN GRID OUTAGE FROM 1033Z, AENA ON BACKUP POWER, TRAFFIC REDUCED",
}


def _at(h: int, m: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=UTC)


LOGS: tuple[tuple[datetime, str, tuple[str, ...], str | None, str, str], ...] = (
    (_at(10, 41), "occ", ("NS111",), "87", _REASON["MAD"], "OCC duty manager"),
    (_at(10, 50), "occ", ("NS113", "NS170", "NS171"), "87", _REASON["LIS"], "OCC duty manager"),
    (_at(10, 58), "occ", ("NS172", "NS173"), "87", _REASON["BCN"], "OCC duty manager"),
    (_at(11, 5), "occ", ("NS174", "NS175"), "87", _REASON["MAD"], "OCC duty manager"),
    (_at(13, 30), "occ", ("NS128",), "93", "ROTATION: A/C EI-NSH OUT OF POSITION (AT MAD SINCE NS111 CNL)",
     "OCC duty manager"),
    (_at(13, 40), "spares", ("NS128",), None,
     "NS128: No tail at DUB (EI-NSH at MAD). Spare EI-NTB serviceable at DUB = STD+0h00, not assigned.",
     "OCC fleet desk"),
    (_at(16, 35), "occ", ("NS129",), "64",
     "CREW OUT OF FDP: A/C EI-NSH AT MAD SINCE NS110 (1020Z), NS110 CREW FDP ENDS 1900Z, NO RESERVE CREW CALLED",
     "Crew control"),
)


# ---------------------------------------------------------------- the pinned event

@lru_cache(maxsize=1)
def _event_doc() -> dict[str, Any]:
    return json.loads(EVENT_PATH.read_text(encoding="utf-8"))


def load_event() -> tuple[ExternalEvent, list[Source]]:
    """The pinned ExternalEvent and its Source texts (validated)."""
    doc = _event_doc()
    return ExternalEvent.model_validate(doc["event"]), [Source.model_validate(s) for s in doc["sources"]]


def event_window(icao: str) -> tuple[datetime, datetime] | None:
    ev, _ = load_event()
    w = next((w for w in ev.airports if w.icao == icao), None)
    return (w.start, w.end) if w else None


def is_event_day(icao: str, day: date) -> bool:
    """`generate_day(icao, day)` serves this scenario (LPPT, LEMD, LEBL on 28 April 2025)."""
    return day == DAY and icao in STATIONS


# ---------------------------------------------------------------- the simulation

def sectors() -> list[N.Sector]:
    pairs = [p for p in N.PAIRS if p.out_number in NETWORK_PAIRS] + list(EXTRA_PAIRS)
    return N.day_sectors(DAY, pairs)


class BlackoutSim(DaySim):
    """`DaySim` with the outcomes fixed by `PLAN` and the scenario's own OCC, crew-control and spares lines."""

    def run(self) -> DayOutput:
        secs = list(self.fixed_sectors or [])
        self.out.sectors = {s.id: s for s in secs}
        self.out.idx = self.load_metar(secs)
        day = self.day.isoformat()
        for s in secs:
            o = PLAN[s.number]
            r = rng_for(self.seed, "blackout", s.id)
            if o.status == "cancelled":
                self._flight(s, s.tail, "cancelled", r)
                self.out.truth[s.id] = _truth(s, o, day, self.w.split)
            else:
                self._flight(s, s.tail, "delayed" if o.delay_min >= 60 else "operated", r, delay_min=o.delay_min)
                self.out.truth[s.id] = FlightTruth(s.id, day, self.w.split, "operated", "none")
        self._link_rotations(secs, {})
        self._logs(secs)
        self.out.meta = {"date": day, "storm_id": RUN_ID, "kind": "event", "split": self.w.split,
                         "atc_strike": False, "flights": [s.id for s in secs],
                         "cancelled": sorted(f.id for f in self.out.flights if f.status == "cancelled"),
                         "event_id": EVENT_ID}
        self._metar_sources()
        return self.out

    def _logs(self, secs: list[N.Sector]) -> None:
        by_num = {s.number: s for s in secs}
        codes: dict[str, str] = {}
        notified: dict[str, datetime] = {}
        for at, kind, nums, code, text, author in LOGS:
            fids = sorted(by_num[n].id for n in nums)
            if kind == "occ":
                group = " ".join(_groups([by_num[n] for n in nums]))
                sms = at + timedelta(minutes=6)
                line = T.occ_single_line(at, group, code or "", text, sms)
                oid = f"OCC-{stamp(at)}-{nums[0]}"
                src_kind, tier, title = SourceKind.OCC_LOG, 3, f"{author} log {T.ddmon(at)} {T.hhmmz(at)}"
                for n in nums:
                    codes[by_num[n].id] = code or ""
                    notified[by_num[n].id] = min(sms, by_num[n].std)
            else:
                line = text
                oid = f"SPARES-{stamp(at)}-{nums[0]}"
                src_kind, tier, title = SourceKind.SPARES, 2, f"SPARES log {T.ddmon(at)} {T.hhmmz(at)} · {nums[0]}"
            self.out.ops_log.append(OpsLogEntry(id=oid, at=at, kind=kind, flight_ids=fids, code=code, text=line,  # type: ignore[arg-type]
                                                author=author))
            self._source(f"SRC-{oid}", src_kind, title, line + "\n", at + timedelta(minutes=1), tier, ["ops"])
        flights = []
        for f in self.out.flights:
            if f.id in codes:
                f = f.model_copy(update={"ops_cause_code": codes[f.id], "notified_at": notified[f.id]})
                self.out.truth[f.id].ops_code = codes[f.id]
            flights.append(f)
        self.out.flights = flights


def _groups(secs: list[N.Sector]) -> list[str]:
    """'NS170/171' for an outbound with its return, else the number (OCC convention)."""
    out, seen = [], set()
    for s in sorted(secs, key=lambda s: s.std):
        if s.number in seen:
            continue
        mate = next((x for x in secs if x.pair is s.pair and x.is_return != s.is_return), None)
        if mate is not None and not s.is_return:
            out.append(f"{s.number}/{mate.number[2:]}")
            seen.update({s.number, mate.number})
        else:
            out.append(s.number)
            seen.add(s.number)
    return out


def _truth(s: N.Sector, o: Outcome, day: str, split: str) -> FlightTruth:
    if o.latent == "external_event":
        icao = airport(s.dest if s.origin == N.HUB else s.origin).icao
        return FlightTruth(s.id, day, split, "cancelled", "external_event", cause="external_event",
                           extraordinary="extraordinary", expected_route="legal", planted=["event_window"],
                           note=f"scheduled inside the {icao} grid-outage window; extraordinary once Legal rules "
                                "(no precedent for a grid outage)")
    if o.latent == "aircraft_out_of_position":
        return FlightTruth(s.id, day, split, "cancelled", "aircraft_out_of_position", cause="knock_on",
                           extraordinary="not_extraordinary", root_flight_id=f"NS111@{day}",
                           root_latent="external_event", spare_within_3h=True, reroute_earliest_offered=False,
                           planted=["post_restoration_internal"],
                           note="scheduled after power returned at MAD; A/C EI-NSH out of position while the DUB spare "
                                "EI-NTB was serviceable and not assigned (OCC RSN 93, spares log): owed")
    return FlightTruth(s.id, day, split, "cancelled", "crew", cause="crew", extraordinary="not_extraordinary",
                       planted=["post_restoration_internal"],
                       note="scheduled after power returned at MAD; crew out of FDP and no reserve crew called "
                            "(crew control RSN 64): owed")


# ---------------------------------------------------------------- the world

def _station_meta(icao: str | None, flights: list[Any], metar_keys: list[str]) -> dict[str, Any]:
    codes = None if icao is None else {airport(icao).iata}
    fl = [f for f in flights if codes is None or f.origin in codes or f.dest in codes]
    cancelled = [f for f in fl if f.status == "cancelled"]
    station = icao or N.HUB_ICAO
    return {"name": NAME, "station": station, "local_date": DAY.isoformat(),
            "known_at": KNOWN_AT.strftime("%Y-%m-%dT%H:%M:%SZ"), "event_id": EVENT_ID, "kind": "grid_outage",
            "flight_ids": [f.id for f in fl], "cancelled": len(cancelled), "operated": len(fl) - len(cancelled),
            "passengers_cancelled": sum(f.pax for f in cancelled),
            "metar_keys": [k for k in metar_keys if icao is None or k.startswith(f"{icao}@")
                           or k.startswith(f"{N.HUB_ICAO}@")]}


@lru_cache(maxsize=4)
def _generated(seed: int) -> Generated:
    ev, ev_sources = load_event()
    wd = WorldDay(DAY, "event", split_of(DAY), None)
    out = BlackoutSim(wd, seed, sectors=sectors()).run()
    populate_pax(out, seed)
    flights = out.flights
    metar_keys = sorted(out.metar)
    storms = {RUN_ID: _station_meta(None, flights, metar_keys)}
    for icao in STATIONS:
        storms[f"{icao}@{DAY.isoformat()}"] = _station_meta(icao, flights, metar_keys)
    windows = {w.icao: {"start": w.start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": w.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "note": w.note} for w in ev.airports}
    extra = {
        "scenario": {"id": "blackout", "version": VERSION, "name": NAME, "event_id": EVENT_ID, "run_id": RUN_ID,
                     "station": N.HUB_ICAO, "local_date": DAY.isoformat(),
                     "known_at": KNOWN_AT.strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": list(STATIONS),
                     "window_label": CHAPTER_LABEL, "event_windows": windows,
                     "planted": {"event_window": list(EVENT_WINDOW_FLIGHTS),
                                 "post_restoration_internal": list(POST_RESTORATION_FLIGHTS)}},
        "storms": storms,
        "real_vs_simulated": {
            "real": ["ENTSO-E blackout onset 12:33 CEST and restoration timeline", "Red Eléctrica restoration notes",
                     "ANA, Aena, daa statements as reported", "IAA passenger advice",
                     "METAR (IEM, pinned: LPPT, LEMD, LEBL, EIDW)", "airport coordinates and timezones"],
            "approximate": [f"{w.icao} outage window end ({w.end.strftime('%H:%MZ')})" for w in ev.airports],
            "simulated": ["Northstar schedules (NS170-NS175 are scenario-only)", "operational logs", "passengers",
                          "claims", "care costs"],
        },
    }
    world = assemble([out], seed, extra_meta=extra)
    ctx = dict(_event_doc().get("real_context") or {})
    world = world.model_copy(update={
        "events": [ev],
        "sources": sorted([*world.sources, *ev_sources], key=lambda s: (s.received_at, s.id)),
        "real_context": {RUN_ID: {"event_name": "Iberian blackout", "event_id": EVENT_ID, **ctx}},
    })
    truth = Truth(flights=dict(out.truth), coupons=dict(out.pax.coupon_truth), claims=dict(out.pax.claim_truth),
                  planted={"blackout": {"event_window": len(EVENT_WINDOW_FLIGHTS),
                                        "post_restoration_internal": len(POST_RESTORATION_FLIGHTS)}})
    return Generated(world, truth)


def blackout_generated(seed: int = 0) -> Generated:
    """The scenario World and its ground truth (the scenario's answer key; never part of the World)."""
    g = _generated(seed)
    return Generated(g.world.model_copy(deep=True), g.truth)


def blackout_world(seed: int = 0) -> World:
    """The Iberian blackout World slice, loadable as a scenario run (`meta.scenario.run_id`, `KNOWN_AT`)."""
    return blackout_generated(seed).world


def desk_world(icao: str, seed: int = 0) -> Generated:
    """`generate_day(icao, 2025-04-28)` for LPPT, LEMD, LEBL: the scenario World with the judge's station marked."""
    g = blackout_generated(seed)
    sid = f"{icao}@{DAY.isoformat()}"
    st = g.world.meta["storms"][sid]
    desk = {"version": VERSION, "icao": icao, "iata": airport(icao).iata, "name": airport(icao).name,
            "local_day": DAY.isoformat(), "storm_id": sid, "hub_day": False, "kind": "event", "event_id": EVENT_ID,
            "context_flights": [f for f in g.world.meta["storms"][RUN_ID]["flight_ids"] if f not in st["flight_ids"]],
            "not_yet_landed": [], "metar": {k: "pinned" for k in (N.HUB_ICAO, *STATIONS)},
            "planted": g.world.meta["scenario"]["planted"], "counts": {"cancelled": st["cancelled"],
                                                                       "operated": st["operated"]}}
    meta = {**g.world.meta, "judge_station": icao, "judge_local_day": DAY.isoformat(), "desk": desk}
    return Generated(g.world.model_copy(update={"meta": meta}), g.truth)


def answer_key(seed: int = 0) -> dict[str, Any]:
    """Per-flight truth of the scenario (cause, extraordinary, owed coupons), from the generator, never the engine."""
    g = _generated(seed)
    flights = {}
    for fid, t in sorted(g.truth.flights.items()):
        row = t.to_json()
        coupons = [c for c in g.truth.coupons.values() if c["flight_id"] == fid]
        if coupons:
            row["coupons"] = len(coupons)
            row["owed"] = sum(1 for c in coupons if c["status"] == "owed")
            row["compensation_cents"] = sum(c["compensation_cents"] for c in coupons)
        flights[fid] = row
    care = [c for c in g.world.care if not c.invoiced]
    return {"version": VERSION, "event_id": EVENT_ID, "run_id": RUN_ID,
            "known_at": KNOWN_AT.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "flights": flights, "care_accrued_cents": sum(c.amount_cents for c in care),
            "planted": g.world.meta["scenario"]["planted"],
            "label": "ground truth from the scenario plan; never from the engine"}
