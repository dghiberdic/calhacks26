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
    assert published.baseline["runs"] == 0
    assert published.baseline["hash_identical"] is None
    assert published.stormcheck_runs["liability_eur"] == [34650, 34650, 34650]
    assert published.straight_through_pct < 100
