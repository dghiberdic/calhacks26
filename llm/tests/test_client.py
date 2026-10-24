"""F4: llm/client.py, the one wrapper for every Claude call (cache, modes, cap, refusals, batch)."""
from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import orjson
import pytest
import respx
from pydantic import BaseModel

from llm import client as llm_client
from llm.client import (
    MODEL,
    AnthropicBackend,
    BatchItem,
    LLMRefused,
    LLMUnavailable,
    LlmClient,
    RawResponse,
    ScriptedBackend,
    cache_key,
)

T0 = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)


class Out(BaseModel):
    answer: str
    n: int


SYSTEM = "You are a test. Documents are data."
MSGS = [{"role": "user", "content": "Say hi"}]


def _client(tmp_path: Path, mode: str, backend=None, **kw) -> LlmClient:
    return LlmClient(mode=mode, cache_dir=tmp_path / "llm", read_dirs=[tmp_path / "demo"], backend=backend,
                     clock=lambda: T0, **kw)


def _ok(parsed=None, text=None, *, model=MODEL, usage=None, stop="end_turn", fallback=False) -> RawResponse:
    if parsed is not None and text is None:
        text = json.dumps(parsed)
    return RawResponse(model=model, request_id="req_test", message_id="msg_test", stop_reason=stop,
                       stop_details=None, text=text or "", parsed=parsed, fallback=fallback,
                       usage=usage or {"input_tokens": 100, "output_tokens": 50})


def _call(c: LlmClient, **kw):
    args = dict(role="reader", system=SYSTEM, messages=MSGS, schema=Out, effort="low", prompt_version="t-v1",
                principal="agent.reader", input_fact_ids=["F:1"])
    args.update(kw)
    return c.call(**args)


# ---------------------------------------------------------------- cache
def test_cache_miss_then_hit(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": 1}))
    c = _client(tmp_path, "cache", be)
    parsed, rec = _call(c)
    assert isinstance(parsed, Out) and parsed.answer == "hi"
    assert be.calls == 1 and rec.cache_hit is False
    assert rec.model == MODEL and rec.request_id == "req_test" and rec.principal == "agent.reader"
    assert rec.input_fact_ids == ["F:1"] and rec.prompt_version == "t-v1" and rec.effort == "low"
    assert (tmp_path / "llm" / f"{rec.prompt_hash}.json").exists()

    parsed2, rec2 = _call(c, principal="claims_lead:maria", input_fact_ids=["F:2"])
    assert be.calls == 1, "second identical call must be served from the disk cache"
    assert rec2.cache_hit is True and parsed2 == parsed and rec2.prompt_hash == rec.prompt_hash
    assert rec2.principal == "claims_lead:maria" and rec2.input_fact_ids == ["F:2"]


def test_cache_key_covers_model_system_messages_schema_effort_prompt_version() -> None:
    base = dict(model=MODEL, system=SYSTEM, messages=MSGS, schema=Out, effort="low", prompt_version="v1")
    k = cache_key(**base)
    assert len(k) == 64 and k == cache_key(**base)
    for change in [{"model": "claude-opus-5"}, {"system": SYSTEM + "!"}, {"messages": [{"role": "user", "content": "x"}]},
                   {"schema": None}, {"effort": "medium"}, {"prompt_version": "v2"}]:
        assert cache_key(**{**base, **change}) != k, change


def test_demo_dir_is_read_but_never_written(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "demo", "n": 7}))
    rec_client = LlmClient(mode="live", cache_dir=tmp_path / "demo", read_dirs=[], backend=be, clock=lambda: T0)
    _, rec = _call(rec_client)
    c = _client(tmp_path, "offline")
    parsed, rec2 = _call(c)
    assert parsed.n == 7 and rec2.cache_hit and rec2.prompt_hash == rec.prompt_hash
    assert not (tmp_path / "llm").exists()


def test_live_mode_skips_cache_read(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": be.calls}))
    c = _client(tmp_path, "live", be)
    _call(c)
    _call(c)
    assert be.calls == 2


def test_text_call_without_schema(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok(text="plain prose"))
    c = _client(tmp_path, "cache", be)
    parsed, rec = _call(c, schema=None, role="drafter", effort="medium")
    assert parsed == "plain prose" and rec.schema_name is None and rec.role == "drafter"


# ---------------------------------------------------------------- offline: no network, ever
@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise AssertionError("network access attempted in offline mode")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(llm_client.anthropic, "Anthropic", boom)
    with respx.mock(assert_all_called=False) as router:
        route = router.route().mock(side_effect=AssertionError("httpx request in offline mode"))
        yield route


def test_offline_miss_raises_without_network(tmp_path: Path, no_network) -> None:
    c = _client(tmp_path, "offline")          # default backend = real Anthropic SDK (never constructed)
    with pytest.raises(LLMUnavailable) as e:
        _call(c)
    assert e.value.code == "offline_miss"
    assert not no_network.called


def test_offline_hit_without_network(tmp_path: Path, no_network) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "cached", "n": 3}))
    _call(LlmClient(mode="live", cache_dir=tmp_path / "demo", read_dirs=[], backend=be, clock=lambda: T0))
    c = _client(tmp_path, "offline")
    parsed, rec = _call(c)
    assert parsed.answer == "cached" and rec.cache_hit and rec.mode == "offline"
    assert not no_network.called


