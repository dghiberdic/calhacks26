"""Server test fixtures. Every app gets its own temp DB; nothing writes under data/."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="stormcheck-server-tests-"))
# module-level `server.app:app` boots on import: point it at a temp DB and keep it offline
os.environ.setdefault("STORMCHECK_DB", str(_TMP / "default" / "live.db"))
os.environ.setdefault("STORMCHECK_MODE", "offline")
os.environ.setdefault("LLM_MODE", "offline")
os.environ.setdefault("STORMCHECK_WEB_DIST", str(_TMP / "no-web-dist"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import GOLDEN_WORLD, Settings  # noqa: E402


def make_settings(tmp: Path, world: Path | None = None, **kw) -> Settings:
    return Settings(db_path=tmp / "live.db", world_path=world or (tmp / "no-world.json"), mode="offline",
                    web_dist=tmp / "no-web-dist", heartbeat_s=kw.pop("heartbeat_s", 0.2),
                    sse_poll_s=kw.pop("sse_poll_s", 0.05), **kw)


@pytest.fixture(scope="session")
def mini_world_path(tmp_path_factory) -> Path:
    from engine.tests.mini_world import build
    p = tmp_path_factory.mktemp("world") / "mini_world.json"
    p.write_text(build().model_dump_json())
    return p


@pytest.fixture(scope="session")
def mini_app(tmp_path_factory, mini_world_path):
    return create_app(make_settings(tmp_path_factory.mktemp("mini"), mini_world_path))


@pytest.fixture()
def mini(mini_app):
    c = TestClient(mini_app)
    assert c.post("/api/reset").status_code == 200
    return c


@pytest.fixture(scope="session")
def stub_pipeline_app(tmp_path_factory):
    return create_app(make_settings(tmp_path_factory.mktemp("stubpipe")))


@pytest.fixture(scope="session")
def golden_app(tmp_path_factory):
    if not GOLDEN_WORLD.exists():
        pytest.skip("contracts/fixtures/golden/world.json has not landed yet")
    return create_app(make_settings(tmp_path_factory.mktemp("golden"), GOLDEN_WORLD))


@pytest.fixture()
def golden(golden_app):
    c = TestClient(golden_app)
    assert c.post("/api/reset").status_code == 200
    return c


@pytest.fixture(params=["mini", "stub"])
def any_client(request, mini_app, stub_pipeline_app):
    app = mini_app if request.param == "mini" else stub_pipeline_app
    c = TestClient(app)
    assert c.post("/api/reset").status_code == 200
    return c
