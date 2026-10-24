# server/ decisions (David lane B)

Judgment calls made while building the real server. Newest at the bottom of each section.

## D10a · thin real server

**Shape**
- **`create_app(settings)` is a factory;** `server.app:app` is `create_app()` from env. Tests build their own apps on temp DBs (`server/tests/conftest.py` points the module app at a temp `STORMCHECK_DB` before import), so nothing in tests writes under `data/`.
- **Real routes are registered first; every other contract route is the stub's own `APIRoute` object appended afterwards** (`add_stub_fallbacks`). Same paths, same `response_model`s, so the OpenAPI stays a superset of `contracts/openapi.json` (tested). The stub's `ApiError`/`envelope` are reused, so error bodies are identical. `POST /api/reset` resets both the real runtime and the stub's in-memory state.
- **`web/dist` is served at `/`** via a catch-all GET registered after every API route (SPA: unknown paths get `index.html`; `/api/*` never does). It is skipped when `web/dist/index.html` doesn't exist.
- **Run it:** `uv run uvicorn server.app:app --port 8000`. `make dev` still prints a placeholder; the Makefile is not this lane's to edit in this session, so it is requested in `contracts/requests/server.md`.

**Boot pipeline** (`server/runtime.py`)
- **Every process start boots fresh:** the live DB (`STORMCHECK_DB`, default `data/stormcheck.db`) and its `-wal`/`-shm` are deleted, the pipeline runs, and the whole DB is snapshotted to `baseline.db` next to it (default `data/baseline.db`; `STORMCHECK_BASELINE` overrides). A deterministic start beats resuming a half-played demo.
- **World:** `STORMCHECK_WORLD` (default `contracts/fixtures/golden/world.json`). If it is missing or doesn't validate, the server serves the stub fixtures through the same document store (`/api/health` → `impl.pipeline = "stub"`). If the real pipeline throws mid-boot, it also falls back to the stub and reports `impl.boot_error`.
- **Boot clock** = `world.meta.known_at|demo_start|as_of`, else 2025-01-25T06:00Z ("the morning after"), the stub's start.
- **Which storms run at boot:** `world.meta.storms` when present; else each METAR key of the hub (`meta.hub_icao`, default EIDW) on a day with cancellations. A storm runs at boot only if its morning-after (day + 1 d 06:00Z) is ≤ the boot clock. Later ones (Herminia, 26 Jan) are stored as `pending_storm` docs and run when the clock reaches them or on the desk (D10c).
- **Which flights belong to a run:** flights touching the station's IATA whose local date, STD or STA falls on the day, so the overnight inbounds dated the 23rd (NS20/30/40/50) are in the 24 Jan run.
- **Engine, in order:** an importable `run_storm` (a real `Engine` class or module function; discovery list in `server/impls.py`) → `contracts.fakes.FakeEngine` → **composed** from the engine modules that exist (`impl.engine = "mixed"`):
  - windows: real `engine.timeline.storm_windows` on the station-day obs;
  - decisions: the stub fixture decision for the same flight id (golden-exact values from plan §1.2) until `engine.cause` lands; for a flight with no fixture, a **provisional window-only decision** (weather if STD/STA is inside a storm window, else `unknown → Ops`, uncalibrated or <0.6). It never recodes and never owes compensation on its own;
  - entitlements: real `engine.eu261.entitlements` (so NS31 = 9,900,000 comes from the engine, with R-MINED-REDUCE active);
  - questions: the stub's curated questions (Q-1/Q-2/Q-3) when their cases are in the run (Q-3 via the world's opening-balance cohort); otherwise one question per (pattern, storm) grouped from escalated decisions and `needs_ruling` coupons.
- **Rules at boot:** the stub's rule cards (regulation, hard controls, the static Reg 2026/2202 card, R-MINED-REDUCE) plus `engine.miner.mine_rules` output when it lands. Mined rules are activated at onboarding (they drive day 1's 50% reroute cut).
- **Books:** `books.Books(db_path=STORMCHECK_DB, clock=server clock)`: the same SQLite file as the server's own tables, through Books' own connection. One file means `baseline.db` and reset cover the books state too. `liability_drafted_cents` is Σ Cr 2140 of the run's `compensation_estimate` JEs, read back from Books. Opening balances (Isha) are posted at boot.
- **Server-side numbers:** none. Counters are counts; every cent is the engine's (entitlements) or Books' (journals).

**Event store** (`server/store.py`)
- **One SQLite file in WAL mode; every `sc_*` table has BEFORE UPDATE/DELETE triggers that abort** (tested). Tables: trace, commits, versioned docs, clock, access log.
- **Docs are versioned rows;** the current value of (kind, key) is its latest row. Storm runs, flight files, decisions, entitlements, questions and rules are docs, so "status" fields are views over appended rows.
- **Commits** hash per THREAD_DAVID D8: sha256 of canonical(kind, parent, payload_hash, inputs, at, actor), with `inputs` = referenced hashes + `engine@<git short sha>` + `cal@cal-v1`. Payload JSON is stored beside each commit, and `verify_chain()` recomputes every hash and parent link. When `engine.trace` lands, the server should delegate to it.
- **Commit order at boot:** sources (`fact`) → per flight `decision` → `entitlement` → Books JEs (`journal_event`, inputs = the decision commit) → `question`. `FlightDecision.commit` is set before posting to Books, so `JournalEntry.source_decision_id` points at it.
- **Reset** copies `baseline.db` into the live DB with SQLite's backup API, which is safe while Books' connection stays open (no file swap under an open handle). Document caches are dropped.
- **`/api/storms/{id}.feed`** is the whole trace (boot plus live). `StormRun.questions` carries status as a view (answered when a ruling doc exists; reminded once the clock passes `remind_at`).

**Flight files**
- `entitlements_summary` = `engine.eu261.summarize` + distance/band/margin + `band_note` ("1,486 km · 14 km under the €400 band").
- `sample_entitlements` = one coupon per distinct (status, reduction, refund, offset) shape, rulings first (so 14C shows), at most 6.
- `journal_preview` = Books JEs with a line dimensioned to the flight.
- `timeline` = tech log for the tail (STD −48 h … STA +24 h), ops log entries naming the flight or tail, the main window's edges, the METAR obs nearest STD and STA (±60 min), and CRM events **as counts per kind** (no PII in the timeline).
- `handoff` appears when any coupon had a refund already initiated; `rights_notices_drafted` counts only on owed flights.
- `explanation`: `Drafter.explain` with an 8 s timeout when a drafter exists and the mode isn't offline; otherwise a template draft of the engine's reason (`template_fallback: true`).
