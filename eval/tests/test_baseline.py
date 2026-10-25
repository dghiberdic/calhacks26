from datetime import UTC, datetime

import pytest

from world.golden import load_golden


def test_baseline_requests_hide_truth_and_future_documents_and_separate_replicates():
    from eval.baseline import prepare_requests

    requests = prepare_requests(load_golden(), days=["2025-01-24"])
    assert len(requests) == 3
    assert len({r["custom_id"] for r in requests}) == 3
    assert len({r["prompt_version"] for r in requests}) == 3
    assert len({str(r["messages"]) for r in requests}) == 1
    payload = requests[0]["input"]
    assert "truth" not in payload and "answer_key" not in payload and "meta" not in payload
    cut = datetime(2025, 1, 25, 9, tzinfo=UTC)
    assert all(datetime.fromisoformat(s["received_at"]) <= cut
               for s in payload["sources"])
    assert {f["id"] for f in payload["flights"] if f["status"] == "cancelled"} >= {"NS31@2025-01-24"}


def test_missing_or_duplicate_flights_do_not_count_as_completed_baseline_runs():
    from eval.baseline import summarize_results

    rows = [{"day": "2025-01-24", "flight_id": "A", "truth_cause": "technical",
             "truth_extraordinary": "not_extraordinary"}]
    prediction = {"flight_id": "A", "cause": "technical", "extraordinary": "not_extraordinary",
                  "liability_cents": 3465000}
    results = {
        "plain-2025-01-24-run-1": {"completed": True, "result": {"flights": [prediction]}},
        "plain-2025-01-24-run-2": {"completed": True, "result": {"flights": []}},
        "plain-2025-01-24-run-3": {"completed": True, "result": {"flights": [prediction, prediction]}},
    }
    report = summarize_results(results, rows, days=["2025-01-24"])
    assert report["completed_requests"] == 1 and report["status"] == "partial"
    storm = report["storms"]["2025-01-24"]
    assert storm["liability_eur"] == [34650.0]
    assert storm["cause_accuracy"] == [1.0]
    assert storm["hash_identical"] is None


@pytest.fixture(scope="module")
def golden_requests():
    from eval.baseline import prepare_requests

    return load_golden(), prepare_requests(load_golden(), days=["2025-01-24"])


def test_baseline_documents_carry_no_passenger_pii(golden_requests):
    world, requests = golden_requests
    sent = requests[0]["system"] + requests[0]["messages"][0]["content"]
    assert '"pnr"' not in sent and '"pax_ref"' not in sent and "pax_ref" not in sent
    coupons = [c for c in world.coupons if c.flight_id == "NS31@2025-01-24"]
    assert coupons and not any(f",{c.pnr}," in sent or c.pax_ref in sent for c in coupons)
    for claim in world.claims:
        assert claim.text not in sent
    for s in world.sources:
        if "pii" in s.acl_tags or s.kind.value in ("claim", "email", "crm"):
            assert s.text is None or s.text not in sent, s.id
    for e in world.crm:
        assert e.text not in sent or len(e.text) < 12
    lines = requests[0]["input"]["coupons"]["NS31@2025-01-24"].splitlines()
    assert lines[0].startswith("seat,fare_type") and len(lines) == 1 + len(coupons)


def _scripted(provenance: str):
    from llm.client import RawResponse, ScriptedBackend

    def respond(req):
        import orjson

        payload = orjson.loads(req.messages[0]["content"])
        flights = [{"flight_id": f, "cause": "weather", "extraordinary": "extraordinary", "liability_cents": 0}
                   for f in payload["target_flight_ids"]]
        return RawResponse(model="claude-opus-5-5", request_id="req_scripted", message_id="msg_scripted",
                           stop_reason="end_turn", stop_details=None, text="", parsed={"flights": flights},
                           usage={"input_tokens": 1, "output_tokens": 1})
    return ScriptedBackend(respond, provenance=provenance)