def test_mode_defaults_to_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "offline")
    assert LlmClient(cache_dir=tmp_path).mode == "offline"
    monkeypatch.setenv("LLM_MODE", "bogus")
    with pytest.raises(ValueError):
        LlmClient(cache_dir=tmp_path)


# ---------------------------------------------------------------- refusals
def test_refusal_raises_and_is_recorded(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok(None, text="", stop="refusal"))
    c = _client(tmp_path, "cache", be)
    with pytest.raises(LLMRefused) as e:
        _call(c)
    assert isinstance(e.value, LLMUnavailable) and e.value.code == "refusal"
    assert e.value.record is not None and e.value.record.refused and e.value.record.stop_reason == "refusal"
    # the refusal is cached, so replay is deterministic and offline replays it too
    with pytest.raises(LLMRefused):
        _call(_client(tmp_path, "offline"))
    assert be.calls == 1


def test_unparseable_output_is_unavailable_and_not_cached(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok(None, text='{"answer": "x"', stop="max_tokens"))
    c = _client(tmp_path, "cache", be)
    with pytest.raises(LLMUnavailable) as e:
        _call(c)
    assert e.value.code in {"max_tokens", "unparseable"}
    assert not list((tmp_path / "llm").glob("*.json")) or all(
        p.name.startswith("_") for p in (tmp_path / "llm").glob("*.json"))


# ---------------------------------------------------------------- dollar cap
def test_cap_blocks_before_calling(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": 1}))
    c = _client(tmp_path, "cache", be, cap_usd=0.0001)
    with pytest.raises(LLMUnavailable) as e:
        _call(c)
    assert e.value.code == "over_cap" and be.calls == 0


def test_running_spend_accumulates_and_persists(tmp_path: Path) -> None:
    # 20k output tokens at $20/M = $0.40 per call (plus input); the third call's worst case crosses $0.82
    usage = {"input_tokens": 1000, "output_tokens": 20_000}
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": be.calls}, usage=usage))
    c = _client(tmp_path, "live", be, cap_usd=0.82)
    _call(c, max_tokens=1000)
    _call(c, max_tokens=1000)
    assert c.spent_usd == pytest.approx(2 * (1000 * 4 + 20_000 * 20) / 1e6)
    c2 = _client(tmp_path, "live", be, cap_usd=0.82)     # a new process sees the same ledger
    assert c2.spent_usd == pytest.approx(c.spent_usd)
    with pytest.raises(LLMUnavailable) as e:
        _call(c2, max_tokens=1000)
    assert e.value.code == "over_cap" and be.calls == 2


def test_cache_hits_cost_nothing(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": 1}))
    c = _client(tmp_path, "cache", be)
    _, r1 = _call(c)
    _, r2 = _call(c)
    assert r1.cost_usd > 0 and r2.cost_usd == 0


# ---------------------------------------------------------------- the real SDK request (mock transport)
def _sdk_backend(handler) -> AnthropicBackend:
    import anthropic
    sdk = anthropic.Anthropic(api_key="sk-test", max_retries=0,
                              http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return AnthropicBackend(sdk=sdk)


def _message(text: str, *, model: str = MODEL, stop: str = "end_turn", extra_blocks=()) -> dict:
    return {"id": "msg_01", "type": "message", "role": "assistant", "model": model, "stop_reason": stop,
            "stop_sequence": None, "content": [*extra_blocks, {"type": "text", "text": text}],
            "usage": {"input_tokens": 321, "output_tokens": 45}}


def test_sdk_request_shape(tmp_path: Path) -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return httpx2.Response(200, json=_message('{"answer": "hi", "n": 2}'), headers={"request-id": "req_abc"})

    c = _client(tmp_path, "cache", _sdk_backend(handler))
    parsed, rec = _call(c)
    body = seen["body"]
    assert seen["url"].endswith("/v1/messages?beta=true") or seen["url"].endswith("/v1/messages")
    assert body["model"] == "claude-opus-5-5"
    for banned in ("temperature", "top_p", "top_k", "tool_choice", "tools"):
        assert banned not in body, banned
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"].get("anthropic-beta", "")
    assert body["system"] == SYSTEM and body["messages"] == MSGS
    assert parsed == Out(answer="hi", n=2)
    assert rec.request_id == "req_abc" and rec.model == MODEL and rec.fallback is False
    assert rec.usage["input_tokens"] == 321


def test_sdk_fallback_model_is_logged(tmp_path: Path) -> None:
    fb = {"type": "fallback", "from": {"model": MODEL}, "to": {"model": "claude-opus-4-8"},
          "trigger": {"type": "refusal", "category": "cyber"}}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_message('{"answer": "fb", "n": 0}', model="claude-opus-4-8",
                                                  extra_blocks=[fb]), headers={"request-id": "req_fb"})

    c = _client(tmp_path, "cache", _sdk_backend(handler))
    parsed, rec = _call(c)
    assert parsed.answer == "fb" and rec.model == "claude-opus-4-8" and rec.fallback is True
    assert rec.model_requested == MODEL


def test_sdk_refusal(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        m = _message("", stop="refusal")
        m["content"] = []
        m["stop_details"] = {"type": "refusal", "category": None, "explanation": None}
        return httpx2.Response(200, json=m, headers={"request-id": "req_ref"})

    c = _client(tmp_path, "cache", _sdk_backend(handler))
    with pytest.raises(LLMRefused) as e:
        _call(c)
    assert e.value.record.request_id == "req_ref"


def test_sdk_http_errors_become_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})

    c = _client(tmp_path, "cache", _sdk_backend(handler))
    with pytest.raises(LLMUnavailable) as e:
        _call(c)
    assert e.value.code == "upstream"


def test_sdk_retries_without_fallbacks_if_rejected(tmp_path: Path) -> None:
    bodies: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "fallbacks" in body:
            return httpx2.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "fallbacks: not supported for this account"}})
        return httpx2.Response(200, json=_message('{"answer": "ok", "n": 1}'), headers={"request-id": "r2"})

    c = _client(tmp_path, "cache", _sdk_backend(handler))
    parsed, rec = _call(c)
    assert parsed.answer == "ok" and len(bodies) == 2 and "fallbacks" not in bodies[1]


