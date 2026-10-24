"""D1 · storm windows and in/out/unknown positions, on the REAL pinned IEM METAR (Éowyn, Herminia)."""
from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import Flight, MetarObs
from engine.timeline import (
    arrival_position,
    departure_position,
    is_storm_obs,
    load_iem_csv,
    margin_min,
    position,
    storm_windows,
)

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
EOWYN_CSV = GOLDEN / "eidw_2025-01-23_25.csv"
HERMINIA_CSV = GOLDEN / "eidw_2025-01-26.csv"


def z(hhmm: str, day: int = 24) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2025, 1, day, int(h), int(m), tzinfo=UTC)


def near(a: datetime, b: datetime, minutes: int = 30) -> bool:
    return abs(a - b) <= timedelta(minutes=minutes)


@pytest.fixture(scope="module")
def eowyn() -> list[MetarObs]:
    return load_iem_csv(EOWYN_CSV)


@pytest.fixture(scope="module")
def eowyn_windows(eowyn):
    return storm_windows(eowyn)


@pytest.fixture(scope="module")
def main_window(eowyn_windows):
    return max(eowyn_windows, key=lambda w: w.end - w.start)


# ---------- load_iem_csv ----------

def test_load_iem_csv_parses_real_file(eowyn):
    assert len(eowyn) == 60
    first = eowyn[0]
    assert first.station == "EIDW"
    assert first.valid == datetime(2025, 1, 23, 18, 0, tzinfo=UTC)
    assert first.valid.tzinfo is not None and first.valid.utcoffset() == timedelta(0)
    assert first.sknt == 6 and first.drct == 210
    assert first.gust is None                      # empty gust column -> None
    assert first.vsby_sm == pytest.approx(6.21)
    assert first.wxcodes is None                   # empty wxcodes -> None
    assert first.raw.startswith("EIDW 231800Z 21006KT")
    rain = next(o for o in eowyn if o.valid == z("22:00", 23))
    assert rain.wxcodes == "-RA"
    peak = next(o for o in eowyn if o.valid == z("07:00"))
    assert peak.gust == 56 and peak.sknt == 28
    assert [o.valid for o in eowyn] == sorted(o.valid for o in eowyn)


