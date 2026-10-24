"""Pin real METAR into `data/pinned/` so the demo, tests and offline mode never need the network.

    uv run python -m world.pin_metar all            # everything below, in order
    uv run python -m world.pin_metar eidw           # EIDW 2023-07-01 → 2025-07-01 in ONE request → gz bundle + demo days
    uv run python -m world.pin_metar judge          # judge-likely storm days, one request per station
    uv run python -m world.pin_metar recent         # last 7 complete UTC days at EIDW (re-run before the demo)
    uv run python -m world.pin_metar storm-days     # data/pinned/STORM_DAYS.md from the EIDW bundle (no network)
    uv run python -m world.pin_metar network        # outstation METAR for every generator world day (F3a)

IEM allows 1 request/second/IP: every request goes through `metar.IEM_THROTTLE`, set here to 1.5 s spacing.
Raw responses are kept in `--raw-dir` (default /tmp/stormcheck_iem_raw) so re-runs don't re-fetch.
Pinned CSVs are the verbatim IEM rows for each UTC day (header + rows); gzip is written with mtime=0 (deterministic).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from world import metar
from world.metar import CSV_HEADER, PINNED_DIR, DaySummary, MetarObs, iem_request, parse_iem_csv, summarize_days

PIN_SPACING_S = 1.5
BULK_TIMEOUT_S = 300.0
GUST_KT = 35
MIN_HOURS = 3

EIDW_BUNDLE = ("EIDW", date(2023, 7, 1), date(2025, 7, 1))
DEMO_DAYS = [date(2025, 1, 23), date(2025, 1, 24), date(2025, 1, 25),   # Éowyn
             date(2025, 1, 26),                                          # Herminia
             date(2024, 1, 21)]                                          # Isha (opening-balance cohort)
JUDGE_STATIONS = ["EGLL", "EHAM", "LFPG", "EDDF", "LEBL", "EGCC", "KBOS", "KJFK", "KORD"]
JUDGE_SEARCH = (date(2023, 7, 1), date(2025, 7, 1))
CANDIDATES = {"EU": [date(2024, 1, 21), date(2023, 11, 2)], "US": [date(2024, 1, 9), date(2024, 1, 10)]}
STATION_TZ = {"EIDW": "Europe/Dublin", "EGLL": "Europe/London", "EHAM": "Europe/Amsterdam", "LFPG": "Europe/Paris",
              "EDDF": "Europe/Berlin", "LEBL": "Europe/Madrid", "EGCC": "Europe/London", "KBOS": "America/New_York",
              "KJFK": "America/New_York", "KORD": "America/Chicago"}

# Named storms (Met Éireann / UK Met Office / KNMI / AEMET naming lists), matched to EIDW storm days by date only.
NAMED_STORMS = {
    date(2023, 9, 27): "Agnes", date(2023, 10, 18): "Babet", date(2023, 10, 19): "Babet",
    date(2023, 11, 1): "Ciarán", date(2023, 11, 2): "Ciarán", date(2023, 11, 13): "Debi",
    date(2023, 12, 9): "Elin", date(2023, 12, 10): "Fergus", date(2023, 12, 27): "Gerrit",
    date(2023, 12, 28): "Gerrit", date(2024, 1, 2): "Henk", date(2024, 1, 21): "Isha", date(2024, 1, 22): "Isha",
    date(2024, 1, 23): "Jocelyn", date(2024, 1, 24): "Jocelyn", date(2024, 4, 6): "Kathleen",
    date(2024, 8, 22): "Lilian", date(2024, 8, 23): "Lilian", date(2024, 10, 20): "Ashley",
    date(2024, 11, 23): "Bert", date(2024, 11, 24): "Bert", date(2024, 11, 26): "Conall",
    date(2024, 12, 6): "Darragh", date(2024, 12, 7): "Darragh", date(2025, 1, 24): "Éowyn",
    date(2025, 1, 26): "Herminia", date(2025, 1, 27): "Herminia",
}


def _midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), UTC)


def fetch_raw(icao: str, start: date, end: date, raw_dir: Path) -> str:
    """One IEM request for [start, end) UTC days, cached verbatim in raw_dir."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache = raw_dir / f"{icao}_{start.isoformat()}_{end.isoformat()}.csv"
    if cache.exists():
        print(f"  cached  {cache.name}")
        return cache.read_text()
    print(f"  IEM     {icao} {start} → {end} ...", flush=True)
    text = iem_request(icao, _midnight(start), _midnight(end), timeout=BULK_TIMEOUT_S, retry_transport_errors=True)
    cache.write_text(text)
    print(f"          {len(text.splitlines()) - 1} rows, {len(text) / 1e6:.1f} MB")
    return text


