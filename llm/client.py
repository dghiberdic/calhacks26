"""The one wrapper for every Claude call in StormCheck (F4).

``LlmClient.call(role, system, messages, schema, effort, prompt_version, principal)`` → ``(parsed, LlmCallRecord)``.

- **Disk cache** at ``data/cache/llm/<sha256(model, system, messages, schema, effort, prompt_version)>.json``. Reads
  also look in ``data/cache/demo/`` (committed recordings); writes only go to the write dir.
- **``LLM_MODE``** = ``live`` (always call, refresh the cache) | ``cache`` (cache first, call on a miss) |
  ``offline`` (cache only; a miss raises ``LLMUnavailable``). Falls back to ``STORMCHECK_MODE``, then ``cache``.
- **Dollar cap** (``LLM_CAP_USD``, default 30): a running spend estimate persisted next to the cache. A call whose
  worst case would cross the cap raises ``LLMUnavailable(code="over_cap")`` before anything is sent.
- **Requests** use ``claude-opus-5-5`` with adaptive thinking, ``output_config.effort`` set explicitly, structured
  output via ``client.beta.messages.parse(..., output_format=Model)`` and server-side ``fallbacks="default"``
  (beta ``server-side-fallback-2026-07-01``). Never ``temperature``/``top_p``/``top_k``, never a forced
  ``tool_choice``, never tools.
- **Refusals** (``stop_reason == "refusal"``) raise ``LLMRefused`` (an ``LLMUnavailable``) carrying the record; they
  are cached, so replay is deterministic.
- **Batches** (``LlmClient.batch``): 50% cheaper, results keyed by ``custom_id`` (never by position).

Every call returns an ``LlmCallRecord`` (prompt hash, ``response.model``, request id, principal, input fact ids):
the server turns it into an ``llm_call`` commit.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
import orjson
import pydantic
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache" / "llm"
DEMO_CACHE_DIR = ROOT / "data" / "cache" / "demo"

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODES = ("live", "cache", "offline")
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# $ per million tokens (input, output). Fallback models are priced at their own rates.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
}
BATCH_DISCOUNT = 0.5
DEFAULT_CAP_USD = 30.0
SPEND_FILE = "_spend.json"


# ---------------------------------------------------------------- errors
class LLMUnavailable(RuntimeError):
    """The LLM could not produce a usable answer. Callers fall back (regex parsers, templates)."""

    def __init__(self, code: str, message: str, record: LlmCallRecord | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.record = record


class LLMRefused(LLMUnavailable):
    """``stop_reason == "refusal"`` after the server-side fallback chain."""


# ---------------------------------------------------------------- records
class LlmCallRecord(BaseModel):
    """What David's server turns into an ``llm_call`` commit. Outputs are stored separately as Facts/Drafts."""

    id: str                                  # "LLM:<prompt_hash[:16]>"
    role: str                                # "reader" | "drafter" | "baseline" | ...
    prompt_version: str
    prompt_hash: str                         # the cache key (sha256 hex)
    model_requested: str
    model: str | None = None                 # response.model (a fallback can change it)
    request_id: str | None = None            # response._request_id
    message_id: str | None = None
    principal: str
    input_fact_ids: list[str] = []
    effort: str
    schema_name: str | None = None
    mode: str
    cache_hit: bool
    provenance: str = "live"                 # "live" | "live-batch" | "hand-written"
    stop_reason: str | None = None
    refused: bool = False
    fallback: bool = False                   # served by a fallback model
    usage: dict[str, int] = {}
    cost_usd: float = 0.0                    # spend caused by THIS call (0 on a cache hit)
    recorded_at: datetime | None = None      # when the response was recorded (from the cache file on a hit)
    batch_custom_id: str | None = None


@dataclass
class LlmRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    effort: str
    max_tokens: int
    schema: type[BaseModel] | None
    timeout_s: float | None = None


