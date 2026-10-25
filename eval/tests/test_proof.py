from pathlib import Path

import orjson

from contracts.models import EvalReport
from eval.run import report_from_cache

ROOT = Path(__file__).resolve().parents[2]


def test_published_proof_is_reproducible_from_offline_metric_inputs():
    cache = orjson.loads((ROOT / "eval/cache/results.json").read_bytes())
    fitted = orjson.loads((ROOT / "eval/cache/calibration.json").read_bytes())
    published = EvalReport.model_validate_json((ROOT / "eval/proof.json").read_bytes())
    assert report_from_cache(cache, fitted) == published
    assert published.stormcheck_runs["liability_eur"] == [34650, 34650, 34650]
    assert published.straight_through_pct < 100


def test_a_published_baseline_is_genuine_live_batch_output_or_claims_nothing():
    """A plain-Claude number is published only from three genuine live-batch runs per storm; otherwise none is."""
    base = EvalReport.model_validate_json((ROOT / "eval/proof.json").read_bytes()).baseline
    if base["status"] != "complete":
        assert base["runs"] == 0 and base["hash_identical"] is None and base["liability_eur"] == []
        return
    assert base["model"] == "claude-opus-5-5" and base["effort"] == "medium" and base["runs"] == 3
    assert len(base["liability_eur"]) == 3 and len(base["cause_accuracy"]) == 3
    assert isinstance(base["hash_identical"], bool)
    results = orjson.loads((ROOT / "eval/cache/baseline_results.json").read_bytes())
    assert len(results) == base["completed_requests"] == 9
    for r in results.values():
        assert r["completed"] and r["error"] is None
        assert r["record"]["provenance"] == "live-batch" and r["record"]["model_requested"] == "claude-opus-5-5"
        assert r["record"]["message_id"] not in (None, "hand-written") and r["record"]["usage"]["output_tokens"] > 0
