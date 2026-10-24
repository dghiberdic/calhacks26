"""Northstar Air's network (F3a): ~35 routes from Dublin, the fleet, and each tail's daily rotation.

Times of DUB departures are **Dublin local** (UTC in winter, UTC+1 in summer); a return sector leaves the outstation
`turn` minutes after the outbound's scheduled arrival. Long-haul inbounds leave North America in the evening, **origin
local** time, and land in Dublin the next morning. The morning and afternoon waves reuse the plan's flight numbers and
tails (§1.2) so the generated days look like the golden Éowyn day around them.

Everything here is static data plus pure functions: no randomness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from world.airports import airport, distance_km

HUB = "DUB"
HUB_ICAO = "EIDW"
HUB_TZ = ZoneInfo("Europe/Dublin")


@dataclass(frozen=True)
class AircraftType:
    code: str
    name: str
    seats: int
    range_km: int


A20N = AircraftType("A20N", "A320neo", 194, 6300)
A21N = AircraftType("A21N", "A321neo", 212, 6400)
A21X = AircraftType("A21X", "A321XLR", 184, 8700)
A333 = AircraftType("A333", "A330-300", 277, 11700)
TYPES = {t.code: t for t in (A20N, A21N, A21X, A333)}

# tail -> type. EI-NS* = narrowbody (incl. the two golden XLRs EI-NSB / EI-NSN), EI-NW* = A330 (as in the plan's
# stub), EI-NL* = later XLR deliveries, EI-NT* = DUB standby spares.
FLEET: dict[str, AircraftType] = {      # types of the golden tails as in golden world.json meta.fleet
    **{f"EI-NS{c}": A20N for c in "CDEFGHJKLPQRST"},
    "EI-NSM": A21N,
    **{f"EI-NS{c}": A21N for c in "UVWXYZA"},
    "EI-NSB": A21X, "EI-NSN": A21X, "EI-NLA": A21X,
    "EI-NWA": A333, "EI-NWB": A333, "EI-NWC": A333, "EI-NWD": A333,
    "EI-NTA": A20N, "EI-NTB": A21N, "EI-NWE": A333,
}
SPARES = ("EI-NTA", "EI-NTB", "EI-NWE")


@dataclass(frozen=True)
class Pair:
    """One DUB→X→DUB rotation (short haul) or DUB→X + X→DUB overnight (long haul)."""
    out_number: str
    ret_number: str
    dest: str                      # IATA
    std_local: time                # DUB departure, Dublin local
    block_out: int                 # minutes
    turn: int                      # minutes at the outstation (short haul)
    block_ret: int
    tail: str
    long_haul: bool = False
    inbound_std_local: time | None = None   # long haul: X departure, origin local, the evening before DUB arrival
    wave: str = "morning"


def _block(dest: str) -> int:
    km = distance_km(HUB, dest)
    return int(round((km / 14 + 40) / 5) * 5)


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _sh(out: str, dest: str, std: str, tail: str, *, block_out: int | None = None, turn: int = 40,
        block_ret: int | None = None, wave: str) -> Pair:
    b = block_out or _block(dest)
    return Pair(out, f"NS{int(out[2:]) + 1}", dest, _t(std), b, turn, block_ret or b, tail, wave=wave)


def _lh(out: str, ret: str, dest: str, std: str, block_out: int, inbound_std: str, block_ret: int, tail: str) -> Pair:
    return Pair(out, ret, dest, _t(std), block_out, 0, block_ret, tail, long_haul=True,
                inbound_std_local=_t(inbound_std), wave="long_haul")


# Morning wave: the plan's numbers, times and tails (§1.2); return times as in the plan.
MORNING = [
    _sh("NS100", "LHR", "06:10", "EI-NSC", block_out=75, turn=35, block_ret=75, wave="morning"),
    _sh("NS102", "CDG", "06:40", "EI-NSD", block_out=95, turn=35, block_ret=100, wave="morning"),
    _sh("NS104", "AMS", "07:05", "EI-NSE", block_out=85, turn=45, block_ret=85, wave="morning"),
    _sh("NS106", "FRA", "07:30", "EI-NSF", block_out=105, turn=35, block_ret=90, wave="morning"),
    _sh("NS108", "BCN", "08:15", "EI-NSG", block_out=145, turn=35, block_ret=145, wave="morning"),
    _sh("NS110", "MAD", "09:00", "EI-NSH", block_out=140, turn=35, block_ret=145, wave="morning"),
    _sh("NS112", "LIS", "09:40", "EI-NSJ", block_out=160, turn=60, block_ret=155, wave="morning"),
    _sh("NS114", "FCO", "10:20", "EI-NSK", block_out=175, turn=55, block_ret=170, wave="morning"),
    _sh("NS116", "MUC", "11:00", "EI-NSL", block_out=130, turn=55, block_ret=135, wave="morning"),
    _sh("NS118", "ATH", "12:40", "EI-NSM", block_out=230, turn=45, block_ret=240, wave="morning"),
]
# Midday: one or two pairs per tail.
MIDDAY = [
    _sh("NS142", "LGW", "07:15", "EI-NSU", wave="midday"),
    _sh("NS144", "BHX", "07:40", "EI-NSV", wave="midday"),
    _sh("NS146", "GLA", "08:05", "EI-NSW", wave="midday"),
    _sh("NS148", "MXP", "08:30", "EI-NSX", wave="midday"),
    _sh("NS150", "VIE", "09:10", "EI-NSY", wave="midday"),
    _sh("NS152", "PRG", "09:30", "EI-NSZ", wave="midday"),
    _sh("NS154", "WAW", "10:00", "EI-NSA", wave="midday"),
    _sh("NS164", "AGP", "13:10", "EI-NSU", wave="midday"),
    _sh("NS166", "FAO", "13:40", "EI-NSV", wave="midday"),
    _sh("NS168", "DUS", "14:20", "EI-NSW", wave="midday"),
    _sh("NS158", "OSL", "15:00", "EI-NSX", wave="midday"),
    _sh("NS160", "GVA", "15:50", "EI-NSY", wave="midday"),
    _sh("NS162", "NCE", "15:40", "EI-NSZ", wave="midday"),
    _sh("NS156", "ARN", "16:50", "EI-NSA", wave="midday"),
]
# Afternoon wave: the plan's 11 departures 15:30-17:30Z that operated on Éowyn day ("everyone else flew").
AFTERNOON = [
    _sh("NS120", "LHR", "15:30", "EI-NSC", block_out=75, wave="afternoon"),
    _sh("NS122", "AMS", "15:40", "EI-NSE", block_out=85, wave="afternoon"),
    _sh("NS124", "CDG", "15:50", "EI-NSD", block_out=95, wave="afternoon"),
    _sh("NS126", "FRA", "16:00", "EI-NSF", block_out=105, wave="afternoon"),
    _sh("NS128", "MAD", "16:10", "EI-NSH", block_out=140, wave="afternoon"),
    _sh("NS130", "BCN", "16:20", "EI-NSG", block_out=145, wave="afternoon"),
    _sh("NS132", "BRU", "16:35", "EI-NSP", wave="afternoon"),
    _sh("NS134", "MAN", "16:45", "EI-NSQ", wave="afternoon"),
    _sh("NS136", "EDI", "16:55", "EI-NSR", wave="afternoon"),
    _sh("NS138", "CPH", "17:10", "EI-NSS", wave="afternoon"),
    _sh("NS140", "ZRH", "17:25", "EI-NST", wave="afternoon"),
]
# Long haul (A330 / A321XLR): outbound DUB late morning/afternoon, inbound overnight (origin-local evening).
LONG_HAUL = [
    _lh("NS21", "NS20", "JFK", "11:05", 465, "18:30", 380, "EI-NWA"),
    _lh("NS31", "NS30", "BOS", "16:30", 400, "19:10", 320, "EI-NSN"),
    _lh("NS41", "NS40", "ORD", "12:10", 525, "17:00", 400, "EI-NWB"),
    _lh("NS51", "NS50", "YYZ", "13:00", 480, "18:45", 350, "EI-NWC"),
    _lh("NS61", "NS60", "EWR", "15:10", 445, "18:55", 370, "EI-NSB"),
    _lh("NS71", "NS70", "IAD", "14:00", 490, "17:50", 410, "EI-NWD"),
]
PAIRS: list[Pair] = MORNING + MIDDAY + AFTERNOON + LONG_HAUL
ROUTES: list[str] = sorted({p.dest for p in PAIRS})


@dataclass(frozen=True)
class Sector:
    """One scheduled flight on a given world day."""
    number: str
    origin: str
    dest: str
    std: datetime          # UTC
    sta: datetime          # UTC
    tail: str
    local_date: date       # local departure date at the origin (Flight.date, part of the id)
    pair: Pair
    is_return: bool

    @property
    def id(self) -> str:
        return f"{self.number}@{self.local_date.isoformat()}"


def _utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tz).astimezone(UTC)


def _local_date(t: datetime, code: str) -> date:
    return t.astimezone(ZoneInfo(airport(code).tz)).date()


def day_sectors(day: date, pairs: list[Pair] | None = None) -> list[Sector]:
    """Every sector of world day `day` (Dublin local): DUB departures on `day`, their returns, and the long-haul
    inbounds that land in Dublin on `day` (they left North America the evening before, so their id carries that
    local date). Sorted by STD, then number."""
    out: list[Sector] = []
    for p in pairs or PAIRS:
        std = _utc(day, p.std_local, HUB_TZ)
        sta = std + timedelta(minutes=p.block_out)
        out.append(Sector(p.out_number, HUB, p.dest, std, sta, p.tail, day, p, False))
        if p.long_haul:
            tz = ZoneInfo(airport(p.dest).tz)
            # inbound landing in DUB on `day` left the outstation on the evening of `day - 1` (origin local)
            istd = _utc(day - timedelta(days=1), p.inbound_std_local, tz)
            ista = istd + timedelta(minutes=p.block_ret)
            out.append(Sector(p.ret_number, p.dest, HUB, istd, ista, p.tail, _local_date(istd, p.dest), p, True))
        else:
            rstd = sta + timedelta(minutes=p.turn)
            rsta = rstd + timedelta(minutes=p.block_ret)
            out.append(Sector(p.ret_number, p.dest, HUB, rstd, rsta, p.tail, _local_date(rstd, p.dest), p, True))
    out.sort(key=lambda s: (s.std, s.number))
    return out


def tail_rotation(sectors: list[Sector]) -> dict[str, list[Sector]]:
    by_tail: dict[str, list[Sector]] = {}
    for s in sorted(sectors, key=lambda s: s.std):
        by_tail.setdefault(s.tail, []).append(s)
    return by_tail


@lru_cache(maxsize=1)
def network_airports() -> tuple[str, ...]:
    return tuple(sorted({HUB, *ROUTES}))


def pair_for_dest(dest: str) -> list[Pair]:
    return [p for p in PAIRS if p.dest == dest]


def adhoc_pair(dest: str) -> Pair:
    """A hypothetical Northstar rotation for a desk airport outside the network (judge's choice).

    Narrowbody up to 3,500 km, XLR up to 7,500 km, A330 beyond. Deterministic from the code. Never flown by a DUB
    standby spare (EI-NT*, EI-NWE): a spare can't stand in for its own rotation.
    """
    km = distance_km(HUB, dest)
    n = 900 + (sum(ord(c) for c in dest) % 49) * 2
    if km <= 3500:
        return Pair(f"NS{n}", f"NS{n + 1}", dest, time(9, 30), _block(dest), 45, _block(dest), "EI-NSU",
                    wave="adhoc")
    tail = "EI-NLA" if km <= 7500 else "EI-NWD"
    block = int(round((km / 13.5 + 45) / 5) * 5)
    return Pair(f"NS{n}", f"NS{n + 1}", dest, time(12, 15), block, 0, max(60, block - 45), tail, long_haul=True,
                inbound_std_local=time(19, 0), wave="adhoc")
