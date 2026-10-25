"""Clock marks and clock-triggered scenarios (the Iberian blackout's mechanism) on the golden world.

`blackout_slice` stands in for `world.events.blackout_world()`: two Northstar DUB-LIS rotations on 28 Apr 2025, one
cancelled each way, with care costs for the stranded passengers.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from contracts.models import CareCost, ClockResponse, OpsLogEntry, SourceKind, StormRun
from engine.tests.mini_world import Builder, calm_obs, flight

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2025, 4, 28)
MARK = "2025-04-29T06:00:00Z"
RUN = "EIDW@2025-04-28"


def at(hhmm: str, day: int = 28) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2025, 4, day, int(h), int(m), tzinfo=UTC)


def blackout_slice():
    b = Builder()
    b.meta = {"carrier": "Northstar Air", "distances_km": {"DUB-LIS": 1643}}
    out = b.add_flight(flight("NS112", "DUB", "LIS", at("11:00"), at("13:45"), 6, "EI-NSC", code="93", day=DAY,
                              notified_at=at("10:50")))
    back = b.add_flight(flight("NS113", "LIS", "DUB", at("14:45"), at("17:25"), 6, "EI-NSC", code="93", day=DAY,
                               notified_at=at("10:50")))
    b.add_flight(flight("NS114", "DUB", "LIS", at("18:00"), at("20:45"), 0, "EI-NSD", status="operated", day=DAY))
    for f in (out, back):
        b.add_coupons(f, [(4, "refund", {}), (2, "none", {})])
    b.ops_log.append(OpsLogEntry(id="OCC-2025-04-28T1045Z", at=at("10:45"), kind="occ", flight_ids=[out.id, back.id],
                                 code="93", text="10:45Z OCC: LIS GRID DOWN. CNL NS112/113.", author="OCC"))
    b.metar["EIDW@2025-04-28"] = calm_obs("EIDW", at("06:00"), 16)
    b.metar["LPPT@2025-04-28"] = calm_obs("LPPT", at("06:00"), 16)
    b.source("SRC-ENTSOE-2025-04-28", SourceKind.REGULATION, "ENTSO-E: 28 April 2025 Iberian blackout",
             "At 12:33 CEST on 28 April 2025 the power systems of Spain and Portugal blacked out.", at("10:40"), 1)
    care = [CareCost(id="CARE-NS113-HOTEL", flight_id=back.id, kind="hotel", amount_cents=96_000, vendor="Lisbon hotel",
                     at=at("22:00"))]
    return b.world().model_copy(update={"care": care})


@pytest.fixture()
def blackout(golden, golden_app, monkeypatch):
    from server import scenario
    sc = dataclasses.replace(scenario.BLACKOUT, loader=(__name__, "blackout_slice"))
    monkeypatch.setattr(scenario, "SCENARIOS", (sc,))
    yield golden
    golden.post("/api/reset")


def test_get_clock_serves_every_mark(golden):
    c = ClockResponse.model_validate(golden.get("/api/clock").json())
    assert c.known_at == datetime(2025, 1, 25, 9, 0, tzinfo=UTC)               # reset lands at 09:00Z
    marks = {m.label: m.at for m in c.marks}
    assert list(marks) == ["OCC cancel list", "The morning after", "Storm Herminia", "January close",
                           "February month-end", "Iberian blackout · 28 Apr 2025"]
    assert marks["Storm Herminia"] == datetime(2025, 1, 27, 6, 0, tzinfo=UTC)  # when the Herminia run happens
    assert marks["Iberian blackout · 28 Apr 2025"].isoformat().replace("+00:00", "Z") == MARK
    moved = golden.post("/api/clock", json={"known_at": "2025-01-26T00:00:00Z"}).json()
    assert len(moved["marks"]) == 6


def test_the_mark_runs_the_scenario_once_into_the_queue_books_and_trace(blackout, golden_app):
    rt = golden_app.state.runtime
    assert RUN not in {s["id"] for s in blackout.get("/api/storms").json()}
    assert blackout.post("/api/clock", json={"known_at": MARK}).status_code == 200
    run = StormRun.model_validate(blackout.get(f"/api/storms/{RUN}").json())
    assert run.counters["cancelled"] == 2 and run.counters["operated"] == 1
    assert {"NS112@2025-04-28", "NS113@2025-04-28"} <= {r.flight.id for r in run.flights if r.decision}
    assert any(e["kind"] == "info" and e["ref"] == "EVT-IBERIA-BLACKOUT@2025-04-28" and "Iberian blackout" in
               e["summary"] for e in blackout.get("/api/trace").json())
    # its questions are in the normal queue, its decisions on the chain
    assert any(set(q["case_refs"]) & {"NS112@2025-04-28", "NS113@2025-04-28"}
               for q in blackout.get("/api/questions").json())
    assert {c.payload_ref for c in rt.trace.log(None, kind="decision")} >= {"NS112@2025-04-28", "NS113@2025-04-28"}
    # Books: its own cohort, with the care accrual
    rf = blackout.get("/api/books/rollforward?period=2025-04").json()
    assert any(r["cohort"] == RUN for r in rf["rows"]) and rf["ties_to_gl"]
    care = [j for j in blackout.get("/api/books/journal?period=2025-04").json() if j["kind"] == "care_accrual"]
    assert care and all(RUN in j["memo"] for j in care)
    assert [i["id"] for i in blackout.get("/api/books/invariants").json() if not i["ok"]] == []
    # once: a later clock move does not run it again
    n = len(rt.trace.log(None, kind="decision"))
    blackout.post("/api/clock", json={"known_at": "2025-04-30T06:00:00Z"})
    assert len(rt.trace.log(None, kind="decision")) == n
    # reset returns to the base world
    blackout.post("/api/reset")
    assert rt.world is rt.base_world and RUN not in {s["id"] for s in blackout.get("/api/storms").json()}


def test_scenario_commits_replay_identical(blackout, golden_app):
    spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts" / "verify.py")
    verify = importlib.util.module_from_spec(spec)
    sys.modules["verify"] = verify
    spec.loader.exec_module(verify)
    rt = golden_app.state.runtime
    blackout.post("/api/clock", json={"known_at": MARK})
    n, head, problems = verify.chain(rt)
    assert problems == [] and n > 0
    replayed, bad = verify.replay_trace_decisions(rt.trace, rt.lifecycle.decide_fn)
    assert bad == []
    scenario_decisions = [c for c in rt.trace.log(None, kind="decision") if c.payload_ref.endswith("@2025-04-28")]
    assert scenario_decisions and replayed >= len(scenario_decisions)


def test_a_missing_scenario_loader_is_reported_not_raised(golden, golden_app, monkeypatch):
    from server import scenario
    sc = dataclasses.replace(scenario.BLACKOUT, loader=("world.no_such_module", "blackout_world"))
    monkeypatch.setattr(scenario, "SCENARIOS", (sc,))
    r = golden.post("/api/clock", json={"known_at": MARK})
    assert r.status_code == 200
    assert any(e["ref"] == sc.id and "not available" in e["summary"] for e in golden.get("/api/trace").json())
    golden.post("/api/reset")
