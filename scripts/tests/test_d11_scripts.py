"""D11: make verify, the CP1 smoke checks and make record, run in-process on temp databases."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("d11")
    os.environ.setdefault("STORMCHECK_DB", str(tmp / "import" / "stormcheck.db"))   # server.app's module-level app
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import Settings
    app = create_app(Settings(db_path=tmp / "stormcheck.db", mode="offline"))
    with TestClient(app) as c:
        yield c


def test_verify_two_offline_boots_are_hash_identical(capsys):
    assert load("verify").main([]) == 0
    out = capsys.readouterr().out
    assert "commits verified · replay identical" in out


def test_cp1_smoke_in_process(client):
    smoke = load("smoke")
    c = smoke.run("cp1", client)
    failed = [r for r in c.results if not r[1]]
    assert not failed, failed


def test_record_writes_every_get_route(client, tmp_path):
    rec = load("record")
    index = rec.record(client, tmp_path / "rec")
    assert "/api/storms/EIDW@2025-01-24" in index and "/api/flights/NS31@2025-01-24" in index
    assert all(":" not in f for f in index.values())
    saved = json.loads((tmp_path / "rec" / "index.json").read_text())
    assert saved == dict(sorted(index.items()))
    assert all((tmp_path / "rec" / f).is_file() for f in index.values())


def test_fuzz_inputs_are_deterministic_and_varied():
    smoke = load("smoke")
    a, b = smoke.fuzz_inputs(), smoke.fuzz_inputs()
    assert a == b and len(a) == 20 and len({x["kind"] for x in a}) >= 4