def split_by_day(text: str) -> dict[date, list[str]]:
    """Raw IEM data lines grouped by UTC day of the `valid` column (header dropped)."""
    days: dict[date, list[str]] = {}
    for line in text.splitlines()[1:]:
        if not line or line.startswith("#"):
            continue
        valid = line.split(",", 2)[1]
        days.setdefault(date.fromisoformat(valid[:10]), []).append(line)
    return days


def write_daily(icao: str, day: date, lines: list[str]) -> Path:
    path = PINNED_DIR / f"{icao}@{day.isoformat()}.csv"
    path.write_text(CSV_HEADER + "\n" + "\n".join(lines) + "\n")
    return path


def write_gz(path: Path, text: str) -> None:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(text.encode())
    path.write_bytes(buf.getvalue())


def _canonical(text: str) -> str:
    lines = text.splitlines()
    assert lines and lines[0] == CSV_HEADER, f"unexpected IEM header {lines[:1]!r}"
    return "\n".join(lines) + "\n"


def local_day_utc_dates(icao: str, day: date) -> list[date]:
    """UTC days overlapping the station's local calendar day (so generate_day's local-day fetch is fully pinned)."""
    tz = ZoneInfo(STATION_TZ.get(icao, "UTC"))
    start = datetime.combine(day, datetime.min.time(), tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tz).astimezone(UTC) - timedelta(seconds=1)
    out, d = [], start.date()
    while d <= end.date():
        out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- commands

def cmd_eidw(raw_dir: Path) -> None:
    icao, start, end = EIDW_BUNDLE
    print(f"EIDW bundle {start} → {end} (one request)")
    text = _canonical(fetch_raw(icao, start, end, raw_dir))
    bundle = PINNED_DIR / f"{icao}_{start:%Y-%m}_{end:%Y-%m}.csv.gz"
    write_gz(bundle, text)
    days = split_by_day(text)
    print(f"  wrote {bundle.name}: {sum(len(v) for v in days.values())} rows over {len(days)} days, "
          f"{bundle.stat().st_size / 1e6:.2f} MB")
    for d in DEMO_DAYS:
        print(f"  demo    {write_daily(icao, d, days[d]).name} ({len(days[d])} rows)")


@dataclass
class JudgePick:
    station: str
    local_day: date
    summary: DaySummary
    why: str
    utc_days: list[date]


def pick_judge_days(icao: str, obs: list[MetarObs]) -> list[JudgePick]:
    """Day 1 = highest max gust in the search range (by local day); day 2 = the candidate date with the most
    storm-condition hours (gust/sustained/visibility/wx, plan §1.2) if >= 3, else the runner-up by max gust."""
    tz = STATION_TZ[icao]
    sums = summarize_days(obs, GUST_KT, tz=tz)
    ranked = sorted(sums, key=lambda s: ((s.max_gust or 0), s.hours_gust_ge, s.day), reverse=True)
    picks = [JudgePick(icao, ranked[0].day, ranked[0], "highest max gust Jul 2023 → Jun 2025", [])]
    by_day = {s.day: s for s in sums}
    region = "US" if icao.startswith("K") else "EU"
    cands = [by_day[d] for d in CANDIDATES[region] if d in by_day and d != picks[0].local_day
             and by_day[d].hours_storm >= MIN_HOURS]
    if cands:
        best = max(cands, key=lambda s: (s.hours_storm, (s.max_gust or 0)))
        picks.append(JudgePick(icao, best.day, best, "candidate date", []))
    else:
        stormy = [s for s in ranked[1:] if s.hours_storm >= MIN_HOURS] or ranked[1:]
        nxt = stormy[0]
        picks.append(JudgePick(icao, nxt.day, nxt, f"runner-up max gust with ≥{MIN_HOURS} h storm conditions", []))
    for p in picks:
        p.utc_days = local_day_utc_dates(icao, p.local_day)
    return picks


