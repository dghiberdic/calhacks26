"""`python -m eval.run --check` on a cache that predates the code reports a stale proof and exits 1; it never
crashes."""
import orjson
import pytest

import eval.run as R


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    paths = {"CACHE": tmp_path / "results.json", "FITTED": tmp_path / "calibration.json",
             "MANIFEST": tmp_path / "manifest.json", "PROOF": tmp_path / "proof.json",
             "NUMBERS": tmp_path / "NUMBERS.md"}
    for name, path in paths.items():
        monkeypatch.setattr(R, name, path)
    paths["FITTED"].write_bytes(orjson.dumps({"version": "x", "models": {}}))
    paths["MANIFEST"].write_bytes(orjson.dumps({"generator_seed": 0, "sha256": {}}))
    paths["PROOF"].write_bytes(b"{}\n")
    paths["NUMBERS"].write_bytes(b"# old\n")
    return paths


def _check(capsys) -> tuple[int, str]:
    code = R.main(["--check"])
    return code, capsys.readouterr().out


@pytest.mark.parametrize("cache", [
    {"version": "eval-v1", "scored_rows": [], "calibration_rows": []},                # legacy cache, no "calibration"
    {"version": R.CACHE_VERSION, "scored_rows": [], "calibration_rows": [], "replay": {}},   # current tag, old shape
    {"scored_rows": []},                                                               # no version at all
])
def test_check_on_a_cache_that_predates_the_code_reports_stale_and_exits_1(scratch, capsys, cache):
    scratch["CACHE"].write_bytes(orjson.dumps(cache))
    code, out = _check(capsys)
    assert code == 1
    assert "stale proof: regenerate" in out
    assert "Traceback" not in out


def test_check_with_a_missing_cache_or_manifest_reports_stale_and_exits_1(scratch, capsys):
    scratch["MANIFEST"].unlink()
    code, out = _check(capsys)
    assert code == 1 and "stale proof: regenerate" in out
    assert "cannot read the cache" in out and "manifest.json is missing" in out


def test_from_cache_on_a_legacy_cache_exits_with_a_message_not_a_traceback(scratch, monkeypatch):
    scratch["CACHE"].write_bytes(orjson.dumps({"version": "eval-v1"}))
    monkeypatch.setattr(R, "stale_inputs", lambda: [])
    with pytest.raises(SystemExit, match="stale proof: regenerate"):
        R.main(["--from-cache"])
