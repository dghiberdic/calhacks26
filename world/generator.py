"""Northstar's world, generated deterministically by seed on real METAR (F3).

    from world.generator import generate_world
    g = generate_world(seed=0)          # g.world: contracts.models.World · g.truth: ground truth (answer key source)

Layout of a world day D (Dublin local): every DUB departure on D, its return, and the long-haul inbounds that land
in Dublin on D (`world.network.day_sectors`). Each sector's fate is drawn from latent causes (`world.causes`) with
an RNG keyed by (seed, flight id), so the same flight comes out the same in `generate_world` and `generate_day`.

Ground truth (`Truth`) is written from the latent draws here, never from the engine.
"""
from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from contracts.models import (
    Cause,
    Extraordinary,
    Flight,
    MetarObs,
    OpsLogEntry,
    Source,
    SourceKind,
    TechLogEntry,
    World,
)
from world import causes as C
from world import network as N
from world import texts as T
from world.airports import airport, distance_km
from world.days import WorldDay
from world.metar import pinned_day

GENERATOR_VERSION = "northstar-gen@1"
CARRIER = "Northstar Air"
WX_LATENT = ("weather_dep", "weather_arr")
EXTRAORDINARY_LATENT = frozenset({"weather_dep", "weather_arr", "external_hit", "atc"})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def rng_for(seed: int, *key: object) -> random.Random:
    return random.Random(":".join([str(seed), *map(str, key)]))


def midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), UTC)


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H%MZ")


# ---------------------------------------------------------------- truth

@dataclass
class FlightTruth:
    flight_id: str
    day: str                       # world day (Dublin local)
    split: str
    status: str                    # operated | delayed | cancelled
    latent: str                    # none | weather_dep | weather_arr | internal_aog | external_hit | crew | atc |
    #                                rotation | concurrent | notice
    cause: str | None = None       # contracts Cause value, cancelled flights only
    extraordinary: str | None = None
    root_flight_id: str | None = None
    root_latent: str | None = None
    ambiguous: bool = False
    planted: list[str] = field(default_factory=list)
    expected_route: str | None = None
    spare_within_3h: bool | None = None
    reroute_earliest_offered: bool | None = None
    ops_code: str | None = None
    note: str = ""
    golden: bool = False

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "", False) or k in ("status",)}


@dataclass
class Truth:
    flights: dict[str, FlightTruth] = field(default_factory=dict)
    coupons: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    planted: dict[str, dict[str, int]] = field(default_factory=dict)   # split -> type -> count


def truth_for(latent: str, root_latent: str | None = None, *, spare_within_3h: bool | None = None,
              reroute_earliest: bool | None = None) -> tuple[str, str, str | None]:
    """(cause, extraordinary, expected_route) for a cancellation, from its latent cause (the law as Northstar's
    Legal has ruled it: C-315/15 external hits, C-74/19 rotations per R-LEG-1)."""
    E, N_ = Extraordinary.YES.value, Extraordinary.NO.value
    if latent in WX_LATENT:
        return Cause.WEATHER.value, E, None
    if latent == "external_hit":
        return Cause.TECHNICAL.value, E, None
    if latent in ("internal_aog", "notice"):
        return Cause.TECHNICAL.value, N_, None
    if latent == "crew":
        return Cause.CREW.value, N_, None
    if latent == "atc":
        return Cause.ATC.value, E, None
    if latent == "concurrent":
        return Cause.CONCURRENT.value, N_, "legal"
    if latent == "rotation":
        if root_latent in EXTRAORDINARY_LATENT:
            ok = (spare_within_3h is False) and bool(reroute_earliest)
            return Cause.KNOCK_ON.value, E if ok else N_, "legal"
        return Cause.KNOCK_ON.value, N_, None
    return Cause.UNKNOWN.value, N_, None


# ---------------------------------------------------------------- METAR access

MetarLoader = Callable[[str, date], list[MetarObs]]


def pinned_loader(icao: str, utc_day: date) -> list[MetarObs]:
    return pinned_day(icao, utc_day) or []


# ---------------------------------------------------------------- one day

@dataclass
class Cancel:
    latent: str
    known_at: datetime
    root: str | None = None                  # flight id whose cancellation left this aircraft out of position
    defect_entry: str | None = None          # tech log id
    spare: dict[str, Any] | None = None      # spares-log facts for rotations / AOG at DUB


@dataclass
class Aog:
    until: datetime
    entry_id: str
    station: str
    logged_at: datetime
    latent: str                              # internal_aog | external_hit
    defect: T.Defect


@dataclass
class DayPlan:
    """Forced latent events used to plant the answer key's error cases (F3c). Empty = the natural day."""
    aog: dict[str, tuple[datetime, bool]] = field(default_factory=dict)   # tail -> (logged at DUB, recorded?)
    crew: set[str] = field(default_factory=set)            # flight ids cancelled for crew shortage
    wx: set[str] = field(default_factory=set)              # flight ids cancelled for weather (needs storm obs)
    batch: set[str] = field(default_factory=set)           # flight ids the storm-day OCC batch always lists (RSN 71)
    code: dict[str, str] = field(default_factory=dict)     # flight id -> OCC code typed
    notice: dict[str, int] = field(default_factory=dict)   # flight id -> days of advance notice (planned CNL)
    pax_mismatch: dict[str, int] = field(default_factory=dict)   # flight id -> pax typed by OCC (manifest wins)

    def __bool__(self) -> bool:
        return any((self.aog, self.crew, self.wx, self.batch, self.code, self.notice, self.pax_mismatch))


@dataclass
class DayOutput:
    flights: list[Flight] = field(default_factory=list)
    tech_log: list[TechLogEntry] = field(default_factory=list)
    ops_log: list[OpsLogEntry] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    metar: dict[str, list[MetarObs]] = field(default_factory=dict)
    truth: dict[str, FlightTruth] = field(default_factory=dict)
    sectors: dict[str, N.Sector] = field(default_factory=dict)
    cancels: dict[str, Cancel] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    pax: Any = None                      # world.pax.PaxOutput once populate_pax ran
    idx: dict[str, Any] = field(default_factory=dict)      # station -> causes.ObsIndex (not serialized)
    w_day: date | None = None


