"""F1: METAR fetch + pins. Everything runs offline from data/pinned/ (network paths are mocked with respx)."""
from __future__ import annotations

import csv
import itertools
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from world import metar
from world.errors import WorldError
from world.metar import Throttle, fetch_day, fetch_metar

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts" / "fixtures" / "golden"


def Z(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "offline")
    metar._MEMO.clear()


class FakeTime:
    """Deterministic monotonic clock: sleep() advances it, nothing really waits."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def fake_time(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(metar, "IEM_THROTTLE", Throttle(1.0, clock=ft.monotonic, sleep=ft.sleep))
    monkeypatch.setattr(metar, "AWC_THROTTLE", Throttle(1.0, clock=ft.monotonic, sleep=ft.sleep))
    return ft


IEM_CSV = (metar.CSV_HEADER + "\n"
           "EGLL,2019-03-01 00:20,10.00,22.00,240.00,6.21,,EGLL 010020Z 24010G22KT 9999 FEW030 08/04 Q1012\n"
           "EGLL,2019-03-01 00:50,11.00,,250.00,6.21,-RA,EGLL 010050Z 25011KT 9999 -RA FEW030 08/04 Q1012\n")


# ---------------------------------------------------------------- the demo days (plan §1.2)

def gust(o):
    return o.gust or 0


def test_eowyn_gusts_ge_40_from_0300_to_1230():
    obs = fetch_day("EIDW", date(2025, 1, 24))
    strong = [o.valid for o in obs if gust(o) >= 40]
    assert strong[0] == Z(2025, 1, 24, 3, 0) and strong[-1] == Z(2025, 1, 24, 12, 30)
    inside = [o for o in obs if Z(2025, 1, 24, 3) <= o.valid <= Z(2025, 1, 24, 12, 30)]
    assert len(inside) == 20
    # The only report under 40 kt inside the span is the real 11:30Z lull: "24018G32KT".
    lulls = [o for o in inside if gust(o) < 40]
    assert [o.valid for o in lulls] == [Z(2025, 1, 24, 11, 30)] and "24018G32KT" in lulls[0].raw


def test_eowyn_peak_g56_at_0700_and_1200():
    obs = fetch_day("EIDW", date(2025, 1, 24))
    assert max(gust(o) for o in obs) == 56
    assert [o.valid for o in obs if gust(o) == 56] == [Z(2025, 1, 24, 7), Z(2025, 1, 24, 12)]
    assert "22028G56KT" in next(o.raw for o in obs if o.valid == Z(2025, 1, 24, 7))


def test_eowyn_calm_from_1600():
    obs = fetch_metar("EIDW", Z(2025, 1, 24, 16), Z(2025, 1, 25))
    assert len(obs) == 16
    assert all(gust(o) <= 25 for o in obs)
    assert all(9 <= o.sknt <= 14 for o in obs)


def test_herminia_gusts_ge_35_only_1130_to_1300():
    obs = fetch_day("EIDW", date(2025, 1, 26))
    strong = [o.valid for o in obs if gust(o) >= 35]
    assert strong == [Z(2025, 1, 26, 11, 30), Z(2025, 1, 26, 12), Z(2025, 1, 26, 13)]
    assert max(gust(o) for o in obs) == 43


def test_pins_match_golden_fixture():
    """data/pinned and contracts/fixtures/golden are the same real IEM rows."""
    for name, start, end in [("eidw_2025-01-23_25.csv", Z(2025, 1, 23, 18), Z(2025, 1, 25)),
                             ("eidw_2025-01-26.csv", Z(2025, 1, 26), Z(2025, 1, 27))]:
        golden = list(csv.DictReader((GOLDEN / name).open()))
        obs = fetch_metar("EIDW", start, end)
        assert [o.raw for o in obs] == [r["metar"] for r in golden]
        assert [o.gust for o in obs] == [int(float(r["gust"])) if r["gust"] else None for r in golden]


def test_isha_and_eowyn_neighbours_pinned_as_daily_files():
    for d in ["2025-01-23", "2025-01-24", "2025-01-25", "2025-01-26", "2024-01-21"]:
        assert (metar.PINNED_DIR / f"EIDW@{d}.csv").exists()
    isha = fetch_day("EIDW", date(2024, 1, 21))
    assert len(isha) >= 48 and max(gust(o) for o in isha) >= 45


def test_bundle_serves_any_day_in_24_months():
    assert (metar.PINNED_DIR / "EIDW_2023-07_2025-07.csv.gz").exists()
    obs = fetch_day("EIDW", date(2024, 12, 7))            # Darragh, bundle only (no daily file)
    assert not metar.daily_pin_path("EIDW", date(2024, 12, 7)).exists()
    assert len(obs) >= 48 and max(gust(o) for o in obs) == 61
    days = metar.pinned_dates("EIDW")
    assert days[0] <= date(2023, 7, 1) and date(2025, 6, 30) in days and len(days) >= 731


def test_obs_sorted_utc_half_open_and_station_normalised():
    obs = fetch_metar("eidw", Z(2025, 1, 24, 6), Z(2025, 1, 24, 7))
    assert [o.valid for o in obs] == [Z(2025, 1, 24, 6), Z(2025, 1, 24, 6, 30)]
    assert all(o.station == "EIDW" and o.valid.tzinfo is not None for o in obs)


def test_corrupt_gust_dropped_raw_kept():
    obs = fetch_metar("EIDW", Z(2024, 12, 9, 11, 30), Z(2024, 12, 9, 12))
    assert obs[0].gust is None and "35008G100KT" in obs[0].raw


def test_storm_day_rule_selects_named_storms():
    obs = []
    for d in [date(2025, 1, 23), date(2025, 1, 24), date(2025, 1, 25), date(2025, 1, 26), date(2024, 12, 9)]:
        obs += fetch_day("EIDW", d)
    assert [s.day for s in metar.storm_days(obs)] == [date(2025, 1, 24), date(2025, 1, 26)]


# ---------------------------------------------------------------- errors

def test_offline_miss_raises_no_metar_without_network():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route()                                # would catch any request
        with pytest.raises(WorldError) as exc:
            fetch_metar("EGLL", Z(2019, 3, 1), Z(2019, 3, 2))
        assert not route.called
    assert exc.value.code == "no_metar" and "offline" in exc.value.message


def test_future_date_and_bad_code():
    with pytest.raises(WorldError) as exc:
        fetch_metar("KBOS", datetime.now(UTC) + timedelta(days=3), datetime.now(UTC) + timedelta(days=4))
    assert exc.value.code == "future_date"
    with pytest.raises(WorldError) as exc:
        fetch_metar("not-a-station", Z(2025, 1, 24), Z(2025, 1, 25))
    assert exc.value.code == "unknown_airport"


# ---------------------------------------------------------------- network path (mocked)

def test_throttle_spaces_iem_calls_at_least_1s(fake_time):
    seen: list[float] = []

    def reply(request):
        seen.append(fake_time.t)
        return httpx.Response(200, text=IEM_CSV)

    with respx.mock:
        respx.get(metar.IEM_URL).mock(side_effect=reply)
        for _ in range(3):
            metar.fetch_iem("EGLL", Z(2019, 3, 1), Z(2019, 3, 2))
    assert len(seen) == 3
    assert all(b - a >= 1.0 for a, b in itertools.pairwise(seen))


def test_throttle_real_clock():
    th = Throttle(0.05)
    import time
    t0 = time.monotonic()
    for _ in range(3):
        th.wait()
    assert time.monotonic() - t0 >= 0.1


def test_iem_retries_429_and_503_with_backoff(fake_time):
    responses = iter([httpx.Response(429), httpx.Response(503, headers={"Retry-After": "5"}),
                      httpx.Response(200, text=IEM_CSV)])
    with respx.mock:
        route = respx.get(metar.IEM_URL).mock(side_effect=lambda req: next(responses))
        obs = metar.fetch_iem("EGLL", Z(2019, 3, 1), Z(2019, 3, 2))
    assert route.call_count == 3 and len(obs) == 2
    assert fake_time.sleeps[:2] == [metar.BACKOFF_BASE_S, 5.0]
    q = route.calls[0].request.url.params
    assert q.get_list("data") == list(metar.IEM_FIELDS) and q.get_list("report_type") == ["3", "4"]
    assert q["sts"] == "2019-03-01T00:00Z" and q["ets"] == "2019-03-02T00:00Z" and q["tz"] == "Etc/UTC"


def test_cache_mode_falls_back_iem_then_awc(monkeypatch, fake_time):
    monkeypatch.setenv("STORMCHECK_MODE", "cache")
    now = Z(2026, 10, 24, 12)
    monkeypatch.setattr(metar, "_now", lambda: now)
    awc = [{"icaoId": "EGLL", "obsTime": int(Z(2026, 10, 23, 9, 50).timestamp()), "wspd": 31, "wgst": 47,
            "wdir": "VRB", "visib": "6+", "wxString": "-RA", "rawOb": "METAR EGLL 230950Z VRB31G47KT 9999 -RA BKN012 Q0980"},
           {"icaoId": "EGLL", "obsTime": int(Z(2026, 10, 23, 9, 20).timestamp()), "wspd": 12, "wgst": None,
            "wdir": 240, "visib": 0.25, "wxString": None, "rawOb": "EGLL 230920Z 24012KT 0400 FG VV001 Q0990"}]
    with respx.mock:
        iem = respx.get(metar.IEM_URL).mock(side_effect=httpx.ConnectTimeout("wifi"))
        aw = respx.get(metar.AWC_URL).mock(return_value=httpx.Response(200, json=awc))
        obs = fetch_metar("EGLL", Z(2026, 10, 23), Z(2026, 10, 24))
    assert iem.call_count == 1 and aw.call_count == 1           # an interactive timeout is not retried
    assert aw.calls[0].request.url.params["hours"] == "37"
    assert [o.valid for o in obs] == [Z(2026, 10, 23, 9, 20), Z(2026, 10, 23, 9, 50)]
    assert obs[1].raw.startswith("EGLL 230950Z") and obs[1].gust == 47 and obs[1].drct is None and obs[1].vsby_sm == 6.0 and obs[0].vsby_sm == 0.25


def test_cache_mode_prefers_pins_over_network(monkeypatch):
    monkeypatch.setenv("STORMCHECK_MODE", "cache")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route()
        obs = fetch_day("EIDW", date(2025, 1, 24))
        assert not route.called
    assert len(obs) == 48


def test_cache_mode_miss_everywhere_raises_no_metar(monkeypatch, fake_time):
    monkeypatch.setenv("STORMCHECK_MODE", "cache")
    with respx.mock:
        respx.get(metar.IEM_URL).mock(return_value=httpx.Response(200, text=metar.CSV_HEADER + "\n"))
        with pytest.raises(WorldError) as exc:
            fetch_metar("EGLL", Z(2019, 3, 1), Z(2019, 3, 2))   # older than 30 days: AWC not asked
    assert exc.value.code == "no_metar"


def test_partial_pin_coverage_fetches_only_missing_span(monkeypatch, fake_time):
    monkeypatch.setenv("STORMCHECK_MODE", "cache")
    late = (metar.CSV_HEADER + "\n"
            "EIDW,2025-07-01 00:00,7.00,,200.00,6.21,,EIDW 010000Z 20007KT CAVOK 14/10 Q1018 NOSIG\n")
    with respx.mock:
        route = respx.get(metar.IEM_URL).mock(return_value=httpx.Response(200, text=late))
        obs = fetch_metar("EIDW", Z(2025, 6, 30, 23), Z(2025, 7, 1, 1))
    assert route.calls[0].request.url.params["sts"] == "2025-07-01T00:00Z"
    assert [o.valid for o in obs] == [Z(2025, 6, 30, 23), Z(2025, 6, 30, 23, 30), Z(2025, 7, 1)]