def cmd_judge(raw_dir: Path) -> list[JudgePick]:
    start, end = JUDGE_SEARCH
    all_picks: list[JudgePick] = []
    for icao in JUDGE_STATIONS:
        print(f"{icao} search {start} → {end} (one request)")
        text = _canonical(fetch_raw(icao, start, end, raw_dir))
        obs = parse_iem_csv(text, icao)
        days = split_by_day(text)
        # Sparse bundle: every storm day (EIDW rule: gust >= 35 kt in >= 3 h, by local day) so judges' storm dates
        # work offline too. The loader treats a day as pinned iff the bundle has rows for it.
        storm_utc: set[date] = set()
        for s in summarize_days(obs, GUST_KT, tz=STATION_TZ[icao]):
            if s.hours_gust_ge >= MIN_HOURS:
                storm_utc.update(local_day_utc_dates(icao, s.day))
        bundle = PINNED_DIR / f"{icao}_storms_{start:%Y-%m}_{end:%Y-%m}.csv.gz"
        write_gz(bundle, CSV_HEADER + "\n" + "".join(line + "\n" for d in sorted(storm_utc) if d in days
                                                          for line in days[d]))
        print(f"  storms  {bundle.name}: {len(storm_utc)} UTC days, {bundle.stat().st_size / 1e3:.0f} kB")
        for p in pick_judge_days(icao, obs):
            s = p.summary
            print(f"  pick    {icao} local {p.local_day} max G{s.max_gust} kt, {s.hours_gust_ge} h ≥{GUST_KT} kt, "
                  f"{s.hours_storm} h storm conditions "
                  f"({p.why}); UTC days {[d.isoformat() for d in p.utc_days]}")
            for d in p.utc_days:
                if d in days:
                    write_daily(icao, d, days[d])
            all_picks.append(p)
    write_judge_md(all_picks)
    return all_picks


def cmd_recent(raw_dir: Path, n: int = 7) -> None:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=n)
    print(f"EIDW last {n} complete UTC days {start} → {today - timedelta(days=1)} (one request)")
    cache = raw_dir / f"EIDW_{start.isoformat()}_{today.isoformat()}.csv"
    cache.unlink(missing_ok=True)   # recent data may still be arriving; always refetch
    text = _canonical(fetch_raw("EIDW", start, today, raw_dir))
    for d, lines in sorted(split_by_day(text).items()):
        if start <= d < today:
            print(f"  recent  {write_daily('EIDW', d, lines).name} ({len(lines)} rows)")


