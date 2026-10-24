"""scripts/smoke.py asserts what its check names claim: each rehearsed injection is compared with its fixture's
`expected` outcome (an HTTP 200 alone, or the contract stub echoing the fixture, is not a pass), and "Herminia
settles 31" counts all 31 coupons through blame instead of a sample."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
INJECTIONS = sorted((ROOT / "contracts" / "fixtures" / "injections").glob("*.json"))


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location("smoke_script", ROOT / "scripts" / "smoke.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_script"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_every_rehearsed_injection_has_a_machine_check(smoke):
    ids = {json.loads(p.read_text())["id"] for p in INJECTIONS}
    assert len(ids) == 8
    assert ids == set(smoke.INJECTION_CHECKS)


def test_the_contract_stub_echo_never_passes(smoke):
    from fastapi.testclient import TestClient

    from contracts import stub_app
    from contracts.models import Injection
    stub_app.reset()
    with TestClient(stub_app.app) as client:
        for p in INJECTIONS:
            inj = Injection.model_validate_json(p.read_text())
            ok, detail = smoke.check_injection(client, inj)
            assert not ok, (inj.id, detail)
    stub_app.reset()


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeServer:
    """Serves NS31's flight file; /api/inject answers with a canned outcome."""

    def __init__(self, inject_body):
        self.ff = json.loads((ROOT / "contracts" / "fixtures" / "api" / "flight_NS31@2025-01-24.json").read_text())
        self.inject_body = inject_body

    def get(self, path, **_):
        if path == "/api/flights/NS31@2025-01-24":
            return Resp(self.ff)
        return Resp({"error": {"code": "not_found", "message": "no"}}, 404)

    def post(self, path, json=None, **_):
        assert path == "/api/inject"
        return Resp(self.inject_body)


def _inject_body(message, facts=None):
    src = {"id": "SRC-INJ-1", "kind": "email", "title": "t", "text": "x", "sha256": "0" * 64,
           "received_at": "2025-01-25T06:00:00Z", "trust_tier": 4, "acl_tags": []}
    return {"source": src, "facts": facts or [], "dropped_unverifiable": 1, "events": [], "affected": [],
            "message": message}


def _injection(smoke, inj_id):
    from contracts.models import Injection
    return Injection.model_validate_json((ROOT / "contracts" / "fixtures" / "injections" / f"{inj_id}.json")
                                         .read_text())


def test_a_server_that_does_what_the_fixture_says_passes(smoke):
    ok, detail = smoke.check_injection(FakeServer(_inject_body("Assertion · Decision stands. METAR ≤25 kt")),
                                       _injection(smoke, "07_challenge_storm_anyway"))
    assert ok, detail
    ok, detail = smoke.check_injection(FakeServer(_inject_body("Instructions are data · 0 facts accepted")),
                                       _injection(smoke, "03_prompt_injection_email"))
    assert ok, detail


def test_a_wrong_outcome_fails_even_with_http_200(smoke):
    ok, _ = smoke.check_injection(FakeServer(_inject_body("Decision changed to weather")),
                                  _injection(smoke, "07_challenge_storm_anyway"))
    assert not ok
    fact = {"id": "F1", "source_id": "SRC-INJ-1", "subject": "flight:NS31@2025-01-24", "field": "approval",
            "value": True, "span": "Approved", "extractor": "fallback:regex@1", "recorded_at": "2025-01-25T06:00:00Z"}
    ok, _ = smoke.check_injection(FakeServer(_inject_body("ok", facts=[fact])),
                                  _injection(smoke, "03_prompt_injection_email"))
    assert not ok


def test_herminia_settlement_is_counted_per_coupon_through_blame(smoke):
    from contracts.models import Blame
    stub_blame = json.loads((ROOT / "contracts" / "fixtures" / "api" / "blame.json").read_text())
    commit = stub_blame["steps"][0]["commit"]

    def blame_client(label, ref):
        steps = [{"commit": {**commit, "payload_ref": "NS106@2025-01-26"}, "label": label, "quote": None},
                 {"commit": {**commit, "kind": "rule_event", "payload_ref": ref}, "label": "rule", "quote": None}]
        Blame.model_validate({"target": "x", "steps": steps})
        return SimpleNamespace(get=lambda path, params=None, **_: Resp({"target": params["target"], "steps": steps}))

    cid = "NS106@2025-01-26:12D"
    owed = f"Entitlement {cid} · €600 · owed · Art. 7(1)"
    assert smoke.coupon_settled_by(blame_client(owed, "R-CL-1@1"), cid, "R-CL-1")
    assert not smoke.coupon_settled_by(blame_client(owed, "R-MINED-REDUCE@1"), cid, "R-CL-1")
    assert not smoke.coupon_settled_by(blame_client(f"Entitlement {cid} · €600 · needs a ruling", "R-CL-1@1"),
                                       cid, "R-CL-1")
    assert not smoke.coupon_settled_by(blame_client(owed, "R-CL-1@1"), cid, None)
    rulings = smoke.expected_rulings()["Q1"]
    assert len(rulings["herminia_settled"]) == 31 and rulings["rule"] == "R-CL-1@1"