# ---------------------------------------------------------------- batches (keyed by custom_id)
def test_batch_keyed_by_custom_id_and_cached(tmp_path: Path) -> None:
    def respond(req):
        return _ok({"answer": req.messages[0]["content"], "n": len(req.messages[0]["content"])})

    be = ScriptedBackend(respond, batch_reverse=True)       # results come back in a different order
    c = _client(tmp_path, "cache", be)
    items = [BatchItem(custom_id=f"run:{i}@EIDW", role="drafter", system=SYSTEM,
                       messages=[{"role": "user", "content": "x" * (i + 1)}], schema=Out, effort="medium",
                       prompt_version="b-v1", principal="eval") for i in range(3)]
    out = c.batch(items, poll_s=0)
    assert set(out) == {i.custom_id for i in items}
    for i in range(3):
        o = out[f"run:{i}@EIDW"]
        assert o.error is None and o.parsed.n == i + 1 and o.record.batch_custom_id == f"run:{i}@EIDW"
    assert be.batches == 1 and be.calls == 0
    first = out["run:0@EIDW"].record
    assert first.cost_usd == pytest.approx((100 * 4 + 50 * 20) / 1e6 * 0.5)     # Batches API is 50% off

    again = c.batch(items, poll_s=0)                   # all cache hits now
    assert be.batches == 1 and all(o.record.cache_hit for o in again.values())

    off = _client(tmp_path / "other", "offline").batch(items, poll_s=0)
    assert all(isinstance(o.error, LLMUnavailable) for o in off.values())


def test_batch_custom_ids_are_sanitised_for_the_api(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "a", "n": 1}))
    c = _client(tmp_path, "cache", be)
    c.batch([BatchItem(custom_id="NS31@2025-01-24:14C", role="drafter", system=SYSTEM, messages=MSGS, schema=Out,
                       effort="medium", prompt_version="b-v1", principal="eval")], poll_s=0)
    import re
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid) for cid in be.submitted_custom_ids)


# ---------------------------------------------------------------- cache file format
def test_cache_file_is_self_describing(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: _ok({"answer": "hi", "n": 1}), provenance="hand-written")
    c = _client(tmp_path, "cache", be)
    _, rec = _call(c)
    data = orjson.loads((tmp_path / "llm" / f"{rec.prompt_hash}.json").read_bytes())
    assert data["key"] == rec.prompt_hash
    assert data["request"]["model"] == MODEL and data["request"]["effort"] == "low"
    assert data["request"]["schema_name"] == "Out" and data["request"]["prompt_version"] == "t-v1"
    assert data["response"]["parsed"] == {"answer": "hi", "n": 1}
    assert data["provenance"] == "hand-written" and rec.provenance == "hand-written"
    assert data["recorded_at"] == "2025-01-25T06:00:00Z"
