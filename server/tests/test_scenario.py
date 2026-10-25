"""Clock marks and the clock-triggered Iberian blackout scenario (`world.events.blackout_world()`) on the golden
world. These pin the server's part: the mark runs the slice once, into the Questions queue, the trace and Books, and
its commits replay identically. What the engine decides on each flight is the engine's tests' business."""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

from contracts.models import ClockResponse, StormRun

ROOT = Path(__file__).resolve().parents[2]
MARK = "2025-04-29T06:00:00Z"
RUN = "EIDW@2025-04-28"
EVENT = "EVT-IBERIA-BLACKOUT@2025-04-28"


def blackout(c) -> StormRun:
    assert c.post("/api/clock", json={"known_at": MARK}).status_code == 200
    return StormRun.model_validate(c.get(f"/api/storms/{RUN}").json())


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


def test_the_mark_runs_the_blackout_once_into_the_queue_books_and_trace(golden, golden_app):
    from world.events import blackout_world
    rt = golden_app.state.runtime
    cancelled = {f.id for f in blackout_world().flights if f.status == "cancelled"}
    assert RUN not in {s["id"] for s in golden.get("/api/storms").json()}
    run = blackout(golden)
    assert run.counters["cancelled"] == len(cancelled) == 10 and run.counters["operated"] == 6
    assert {r.flight.id for r in run.flights if r.decision} == cancelled
    assert any(e["kind"] == "info" and e["ref"] == EVENT for e in golden.get("/api/trace").json())
    # an event run: its id, and the outage window at each Iberian airport its flights touch
    assert run.event_id == EVENT
    assert {w.station for w in run.windows if w.kind == "grid_outage"} == {"LPPT", "LEMD", "LEBL"}
    assert all(w.label and w.label.startswith("Grid outage") for w in run.windows if w.kind == "grid_outage")
    # its questions are in the normal queue, its decisions on the chain
    assert any(set(q["case_refs"]) & cancelled for q in golden.get("/api/questions").json())
    assert {c.payload_ref for c in rt.trace.log(None, kind="decision")} >= cancelled
    # Books: its own cohort, with the care accrual
    rf = golden.get("/api/books/rollforward?period=2025-04").json()
    assert any(r["cohort"] == RUN for r in rf["rows"]) and rf["ties_to_gl"]
    care = [j for j in golden.get("/api/books/journal?period=2025-04").json() if j["kind"] == "care_accrual"]
    assert care and all(RUN in j["memo"] for j in care)
    # the invariants the server's plumbing can break (ties, balances, completeness, cut-off); INV-7 follows the
    # engine's event-window decisions, which engine/tests own
    plumbing = {"INV-1", "INV-2", "INV-3", "INV-11", "INV-T1"}
    assert [(i["id"], i["detail"]) for i in golden.get("/api/books/invariants").json()
            if i["id"] in plumbing and not i["ok"]] == []
    # once: a later clock move does not run it again; reset returns to the base world
    n = len(rt.trace.log(None, kind="decision"))
    golden.post("/api/clock", json={"known_at": "2025-04-30T06:00:00Z"})
    assert len(rt.trace.log(None, kind="decision")) == n
    golden.post("/api/reset")
    assert rt.world is rt.base_world and RUN not in {s["id"] for s in golden.get("/api/storms").json()}


def test_blackout_commits_replay_identical(golden, golden_app):
    spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts" / "verify.py")
    verify = importlib.util.module_from_spec(spec)
    sys.modules["verify"] = verify
    spec.loader.exec_module(verify)
    rt = golden_app.state.runtime
    blackout(golden)
    n, head, problems = verify.chain(rt)
    assert problems == [] and n > 0
    replayed, bad = verify.replay_trace_decisions(rt.trace, rt.lifecycle.decide_fn)
    assert bad == []
    ours = [c for c in rt.trace.log(None, kind="decision") if c.payload_ref.endswith("@2025-04-28")]
    assert ours and replayed >= len(ours)
    golden.post("/api/reset")


def test_the_desk_runs_lisbon_on_the_blackout_day(golden):
    r = golden.post("/api/desk", json={"icao": "LPPT", "date": "2025-04-28"})
    assert r.status_code == 200, r.text
    run = StormRun.model_validate(r.json())
    assert run.id == "LPPT@2025-04-28" and run.counters["cancelled"] > 0


def test_a_missing_scenario_loader_is_reported_not_raised(golden, monkeypatch):
    from server import scenario
    sc = dataclasses.replace(scenario.BLACKOUT, loader=("world.no_such_module", "blackout_world"))
    monkeypatch.setattr(scenario, "SCENARIOS", (sc,))
    r = golden.post("/api/clock", json={"known_at": MARK})
    assert r.status_code == 200
    assert any(e["ref"] == sc.id and "not available" in e["summary"] for e in golden.get("/api/trace").json())
    golden.post("/api/reset")