def test_live_path_uses_the_capped_batch_wrapper_and_scores_offline_from_the_cache(golden_requests, tmp_path,
                                                                                    monkeypatch):
    import anthropic

    from eval.baseline import EFFORT, MODEL, run_batch, summarize_results
    from llm.client import LlmClient

    def no_network(*a, **k):
        raise AssertionError("the baseline test touched the network")
    monkeypatch.setattr(anthropic, "Anthropic", no_network)
    world, requests = golden_requests
    backend = _scripted("live")
    live = LlmClient(mode="cache", cache_dir=tmp_path, read_dirs=[], backend=backend, cap_usd=30)
    out = run_batch(requests, live)
    assert backend.batches == 1 and len(backend.submitted_custom_ids) == 3      # one batch, three replicates
    assert all(r["completed"] for r in out.values())
    assert {r["record"]["model_requested"] for r in out.values()} == {MODEL}
    assert {r["record"]["effort"] for r in out.values()} == {EFFORT}
    offline = LlmClient(mode="offline", cache_dir=tmp_path, read_dirs=[], backend=_scripted("live"))
    replay = run_batch(requests, offline)                                       # scoring works from the cache
    assert offline.backend.batches == 0 and replay.keys() == out.keys()
    assert [r["result"] for r in replay.values()] == [r["result"] for r in out.values()]
    targets = requests[0]["input"]["target_flight_ids"]
    rows = [{"day": "2025-01-24", "flight_id": f, "truth_cause": "weather", "truth_extraordinary": "extraordinary"}
            for f in targets]
    s = summarize_results(out, rows, days=["2025-01-24"])
    assert s["storms"]["2025-01-24"]["liability_eur"] == [0.0, 0.0, 0.0]
    assert s["storms"]["2025-01-24"]["hash_identical"] is True


def test_hand_written_or_offline_responses_never_count_as_baseline_runs(golden_requests, tmp_path):
    from eval.baseline import pending, run_batch
    from llm.client import LlmClient

    _, requests = golden_requests
    out = run_batch(requests, LlmClient(mode="cache", cache_dir=tmp_path, read_dirs=[],
                                        backend=_scripted("hand-written")))
    assert not any(r["completed"] for r in out.values())
    missing = run_batch(requests, LlmClient(mode="offline", cache_dir=tmp_path / "empty", read_dirs=[],
                                            backend=_scripted("live")))
    assert not any(r["completed"] for r in missing.values())
    p = pending()
    assert p["runs"] == 0 and p["hash_identical"] is None and "python -m eval.baseline --live" in p["note"]


def test_live_refuses_without_a_key(monkeypatch, tmp_path):
    import eval.baseline as B

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(B, "load_env", lambda path=None: None)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        B.main(["--live"])


def test_stormcheck_is_scored_on_the_same_flights_by_the_same_rule():
    from eval.baseline import summarize_results

    day = "2025-01-24"
    rows = [
        {"day": day, "flight_id": "A", "truth_cause": "technical", "truth_extraordinary": "not_extraordinary",
         "predicted_cause": "technical", "predicted_extraordinary": "not_extraordinary", "preview_cents": 60000,
         "ultimate_cents": 21000},
        {"day": day, "flight_id": "B", "truth_cause": "weather", "truth_extraordinary": "extraordinary",
         "expected_route": "legal", "predicted_cause": "knock_on", "predicted_extraordinary": "needs_legal",
         "preview_cents": 25000, "ultimate_cents": 0},
        {"day": day, "flight_id": "C", "truth_cause": "technical", "truth_extraordinary": "not_extraordinary",
         "predicted_cause": "weather", "predicted_extraordinary": "extraordinary", "preview_cents": 0,
         "ultimate_cents": 14000},
    ]
    s = summarize_results({}, rows, days=[day])
    storm = s["storms"][day]
    assert s["status"] == "pending" and s["runs"] == 0 and storm["liability_eur"] == []
    assert storm["flights"] == 3 and storm["stormcheck_accuracy"] == round(2 / 3, 6)
    assert storm["stormcheck_preview_eur"] == 850.0 and storm["key_ultimate_expected_eur"] == 350.0