class DaySim:
    """Simulate one world day's ops: latent causes → flights, OCC/MCC/spares/tech logs, METAR, flight truth."""

    def __init__(self, wday: WorldDay, seed: int, *, pairs: list[N.Pair] | None = None,
                 loader: MetarLoader = pinned_loader, storm_name: str = "", plan: DayPlan | None = None) -> None:
        self.plan = plan or DayPlan()
        self.w = wday
        self.day = wday.day
        self.seed = seed
        self.pairs = pairs or N.PAIRS
        self.loader = loader
        self.storm = wday.kind == "storm"
        self.storm_name = storm_name
        self.out = DayOutput(w_day=wday.day)
        self.drng = rng_for(seed, "day", self.day.isoformat())

    # ---- METAR
    def _obs(self, code: str, utc_days: Iterable[date]) -> list[MetarObs]:
        icao = airport(code).icao
        out: list[MetarObs] = []
        for d in utc_days:
            out.extend(self.loader(icao, d))
        return out

    def load_metar(self, sectors: list[N.Sector]) -> dict[str, C.ObsIndex]:
        d = self.day
        idx: dict[str, C.ObsIndex] = {}
        hub_obs = [o for o in self._obs(N.HUB, (d - timedelta(days=1), d, d + timedelta(days=1)))
                   if midnight(d) - timedelta(hours=6) <= o.valid < midnight(d) + timedelta(hours=30)]
        idx[N.HUB] = C.ObsIndex(hub_obs)
        self.out.metar[f"{N.HUB_ICAO}@{d.isoformat()}"] = idx[N.HUB].obs
        for code in sorted({s.dest for s in sectors if s.dest != N.HUB} | {s.origin for s in sectors
                                                                              if s.origin != N.HUB}):
            times = [s.sta for s in sectors if s.dest == code] + [s.std for s in sectors if s.origin == code]
            lo, hi = min(times) - timedelta(hours=3), max(times) + timedelta(hours=3)
            obs = [o for o in self._obs(code, sorted({lo.date(), hi.date()})) if lo <= o.valid <= hi]
            idx[code] = C.ObsIndex(obs)
            if obs:
                self.out.metar[f"{airport(code).icao}@{d.isoformat()}"] = idx[code].obs
        return idx

    # ---- the simulation
    def run(self) -> DayOutput:
        d = self.day
        sectors = N.day_sectors(d, self.pairs)
        self.out.sectors = {s.id: s for s in sectors}
        idx = self.load_metar(sectors)
        self.out.idx = idx
        rot = N.tail_rotation(sectors)

        # day-level draws
        atc_strike = (not self.storm) and self.drng.random() < C.P_ATC_STRIKE_DAY
        spare_free: dict[str, datetime | None] = {}
        for sp in N.SPARES:
            r = rng_for(self.seed, "spare", sp, d.isoformat())
            p = C.P_SPARE_STORM if self.storm else C.P_SPARE_CALM
            spare_free[sp] = (midnight(d) + timedelta(hours=5, minutes=r.randrange(0, 600, 15))
                              if r.random() < p else None)

        # tail-level draws: internal AOG (night before at DUB, or after the k-th sector) and MEL noise
        aog: dict[str, Aog | None] = {t: None for t in rot}
        aog_after: dict[str, tuple[int, T.Defect]] = {}
        for tail, secs in rot.items():
            r = rng_for(self.seed, "tail", tail, d.isoformat())
            if r.random() < C.P_AOG_TAIL_DAY:
                defect = r.choice(T.AOG_DEFECTS)
                if secs[0].origin == N.HUB and r.random() < 0.5:
                    logged = midnight(d) - timedelta(hours=r.randint(1, 5), minutes=r.choice([0, 10, 20, 40, 50]))
                    aog[tail] = self._log_aog(tail, N.HUB, logged, defect, r, "internal_aog")
                else:
                    aog_after[tail] = (r.randrange(0, len(secs)), defect)
            if r.random() < C.P_MEL_TAIL_DAY:
                s0 = secs[0]
                logged = s0.std - timedelta(minutes=r.randint(50, 110))
                self._log_mel(tail, s0.origin, logged, r.choice(T.MEL_DEFECTS), r)
        for tail, (logged, recorded) in sorted(self.plan.aog.items()):
            if tail not in rot or aog.get(tail) is not None:
                continue
            r = rng_for(self.seed, "planted-aog", tail, d.isoformat())
            defect = r.choice(T.AOG_DEFECTS)
            aog_after.pop(tail, None)
            if recorded:
                aog[tail] = self._log_aog(tail, N.HUB, logged, defect, r, "internal_aog")
            else:   # the defect was never written up: invisible to every feature
                aog[tail] = Aog(until=logged + timedelta(hours=30), entry_id="", station=N.HUB, logged_at=logged,
                                latent="internal_aog", defect=defect)

        loc = {tail: secs[0].origin for tail, secs in rot.items()}
        avail = {tail: secs[0].std - timedelta(hours=2) for tail, secs in rot.items()}
        actual: dict[str, str] = {t: t for t in rot}
        for sp in N.SPARES:
            loc.setdefault(sp, N.HUB)
            avail.setdefault(sp, midnight(d))
            aog.setdefault(sp, None)
        last_cancel_at: dict[str, str] = {}   # tail -> id of the cancelled sector that left it out of position

        for s in sectors:
            r = rng_for(self.seed, "sector", s.id)
            u_wx, u_crew, u_atc, u_ext, u_delay, u_reroute = (r.random() for _ in range(6))
            tail = actual[s.tail]
            sev_dep = C.severity(idx.get(s.origin), s.std)
            sev_arr = C.severity(idx.get(s.dest), s.sta)
            p_wx = 1 - (1 - sev_dep) * (1 - sev_arr)
            wx = u_wx < p_wx or (s.id in self.plan.wx and max(sev_dep, sev_arr) > 0)
            wx_latent = "weather_dep" if sev_dep >= sev_arr else "weather_arr"
            hub_sev = sev_dep if s.origin == N.HUB else sev_arr
            ready = avail.get(tail, s.std) + timedelta(minutes=25)
            reactionary = max(0, int((ready - s.std).total_seconds() // 60))
            positioned = loc.get(tail) == s.origin and reactionary <= 180
            grounded = (aog.get(tail) is not None and aog[tail].until > s.std  # type: ignore[union-attr]
                        and aog[tail].logged_at <= s.std)  # type: ignore[union-attr]
            cancel: Cancel | None = None
            delay_min = 0
            used_spare: str | None = None

            if s.id in self.plan.notice:
                cancel = Cancel("notice", s.std - timedelta(days=self.plan.notice[s.id]))
            elif not positioned:
                if max(sev_dep, sev_arr) > 0:
                    # the storm is still on at this sector's own ends: it would not have flown anyway
                    cancel = Cancel(wx_latent, self._wx_known(s))
                elif s.origin == N.HUB and (sp := self._spare(s, spare_free, at=s.std - timedelta(minutes=30))):
                    used_spare = sp
                else:
                    root = last_cancel_at.get(tail)
                    spare_info = self._ferry(s, spare_free, idx) if s.origin != N.HUB else {"spare": None,
                                                                                            "station": s.origin}
                    if spare_info.get("delay_min") is not None and spare_info["delay_min"] <= 180:
                        used_spare = spare_info["spare"]
                        delay_min = max(0, spare_info["delay_min"])
                    else:
                        spare_info["reroute"] = self._reroute_label(s) if u_reroute < C.P_REROUTE_EARLIEST else None
                        known = self.out.cancels[root].known_at if root in self.out.cancels else s.std
                        cancel = Cancel("rotation", known, root=root, spare=spare_info)
            elif grounded:
                a = aog[tail]
                assert a is not None
                if wx and hub_sev > 0:
                    cancel = Cancel("concurrent", a.logged_at, defect_entry=a.entry_id)
                elif s.origin == N.HUB and (sp := self._spare(s, spare_free, at=s.std - timedelta(minutes=30))):
                    used_spare = sp
                else:
                    cancel = Cancel(a.latent, a.logged_at, defect_entry=a.entry_id,
                                    spare={"spare": None, "station": s.origin} if s.origin == N.HUB else None)
            elif wx:
                cancel = Cancel(wx_latent, self._wx_known(s))
            elif s.id in self.plan.crew or u_crew < (C.P_CREW_STORM_LATE if self.storm and s.std.hour >= 13
                                                       else C.P_CREW):
                cancel = Cancel("crew", s.std - timedelta(minutes=60 + int(u_delay * 90)))
            elif atc_strike and self._atc_affected(s) and u_atc < C.P_ATC_CANCEL:
                cancel = Cancel("atc", midnight(d) + timedelta(hours=4, minutes=30))

            if used_spare is not None:
                # the spare takes over this tail's remaining rotation today
                actual[s.tail] = used_spare
                tail = used_spare
                loc[tail] = s.origin
                spare_free[used_spare] = None

            if cancel is not None:
                self.out.cancels[s.id] = cancel
                last_cancel_at[tail] = s.id
                self._truth_cancel(s, cancel, idx)
                self._flight(s, tail, "cancelled", r)
                if positioned and s.dest == N.HUB and not s.pair.long_haul and not grounded:
                    # stranded at the outstation: ferry home empty once both ends are workable again
                    back = self._ferry_home(s, idx)
                    if back is not None:
                        loc[tail], avail[tail] = N.HUB, back
            else:
                if delay_min == 0:
                    base = 4 + int(u_delay * 18)
                    if max(sev_dep, sev_arr) > 0:
                        base += int(max(sev_dep, sev_arr) * 120 * u_delay)
                    delay_min = max(base, reactionary if used_spare is None else 0)
                status = "delayed" if delay_min >= 60 else "operated"
                self._flight(s, tail, status, r, delay_min=delay_min)
                self.out.truth[s.id] = FlightTruth(s.id, d.isoformat(), self.w.split, status, "none",
                                                   spare_within_3h=True if used_spare and s.origin != N.HUB else None)
                arr = s.sta + timedelta(minutes=delay_min)
                loc[tail], avail[tail] = s.dest, arr
                # external hit on arrival → grounded for inspection
                p_ext = C.P_BIRD + (C.P_LIGHTNING_STORM if (C.thunder_near(idx.get(s.dest), s.sta)
                                                            or self.storm and sev_arr > 0) else 0.0)
                if u_ext < p_ext and aog.get(tail) is None:
                    defect = T.EXTERNAL_DEFECTS[1 if (self.storm and u_ext < C.P_LIGHTNING_STORM) else 0]
                    rr = rng_for(self.seed, "ext", s.id)
                    aog[tail] = self._log_aog(tail, s.dest, arr + timedelta(minutes=15), defect, rr, "external_hit")
                # internal AOG found after the k-th sector of the scheduled tail
                planned = aog_after.get(s.tail)
                if planned is not None and aog.get(tail) is None:
                    k, defect = planned
                    if [x.id for x in rot[s.tail]].index(s.id) == k:
                        rr = rng_for(self.seed, "aog", tail, d.isoformat())
                        aog[tail] = self._log_aog(tail, s.dest, arr + timedelta(minutes=20 + rr.randint(0, 30)),
                                                  defect, rr, "internal_aog")
                        aog_after.pop(s.tail, None)

        self._link_rotations(sectors, actual)
        self._occ_logs(sectors, idx)
        self._spares_logs()
        self.out.meta = {"date": d.isoformat(), "storm_id": self.w.storm_id, "kind": self.w.kind,
                         "split": self.w.split, "atc_strike": atc_strike,
                         "flights": [s.id for s in sectors],
                         "cancelled": sorted(self.out.cancels)}
        self._metar_sources()
        return self.out

    # ---- helpers
    def _wx_known(self, s: N.Sector) -> datetime:
        return max(midnight(self.day) + timedelta(hours=3, minutes=30), s.std - timedelta(minutes=150)) \
            if s.std > midnight(self.day) else s.std - timedelta(minutes=90)

    def _atc_affected(self, s: N.Sector) -> bool:
        other = s.dest if s.origin == N.HUB else s.origin
        return airport(other).country in C.ATC_STRIKE_COUNTRIES

    def _spare(self, s: N.Sector, spare_free: dict[str, datetime | None], at: datetime) -> str | None:
        lh = N.FLEET[s.tail].code in ("A21X", "A333")
        for sp in N.SPARES:
            if (N.FLEET[sp].code == "A333") != lh:
                continue
            free = spare_free.get(sp)
            if free is not None and free <= at:
                return sp
        return None

    def _ferry(self, s: N.Sector, spare_free: dict[str, datetime | None],
               idx: dict[str, C.ObsIndex]) -> dict[str, Any]:
        """Earliest spare ferried ex-DUB to the outstation; delay vs STD in minutes (None when no spare today)."""
        lh = N.FLEET[s.tail].code in ("A21X", "A333")
        best: dict[str, Any] = {"spare": None, "station": s.origin}
        block = s.pair.block_out
        for sp in N.SPARES:
            if (N.FLEET[sp].code == "A333") != lh or spare_free.get(sp) is None:
                continue
            dep = max(spare_free[sp], s.std - timedelta(minutes=block + 40))  # type: ignore[type-var]
            for _ in range(48):     # a ferry can't leave into the storm
                if C.severity(idx.get(N.HUB), dep) < 0.25:
                    break
                dep += timedelta(minutes=30)
            station_dep = dep + timedelta(minutes=block + 40)
            delay = int((station_dep - s.std).total_seconds() // 60)
            if best.get("delay_min") is None or delay < best["delay_min"]:
                best = {"spare": sp, "station": s.origin, "ferry_dep": dep, "station_dep": station_dep,
                        "delay_min": delay}
        return best

    def _ferry_home(self, s: N.Sector, idx: dict[str, C.ObsIndex]) -> datetime | None:
        """Earliest empty positioning flight outstation → DUB after a cancelled return (None: not today)."""
        t = s.std
        for _ in range(36):
            arr = t + timedelta(minutes=s.pair.block_ret)
            if C.severity(idx.get(s.origin), t) < 0.25 and C.severity(idx.get(N.HUB), arr) < 0.25:
                return arr
            t += timedelta(minutes=30)
        return None

    def _reroute_label(self, s: N.Sector) -> str:
        partners = {"MUC": "LH via FRA", "FCO": "AZ via LIN", "LIS": "TP via OPO", "ATH": "A3 via MUC",
                    "BCN": "VY direct", "MAD": "IB direct", "CDG": "AF direct", "AMS": "KL direct",
                    "FRA": "LH direct", "LHR": "BA direct", "JFK": "AA via LHR", "BOS": "BA via LHR",
                    "ORD": "UA via LHR", "YYZ": "AC via LHR", "EWR": "UA via LHR", "IAD": "UA via LHR"}
        other = s.dest if s.origin == N.HUB else s.origin
        return partners.get(other, "partner via LHR")

    def _log_aog(self, tail: str, station: str, logged: datetime, defect: T.Defect, r: random.Random,
                 latent: str) -> Aog:
        narrative = T.fill(defect, r, station)
        text = T.tech_log_line(logged, tail, station, narrative, defect)
        eid = f"TECHLOG-{tail}-{stamp(logged)}"
        if defect.external:
            rts = logged + timedelta(hours=r.randint(3, 8))
            eta = rts
        else:
            eta = logged + timedelta(hours=r.randint(12, 30))
            rts = eta + timedelta(hours=r.randint(4, 8))
        self.out.tech_log.append(TechLogEntry(id=eid, aircraft=tail, logged_at=logged, station=station,
                                              ata=defect.ata, text=text, mel_relief=defect.mel_relief, aog=True,
                                              rts_est=rts))
        self._source(f"SRC-{eid}", SourceKind.TECH_LOG, f"Tech log {tail} {T.ddmon(logged)} {T.hhmmz(logged)}",
                     T.amos_record(tail, N.FLEET[tail].name, station, logged, defect, text, rts),
                     logged + timedelta(minutes=2), 1, ["maintenance", "ops"])
        mcc_at = logged + timedelta(minutes=r.choice([25, 35, 40, 55]))
        mtext = T.mcc_line(mcc_at, station, defect, r.choice(T.POOLS), eta, rts)
        mid = f"MCC-{stamp(mcc_at)}-{tail}"
        self.out.ops_log.append(OpsLogEntry(id=mid, at=mcc_at, kind="mcc", flight_ids=[], text=mtext,
                                            author="MCC DUB"))
        self._source(f"SRC-{mid}", SourceKind.MCC_LOG, f"MCC log {T.ddmon(mcc_at)} {T.hhmmz(mcc_at)} · {tail}",
                     mtext + "\n", mcc_at + timedelta(minutes=1), 1, ["ops", "maintenance"])
        return Aog(until=rts, entry_id=eid, station=station, logged_at=logged, latent=latent, defect=defect)

    def _log_mel(self, tail: str, station: str, logged: datetime, defect: T.Defect, r: random.Random) -> None:
        text = T.tech_log_line(logged, tail, station, T.fill(defect, r, station), defect)
        eid = f"TECHLOG-{tail}-{stamp(logged)}"
        self.out.tech_log.append(TechLogEntry(id=eid, aircraft=tail, logged_at=logged, station=station,
                                              ata=defect.ata, text=text, mel_relief=True, aog=False))
        self._source(f"SRC-{eid}", SourceKind.TECH_LOG, f"Tech log {tail} {T.ddmon(logged)} {T.hhmmz(logged)}",
                     T.amos_record(tail, N.FLEET[tail].name, station, logged, defect, text, None),
                     logged + timedelta(minutes=2), 1, ["maintenance", "ops"])

    def _source(self, sid: str, kind: SourceKind, title: str, text: str, at: datetime, tier: int,
                tags: list[str]) -> Source:
        src = Source(id=sid, kind=kind, title=title, text=text, sha256=sha(text), received_at=at, trust_tier=tier,
                     acl_tags=tags)
        self.out.sources.append(src)
        return src

    def _truth_cancel(self, s: N.Sector, c: Cancel, idx: dict[str, C.ObsIndex]) -> None:
        root_latent = None
        if c.latent == "rotation" and c.root:
            rt = self.out.truth.get(c.root)
            root_latent = (rt.root_latent or rt.latent) if rt and rt.latent == "rotation" else (rt.latent if rt else None)
        spare3 = None if c.spare is None else (c.spare.get("delay_min") is not None and c.spare["delay_min"] <= 180)
        reroute = None if c.spare is None else bool(c.spare.get("reroute"))
        cause, extra, route = truth_for(c.latent, root_latent, spare_within_3h=spare3, reroute_earliest=reroute)
        t = FlightTruth(s.id, self.day.isoformat(), self.w.split, "cancelled", c.latent, cause, extra,
                        root_flight_id=c.root, root_latent=root_latent, expected_route=route,
                        spare_within_3h=spare3 if c.latent == "rotation" else None,
                        reroute_earliest_offered=reroute if c.latent == "rotation" else None)
        self.out.truth[s.id] = t

    def _flight(self, s: N.Sector, tail: str, status: str, r: random.Random, delay_min: int = 0) -> None:
        seats = N.FLEET[tail].seats if tail in N.FLEET else N.FLEET[s.tail].seats
        pax = int(seats * (0.78 + 0.2 * r.random()))
        kw: dict[str, Any] = {}
        if status != "cancelled":
            kw["actual_dep"] = s.std + timedelta(minutes=delay_min)
            kw["actual_arr"] = s.sta + timedelta(minutes=delay_min + r.randint(-8, 6))
        self.out.flights.append(Flight(id=s.id, number=s.number, date=s.local_date, origin=s.origin, dest=s.dest,
                                       sched_dep=s.std, sched_arr=s.sta, aircraft=tail, status=status, pax=pax,
                                       **kw))

    def _link_rotations(self, sectors: list[N.Sector], actual: dict[str, str]) -> None:
        by_id = {f.id: f for f in self.out.flights}
        for tail, secs in N.tail_rotation(sectors).items():
            prev: N.Sector | None = None
            for s in secs:
                f = by_id[s.id]
                upd: dict[str, Any] = {}
                if prev is not None:
                    upd["inbound_flight_id"] = prev.id
                if s.is_return and not s.pair.long_haul:
                    upd["outbound_pair_id"] = next(x.id for x in secs if x.number == s.pair.out_number)
                if upd:
                    by_id[s.id] = f.model_copy(update=upd)
                prev = s
        self.out.flights = [by_id[s.id] for s in sectors]

    # ---- OCC: batch list on storm days, single messages otherwise
    def _occ_logs(self, sectors: list[N.Sector], idx: dict[str, C.ObsIndex]) -> None:
        d = self.day
        cancels = self.out.cancels
        if not cancels:
            return
        by_id = {s.id: s for s in sectors}
        codes: dict[str, str] = {}
        notified: dict[str, datetime] = {}
        batch: list[str] = []
        wx_ids = [fid for fid, c in cancels.items() if c.latent in WX_LATENT or c.latent == "concurrent"]
        t_batch = None
        if self.storm and wx_ids:
            first = min(by_id[f].std for f in wx_ids if by_id[f].std >= midnight(d))  \
                if any(by_id[f].std >= midnight(d) for f in wx_ids) else midnight(d) + timedelta(hours=5)
            t_batch = max(midnight(d) + timedelta(hours=4, minutes=self.drng.randrange(0, 50)),
                          min(first - timedelta(minutes=70), midnight(d) + timedelta(hours=14)))
            t_batch = t_batch.replace(second=0, microsecond=0)
            for fid, c in sorted(cancels.items()):
                rr = rng_for(self.seed, "occ", fid)
                in_batch = c.latent != "notice" and (
                    c.latent in WX_LATENT or c.latent == "concurrent" or fid in self.plan.batch
                    or (c.latent == "rotation" and (c.root in wx_ids or c.root in self.plan.batch))
                    or (c.known_at <= t_batch and rr.random() < C.P_OCC_MISBATCH))
                if in_batch:
                    batch.append(fid)
            sms = t_batch + timedelta(minutes=8)
            inbound = [f for f in batch if by_id[f].pair.long_haul and by_id[f].is_return]
            main = [f for f in batch if f not in inbound]
            groups = self._groups(main, by_id)
            text = T.occ_batch_line(t_batch, self.storm_name, groups, [by_id[f].number for f in inbound], sms,
                                    pax_note=self._pax_note(batch, by_id))
            oid = f"OCC-{stamp(t_batch)}"
            self.out.ops_log.append(OpsLogEntry(id=oid, at=t_batch, kind="occ", flight_ids=sorted(batch), code="71",
                                                text=text, author="OCC DM"))
            self._source(f"SRC-{oid}", SourceKind.OCC_LOG, f"OCC log {T.ddmon(t_batch)} {T.hhmmz(t_batch)}",
                         text + "\n", t_batch + timedelta(minutes=1), 3, ["ops"])
            for f in batch:
                codes[f] = "72" if f in inbound else "71"
                notified[f] = min(sms, by_id[f].std - timedelta(minutes=90))
        # singles (grouped by tail pair)
        rest = [fid for fid in sorted(cancels, key=lambda x: by_id[x].std) if fid not in codes]
        handled: set[str] = set()
        for fid in rest:
            if fid in handled:
                continue
            s, c = by_id[fid], cancels[fid]
            group_ids = [fid]
            for other in rest:
                if other != fid and other not in handled and cancels[other].latent == "rotation" \
                        and cancels[other].root == fid:
                    group_ids.append(other)
            code = self.plan.code.get(fid) or self._occ_code(fid, c, idx)
            at = max(c.known_at + timedelta(minutes=rng_for(self.seed, "occt", fid).randint(10, 35)),
                     midnight(d) - timedelta(hours=6))
            if c.latent == "notice":
                at = c.known_at + timedelta(minutes=rng_for(self.seed, "occt", fid).randint(10, 35))
            elif at > s.std + timedelta(minutes=30):
                at = s.std - timedelta(minutes=5) if c.known_at < s.std else c.known_at + timedelta(minutes=10)
            at = at.replace(second=0, microsecond=0)
            sms = at + timedelta(minutes=6)
            tail = s.tail
            reason = T.OCC_REASON_TEXT.get(code, "OPS").format(tail=tail, station=s.origin,
                                                              fir="FRANCE" if code == "82" else "")
            text = T.occ_single_line(at, self._groups(group_ids, by_id)[0] if len(group_ids) <= 2
                                     else " ".join(self._groups(group_ids, by_id)), code, reason, sms,
                                     pax_note=self._pax_note(group_ids, by_id))
            oid = f"OCC-{stamp(at)}-{s.number}"
            self.out.ops_log.append(OpsLogEntry(id=oid, at=at, kind="occ", flight_ids=sorted(group_ids), code=code,
                                                text=text, author="OCC duty manager"))
            self._source(f"SRC-{oid}", SourceKind.OCC_LOG, f"OCC log {T.ddmon(at)} {T.hhmmz(at)}", text + "\n",
                         at + timedelta(minutes=1), 3, ["ops"])
            for g in group_ids:
                codes[g] = code
                notified[g] = min(sms, by_id[g].std) if sms < by_id[g].std + timedelta(hours=1) else by_id[g].std
                handled.add(g)
        flights = []
        for f in self.out.flights:
            if f.id in codes:
                f = f.model_copy(update={"ops_cause_code": codes[f.id], "notified_at": notified[f.id]})
                self.out.truth[f.id].ops_code = codes[f.id]
                t = self.out.truth[f.id]
                s = by_id[f.id]
                storm_at_ends = max(C.severity(idx.get(s.origin), s.std), C.severity(idx.get(s.dest), s.sta))
                # invisible to the features: a crew cancellation batch-coded 71 inside the storm
                if t.latent == "crew" and codes[f.id] in ("71", "72") and storm_at_ends >= 0.08:
                    t.ambiguous = True
                    t.note = "crew shortage batch-coded as weather inside the storm; no record shows it"
                cancel = cancels[f.id]
                root_t = self.out.truth.get(t.root_flight_id or "")
                if t.latent == "rotation" and root_t is not None and root_t.ambiguous:
                    t.ambiguous = True
                    t.note = "knock-on of a cancellation whose real cause no record shows"
                if t.latent in ("internal_aog", "concurrent") and cancel.defect_entry == "":
                    t.ambiguous = True
                    t.note = "aircraft defect never written up in the tech log; OCC typed the storm code"
                tags = t.planted
                if t.latent == "internal_aog" and codes[f.id] in ("71", "72"):
                    tags.append("miscoded_technical")
                if t.latent == "concurrent":
                    tags.append("concurrent")
                if t.latent == "rotation" and t.expected_route == "legal":
                    tags.append("knock_on_return")
                if t.latent == "notice":
                    tags.append("notice_ge_14d")
                    f = f.model_copy(update={"notified_at": f.sched_dep - timedelta(days=self.plan.notice[f.id])})
                if f.id in self.plan.pax_mismatch:
                    tags.append("manifest_ops_pax_mismatch")
                if t.ambiguous:
                    tags.append("ambiguous")
            flights.append(f)
        self.out.flights = flights

    def _pax_note(self, ids: Iterable[str], by_id: dict[str, N.Sector]) -> str:
        notes = [f"{by_id[i].number} PAX {self.plan.pax_mismatch[i]}" for i in sorted(ids, key=lambda x: by_id[x].std)
                 if i in self.plan.pax_mismatch]
        return ("OPS PAX: " + ", ".join(notes) + ".") if notes else ""

    def _occ_code(self, fid: str, c: Cancel, idx: dict[str, C.ObsIndex]) -> str:
        r = rng_for(self.seed, "code", fid)
        if c.latent == "rotation":
            root = self.out.cancels.get(c.root or "")
            return self._occ_code(c.root, root, idx) if root else "93"  # type: ignore[arg-type]
        if c.latent == "internal_aog":
            s = self.out.sectors[fid]
            windy = max(C.max_gust_near(idx.get(s.origin), s.std, timedelta(hours=3)),
                        C.max_gust_near(idx.get(s.dest), s.sta, timedelta(hours=3))) >= 28
            return "71" if windy and r.random() < 0.3 else "41"
        return {"weather_dep": "71", "weather_arr": "72", "external_hit": "51", "atc": "82", "concurrent": "71",
                "crew": r.choice(["64", "67"]), "notice": "09"}.get(c.latent, "93")

    def _groups(self, ids: list[str], by_id: dict[str, N.Sector]) -> list[str]:
        ids_set = set(ids)
        out, seen = [], set()
        for fid in sorted(ids, key=lambda x: (by_id[x].std, x)):
            if fid in seen:
                continue
            s = by_id[fid]
            mate = next((o for o in ids_set if o != fid and by_id[o].pair is s.pair and by_id[o].is_return != s.is_return
                         and not s.pair.long_haul), None)
            if mate and not s.is_return:
                out.append(f"{s.number}/{by_id[mate].number[2:]}")
                seen.update({fid, mate})
            else:
                out.append(s.number)
                seen.add(fid)
        return out

    def _spares_logs(self) -> None:
        for fid, c in sorted(self.out.cancels.items()):
            if not c.spare:
                continue
            s = self.out.sectors[fid]
            sp = c.spare
            if c.latent == "rotation":
                text = T.spares_line(s.number, s.origin, spare=sp.get("spare"), ferry_dep=sp.get("ferry_dep"),
                                     station_dep=sp.get("station_dep"), std=s.std, reroute=sp.get("reroute"))
            else:
                kind = "long-range" if s.pair.long_haul else "narrowbody"
                text = f"{s.number}: No {kind} spare at DUB before STD {T.hhmmz(s.std)}."
            at = min(s.std, c.known_at + timedelta(minutes=50)).replace(second=0, microsecond=0)
            oid = f"SPARES-{stamp(at)}-{s.number}"
            self.out.ops_log.append(OpsLogEntry(id=oid, at=at, kind="spares", flight_ids=[fid], text=text,
                                                author="OCC fleet desk"))
            self._source(f"SRC-{oid}", SourceKind.SPARES, f"SPARES log {T.ddmon(at)} {T.hhmmz(at)} · {s.number}",
                         text + "\n", at + timedelta(minutes=1), 2, ["ops"])

    def _metar_sources(self) -> None:
        for key, obs in sorted(self.out.metar.items()):
            if not obs:
                continue
            icao = key.split("@")[0]
            src = self._source(f"SRC-METAR-{key}", SourceKind.METAR, f"METAR {icao} (IEM ASOS archive)",
                               T.iem_csv(obs), obs[-1].valid + timedelta(minutes=25), 1, ["ops"])
            self.out.sources[-1] = src.model_copy(
                update={"uri": f"https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station={icao}"})


# ---------------------------------------------------------------- passengers, claims, care (F3b)

def populate_pax(out: DayOutput, seed: int) -> None:
    """Coupons/elections/CRM/care for every cancelled flight of the day, coupon truth, and the day's claims."""
    from world import pax as P

    po = P.PaxOutput()
    ids: set[str] = set()
    flights = {f.id: f for f in out.flights}
    fps: dict[str, P.FlightPax] = {}
    for f in out.flights:
        if f.status == "cancelled":
            fp = P.FlightPax(seed, f, out.truth[f.id].__dict__, po, ids)
            fp.run()
            fps[f.id] = fp
    elections = {e.coupon_id: e for e in po.elections}
    for c in po.coupons:
        po.coupon_truth[c.id] = P.coupon_truth(flights[c.flight_id], out.truth[c.flight_id].__dict__, c,
                                               elections.get(c.id), po.in_lieu.get(c.id))
    day = out.meta["date"]
    event = date.fromisoformat(day)
    by_seg: dict[str, list] = {}
    for c in po.coupons:
        t = po.coupon_truth[c.id]
        if t["status"] == "owed":
            by_seg.setdefault(t["segment"], []).append((c, t["compensation_cents"]))
    for seg in sorted(by_seg):
        r = rng_for(seed, "claims", day, seg)
        for c, comp, at in P.quota_claim_times(event, by_seg[seg], seg, r):
            t = po.coupon_truth[c.id]
            f = flights[c.flight_id]
            spec = P.ClaimSpec(c, f, at, pay_cents=t["pay_cents"], reason="valid")
            if r.random() < P.P_AGENCY:
                spec.channel, spec.agency = "agency", r.choice(T.AGENCIES)
                spec.authority = "poa" if r.random() < 0.65 else "assignment"
            other = f.dest if f.origin == N.HUB else f.origin
            if other in P.UK_ROUTES and r.random() < 0.1:
                spec.regime = "UK261"
            if t["voucher_offset_cents"] >= t["compensation_cents"] > 0:
                spec.reason = "settled_in_kind_signed_voucher"
            P.claim_record(po, spec, ids, r)
    r = rng_for(seed, "claims-invalid", day)
    for c in po.coupons:
        t = po.coupon_truth[c.id]
        if t["status"] in ("no_compensation", "staff_ticket", "exempt_notice") and r.random() < P.P_WEATHER_CLAIM:
            f = flights[c.flight_id]
            at = datetime.combine(event, datetime.min.time(), UTC) + timedelta(days=r.randint(1, 90),
                                                                                minutes=r.randint(0, 1439))
            reason = {"no_compensation": "extraordinary_circumstances", "staff_ticket": "staff_ticket_art3_3",
                      "exempt_notice": "notice_14_days"}[t["status"]]
            spec = P.ClaimSpec(c, f, at, valid=False, reason=reason)
            if r.random() < P.P_AGENCY:
                spec.channel, spec.agency, spec.authority = "agency", r.choice(T.AGENCIES), "poa"
            P.claim_record(po, spec, ids, r)
    out.pax = po


# ---------------------------------------------------------------- the whole world

STORM_NAMES = {  # display names for OCC batch messages (matched by date, as in data/pinned/STORM_DAYS.md)
    "2023-09-27": "Agnes", "2023-11-13": "Debi", "2023-12-09": "Elin", "2023-12-10": "Fergus",
    "2024-01-21": "Isha", "2024-01-22": "Isha", "2024-01-23": "Jocelyn", "2024-01-24": "Jocelyn",
    "2024-04-06": "Kathleen", "2024-10-20": "Ashley", "2024-11-23": "Bert", "2024-11-24": "Bert",
    "2024-12-07": "Darragh", "2025-01-24": "Éowyn", "2025-01-26": "Herminia",
}


@dataclass
class Generated:
    world: World
    truth: Truth


def distances_meta(codes: Iterable[str]) -> dict[str, float]:
    return {f"{N.HUB}-{c}": distance_km(N.HUB, c) for c in sorted(set(codes)) if c != N.HUB}


def assemble(outputs: Sequence[DayOutput], seed: int, *, extra_meta: dict[str, Any] | None = None) -> World:
    flights: list[Flight] = []
    tech: list[TechLogEntry] = []
    ops: list[OpsLogEntry] = []
    sources: list[Source] = []
    metar_: dict[str, list[MetarObs]] = {}
    coupons, elections, crm, claims, care = [], [], [], [], []
    days_meta, legacy_meta = [], []
    for o in outputs:
        flights += o.flights
        tech += o.tech_log
        ops += o.ops_log
        sources += o.sources
        metar_.update(o.metar)
        (legacy_meta if o.meta.get("kind") == "legacy" else days_meta).append(o.meta)
        if o.pax is not None:
            coupons += o.pax.coupons
            elections += o.pax.elections
            crm += o.pax.crm
            claims += o.pax.claims
            care += o.pax.care
            sources += o.pax.sources
    codes = sorted({f.origin for f in flights} | {f.dest for f in flights})
    meta = {"carrier": CARRIER, "generator": GENERATOR_VERSION, "seed": seed, "hub": N.HUB,
            "split": {"train": "2023-07-01..2024-12-31", "test": "2025-01-01..2025-06-30"},
            "days": days_meta, "legacy": legacy_meta, "distances_km": distances_meta(codes),
            "fleet": {t: N.FLEET[t].name for t in sorted(N.FLEET)}}
    meta.update(extra_meta or {})
    return World(meta=meta, airports=sorted((airport(c) for c in codes), key=lambda a: a.iata), flights=flights,
                 tech_log=sorted(tech, key=lambda e: (e.logged_at, e.id)),
                 ops_log=sorted(ops, key=lambda e: (e.at, e.id)),
                 coupons=coupons, elections=elections, crm=sorted(crm, key=lambda e: (e.at, e.id)),
                 claims=sorted(claims, key=lambda c: (c.received_at, c.id)), care=care, metar=metar_,
                 sources=sorted(sources, key=lambda s: (s.received_at, s.id)))


def simulate_days(seed: int = 0, wdays: Sequence[WorldDay] | None = None, *, plant: bool = False
                  ) -> tuple[list[DayOutput], dict[str, Any]]:
    """Simulate the days (flights → passengers). With `plant`, top up every planted-error type per split first
    (world/plant.py) and plant the claim-level cases afterwards. Returns (outputs incl. legacy, planted counts)."""
    from world import plant as PL
    from world.days import world_days

    days = list(wdays if wdays is not None else world_days())

    def run_day(w: WorldDay, plan: DayPlan | None) -> DayOutput:
        return DaySim(w, seed, storm_name=STORM_NAMES.get(w.day.isoformat(), ""), plan=plan).run()

    outs = {w.day: run_day(w, None) for w in days}
    plans: dict[date, DayPlan] = {}
    if plant:
        PL.Planner(seed, run_day).plan(days, plans, outs)
    ordered = [outs[w.day] for w in days]
    for o in ordered:
        populate_pax(o, seed)
    counts: dict[str, Any] = {}
    if plant:
        for split in ("train", "test"):
            split_outs = [outs[w.day] for w in days if w.split == split]
            counts[split] = dict(PL.PaxPlanter(seed, split, split_outs).run())
            ordered.append(PL.legacy_output(seed, split))
        counts["plans"] = {d.isoformat(): {"aog": sorted(p.aog), "crew": sorted(p.crew), "wx": sorted(p.wx),
                                           "notice": sorted(p.notice), "pax_mismatch": sorted(p.pax_mismatch)}
                           for d, p in sorted(plans.items()) if p}
    return ordered, counts


def generate_world(seed: int = 0, wdays: Sequence[WorldDay] | None = None, *,
                   embed_golden: bool | None = None, plant: bool | None = None) -> Generated:
    """The Northstar world. Defaults apply to the full world only (`wdays=None`): `embed_golden` splices the golden
    Éowyn/Herminia world in verbatim instead of simulating those days (F0); `plant` plants ≥5 of every error type
    per split (F3c). An explicit day list gets the natural days unless asked otherwise."""
    from world import golden
    from world.days import split_of, world_days

    if embed_golden is None:
        embed_golden = wdays is None and golden.available()
    if plant is None:
        plant = wdays is None
    all_days = list(wdays if wdays is not None else world_days())
    gdays = golden.golden_days() if embed_golden else frozenset()
    outs, planted = simulate_days(seed, [w for w in all_days if w.day not in gdays], plant=plant)
    truth = Truth()
    truth.planted = planted
    for o in outs:
        truth.flights.update(o.truth)
        if o.pax is not None:
            truth.coupons.update(o.pax.coupon_truth)
            truth.claims.update(o.pax.claim_truth)
    world = assemble(outs, seed)
    if embed_golden:
        g = golden.load_golden()
        world = golden.embed(world, g)
        gdays_meta = [{"date": s["local_date"], "storm_id": sid, "kind": "storm", "split": split_of(
            date.fromisoformat(s["local_date"])), "golden": True, "flights": list(s["flight_ids"]),
            "cancelled": sorted(f.id for f in g.flights if f.id in s["flight_ids"] and f.status == "cancelled")}
            for sid, s in g.meta["storms"].items()]
        days_meta = sorted(world.meta["days"] + gdays_meta, key=lambda m: m["date"])
        world = world.model_copy(update={"meta": {**world.meta, "days": days_meta}})
        for fid, t in golden.golden_flight_truth(g).items():
            f_day = next(m["date"] for m in gdays_meta if fid in m["flights"])
            truth.flights[fid] = FlightTruth(fid, f_day, split_of(date.fromisoformat(f_day)), t["status"],
                                             t["latent"], t["cause"], t["extraordinary"],
                                             root_flight_id=t["root_flight_id"], root_latent=t["root_latent"],
                                             planted=list(t["planted"]), expected_route=t["expected_route"],
                                             spare_within_3h=t["spare_within_3h"],
                                             reroute_earliest_offered=t["reroute_earliest_offered"],
                                             ops_code=next((f.ops_cause_code for f in g.flights if f.id == fid), None),
                                             golden=True)
        _golden_pax_truth(g, truth)
    elif plant:
        world = world.model_copy(update={"history_cases": generated_history(world, truth, seed)})
    return Generated(world, truth)


def _golden_pax_truth(g: World, truth: Truth) -> None:
    """Coupon and claim truth for golden's passengers, from golden's flight truth and its own records."""
    from world import pax as P

    flights = {f.id: f for f in g.flights}
    elections = {e.coupon_id: e for e in g.elections}
    in_lieu = {}
    for e in sorted(g.crm, key=lambda e: e.at):
        if e.kind == "voucher_in_lieu_of_compensation":
            in_lieu[e.coupon_id] = e
    dist = g.meta.get("distances_km", {})
    special = {g.meta.get("ns31", {}).get("bsp_duplicate_coupon"): "crm_bot_plus_bsp_refund",
               g.meta.get("ns31", {}).get("chargeback_coupon"): "duplicate_claim_chargeback"}
    for c in g.coupons:
        t = P.coupon_truth(flights[c.flight_id], truth.flights[c.flight_id].__dict__, c, elections.get(c.id),
                           in_lieu.get(c.id), distances=dist)
        tags = []
        if c.id in in_lieu and not in_lieu[c.id].signed_acceptance_sha256:
            tags.append("voucher_in_lieu_unsigned")
        if c.id in special:
            tags.append(special[c.id])
        if c.fare_type == "staff_id90":
            tags.append("staff_id90")
        if tags:
            t["planted"] = tags
        truth.coupons[c.id] = t
    seen: set[str] = set()
    for cl in sorted(g.claims, key=lambda c: (c.received_at, c.id)):
        t = truth.coupons[cl.coupon_id]
        valid = t["status"] == "owed" and cl.coupon_id not in seen
        seen.add(cl.coupon_id)
        truth.claims[cl.id] = {"coupon_id": cl.coupon_id, "valid": valid,
                               "pay_cents": t.get("pay_cents", 0) if valid else 0,
                               "covers": [cl.coupon_id] if valid else [],
                               "reason": "valid" if valid else ("duplicate_already_claimed" if t["status"] == "owed"
                                                               else t["status"]),
                               "planted": [], "golden": True,
                               "dev_month": P.dev_month(flights[cl.coupon_id.rsplit(":", 1)[0]].date, cl.received_at)}


def _region(o_code: str, d_code: str) -> str:
    o, d = airport(o_code), airport(d_code)
    if o.eu and d.eu:
        return "EU"
    pair = {o.country, d.country}
    return "EU_US" if "US" in pair else ("EU_UK" if "GB" in pair else "OTHER")


def generated_history(world: World, truth: Truth, seed: int) -> list:
    """Northstar's hidden policy as past human decisions with case features (for the miner), used only when golden's
    own history is not embedded: the Art. 7(2) cut applied in 41 of 42 reroute cases, plus 6 cause rulings."""
    from contracts.models import HistoryCase

    r = rng_for(seed, "history")
    flights = {f.id: f for f in world.flights}
    elections = {e.coupon_id: e for e in world.elections}
    cands = sorted(cid for cid, t in truth.coupons.items() if t.get("reduction") == "art7_2_50pct"
                   and truth.flights[t["flight_id"]].split == "train")
    r.shuffle(cands)
    pick = sorted(cands[:42])
    exception = pick[r.randrange(len(pick))] if pick else None
    out = []
    for i, cid in enumerate(pick, 1):
        t, e = truth.coupons[cid], elections[cid]
        f = flights[t["flight_id"]]
        feats = {"pax.election": e.kind, "pax.arrival_delay_min": e.arrival_delay_min, "flight.band_eur": t["band_eur"],
                 "flight.distance_km": distance_km(f.origin, f.dest), "flight.departs_eu": airport(f.origin).eu,
                 "flight.route_region": _region(f.origin, f.dest)}
        decision = "no_reduction" if cid == exception else "apply_7_2_reduction"
        out.append(HistoryCase(ruling_id=f"GH-RR-{i:03d}", case_ref=cid, kind="reroute_reduction", features=feats,
                               decision=decision, at=midnight(f.date) + timedelta(days=30 + r.randint(0, 60), hours=10)))
    wx = sorted(fid for fid, t in truth.flights.items() if t.split == "train" and t.latent == "weather_dep"
                and not t.ambiguous)
    tech = sorted(fid for fid, t in truth.flights.items() if t.split == "train" and t.latent == "internal_aog"
                  and not t.ambiguous)
    r.shuffle(wx)
    r.shuffle(tech)
    for i, fid in enumerate(sorted(wx[:3] + tech[:3]), 1):
        t, f = truth.flights[fid], flights[fid]
        is_wx = t.latent == "weather_dep"
        feats = {"flight.in_window_dep": "in" if is_wx else "out", "flight.in_window_arr": "out",
                 "aog.before_window": not is_wx, "aog.root_cause_internal": not is_wx,
                 "aog.mel_relief": None if is_wx else False, "rotation.prev_cancelled": False}
        out.append(HistoryCase(ruling_id=f"GH-CA-{i:03d}", case_ref=fid, kind="cause", features=feats,
                               decision=t.extraordinary or "", at=midnight(f.date) + timedelta(days=40, hours=11)))
    return sorted(out, key=lambda h: (h.at, h.ruling_id))