def test_load_iem_csv_missing_markers(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(
        "station,valid,sknt,gust,drct,vsby,wxcodes,metar\n"
        "BOS,2025-01-24 00:00,M,M,M,M,M,KBOS 240000Z AUTO 00000KT\n"
        "BOS,2025-01-24 00:30,12.00,,250.00,0.25,FZFG,KBOS 240030Z 25012KT 1/4SM FZFG\n"
    )
    obs = load_iem_csv(p)
    assert obs[0].station == "KBOS"                # ICAO from the raw METAR, not IEM's 3-letter id
    assert obs[0].sknt is None and obs[0].gust is None and obs[0].vsby_sm is None and obs[0].wxcodes is None
    assert obs[1].vsby_sm == 0.25 and obs[1].wxcodes == "FZFG"
    assert load_iem_csv(p, station="XXXX")[0].station == "XXXX"


# ---------- storm criteria ----------

def _obs(t: datetime, **kw) -> MetarObs:
    return MetarObs(station=kw.pop("station", "TEST"), valid=t, raw=kw.pop("raw", "TEST"), **kw)


@pytest.mark.parametrize(
    "kw,expected",
    [
        ({"gust": 35}, True), ({"gust": 34}, False),
        ({"sknt": 30}, True), ({"sknt": 29}, False),
        ({"vsby_sm": 0.49}, True), ({"vsby_sm": 0.5}, False),
        ({"wxcodes": "-SN"}, True), ({"wxcodes": "BLSN"}, True), ({"wxcodes": "FZFG"}, True),
        ({"wxcodes": "-FZRA BR"}, True), ({"wxcodes": "VCTS"}, True), ({"wxcodes": "+TSRAGR"}, True),
        ({"wxcodes": "-RA"}, False), ({"wxcodes": "-RADZ"}, False), ({"wxcodes": "BR"}, False),
        ({"wxcodes": "NSW"}, False), ({}, False),
    ],
)
def test_storm_criteria(kw, expected):
    assert is_storm_obs(_obs(z("12:00"), **kw)) is expected


# ---------- Éowyn windows (real data) ----------

def test_main_window_is_0230_to_1500(main_window):
    assert near(main_window.start, z("02:30"))
    assert near(main_window.end, z("15:00"))
    assert main_window.station == "EIDW"
    assert main_window.peak_gust_kt == 56


def test_eowyn_windows_pinned_exact(eowyn_windows):
    """Exact values the pinned data produces (see engine/DECISIONS.md D1)."""
    got = [(w.start, w.end, w.peak_gust_kt, w.obs_count) for w in eowyn_windows]
    assert got == [
        (z("23:30", 23), z("00:30"), 38, 2),
        (z("02:30"), z("15:00"), 56, 24),   # 18 obs 02:30-11:00, 4 obs 12:00-13:30, 14:30, 15:00
    ]


def test_minor_window_detected_separately(eowyn_windows, main_window):
    minor = [w for w in eowyn_windows if w is not main_window]
    assert len(minor) == 1
    m = minor[0]
    assert near(m.start, z("23:30", 23)) and near(m.end, z("00:30"))
    # 00:30 -> 02:30 is exactly 2 h: "gaps under 2 h" do not merge, so the windows stay separate
    assert main_window.start - m.end >= timedelta(hours=2)


def test_window_never_hardcoded_follows_data(eowyn):
    # drop the 15:00 obs: the window must end earlier (14:30), proving it is computed from data
    trimmed = [o for o in eowyn if o.valid != z("15:00")]
    main = max(storm_windows(trimmed), key=lambda w: w.end - w.start)
    assert main.end == z("14:30")


def test_1630_out_with_margin_ge_60(eowyn, eowyn_windows):
    assert position(z("16:30"), eowyn, eowyn_windows) == "out"
    assert margin_min(z("16:30"), eowyn_windows) >= 60
    assert margin_min(z("16:30"), eowyn_windows) == 90


OUTBOUND_WEATHER_STD = {
    "NS100": "06:10", "NS102": "06:40", "NS104": "07:05", "NS106": "07:30", "NS108": "08:15",
    "NS110": "09:00", "NS112": "09:40", "NS114": "10:20", "NS116": "11:00", "NS21": "11:05",
    "NS41": "12:10", "NS51": "13:00", "NS118": "12:40",
}
RETURN_WEATHER_STA = {"NS101": "09:15", "NS103": "10:30", "NS105": "10:40", "NS107": "11:20",
                      "NS109": "13:40", "NS111": "14:20"}
OVERNIGHT_INBOUND_STA = {"NS20": "05:50", "NS30": "05:30", "NS40": "05:40", "NS50": "05:35"}
KNOCK_ON_STA = {"NS113": "15:55", "NS115": "17:00", "NS117": "16:20"}


def test_all_13_outbound_weather_std_in(eowyn, eowyn_windows):
    assert len(OUTBOUND_WEATHER_STD) == 13
    for flight, std in OUTBOUND_WEATHER_STD.items():
        assert position(z(std), eowyn, eowyn_windows) == "in", flight
        assert margin_min(z(std), eowyn_windows) <= 0, flight


def test_return_sectors_sta_in(eowyn, eowyn_windows):
    for flight, sta in RETURN_WEATHER_STA.items():
        assert position(z(sta), eowyn, eowyn_windows) == "in", flight


def test_overnight_inbounds_sta_in(eowyn, eowyn_windows):
    for flight, sta in OVERNIGHT_INBOUND_STA.items():
        assert position(z(sta), eowyn, eowyn_windows) == "in", flight


def test_knock_on_returns_sta_out(eowyn, eowyn_windows):
    for flight, sta in KNOCK_ON_STA.items():
        assert position(z(sta), eowyn, eowyn_windows) == "out", flight
        assert margin_min(z(sta), eowyn_windows) > 0, flight


def test_margin_sign_and_edges(eowyn_windows):
    # inside: negative minutes to the nearest edge; edge itself: 0 and "in"
    assert margin_min(z("08:45"), eowyn_windows) == -(6 * 60 + 15)
    assert margin_min(z("15:00"), eowyn_windows) == 0
    assert margin_min(z("15:01"), eowyn_windows) == 1
    # between the minor (ends 00:30) and main (starts 02:30) window: nearest edge wins
    assert margin_min(z("01:00"), eowyn_windows) == 30
    assert margin_min(z("12:00"), []) is None


# ---------- unknown ----------

def test_synthetic_gap_gives_unknown(eowyn):
    gapped = [o for o in eowyn if not (z("07:00") <= o.valid <= z("10:00"))]
    windows = storm_windows(gapped)
    assert position(z("08:30"), gapped, windows) == "unknown"     # nearest obs 06:30 / 10:30, 120 min away
    # a >=2 h hole in the data splits the window (counting obs 06:30 and 10:30 are 4 h apart) ...
    assert [(w.start, w.end) for w in windows if w.start.day == 24] == [(z("02:30"), z("06:30")), (z("10:30"), z("15:00"))]
    # ... and 06:30 is exactly 60 min from 07:30, so 07:30 is known: out, by 60 min (see DECISIONS D1)
    assert position(z("07:30"), gapped, windows) == "out"
    assert margin_min(z("07:30"), windows) == 60
    assert position(z("12:00", 26), eowyn, storm_windows(eowyn)) == "unknown"   # outside the data entirely
    assert position(z("12:00"), [], []) == "unknown"


def test_unknown_beats_in_when_no_nearby_obs():
    # a window built from other data never makes a time "in" without an obs within +-60 min
    windows = storm_windows([_obs(z("06:00"), gust=50), _obs(z("07:30"), gust=50)])
    assert position(z("06:45"), [_obs(z("06:00"), gust=50)], windows) == "in"
    assert position(z("06:45"), [_obs(z("09:00"))], windows) == "unknown"


# ---------- flight ends ----------

def _flight(fid: str, origin: str, dest: str, std: datetime, sta: datetime) -> Flight:
    return Flight(id=f"{fid}@2025-01-24", number=fid, date=date(2025, 1, 24), origin=origin, dest=dest,
                  sched_dep=std, sched_arr=sta, aircraft="EI-NSX", status="cancelled", pax=100)


def test_departure_and_arrival_positions(eowyn, eowyn_windows):
    ns31 = _flight("NS31", "DUB", "BOS", z("16:30"), z("23:59"))
    dep = departure_position(ns31, eowyn, eowyn_windows)
    assert dep.end == "dep" and dep.at == z("16:30") and dep.position == "out" and dep.margin_min == 90

    ns117 = _flight("NS117", "MUC", "DUB", z("14:05"), z("16:20"))
    arr = arrival_position(ns117, eowyn, eowyn_windows)
    assert arr.end == "arr" and arr.at == z("16:20") and arr.position == "out" and arr.margin_min == 80
    # no MUC METAR supplied -> the departure end is unknown, never assumed calm
    assert departure_position(ns117, [], []).position == "unknown"
    assert departure_position(ns117, [], []).margin_min is None

    ns101 = _flight("NS101", "LHR", "DUB", z("08:00"), z("09:15"))
    arr = arrival_position(ns101, eowyn, eowyn_windows)
    assert arr.position == "in" and arr.margin_min < 0


# ---------- Herminia (real data) ----------

def test_herminia_window_1130_to_1300():
    obs = load_iem_csv(HERMINIA_CSV)
    windows = storm_windows(obs)
    assert len(windows) == 1
    w = windows[0]
    assert near(w.start, z("11:30", 26)) and near(w.end, z("13:00", 26))
    assert w.peak_gust_kt == 43
    assert (w.start, w.end) == (z("11:30", 26), z("13:00", 26))


# ---------- properties ----------

@settings(max_examples=50, deadline=None)
@given(st.randoms(use_true_random=False))
def test_shuffle_invariant_real_obs(rnd):
    obs = load_iem_csv(EOWYN_CSV)
    base = storm_windows(obs)
    shuffled = list(obs)
    rnd.shuffle(shuffled)
    assert storm_windows(shuffled) == base


_obs_strategy = st.builds(
    lambda slot, gust, sknt, vsby, wx: _obs(
        datetime(2025, 1, 24, tzinfo=UTC) + timedelta(minutes=30 * slot), gust=gust, sknt=sknt, vsby_sm=vsby, wxcodes=wx
    ),
    st.integers(0, 96),
    st.one_of(st.none(), st.integers(0, 70)),
    st.one_of(st.none(), st.integers(0, 45)),
    st.one_of(st.none(), st.sampled_from([0.1, 0.25, 0.5, 3.0, 6.21])),
    st.one_of(st.none(), st.sampled_from(["-RA", "SN", "FZFG", "TSRA", "BR", "GR"])),
)


@settings(max_examples=50, deadline=None)
@given(st.lists(_obs_strategy, max_size=60), st.randoms(use_true_random=False))
def test_window_properties(obs, rnd):
    windows = storm_windows(obs)
    shuffled = list(obs)
    rnd.shuffle(shuffled)
    assert storm_windows(shuffled) == windows
    for a, b in itertools.pairwise(windows):
        assert a.start <= a.end < b.start
        assert b.start - a.end >= timedelta(hours=2)          # merged gaps are < 2 h
    for o in obs:
        if is_storm_obs(o):
            assert any(w.start <= o.valid <= w.end for w in windows)
            assert position(o.valid, obs, windows) == "in"
    assert sum(w.obs_count for w in windows) == sum(1 for o in obs if is_storm_obs(o))
