"""D1 · Storm windows from real METAR, and where a flight sits relative to them at both ends.

Binding definition (plan §1.2): an obs counts when gust >= 35 kt, or sustained >= 30 kt, or visibility < 0.5 SM,
or wxcodes contain SN / FZ / TS / GR. Counting obs whose gap is under 2 h merge into one window, which runs from its
first to its last counting obs. Windows are always computed from data, never hard-coded.

Positions: ``in`` / ``out`` / ``unknown``; ``unknown`` means no obs within +-60 min of the time asked about.
Departure ends use the origin's obs at STD; arrival ends use the destination's obs at STA.

Pure: no wall clock, no randomness, no LLM. All times are tz-aware UTC.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from contracts.models import Flight, MetarObs, StormWindow

Position = Literal["in", "out", "unknown"]

GUST_KT = 35
SKNT_KT = 30
VSBY_SM = 0.5
WX_GROUPS = frozenset({"SN", "FZ", "TS", "GR"})
MERGE_GAP = timedelta(hours=2)          # gaps strictly under this merge
OBS_TOLERANCE = timedelta(minutes=60)   # an obs this close (inclusive) makes a time "known"

_MISSING = {"", "M"}


# ---------- loading ----------

def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if s in _MISSING:
        return None
    return float(s)


def _int(s: str | None) -> int | None:
    v = _num(s)
    return None if v is None else round(v)


def _text(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return None if s in _MISSING else s


def _parse_valid(s: str) -> datetime:
    t = datetime.fromisoformat(s.strip())
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)  # IEM `valid` is UTC
    return t.astimezone(UTC)


def _station_from_raw(raw: str) -> str | None:
    for tok in raw.split():
        if tok in {"METAR", "SPECI", "COR"}:
            continue
        return tok if len(tok) == 4 and tok.isalnum() and tok.isupper() else None
    return None


def load_iem_csv(path: str | Path, station: str | None = None) -> list[MetarObs]:
    """Parse an Iowa Environmental Mesonet ``asos.py`` CSV (station, valid, sknt, gust, drct, vsby, wxcodes, metar).

    Empty or ``M`` cells become ``None``. ``valid`` is UTC. The station is ``station`` if given, else the ICAO id at the
    head of the raw METAR (IEM uses 3-letter ids for US stations), else IEM's ``station`` column. Sorted by time.
    """
    out: list[MetarObs] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        for row in rows:
            raw = (row.get("metar") or "").strip()
            st = station or _station_from_raw(raw) or (row.get("station") or "").strip()
            out.append(MetarObs(
                station=st,
                valid=_parse_valid(row["valid"]),
                sknt=_int(row.get("sknt")),
                gust=_int(row.get("gust")),
                drct=_int(row.get("drct")),
                vsby_sm=_num(row.get("vsby")),
                wxcodes=_text(row.get("wxcodes")),
                raw=raw,
            ))
    out.sort(key=lambda o: (o.station, o.valid, o.raw))
    return out


# ---------- criteria ----------

def _wx_groups(wxcodes: str) -> set[str]:
    """Split present-weather groups into 2-letter descriptor/phenomenon codes: '-FZRA BR' -> {FZ, RA, BR}."""
    groups: set[str] = set()
    for tok in wxcodes.upper().split():
        tok = tok.lstrip("+-")
        groups.update(tok[i:i + 2] for i in range(0, len(tok) - 1, 2))
    return groups


def storm_reasons(o: MetarObs) -> list[str]:
    """Which storm criteria this obs meets (empty list = calm by the binding definition)."""
    reasons: list[str] = []
    if o.gust is not None and o.gust >= GUST_KT:
        reasons.append(f"gust {o.gust}kt>={GUST_KT}")
    if o.sknt is not None and o.sknt >= SKNT_KT:
        reasons.append(f"sknt {o.sknt}kt>={SKNT_KT}")
    if o.vsby_sm is not None and o.vsby_sm < VSBY_SM:
        reasons.append(f"vsby {o.vsby_sm}sm<{VSBY_SM}")
    if o.wxcodes:
        hit = sorted(_wx_groups(o.wxcodes) & WX_GROUPS)
        if hit:
            reasons.append("wx " + "/".join(hit))
    return reasons


def is_storm_obs(o: MetarObs) -> bool:
    return bool(storm_reasons(o))


# ---------- windows ----------

def _peak_kt(o: MetarObs) -> int:
    if o.gust is not None:
        return o.gust
    return o.sknt if o.sknt is not None else 0


def storm_windows(obs: Iterable[MetarObs]) -> list[StormWindow]:
    """Storm windows per station, sorted by (station, start). Independent of input order.

    ``peak_gust_kt`` is the highest gust (sustained wind when no gust is reported) of any obs inside the window;
    ``obs_count`` is the number of counting obs that formed it.
    """
    by_station: dict[str, list[MetarObs]] = {}
    for o in obs:
        by_station.setdefault(o.station, []).append(o)

    windows: list[StormWindow] = []
    for station in sorted(by_station):
        series = sorted(by_station[station], key=lambda o: (o.valid, o.raw))
        groups: list[list[MetarObs]] = []
        for o in series:
            if not is_storm_obs(o):
                continue
            if groups and o.valid - groups[-1][-1].valid < MERGE_GAP:
                groups[-1].append(o)
            else:
                groups.append([o])
        for g in groups:
            start, end = g[0].valid, g[-1].valid
            peak = max(_peak_kt(o) for o in series if start <= o.valid <= end)
            windows.append(StormWindow(station=station, start=start, end=end, peak_gust_kt=peak, obs_count=len(g)))
    return windows


# ---------- positions ----------

def _utc(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"naive datetime {t!r}: engine times must be tz-aware UTC")
    return t


def has_obs_near(t: datetime, obs: Iterable[MetarObs], tolerance: timedelta = OBS_TOLERANCE) -> bool:
    t = _utc(t)
    return any(abs(o.valid - t) <= tolerance for o in obs)


def window_at(t: datetime, windows: Iterable[StormWindow]) -> StormWindow | None:
    """The window containing ``t`` (edges inclusive), if any."""
    t = _utc(t)
    for w in windows:
        if w.start <= t <= w.end:
            return w
    return None


def position(t: datetime, obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> Position:
    """``unknown`` if no obs within +-60 min of ``t``; else ``in`` if ``t`` is inside a window (edges inclusive)."""
    if not has_obs_near(t, obs):
        return "unknown"
    return "in" if window_at(t, windows) is not None else "out"


def _minutes(td: timedelta) -> int:
    return round(td.total_seconds() / 60)


def margin_min(t: datetime, windows: Sequence[StormWindow]) -> int | None:
    """Signed minutes to the nearest window edge: positive = outside by that much, negative = inside, 0 = on an edge.

    ``None`` when there are no windows at all.
    """
    t = _utc(t)
    if not windows:
        return None
    inside = [w for w in windows if w.start <= t <= w.end]
    if inside:
        return -min(_minutes(min(t - w.start, w.end - t)) for w in inside)
    return min(_minutes(w.start - t) if t < w.start else _minutes(t - w.end) for w in windows)


@dataclass(frozen=True)
class EndPosition:
    """Where one end of a flight sits: departure (origin at STD) or arrival (destination at STA)."""
    end: Literal["dep", "arr"]
    at: datetime
    position: Position
    margin_min: int | None   # None when the position is unknown or the station had no window


def _end(end: Literal["dep", "arr"], t: datetime, obs: Sequence[MetarObs],
         windows: Sequence[StormWindow]) -> EndPosition:
    pos = position(t, obs, windows)
    return EndPosition(end=end, at=t, position=pos, margin_min=None if pos == "unknown" else margin_min(t, windows))


def departure_position(flight: Flight, obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> EndPosition:
    """Departure end: pass the ORIGIN station's obs and windows; evaluated at STD."""
    return _end("dep", flight.sched_dep, obs, windows)


def arrival_position(flight: Flight, obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> EndPosition:
    """Arrival end: pass the DESTINATION station's obs and windows; evaluated at STA."""
    return _end("arr", flight.sched_arr, obs, windows)
