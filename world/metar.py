"""Real METAR for any station and time range (F1).

Resolution order for every UTC day the range touches:
  1. pinned data in `data/pinned/`: a daily file `<ICAO>@<YYYY-MM-DD>.csv`, or any gzip bundle `<ICAO>_*.csv.gz`
     that contains rows for that day (bundles may be sparse; a day is pinned iff the bundle has rows for it);
  2. Iowa Environmental Mesonet `asos.py` (one request for the missing span; 1 request/s/IP, throttled);
  3. NOAA AWC `api/data/metar` (only when the range starts within the last 30 days).

`STORMCHECK_MODE=offline` stops after step 1. `fetch_metar` never returns an empty list: no data → `WorldError("no_metar")`.
Ranges are half-open `[start, end)` in UTC; naive datetimes are taken as UTC.

Pinned files are verbatim IEM `format=onlycomma` CSV: `station,valid,sknt,gust,drct,vsby,wxcodes,metar`.
"""
from __future__ import annotations

import csv
import gzip
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from contracts.models import MetarObs
from world.errors import WorldError

ROOT = Path(__file__).resolve().parent.parent
PINNED_DIR = ROOT / "data" / "pinned"

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
AWC_URL = "https://aviationweather.gov/api/data/metar"
IEM_FIELDS = ("sknt", "gust", "drct", "vsby", "wxcodes", "metar")
COLUMNS = ("station", "valid") + IEM_FIELDS
CSV_HEADER = ",".join(COLUMNS)
TIMEOUT_S = 8.0
AWC_MAX_AGE = timedelta(days=30)
RETRY_STATUS = frozenset({429, 502, 503, 504})
BACKOFF_BASE_S = 2.0
MAX_ATTEMPTS = 4
USER_AGENT = "StormCheck/0.1 (Cal Hacks 13.0 hackathon project; METAR for EU261 cause-finding)"
_ICAO_RE = re.compile(r"^[A-Z][A-Z0-9]{3}$")
_REPORT_PREFIX = re.compile(r"^(METAR|SPECI)\s+")


class UpstreamError(Exception):
    """A METAR provider failed (network, HTTP status, or unexpected body). Internal: fetch_metar falls through."""


# ---------------------------------------------------------------- throttle

