"""llm/ tests run offline: no network, recorded responses only (data/cache/demo/)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "offline")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
