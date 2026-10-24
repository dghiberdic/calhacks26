# llm/ decisions (Filip lane B)

Judgment calls made while building the LLM client, the Reader and the Drafter. The binding rules are in
`CLAUDE.md` and `IMPLEMENTATION_PLAN.md §2`: the LLM never decides who is owed, never computes an amount and never
derives root cause, and every call is recorded.

## F4: `llm/client.py`

### Request shape
- **Model** `claude-opus-5-5`. **Thinking** `{"type": "adaptive"}` is sent explicitly. **Effort** always goes
  through `output_config.effort`, because Opus 5.5 defaults to `medium` and the Reader wants `low`.
- **Never sent:** `temperature`, `top_p`, `top_k`, `tool_choice`, `tools`. A test inspects the real SDK request
  body over an `httpx2.MockTransport` to check this.
- **Structured output** uses `client.beta.messages.parse(..., output_format=Model)`. The beta namespace is needed
  because that is where the installed SDK (anthropic 2.3.0) exposes `fallbacks`. Text calls use
  `client.beta.messages.create`.
- **Server-side fallbacks:** `fallbacks="default"` with beta `server-side-fallback-2026-07-01`. If the API rejects
  the parameter with a 400 that mentions "fallback", the client retries once without it.
  - The record logs `response.model`, `_request_id`, and `fallback = True` when any of these holds: there is a
    `fallback` content block, there is a `fallback_message` usage iteration, or the response model differs from the
    one requested.
  - The Batches API rejects `fallbacks`, so batch requests omit it.

### Cache
- **The key** is sha256 over (model, system, messages, schema, effort, prompt_version), using
  `orjson.OPT_SORT_KEYS`. The schema part is the JSON schema the SDK actually sends (`to_json_output_format`), so
  a schema change invalidates the key. Principal and input fact ids are *not* in the key: the same prompt read for a
  different principal is a cache hit, and the record carries the new principal.
- **Directories.** Writes go to `data/cache/llm/` (gitignored, or `LLM_CACHE_DIR`). Reads check that directory
  first, then `data/cache/demo/` (committed recordings). The demo directory is never written by normal calls.
  Recordings are promoted into it on purpose by `llm/recordings.py`.
- **File format.** Each file holds `{key, request{model, system, messages, effort, prompt_version, max_tokens,
  schema_name, schema}, response{model, request_id, message_id, stop_reason, stop_details, text, parsed, usage,
  fallback}, provenance, recorded_at}`. The format is self-describing, so a reviewer can audit any recording.
- **What gets cached.** Refusals are cached, so replay of a refused call stays deterministic and offline replays the
  refusal too. Truncated (`max_tokens`) and unparseable outputs are not cached.

### Modes
- `LLM_MODE` falls back to `STORMCHECK_MODE`, then to `cache`. Any other value raises `ValueError` at
  construction.
- **`offline`** never builds an SDK client. A miss raises `LLMUnavailable(code="offline_miss")`. The test blocks
  `socket.connect`, `socket.create_connection` and `anthropic.Anthropic`, and routes httpx through respx.
  - respx alone can't prove anything here, because SDK 2.x runs on `httpx2`, not `httpx`.
- **`live`** skips cache reads, calls the API, and refreshes the cache.
- `llm/tests/conftest.py` forces `LLM_MODE=offline` and unsets `ANTHROPIC_API_KEY` for every llm test.

### Dollar cap
- `LLM_CAP_USD` defaults to 30, the thread budget. Spend is a running estimate kept in
  `<cache_dir>/_spend.json`, so it survives restarts.
- **Before each call**, the client computes a worst case: input tokens estimated at 3 chars per token, plus
  2,000 tokens if a schema is sent, plus `max_tokens` of output, at the model's price. If spend plus that worst case
  would exceed the cap, the call raises `over_cap` and nothing is sent.
- **After each call**, the client adds the actual `usage` cost (cache reads at 0.1×, cache writes at 1.25×).
- **Prices** are $ per million tokens: opus-5-5 $4 / $20; the fallback models opus-5 and opus-4-8 $5 / $25.
  Batches cost 50% of that.
- Cache hits cost 0. Hand-written recordings cost 0 and are marked `provenance: "hand-written"`.

### Errors
- **`LLMUnavailable(code, message, record)`**, where `code` is one of:
  - `offline_miss`, `over_cap`, `no_credentials`, `timeout`, `connection`, `rate_limited`, `upstream`,
    `bad_request`, `unparseable`, `max_tokens`, `refusal`;
  - for batches: `batch_errored`, `batch_canceled`, `batch_expired`, `batch_timeout`, `batch_missing`.
- **`LLMRefused`** is a subclass, so every caller's single `except LLMUnavailable` takes its fallback path (the regex
  Reader, or a template Draft).
- **Timeout:** a per-call `timeout_s` sets `with_options(timeout=..., max_retries=0)`. This is how the Reader gets its
  8 s budget without SDK retries stretching it.

### Records
- **`LlmCallRecord`** lives in `llm/client.py`, not `contracts/`, because no contract model exists for it. Its fields:
  - `id = "LLM:<hash16>"`, `role`, `prompt_version`, `prompt_hash`;
  - `model_requested`, `model`, `request_id`, `message_id`;
  - `principal`, `input_fact_ids`, `effort`, `schema_name`, `mode`;
  - `cache_hit`, `provenance`, `stop_reason`, `refused`, `fallback`, `usage`, `cost_usd`;
  - `recorded_at` (the cache file's time on a hit), `batch_custom_id`.
- David's server turns a record into an `llm_call` commit. `payload_ref` should be the `prompt_hash` (the cache
  file).

### Batches
- `LlmClient.batch(items)` returns `{custom_id: BatchOutcome(parsed, record, error)}`, always keyed by the caller's
  `custom_id`.
- **custom_id format.** The API only allows `[A-Za-z0-9_-]{1,64}`, but our ids contain `@` and `:`. So each item is
  submitted as `c<n>_<sha12>` and mapped back.
- **Cache.** Hits are served locally. Only misses are submitted, in one batch, and the cap is checked on them first.
  In offline mode a miss becomes an error outcome; the batch call itself never raises.
- **Waiting.** Polling uses an injected `sleep`, and `max_wait_s` defaults to 24 h.

### No API key in this session
`ANTHROPIC_API_KEY` was not set when lanes B ran, so no live calls were made. Every recording in
`data/cache/demo/` is **hand-written**, built by `llm/recordings.py` from the real prompt builders, and marked
`"provenance": "hand-written"` with `request_id: "hand-written"`. To replace them with real responses:

```
LLM_MODE=live LLM_CACHE_DIR=data/cache/demo uv run python -m llm.recordings --live
```

Then re-run the tests. Live outputs that fail span verification are dropped by design, so expected-fact tests may
need loosening only where the live model picks a different, still verbatim, span.