@dataclass
class RawResponse:
    model: str | None
    request_id: str | None
    message_id: str | None
    stop_reason: str | None
    stop_details: dict[str, Any] | None
    text: str
    parsed: dict[str, Any] | None            # structured output as JSON-mode dict (None for text calls / refusals)
    usage: dict[str, int] = field(default_factory=dict)
    fallback: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"model": self.model, "request_id": self.request_id, "message_id": self.message_id,
                "stop_reason": self.stop_reason, "stop_details": self.stop_details, "text": self.text,
                "parsed": self.parsed, "usage": self.usage, "fallback": self.fallback}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RawResponse:
        return cls(model=d.get("model"), request_id=d.get("request_id"), message_id=d.get("message_id"),
                   stop_reason=d.get("stop_reason"), stop_details=d.get("stop_details"), text=d.get("text") or "",
                   parsed=d.get("parsed"), usage=dict(d.get("usage") or {}), fallback=bool(d.get("fallback")))


@dataclass
class BatchItem:
    custom_id: str
    role: str
    system: str
    messages: list[dict[str, Any]]
    schema: type[BaseModel] | None
    effort: str
    prompt_version: str
    principal: str
    input_fact_ids: Sequence[str] = ()
    max_tokens: int = 16000
    model: str = MODEL


@dataclass
class BatchOutcome:
    parsed: Any = None
    record: LlmCallRecord | None = None
    error: LLMUnavailable | None = None


# ---------------------------------------------------------------- hashing
def schema_json(schema: type[BaseModel] | None) -> dict[str, Any] | None:
    """The JSON schema actually sent to the API for ``schema`` (SDK transform), used in the cache key."""
    if schema is None:
        return None
    try:
        from anthropic.lib._parse._transform import to_json_output_format
        return dict(to_json_output_format(schema))
    except Exception:  # pragma: no cover - SDK internals moved; keep a stable key anyway
        return {"type": "json_schema", "schema": schema.model_json_schema()}


