# contracts/DECISIONS.md (David lane B judgment calls)

## D0a: stub server + api fixtures

**Fixtures**
- **Built by a script.** `scripts/build_stub_fixtures.py` turns hand-entered plan numbers (§1.2–1.4, CONTRACTS §5) into validated `contracts.models` instances and writes `contracts/fixtures/api/*.json`. Nothing is hand-typed JSON, so a typo fails at build time. Rebuild with `make stub-fixtures`. D0b's `scripts/build_api_fixtures.py` (golden + fakes) supersedes it.
- **The storm fixture holds the whole day,** not just the brief's minimum: all 27 cancellations plus the 11 that operated. The map and timeline need every arc and tick, and the counters must reconcile (5,292 pax).
- **There is a `flight_*.json` for every cancelled flight.** Operated flights return 404 on `/flights/{id}`, because `FlightFile.decision` is required and they have no decision.
- **Overnight inbound IDs use the local departure date,** per `Flight.date`: `NS20@2025-01-23`, `NS30@2025-01-23`, `NS40@2025-01-23`, `NS50@2025-01-23`.
- **Both storm windows are listed,** sorted by start: the minor one 23:30–00:30Z (peak 38) and the main one 02:30–15:00Z (peak 56). Choose the main window by duration or peak; `windows[0]` is the minor one.
- **`window_margin_min`** is the non-negative distance in minutes to the nearest edge of the main DUB window. It is measured at the DUB end (STD for DUB departures, STA for DUB arrivals). `in_window_*` says which side.
- **The outstation end is `"out"`** for every flight (no outstation METAR in the stub).
- **`Q-3` (Controller, Isha release, 72%) is included** even though the brief named only Q1 and Q2. The plan's headline is "3 questions · 3 people", and counters come from the API.
- **Counters:**
  - `drafted` = 172 (NS31 payouts drafted)
  - `held` = 530 (passengers on the 3 knock-on flights held for Legal)
  - `rules_cited` = 37 citations (23 weather decisions cite R-REG-ART5-3 plus 14 Art. 7(2) reductions)
  - extra keys: `recoded` = 1, `weather` = 23
- **Money:** `entitlement_cents` = 9,900,000 (owed entitlements only, i.e. NS31). `liability_drafted_cents` = 8,214,600 (the storm day-1 golden number, including held knock-on accruals).
- **Invented details** (the plan doesn't give them; D0b's golden world replaces them):
  - STA of outbound sectors (block times)
  - tails other than EI-NSB, EI-NSN and EI-NSL
  - the 11 operated flights' numbers and destinations (incl. BRU/MAN/EDI/CPH/ZRH)
  - the spares and reroute lines for NS113 and NS115 (patterned on NS117)
  - the CRM/claim quotes for 14C
  - chain-ladder 3,726,667 and credibility z 0.31
  - `eval.json`, which is a **placeholder** (only `stormcheck_runs` comes from the contract). Don't quote its numbers.
- **Plan nit:** §1.2 says weather at 21:40Z was 13 kt. The nearest obs (21:30Z) is 14 kt; 21:00Z is 13 kt. The fixture quotes the 21:30Z obs.
- **Hard-control rule cards** (`R-HC-*`) and the static Reg 2026/2202 card use `condition: {"all": []}`. They are code or display-only; the new `Rule.title` carries the text.

**Contract additions** (additive; logged in CHANGELOG)
- `Rule.title` and `StormRun.airports`.
- Envelope models for the shapes CONTRACTS §3 gave only as dict literals.
- `LockResponse.locked` is the period string. `Health.mode` = `"stub"` here, and `impl` is a dict.

**Stub behaviour**
- **State is in memory:** clock, rulings, proposals, rules, journal approvals, locks and the trace. It lasts until `POST /api/reset` or a restart. The clock starts at 2025-01-25T06:00Z ("the morning after").
- **Auth:** `POST /api/session` issues `<b64 Session>.<hmac>`, signed with a fixed, non-secret stub key. A missing, malformed or forged token is treated as `judge` (fail closed).
  - Human principals are `<role>:<name-slug>`. Agents and the judge are the bare role.
- **Questions:**
  - Scoping: `claims_lead`, `legal`, `controller` and `ops` see only questions routed to them. `judge`, `cfo` and no-token see all.
  - Filtering: `?status=open` returns both open and reminded (both unanswered). A question becomes `reminded` once the clock passes `remind_at` (asked_at + 3 h).
- **Answering:**
  - The session role must equal `routed_to`, else 403 `forbidden` plus an `access_denied` trace event.
  - Answering Q-1, Q-2 or Q-3 returns the scripted proposals R-CL-1, R-LEG-1 and R-CTL-1. Q-3 always produces a `rejection` ruling.
  - `confirm`, `widen` and `reject` also work on those canned rule ids before any answer, so screens can be built in any order.
- **Approving journals:**
  - An agent session gets 403 `sod_violation`.
  - Preparer == approver gets 403 `sod_violation`.
  - A role outside controller/cfo/claims_lead gets 403 `forbidden`.
- **Desk:**
  - An unknown ICAO (not in airportsdata) gets 422 `unknown_airport`.
  - A date after today gets 422 `future_date`.
  - EIDW 2025-01-24 returns the Éowyn run.
  - Anything else returns an empty run with a `message`.
- **Inject:** a regex fallback (`fallback_used: true`). Prompt-injection phrases give 0 facts and `dropped_unverifiable` 1. A rehearsed scenario's text puts its `expected` outcome into `message`. It never returns a 500.
- **Errors:** every 4xx is `{"error":{"code","message"}}`, including FastAPI's own validation errors (code `validation`).
- **SSE (`/api/stream`):**
  - Sends `event: trace`, `id: <seq>`, `data: <TraceEvent JSON>` every `STUB_SSE_INTERVAL` s (default 2).
  - Starts after `Last-Event-ID` (default 0).
  - When the log is exhausted it appends replayed copies of `trace.json` events with fresh, monotonic seqs (`STUB_SSE_LOOP=0` stops after one pass). Replays show in `/api/trace` but not in `StormRun.feed`.
  - Events created by POSTs are streamed and appended to `StormRun.feed`.
  - Heartbeat: an SSE comment ping every 15 s.
  - The route declares `response_model=TraceEvent` (ignored at runtime because it returns a Response), so every route has one. The OpenAPI 200 content is `text/event-stream` with a `$ref` to TraceEvent.
- **CORS:** `http://localhost:5173` and `http://127.0.0.1:5173`, all methods and headers.
- **`contracts/openapi.json` is checked by a test** (`test_openapi_json_is_up_to_date`). Any model change that alters the schema needs `make openapi`, per CONTRACTS.
