"""Plan-commit smoke test: contracts import, core models validate, real METAR fixtures exist."""
import csv
from datetime import date, datetime, timezone
from pathlib import Path

from contracts import interfaces, models

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"


def test_interfaces_exist():
    for name in ["Clock", "WorldAPI", "ReaderAPI", "DrafterAPI", "BooksAPI", "EngineAPI"]:
        assert hasattr(interfaces, name)


def test_minimal_world_validates():
    now = datetime(2025, 1, 25, 7, 0, tzinfo=timezone.utc)
    w = models.World(
        meta={"carrier": "Northstar Air"},
        airports=[models.Airport(icao="EIDW", iata="DUB", name="Dublin", lat=53.42, lon=-6.27,
                                 country="IE", eu=True, tz="Europe/Dublin")],
        flights=[models.Flight(id="NS31@2025-01-24", number="NS31", date=date(2025, 1, 24), origin="DUB", dest="BOS",
                               sched_dep=now, sched_arr=now, aircraft="EI-NSB", status="cancelled", pax=172,
                               ops_cause_code="71")],
        tech_log=[], ops_log=[], coupons=[], elections=[], crm=[], claims=[], metar={}, sources=[],
    )
    assert w.flights[0].pax == 172


def test_real_metar_fixtures_present():
    for name, peak in [("eidw_2025-01-23_25.csv", 56), ("eidw_2025-01-26.csv", 43)]:
        rows = list(csv.DictReader((GOLDEN / name).open()))
        assert rows and rows[0]["station"] == "EIDW"
        assert max(float(r["gust"]) for r in rows if r["gust"]) == peak
