from datetime import UTC, datetime

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