class Throttle:
    """Spaces calls at least `min_interval` seconds apart (module-level, shared by every caller in the process)."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                delay = self._last + self.min_interval - self.clock()
                if delay > 0:
                    self.sleep(delay)
            self._last = self.clock()


IEM_THROTTLE = Throttle(1.0)   # IEM: 1 request/second/IP
AWC_THROTTLE = Throttle(1.0)   # AWC allows ~100/min; one per second is plenty


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 30.0)
    except ValueError:
        return None


def _get(url: str, params: Any, *, throttle: Throttle, timeout: float = TIMEOUT_S,
         attempts: int = MAX_ATTEMPTS, retry_transport_errors: bool = False) -> httpx.Response:
    """GET with throttle, retry on 429/5xx-busy (exponential backoff or Retry-After), and a hard timeout.

    Timeouts and connection errors are retried only when `retry_transport_errors` (the pin script); an interactive
    desk request should fall through to the next provider instead of stalling.
    """
    for attempt in range(attempts):
        last = attempt == attempts - 1
        throttle.wait()
        try:
            resp = httpx.get(url, params=params, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            if retry_transport_errors and not last:
                throttle.sleep(BACKOFF_BASE_S * 2 ** attempt)
                continue
            raise UpstreamError(f"{url}: {type(exc).__name__}: {exc}") from exc
        if resp.status_code in RETRY_STATUS and not last:
            throttle.sleep(_retry_after(resp) or BACKOFF_BASE_S * 2 ** attempt)
            continue
        if resp.status_code not in (200, 204):
            raise UpstreamError(f"{url}: HTTP {resp.status_code}")
        return resp
    raise UpstreamError(f"{url}: gave up after {attempts} attempts")  # pragma: no cover


# ---------------------------------------------------------------- parsing

def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if s in ("", "M", "T"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    v = _num(s)
    return None if v is None else round(v)


def _iem_rows(text: str) -> Iterator[list[str]]:
    """Yield canonical rows [station, valid, sknt, gust, drct, vsby, wxcodes, metar] from IEM onlycomma CSV."""
    reader = csv.reader(line for line in text.splitlines() if line and not line.startswith("#"))
    header = next(reader, None)
    if not header or "valid" not in header or "metar" not in header:
        raise UpstreamError(f"unexpected METAR CSV header: {header!r}")
    idx = {name: i for i, name in enumerate(header)}
    metar_i = idx["metar"]
    for row in reader:
        if len(row) <= metar_i:
            continue
        raw = ",".join(row[metar_i:]) if metar_i == len(header) - 1 else row[metar_i]
        yield [row[idx[c]] if c in idx else "" for c in COLUMNS[:-1]] + [raw]


MAX_GUST_SPREAD_KT = 50   # QC: a gust more than 50 kt above the mean wind is a corrupt report (e.g. EIDW 091130Z 35008G100KT)


def qc_gust(sknt: int | None, gust: int | None) -> int | None:
    """Drop physically implausible gusts (the raw METAR text is kept verbatim in `raw`)."""
    if gust is None:
        return None
    if gust - (sknt or 0) > MAX_GUST_SPREAD_KT:
        return None
    return gust


def _rows_to_obs(rows: Iterable[list[str]], icao: str) -> list[MetarObs]:
    seen: set[tuple[datetime, str]] = set()
    out: list[MetarObs] = []
    for row in rows:
        try:
            valid = datetime.strptime(row[1].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        except ValueError:
            continue
        raw = row[7].strip()
        key = (valid, raw)
        if key in seen:
            continue
        seen.add(key)
        wx = row[6].strip()
        sknt = _int(row[2])
        out.append(MetarObs(station=icao, valid=valid, sknt=sknt, gust=qc_gust(sknt, _int(row[3])), drct=_int(row[4]),
                            vsby_sm=_num(row[5]), wxcodes=wx or None, raw=raw))
    out.sort(key=lambda o: o.valid)
    return out


def parse_iem_csv(text: str, icao: str) -> list[MetarObs]:
    """Parse IEM `format=onlycomma` CSV. `station` is set to the requested ICAO (IEM drops the K of US sites)."""
    return _rows_to_obs(_iem_rows(text), icao)


def _awc_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().upper().replace("SM", "").replace("+", "").replace("P", "")
    try:
        return float(s)
    except ValueError:
        return None


def _awc_int(v: Any) -> int | None:
    f = _awc_float(v)
    return None if f is None else round(f)


def _awc_time(item: dict) -> datetime | None:
    t = item.get("obsTime")
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, UTC)
    for key in ("obsTime", "reportTime"):
        s = item.get(key)
        if isinstance(s, str) and s:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
            except ValueError:
                continue
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return None


def parse_awc_json(items: Any, icao: str) -> list[MetarObs]:
    """Parse NOAA AWC `api/data/metar?format=json` (fields rawOb, wspd, wgst, wdir, visib, wxString, obsTime)."""
    seen: set[tuple[datetime, str]] = set()
    out: list[MetarObs] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        raw = _REPORT_PREFIX.sub("", (item.get("rawOb") or "").strip())   # IEM raw has no "METAR "/"SPECI " prefix
        valid = _awc_time(item)
        if not raw or valid is None or (valid, raw) in seen:
            continue
        seen.add((valid, raw))
        wx = item.get("wxString")
        sknt = _awc_int(item.get("wspd"))
        out.append(MetarObs(station=icao, valid=valid, sknt=sknt,
                            gust=qc_gust(sknt, _awc_int(item.get("wgst"))), drct=_awc_int(item.get("wdir")),
                            vsby_sm=_awc_float(item.get("visib")), wxcodes=(wx.strip() or None) if wx else None,
                            raw=raw))
    out.sort(key=lambda o: o.valid)
    return out


# ---------------------------------------------------------------- providers

def _iso_minute(dt: datetime, *, ceil: bool = False) -> str:
    dt = dt.astimezone(UTC)
    if ceil and (dt.second or dt.microsecond):
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def iem_params(icao: str, start: datetime, end: datetime) -> list[tuple[str, str]]:
    return ([("station", icao)] + [("data", f) for f in IEM_FIELDS]
            + [("sts", _iso_minute(start)), ("ets", _iso_minute(end, ceil=True)), ("tz", "Etc/UTC"),
               ("format", "onlycomma"), ("missing", "empty"), ("report_type", "3"), ("report_type", "4")])


def iem_request(icao: str, start: datetime, end: datetime, *, timeout: float = TIMEOUT_S,
                retry_transport_errors: bool = False) -> str:
    """One throttled IEM asos.py request; returns the raw CSV text (header + rows)."""
    resp = _get(IEM_URL, iem_params(icao, start, end), throttle=IEM_THROTTLE, timeout=timeout,
                retry_transport_errors=retry_transport_errors)
    text = resp.text
    if not text.startswith("station,valid"):
        raise UpstreamError(f"IEM returned an unexpected body: {text[:160]!r}")
    return text


def fetch_iem(icao: str, start: datetime, end: datetime, *, timeout: float = TIMEOUT_S) -> list[MetarObs]:
    return [o for o in parse_iem_csv(iem_request(icao, start, end, timeout=timeout), icao) if start <= o.valid < end]


def fetch_awc(icao: str, start: datetime, end: datetime, *, timeout: float = TIMEOUT_S) -> list[MetarObs]:
    hours = max(1, min(int(AWC_MAX_AGE.total_seconds() // 3600), math.ceil((_now() - start).total_seconds() / 3600) + 1))
    resp = _get(AWC_URL, {"ids": icao, "format": "json", "hours": str(hours)}, throttle=AWC_THROTTLE, timeout=timeout)
    if resp.status_code == 204 or not resp.content.strip():
        return []
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamError(f"AWC returned non-JSON: {resp.text[:160]!r}") from exc
    return [o for o in parse_awc_json(data, icao) if start <= o.valid < end]


# ---------------------------------------------------------------- pinned data

def daily_pin_path(icao: str, day: date) -> Path:
    return PINNED_DIR / f"{icao}@{day.isoformat()}.csv"


@lru_cache(maxsize=1024)
def _daily_rows(path: str) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(r) for r in _iem_rows(Path(path).read_text()))


@lru_cache(maxsize=64)
def _bundle_index(path: str) -> dict[str, tuple[tuple[str, ...], ...]]:
    days: dict[str, list[tuple[str, ...]]] = {}
    with gzip.open(path, "rt", newline="") as fh:
        text = fh.read()
    for row in _iem_rows(text):
        days.setdefault(row[1][:10], []).append(tuple(row))
    return {d: tuple(rows) for d, rows in days.items()}


def _bundles(icao: str) -> list[Path]:
    return sorted(PINNED_DIR.glob(f"{icao}_*.csv.gz"))


def pinned_day(icao: str, day: date) -> list[MetarObs] | None:
    """All pinned obs for one UTC day, or None when that day is not pinned (daily file first, then bundles)."""
    p = daily_pin_path(icao, day)
    if p.exists():
        return _rows_to_obs(_daily_rows(str(p)), icao)
    key = day.isoformat()
    for bundle in _bundles(icao):
        rows = _bundle_index(str(bundle)).get(key)
        if rows:
            return _rows_to_obs(rows, icao)
    return None


def pinned_dates(icao: str) -> list[date]:
    """Every UTC day with pinned METAR for `icao` (daily files and bundles)."""
    icao = normalize_icao(icao)
    days = {date.fromisoformat(p.name[len(icao) + 1:-4]) for p in PINNED_DIR.glob(f"{icao}@????-??-??.csv")}
    for bundle in _bundles(icao):
        days.update(date.fromisoformat(d) for d in _bundle_index(str(bundle)))
    return sorted(days)


# ---------------------------------------------------------------- public API

def mode() -> str:
    return (os.environ.get("STORMCHECK_MODE") or "cache").strip().lower()


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _utc_days(start: datetime, end: datetime) -> list[date]:
    d, last = start.date(), (end - timedelta(microseconds=1)).date()
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def normalize_icao(code: str) -> str:
    s = (code or "").strip().upper()
    if not _ICAO_RE.match(s):
        raise WorldError("unknown_airport", f"'{code}' is not an ICAO station code (four characters, e.g. EIDW).")
    return s


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%MZ")


_MEMO: dict[tuple[str, datetime, datetime], list[MetarObs]] = {}
_MEMO_MAX = 256


def _fetch_network(icao: str, start: datetime, end: datetime) -> list[MetarObs]:
    key = (icao, start, end)
    if key in _MEMO:
        return list(_MEMO[key])
    obs: list[MetarObs] = []
    try:
        obs = fetch_iem(icao, start, end)
    except UpstreamError:
        obs = []
    if not obs and _now() - start <= AWC_MAX_AGE:
        try:
            obs = fetch_awc(icao, start, end)
        except UpstreamError:
            obs = []
    if obs and end <= _now() - timedelta(hours=3):   # only memo ranges that can no longer grow
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[key] = obs
    return list(obs)


def fetch_metar(icao: str, start: datetime, end: datetime) -> list[MetarObs]:
    """METAR obs for `icao` with `start <= valid < end` (UTC), sorted. Pinned → IEM → AWC (see module doc).

    Raises WorldError: `unknown_airport` (not an ICAO code), `future_date` (start after now), `no_metar` (nothing found).
    """
    icao = normalize_icao(icao)
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError(f"fetch_metar: end {end} must be after start {start}")
    now = _now()
    if start > now:
        raise WorldError("future_date", f"{_fmt(start)} is in the future; METAR only exists for past hours.")

    pinned: list[MetarObs] = []
    missing: list[date] = []
    for day in _utc_days(start, end):
        day_obs = pinned_day(icao, day)
        if day_obs is None:
            missing.append(day)
        else:
            pinned.extend(o for o in day_obs if start <= o.valid < end)

    if not missing:
        if pinned:
            return pinned
        raise WorldError("no_metar", f"No METAR reports for {icao} between {_fmt(start)} and {_fmt(end)}.")
    if mode() == "offline":
        if pinned:
            return pinned
        raise WorldError("no_metar", f"No pinned METAR for {icao} between {_fmt(start)} and {_fmt(end)}, "
                                     "and offline mode uses pinned data only.")

    span_start = max(start, datetime.combine(missing[0], datetime.min.time(), UTC))
    span_end = min(end, datetime.combine(missing[-1] + timedelta(days=1), datetime.min.time(), UTC), now)
    fetched = _fetch_network(icao, span_start, span_end) if span_end > span_start else []
    pinned_days = {d for d in _utc_days(start, end)} - set(missing)
    merged = pinned + [o for o in fetched if o.valid.date() not in pinned_days]
    if merged:
        merged.sort(key=lambda o: o.valid)
        return merged
    raise WorldError("no_metar", f"No METAR found for {icao} between {_fmt(start)} and {_fmt(end)} "
                                 "(checked pinned data, Iowa Environmental Mesonet and NOAA AWC).")


def fetch_day(icao: str, day: date) -> list[MetarObs]:
    """Convenience: one whole UTC day."""
    start = datetime.combine(day, datetime.min.time(), UTC)
    return fetch_metar(icao, start, start + timedelta(days=1))


# ---------------------------------------------------------------- storm-day selection (used by F3a and pin_metar)

_WX_STORM = ("SN", "FZ", "TS", "GR")


def storm_conditions(o: MetarObs) -> bool:
    """Plan §1.2 window criteria for one report: gust>=35kt or sknt>=30kt or vsby<0.5sm or wx in {SN,FZ,TS,GR}.

    Used only to *select* storm days; the engine's `timeline.py` computes windows itself.
    """
    return ((o.gust or 0) >= 35 or (o.sknt or 0) >= 30 or (o.vsby_sm is not None and o.vsby_sm < 0.5)
            or any(code in (o.wxcodes or "") for code in _WX_STORM))


@dataclass(frozen=True)
class DaySummary:
    station: str
    day: date
    obs: int
    max_gust: int | None
    max_sknt: int | None
    hours_gust_ge: int            # distinct clock hours with at least one report of gust >= threshold
    first_ge: datetime | None
    last_ge: datetime | None
    hours_storm: int = 0          # distinct clock hours with any storm_conditions() report


def summarize_days(obs: Iterable[MetarObs], gust_kt: int = 35, tz: str | None = None) -> list[DaySummary]:
    """Per-day gust summary. Days (and clock hours) are UTC, or local to `tz` (IANA name) when given."""
    zone = ZoneInfo(tz) if tz else UTC
    by_day: dict[date, list[MetarObs]] = {}
    for o in obs:
        by_day.setdefault(o.valid.astimezone(zone).date(), []).append(o)
    out = []
    for day in sorted(by_day):
        day_obs = sorted(by_day[day], key=lambda o: o.valid)
        strong = [o for o in day_obs if (o.gust or 0) >= gust_kt]
        gusts = [o.gust for o in day_obs if o.gust is not None]
        sknts = [o.sknt for o in day_obs if o.sknt is not None]
        out.append(DaySummary(station=day_obs[0].station, day=day, obs=len(day_obs),
                              max_gust=max(gusts) if gusts else None, max_sknt=max(sknts) if sknts else None,
                              hours_gust_ge=len({o.valid.astimezone(zone).hour for o in strong}),
                              first_ge=strong[0].valid if strong else None, last_ge=strong[-1].valid if strong else None,
                              hours_storm=len({o.valid.astimezone(zone).hour for o in day_obs if storm_conditions(o)})))
    return out


def storm_days(obs: Iterable[MetarObs], gust_kt: int = 35, min_hours: int = 3) -> list[DaySummary]:
    """UTC days with gust >= `gust_kt` reported in at least `min_hours` distinct clock hours (plan §5 selection rule)."""
    return [s for s in summarize_days(obs, gust_kt) if s.hours_gust_ge >= min_hours]
