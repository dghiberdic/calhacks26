"""D10a: every contract route exists on the real app with a response_model, and every GET validates."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import TypeAdapter

from contracts.models import (
    AccessDecision, AccessMatrix, Blame, CfoMetrics, ClaimCurve, Commit, ControlMapping, ErrorEnvelope,
    EstimateCard, EvalReport, FlightFile, Health, Injection, InvariantResult, JournalEntry, Question, Rule,
    Rollforward, StormRun, StormSummary, TraceEvent,
)
from contracts.tests.test_stub import CONTRACT_ROUTES

GETS: list[tuple[str, Any]] = [
    ("/api/health", Health),
    ("/api/storms", list[StormSummary]),
    ("/api/questions", list[Question]),
    ("/api/questions?status=open", list[Question]),
    ("/api/rules", list[Rule]),
    ("/api/trace?since=0", list[TraceEvent]),
    ("/api/commits?limit=100", list[Commit]),
    ("/api/blame?target=NS31@2025-01-24", Blame),
    ("/api/books/rollforward?period=2025-01", Rollforward),
    ("/api/books/journal", list[JournalEntry]),
    ("/api/books/curve?segment=long_haul_gt3500", ClaimCurve),
    ("/api/books/cfo", CfoMetrics),
    ("/api/books/invariants", list[InvariantResult]),
    ("/api/access/matrix", AccessMatrix),
    ("/api/access/log", list[AccessDecision]),
    ("/api/controls", list[ControlMapping]),
    ("/api/injections", list[Injection]),
    ("/api/eval", EvalReport),
    ("/api/books/estimate?cohort=EIDW@2025-01-24", EstimateCard),
]


def valid(tp: Any, body: Any) -> Any:
    return TypeAdapter(tp).validate_python(body)


def error_code(r) -> str:
    return ErrorEnvelope.model_validate(r.json()).error.code


def test_every_contract_route_exists_with_a_response_model(mini_app):
    routes = {(m, r.path): r for r in mini_app.routes if isinstance(r, APIRoute) for m in r.methods}
    missing = CONTRACT_ROUTES - routes.keys()
    assert not missing, f"missing routes: {sorted(missing)}"
    for key in CONTRACT_ROUTES:
        assert routes[key].response_model is not None, f"{key} has no response_model"


def test_real_routes_come_before_stub_fallbacks(mini_app):
    first = {}
    for r in mini_app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                first.setdefault((m, r.path), r)
    for key in [("GET", "/api/health"), ("GET", "/api/storms"), ("GET", "/api/storms/{storm_id}"),
                ("GET", "/api/flights/{flight_id}")]:
        assert first[key].endpoint.__module__ == "server.app", key


@pytest.mark.parametrize("path,tp", GETS, ids=[p for p, _ in GETS])
def test_get_returns_a_valid_body(any_client, path, tp):
    r = any_client.get(path)
    assert r.status_code == 200, r.text
    valid(tp, r.json())


def test_every_storm_and_flight_validates(any_client):
    storms = valid(list[StormSummary], any_client.get("/api/storms").json())
    assert storms
    for s in storms:
        run = StormRun.model_validate(any_client.get(f"/api/storms/{s.id}").json())
        assert run.id == s.id and run.flights
        for row in run.flights:
            r = any_client.get(f"/api/flights/{row.flight.id}")
            if row.flight.status == "cancelled":
                assert r.status_code == 200, (row.flight.id, r.text)
                ff = FlightFile.model_validate(r.json())
                assert ff.decision.flight_id == row.flight.id == ff.flight.id
            else:
                assert r.status_code == 404 and error_code(r) == "not_found"


def test_unknown_ids_are_404_envelopes(any_client):
    for path in ["/api/storms/EGLL@2025-01-24", "/api/flights/NS999@2025-01-24"]:
        r = any_client.get(path)
        assert r.status_code == 404 and error_code(r) == "not_found", path
        assert "NS31@2025-01-24" in r.json()["error"]["message"] or "Known" in r.json()["error"]["message"]


def test_cors_allows_the_vite_dev_server(mini):
    r = mini.options("/api/storms", headers={"Origin": "http://localhost:5173",
                                              "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_module_app_boots_offline():
    from fastapi.testclient import TestClient

    from server.app import app
    h = Health.model_validate(TestClient(app).get("/api/health").json())
    assert h.ok and h.mode == "offline" and h.impl["pipeline"] in ("golden", "stub")
