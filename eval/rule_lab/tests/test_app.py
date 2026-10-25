"""Standalone HTTP boundary; the original server is never imported."""

from fastapi.testclient import TestClient

from eval.rule_lab.app import app


def test_reviewer_can_run_a_counterexample_and_unknown_scenarios_are_rejected():
    with TestClient(app) as client:
        response = client.get("/api/report", params={"preset": "broader_scope"})
        assert response.status_code == 200
        assert response.json()["verdict"] == "blocked"
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/report", params={"preset": "../unknown"}).status_code == 422
        assert client.post("/api/approve", json={"rule": "R-CL-1"}).status_code == 404
        assert client.get("/").status_code == 200
        assert len(client.get("/api/scenarios").json()["scenarios"]) == 4