def cmd_storm_days() -> None:
    icao, start, end = EIDW_BUNDLE
    obs: list[MetarObs] = []
    d = start
    while d < end:
        obs.extend(metar.pinned_day(icao, d) or [])
        d += timedelta(days=1)
    sums = summarize_days(obs, GUST_KT)
    storms = [s for s in sums if s.hours_gust_ge >= MIN_HOURS]
    near = [s for s in sums if 1 <= s.hours_gust_ge < MIN_HOURS]
    bundle = PINNED_DIR / f"{icao}_{start:%Y-%m}_{end:%Y-%m}.csv.gz"
    sha = hashlib.sha256(bundle.read_bytes()).hexdigest()[:16]
    t = lambda x: x.strftime("%H:%MZ") if x else ""
    lines = [
        "# EIDW storm days (real METAR, Jul 2023 → Jun 2025)",
        "",
        f"Generated by `uv run python -m world.pin_metar storm-days` from `{bundle.name}` (sha256 {sha}…).",
        (f"**Rule (plan §5):** a UTC day is a storm day when a gust ≥{GUST_KT} kt is reported in at least "
        f"{MIN_HOURS} distinct UTC clock hours (routine + SPECI reports)."),
        "Storm names are matched by date from the public naming lists; the selection itself uses only the data.",
        "",
        (f"**{len(storms)} storm days** out of {len(sums)} days with data "
        f"({sum(1 for s in storms if s.day < date(2025, 1, 1))} in the learn split Jul 2023 → Dec 2024, "
        f"{sum(1 for s in storms if s.day >= date(2025, 1, 1))} in the score split Jan → Jun 2025)."),
        "",
        f"| UTC day | named storm | max gust kt | max sustained kt | hours with gust ≥{GUST_KT} | first ≥{GUST_KT} | last ≥{GUST_KT} | split |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in storms:
        split = "learn" if s.day < date(2025, 1, 1) else "score"
        lines.append(f"| {s.day} | {NAMED_STORMS.get(s.day, '')} | {s.max_gust} | {s.max_sknt} | {s.hours_gust_ge} | "
                     f"{t(s.first_ge)} | {t(s.last_ge)} | {split} |")
    lines += ["", f"Near misses (gust ≥{GUST_KT} kt in 1–{MIN_HOURS - 1} hours): "
              + ", ".join(f"{s.day} ({s.hours_gust_ge} h, G{s.max_gust}"
                          + (f", {NAMED_STORMS[s.day]}" if s.day in NAMED_STORMS else "") + ")" for s in near) + ".", ""]
    named_missing = sorted({n for d, n in NAMED_STORMS.items()} - {NAMED_STORMS.get(s.day) for s in storms})
    if named_missing:
        lines += [f"Named storms with no qualifying EIDW day: {', '.join(named_missing)}.", ""]
    (PINNED_DIR / "STORM_DAYS.md").write_text("\n".join(lines))
    print(f"wrote STORM_DAYS.md: {len(storms)} storm days")


NETWORK_SPAN = (date(2023, 7, 1), date(2025, 7, 1))
NETWORK_TIMEOUT_S = 8.0


def _network_runs(days: list[date]) -> list[tuple[date, date]]:
    """Contiguous [start, end) UTC-day ranges covering D-1 and D for every world day D (one IEM request each)."""
    need = sorted({d - timedelta(days=k) for d in days for k in (0, 1)})
    runs: list[tuple[date, date]] = []
    for d in need:
        if runs and runs[-1][1] == d:
            runs[-1] = (runs[-1][0], d + timedelta(days=1))
        else:
            runs.append((d, d + timedelta(days=1)))
    return runs


def _row_icao(line: str) -> str:
    """ICAO for an IEM row: the head of the raw METAR (IEM writes BOS for KBOS), else the station column."""
    cols = line.split(",", 7)
    head = cols[7].split()[0] if len(cols) > 7 and cols[7].split() else ""
    if len(head) == 4 and head.isalpha():
        return head
    st = cols[0]
    return st if len(st) == 4 else "K" + st


def cmd_network(raw_dir: Path) -> None:
    """Outstation METAR for the generator's world days, one multi-station IEM request per contiguous run.

    Kept rows: UTC day D for every station, plus D-1 for North American stations (long-haul inbounds leave the
    evening before). Written as sparse per-station bundles `<ICAO>_world_2023-07_2025-07.csv.gz`.
    """
    from world import days as world_days, network
    from world.airports import airport

    wdays = [w.day for w in world_days.world_days()]
    stations = [airport(c).icao for c in network.ROUTES]
    na = {airport(c).icao for c in network.ROUTES if airport(c).country in ("US", "CA")}
    keep: dict[str, set[date]] = {s: set(wdays) | ({d - timedelta(days=1) for d in wdays} if s in na else set())
                                  for s in stations}
    rows: dict[str, dict[date, list[str]]] = {s: {} for s in stations}
    raw_dir.mkdir(parents=True, exist_ok=True)
    for start, end in _network_runs(wdays):
        cache = raw_dir / f"NETWORK_{start.isoformat()}_{end.isoformat()}.csv"
        if cache.exists():
            text = cache.read_text()
        else:
            params = ([("station", s) for s in stations] + [("data", f) for f in metar.IEM_FIELDS]
                      + [("sts", f"{start.isoformat()}T00:00Z"), ("ets", f"{end.isoformat()}T00:00Z"),
                         ("tz", "Etc/UTC"), ("format", "onlycomma"), ("missing", "empty"),
                         ("report_type", "3"), ("report_type", "4")])
            print(f"  IEM     {len(stations)} stations {start} → {end} ...", flush=True)
            resp = metar._get(metar.IEM_URL, params, throttle=metar.IEM_THROTTLE, timeout=NETWORK_TIMEOUT_S,
                              retry_transport_errors=True)
            text = _canonical(resp.text)
            cache.write_text(text)
        for line in text.splitlines()[1:]:
            if not line or line.startswith("#"):
                continue
            icao = _row_icao(line)
            d = date.fromisoformat(line.split(",", 2)[1][:10])
            if icao in rows and d in keep[icao]:
                rows[icao].setdefault(d, []).append(line)
    start, end = NETWORK_SPAN
    total = 0
    for icao in stations:
        bundle = PINNED_DIR / f"{icao}_world_{start:%Y-%m}_{end:%Y-%m}.csv.gz"
        write_gz(bundle, CSV_HEADER + "\n" + "".join(line + "\n" for d in sorted(rows[icao]) for line in rows[icao][d]))
        total += bundle.stat().st_size
        print(f"  world   {bundle.name}: {len(rows[icao])} UTC days")
    print(f"  total   {total / 1e6:.2f} MB")


def write_judge_md(picks: list[JudgePick]) -> None:
    lines = ["# Judge-station storm days (real METAR, pinned)", "",
             "Generated by `uv run python -m world.pin_metar judge`: one IEM request per station for Jul 2023 → Jun 2025,",
             "days ranked by max gust per **local** day. Day 1 = highest max gust; day 2 = the candidate date",
             (f"(EU {', '.join(map(str, CANDIDATES['EU']))}; US {', '.join(map(str, CANDIDATES['US']))}) with the most "
             f"storm-condition hours (gust ≥35 kt, sustained ≥30 kt, visibility <0.5 SM or SN/FZ/TS/GR) if ≥{MIN_HOURS}, "
             "else the runner-up by max gust. Each pick pins every UTC day its local day overlaps."), "",
             (f"Every other storm day at these stations (gust ≥{GUST_KT} kt in ≥{MIN_HOURS} local clock hours, the EIDW "
             "rule) is also pinned, in the sparse bundles `<ICAO>_storms_2023-07_2025-07.csv.gz`, so judges' storm "
             "dates work offline."), "",
             f"| station | local day | max gust kt | hours gust ≥{GUST_KT} | hours storm conditions | why | pinned UTC days |",
             "|---|---|---|---|---|---|---|"]
    for p in picks:
        lines.append(f"| {p.station} | {p.local_day} | {p.summary.max_gust} | {p.summary.hours_gust_ge} | "
                     f"{p.summary.hours_storm} | {p.why} | "
                     + ", ".join(f"`{p.station}@{d}.csv`" for d in p.utc_days) + " |")
    (PINNED_DIR / "JUDGE_DAYS.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["all", "eidw", "judge", "recent", "storm-days", "network"])
    ap.add_argument("--raw-dir", type=Path, default=Path("/tmp/stormcheck_iem_raw"))
    args = ap.parse_args(argv)
    metar.IEM_THROTTLE.min_interval = PIN_SPACING_S
    PINNED_DIR.mkdir(parents=True, exist_ok=True)
    if args.command in ("all", "eidw"):
        cmd_eidw(args.raw_dir)
    if args.command in ("all", "storm-days"):
        cmd_storm_days()
    if args.command in ("all", "judge"):
        cmd_judge(args.raw_dir)
    if args.command in ("all", "recent"):
        cmd_recent(args.raw_dir)
    if args.command in ("all", "network"):
        cmd_network(args.raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