def cache_key(*, model: str, system: str, messages: list[dict[str, Any]], schema: type[BaseModel] | None,
              effort: str, prompt_version: str) -> str:
    blob = orjson.dumps({"model": model, "system": system, "messages": messages, "schema": schema_json(schema),
                         "effort": effort, "prompt_version": prompt_version}, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(blob).hexdigest()


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for the pre-call cap check (~3 chars per token)."""
    return max(1, len(text) // 3)


def price_usd(model: str | None, usage: dict[str, int], *, batch: bool = False) -> float:
    pin, pout = PRICES.get(model or MODEL, PRICES[MODEL])
    inp = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) * 1.25 \
        + usage.get("cache_read_input_tokens", 0) * 0.1
    cost = (inp * pin + usage.get("output_tokens", 0) * pout) / 1e6
    return cost * (BATCH_DISCOUNT if batch else 1.0)


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- backends
class AnthropicBackend:
    """The real SDK. Constructed lazily, so offline mode never builds a client (or touches the network)."""

    provenance = "live"

    def __init__(self, sdk: Any = None, *, max_retries: int = 2):
        self._sdk = sdk
        self._max_retries = max_retries

    def sdk(self) -> Any:
        if self._sdk is None:
            try:
                self._sdk = anthropic.Anthropic(max_retries=self._max_retries)
            except Exception as e:  # no credentials, bad config
                raise LLMUnavailable("no_credentials", f"cannot build the Anthropic client: {e}") from e
        return self._sdk

    @staticmethod
    def _kwargs(req: LlmRequest, *, fallbacks: bool) -> dict[str, Any]:
        kw: dict[str, Any] = dict(model=req.model, max_tokens=req.max_tokens, system=req.system,
                                  messages=req.messages, thinking={"type": "adaptive"},
                                  output_config={"effort": req.effort})
        if fallbacks:
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
        return kw

    def call(self, req: LlmRequest) -> RawResponse:
        sdk = self.sdk()
        if req.timeout_s is not None:
            sdk = sdk.with_options(timeout=req.timeout_s, max_retries=0)
        try:
            return self._send(sdk, req, fallbacks=True)
        except anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise LLMUnavailable("bad_request", str(e)) from e
            return self._send(sdk, req, fallbacks=False)   # account/model without server-side fallback

    def _send(self, sdk: Any, req: LlmRequest, *, fallbacks: bool) -> RawResponse:
        kw = self._kwargs(req, fallbacks=fallbacks)
        try:
            if req.schema is not None:
                resp = sdk.beta.messages.parse(output_format=req.schema, **kw)
            else:
                resp = sdk.beta.messages.create(**kw)
        except anthropic.BadRequestError:
            raise
        except pydantic.ValidationError as e:
            raise LLMUnavailable("unparseable", f"structured output did not validate: {e}") from e
        except anthropic.APITimeoutError as e:
            raise LLMUnavailable("timeout", str(e)) from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable("connection", str(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailable("rate_limited", str(e)) from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMUnavailable("no_credentials", str(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailable("upstream", f"HTTP {e.status_code}: {e.message}") from e
        return self._raw(resp, req.model)

    @staticmethod
    def _raw(resp: Any, requested: str) -> RawResponse:
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
        parsed = None
        po = getattr(resp, "parsed_output", None)
        if isinstance(po, BaseModel):
            parsed = po.model_dump(mode="json")
        usage: dict[str, int] = {}
        u = getattr(resp, "usage", None)
        fallback = any(getattr(b, "type", None) == "fallback" for b in resp.content)
        if u is not None:
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                v = getattr(u, k, None)
                if isinstance(v, int):
                    usage[k] = v
            its = getattr(u, "iterations", None) or []
            fallback = fallback or any(getattr(i, "type", None) == "fallback_message" for i in its)
        sd = getattr(resp, "stop_details", None)
        stop_details = sd.model_dump(mode="json") if isinstance(sd, BaseModel) else (sd or None)
        model = getattr(resp, "model", None)
        return RawResponse(model=model, request_id=getattr(resp, "_request_id", None),
                           message_id=getattr(resp, "id", None), stop_reason=getattr(resp, "stop_reason", None),
                           stop_details=stop_details, text=text, parsed=parsed, usage=usage,
                           fallback=fallback or (model is not None and model != requested))

    # -- batches (no server-side fallbacks on the Batches API)
    def batch_submit(self, items: list[tuple[str, LlmRequest]]) -> str:
        reqs = []
        for cid, req in items:
            params: dict[str, Any] = dict(model=req.model, max_tokens=req.max_tokens, system=req.system,
                                          messages=req.messages, thinking={"type": "adaptive"},
                                          output_config={"effort": req.effort})
            fmt = schema_json(req.schema)
            if fmt is not None:
                params["output_config"] = {"effort": req.effort, "format": fmt}
            reqs.append({"custom_id": cid, "params": params})
        try:
            return self.sdk().messages.batches.create(requests=reqs).id
        except anthropic.APIError as e:
            raise LLMUnavailable("upstream", f"batch submit failed: {e}") from e

    def batch_status(self, batch_id: str) -> str:
        return self.sdk().messages.batches.retrieve(batch_id).processing_status

    def batch_results(self, batch_id: str, schemas: dict[str, type[BaseModel] | None],
                      requested: str) -> Iterable[tuple[str, RawResponse | LLMUnavailable]]:
        for r in self.sdk().messages.batches.results(batch_id):
            cid = r.custom_id
            if r.result.type != "succeeded":
                yield cid, LLMUnavailable("batch_" + r.result.type, f"batch item {cid}: {r.result.type}")
                continue
            raw = self._raw(r.result.message, requested)
            schema = schemas.get(cid)
            if schema is not None and raw.stop_reason != "refusal":
                try:
                    raw.parsed = schema.model_validate_json(raw.text).model_dump(mode="json")
                except pydantic.ValidationError as e:
                    yield cid, LLMUnavailable("unparseable", f"batch item {cid}: {e}")
                    continue
            yield cid, raw


class ScriptedBackend:
    """A backend that answers from a function: hand-written recordings and tests. Never touches the network."""

    def __init__(self, respond: Callable[[LlmRequest], RawResponse], *, provenance: str = "scripted",
                 batch_reverse: bool = False):
        self.respond = respond
        self.provenance = provenance
        self.calls = 0
        self.batches = 0
        self.submitted_custom_ids: list[str] = []
        self._batch_reverse = batch_reverse
        self._pending: dict[str, list[tuple[str, LlmRequest]]] = {}

    def call(self, req: LlmRequest) -> RawResponse:
        self.calls += 1
        return self.respond(req)

    def batch_submit(self, items: list[tuple[str, LlmRequest]]) -> str:
        self.batches += 1
        bid = f"batch_{self.batches}"
        self._pending[bid] = list(items)
        self.submitted_custom_ids += [cid for cid, _ in items]
        return bid

    def batch_status(self, batch_id: str) -> str:
        return "ended"

    def batch_results(self, batch_id: str, schemas: dict[str, type[BaseModel] | None],
                      requested: str) -> Iterable[tuple[str, RawResponse | LLMUnavailable]]:
        items = self._pending.pop(batch_id)
        if self._batch_reverse:
            items = items[::-1]
        for cid, req in items:
            yield cid, self.respond(req)


# ---------------------------------------------------------------- client
class LlmClient:
    def __init__(self, *, mode: str | None = None, cache_dir: str | Path | None = None,
                 read_dirs: Sequence[str | Path] | None = None, backend: Any = None,
                 cap_usd: float | None = None, clock: Callable[[], datetime] | None = None):
        mode = mode or os.environ.get("LLM_MODE") or os.environ.get("STORMCHECK_MODE") or "cache"
        if mode not in MODES:
            raise ValueError(f"LLM_MODE must be one of {MODES}, got {mode!r}")
        self.mode = mode
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path(
            os.environ.get("LLM_CACHE_DIR") or DEFAULT_CACHE_DIR)
        extra = [DEMO_CACHE_DIR] if read_dirs is None else [Path(p) for p in read_dirs]
        self.read_dirs = [self.cache_dir, *[p for p in extra if p != self.cache_dir]]
        self.backend = backend if backend is not None else AnthropicBackend()
        self.cap_usd = float(cap_usd if cap_usd is not None else os.environ.get("LLM_CAP_USD", DEFAULT_CAP_USD))
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- spend ledger
    @property
    def _spend_path(self) -> Path:
        return self.cache_dir / SPEND_FILE

    @property
    def spent_usd(self) -> float:
        try:
            return float(orjson.loads(self._spend_path.read_bytes()).get("usd", 0.0))
        except (FileNotFoundError, ValueError):
            return 0.0

    def _add_spend(self, usd: float) -> None:
        if usd <= 0:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = orjson.loads(self._spend_path.read_bytes())
        except (FileNotFoundError, ValueError):
            data = {"usd": 0.0, "calls": 0}
        data["usd"] = float(data.get("usd", 0.0)) + usd
        data["calls"] = int(data.get("calls", 0)) + 1
        self._spend_path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))

    def _check_cap(self, reqs: Iterable[LlmRequest], *, batch: bool = False) -> None:
        worst = 0.0
        for r in reqs:
            inp = estimate_tokens(r.system + orjson.dumps(r.messages).decode()) + 2000 * (r.schema is not None)
            worst += price_usd(r.model, {"input_tokens": inp, "output_tokens": r.max_tokens}, batch=batch)
        spent = self.spent_usd
        if spent + worst > self.cap_usd:
            raise LLMUnavailable("over_cap", f"spend ${spent:.2f} + worst case ${worst:.2f} would exceed the "
                                             f"${self.cap_usd:.2f} cap (LLM_CAP_USD)")

    # -- cache
    def _read(self, key: str) -> dict[str, Any] | None:
        for d in self.read_dirs:
            p = d / f"{key}.json"
            if p.exists():
                return orjson.loads(p.read_bytes())
        return None

    def _write(self, key: str, req: LlmRequest, prompt_version: str, raw: RawResponse, provenance: str,
               recorded_at: datetime) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "key": key,
            "request": {"model": req.model, "system": req.system, "messages": req.messages, "effort": req.effort,
                        "prompt_version": prompt_version, "max_tokens": req.max_tokens,
                        "schema_name": req.schema.__name__ if req.schema else None,
                        "schema": schema_json(req.schema)},
            "response": raw.to_json(),
            "provenance": provenance,
            "recorded_at": _iso(recorded_at),
        }
        tmp = self.cache_dir / f".{key}.tmp"
        tmp.write_bytes(orjson.dumps(entry, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
        tmp.replace(self.cache_dir / f"{key}.json")

    # -- the call
    def call(self, role: str, system: str, messages: list[dict[str, Any]], schema: type[BaseModel] | None = None,
             *, effort: str, prompt_version: str, principal: str, input_fact_ids: Sequence[str] = (),
             max_tokens: int = 16000, timeout_s: float | None = None, model: str = MODEL) -> tuple[Any, LlmCallRecord]:
        if effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")
        req = LlmRequest(model=model, system=system, messages=messages, effort=effort, max_tokens=max_tokens,
                         schema=schema, timeout_s=timeout_s)
        key = cache_key(model=model, system=system, messages=messages, schema=schema, effort=effort,
                        prompt_version=prompt_version)
        base = dict(id=f"LLM:{key[:16]}", role=role, prompt_version=prompt_version, prompt_hash=key,
                    model_requested=model, principal=principal, input_fact_ids=list(input_fact_ids), effort=effort,
                    schema_name=schema.__name__ if schema else None, mode=self.mode)

        if self.mode != "live":
            hit = self._read(key)
            if hit is not None:
                raw = RawResponse.from_json(hit["response"])
                rec = self._record(base, raw, cache_hit=True, provenance=hit.get("provenance", "live"),
                                   recorded_at=hit.get("recorded_at"), cost=0.0)
                return self._finish(raw, schema, rec), rec
            if self.mode == "offline":
                raise LLMUnavailable("offline_miss", f"LLM_MODE=offline and no recording for {role} "
                                                     f"{prompt_version} ({key[:12]})")

        self._check_cap([req])
        raw = self.backend.call(req)
        provenance = getattr(self.backend, "provenance", "live")
        cost = 0.0 if provenance == "hand-written" else price_usd(raw.model, raw.usage)
        self._add_spend(cost)
        now = self._clock()
        rec = self._record(base, raw, cache_hit=False, provenance=provenance, recorded_at=now, cost=cost)
        if raw.stop_reason == "refusal" or self._usable(raw, schema):
            self._write(key, req, prompt_version, raw, provenance, now)
        return self._finish(raw, schema, rec), rec

    @staticmethod
    def _usable(raw: RawResponse, schema: type[BaseModel] | None) -> bool:
        if raw.stop_reason == "max_tokens":
            return False
        if schema is None:
            return True
        if raw.parsed is not None:
            return True
        try:
            raw.parsed = schema.model_validate_json(raw.text).model_dump(mode="json")
            return True
        except pydantic.ValidationError:
            return False

    @staticmethod
    def _record(base: dict[str, Any], raw: RawResponse, *, cache_hit: bool, provenance: str,
                recorded_at: Any, cost: float, batch_custom_id: str | None = None) -> LlmCallRecord:
        return LlmCallRecord(**base, model=raw.model, request_id=raw.request_id, message_id=raw.message_id,
                             cache_hit=cache_hit, provenance=provenance, stop_reason=raw.stop_reason,
                             refused=raw.stop_reason == "refusal", fallback=raw.fallback, usage=raw.usage,
                             cost_usd=cost, recorded_at=recorded_at, batch_custom_id=batch_custom_id)

    @staticmethod
    def _finish(raw: RawResponse, schema: type[BaseModel] | None, rec: LlmCallRecord) -> Any:
        if raw.stop_reason == "refusal":
            cat = (raw.stop_details or {}).get("category")
            raise LLMRefused("refusal", f"the model declined (category {cat!r})", rec)
        if raw.stop_reason == "max_tokens":
            raise LLMUnavailable("max_tokens", "output hit max_tokens", rec)
        if schema is None:
            return raw.text
        try:
            if raw.parsed is not None:
                return schema.model_validate(raw.parsed)
            return schema.model_validate_json(raw.text)
        except pydantic.ValidationError as e:
            raise LLMUnavailable("unparseable", f"structured output did not validate: {e}", rec) from e

    # -- batches
    def batch(self, items: Sequence[BatchItem], *, poll_s: float = 30.0, max_wait_s: float = 24 * 3600,
              sleep: Callable[[float], None] = time.sleep) -> dict[str, BatchOutcome]:
        """Run many requests through the Batches API (50% off). Cache hits never leave the process."""
        out: dict[str, BatchOutcome] = {}
        todo: list[tuple[BatchItem, LlmRequest, str, dict[str, Any]]] = []
        for it in items:
            req = LlmRequest(model=it.model, system=it.system, messages=it.messages, effort=it.effort,
                             max_tokens=it.max_tokens, schema=it.schema)
            key = cache_key(model=it.model, system=it.system, messages=it.messages, schema=it.schema,
                            effort=it.effort, prompt_version=it.prompt_version)
            base = dict(id=f"LLM:{key[:16]}", role=it.role, prompt_version=it.prompt_version, prompt_hash=key,
                        model_requested=it.model, principal=it.principal, input_fact_ids=list(it.input_fact_ids),
                        effort=it.effort, schema_name=it.schema.__name__ if it.schema else None, mode=self.mode)
            hit = self._read(key) if self.mode != "live" else None
            if hit is not None:
                raw = RawResponse.from_json(hit["response"])
                rec = self._record(base, raw, cache_hit=True, provenance=hit.get("provenance", "live"),
                                   recorded_at=hit.get("recorded_at"), cost=0.0, batch_custom_id=it.custom_id)
                out[it.custom_id] = self._outcome(raw, it.schema, rec)
            elif self.mode == "offline":
                out[it.custom_id] = BatchOutcome(error=LLMUnavailable(
                    "offline_miss", f"LLM_MODE=offline and no recording for batch item {it.custom_id}"))
            else:
                todo.append((it, req, key, base))
        if not todo:
            return out

        try:
            self._check_cap([r for _, r, _, _ in todo], batch=True)
        except LLMUnavailable as e:
            for it, *_ in todo:
                out[it.custom_id] = BatchOutcome(error=e)
            return out
        api_ids = {f"c{n:05d}_{hashlib.sha256(it.custom_id.encode()).hexdigest()[:12]}": (it, req, key, base)
                   for n, (it, req, key, base) in enumerate(todo)}
        batch_id = self.backend.batch_submit([(cid, v[1]) for cid, v in api_ids.items()])
        waited = 0.0
        while self.backend.batch_status(batch_id) != "ended":
            if waited >= max_wait_s:
                for it, *_ in todo:
                    out[it.custom_id] = BatchOutcome(error=LLMUnavailable("batch_timeout", f"batch {batch_id}"))
                return out
            sleep(poll_s)
            waited += poll_s
        provenance = getattr(self.backend, "provenance", "live")
        provenance = "live-batch" if provenance == "live" else provenance
        schemas = {cid: v[1].schema for cid, v in api_ids.items()}
        now = self._clock()
        for cid, res in self.backend.batch_results(batch_id, schemas, MODEL):
            if cid not in api_ids:
                continue
            it, req, key, base = api_ids[cid]
            if isinstance(res, LLMUnavailable):
                out[it.custom_id] = BatchOutcome(error=res)
                continue
            cost = 0.0 if provenance == "hand-written" else price_usd(res.model, res.usage, batch=True)
            self._add_spend(cost)
            rec = self._record(base, res, cache_hit=False, provenance=provenance, recorded_at=now, cost=cost,
                               batch_custom_id=it.custom_id)
            if res.stop_reason == "refusal" or self._usable(res, it.schema):
                self._write(key, req, it.prompt_version, res, provenance, now)
            out[it.custom_id] = self._outcome(res, it.schema, rec)
        for it, *_ in todo:
            out.setdefault(it.custom_id, BatchOutcome(error=LLMUnavailable("batch_missing", it.custom_id)))
        return out

    def _outcome(self, raw: RawResponse, schema: type[BaseModel] | None, rec: LlmCallRecord) -> BatchOutcome:
        try:
            return BatchOutcome(parsed=self._finish(raw, schema, rec), record=rec)
        except LLMUnavailable as e:
            return BatchOutcome(record=rec, error=e)


_default: LlmClient | None = None


def default_client() -> LlmClient:
    """Process-wide client built from the environment (LLM_MODE, LLM_CACHE_DIR, LLM_CAP_USD)."""
    global _default
    if _default is None:
        _default = LlmClient()
    return _default


def call(role: str, system: str, messages: list[dict[str, Any]], schema: type[BaseModel] | None = None, *,
         effort: str, prompt_version: str, principal: str, **kw: Any) -> tuple[Any, LlmCallRecord]:
    """Module-level convenience: ``default_client().call(...)``."""
    return default_client().call(role, system, messages, schema, effort=effort, prompt_version=prompt_version,
                                 principal=principal, **kw)


_SAFE_ID = re.compile(r"[^A-Za-z0-9@.:_-]")


def safe_id(s: str) -> str:
    """Project id alphabet: only ``[A-Za-z0-9@.:_-]``."""
    return _SAFE_ID.sub("-", s)


Mode = Literal["live", "cache", "offline"]
