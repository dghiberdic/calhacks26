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

## D10b · full API on the real pipeline

**Sessions** (`server/auth.py`)
- `POST /api/session` returns `<urlsafe-b64 Session>.<hex hmac-sha256>` signed with `STORMCHECK_SECRET` (a dev default that is not a secret). It uses `engine.acl.sign_session` / `verify_session` instead once those exist. Missing, malformed, forged or unknown-role tokens are the `judge` (fail closed). Principals follow the stub: `<role>:<name-slug>` for people, the bare role for agents and the judge. Issuing a token writes an allowed row to the access log.

**Questions**
- Role-scoped like the stub (claims_lead / legal / controller / ops see only theirs; judge and cfo see all). `?status=open` includes reminded.
- **Redaction per recipient:** only the Claims Lead sees passenger PII. For everyone else, an evidence quote from a source tagged `pii` (or a claim/CRM/call-note/email/PNR/manifest source) becomes `[redacted · PII]`.
- Status is a view: `answered` once a ruling doc exists, `reminded` once the clock passes `remind_at`.

**Rulings → rules → replay** (`server/lifecycle.py`; `engine.lifecycle` replaces it when it lands)
- **Answer:** the session role must equal `routed_to`, else 403 plus an `access_denied` commit, trace event and access-log row. A second answer to the same question returns the first ruling (idempotent). Rulings are append-only docs plus a `ruling` commit.
- **Proposal source:** the Drafter's `propose_rule` for unknown patterns (when a drafter exists), else the scripted R-CL-1 / R-LEG-1 / R-CTL-1 rule bodies (the stub's, with the case refs from the question), else none. With no proposal, the ruling is applied directly to its own cases as a human override (decision text "extraordinary/weather" vs "not extraordinary/technical/owed").
- **`would_flip` is a real replay, never canned:**
  - flight-level rules (`set_extraordinary` / `set_not_extraordinary`) flip a `needs_legal` decision on the rule's own cases, or wherever `engine.dsl.applies` matches the flight features the server can derive (windows, return sector, previous rotation, spares "STD+4h20" → 4.33 h, "earliest reroute" in the logs);
  - coupon-level rules (R-CL-1 `deny_offset`, reductions) go through `engine.eu261.entitlements` with the candidate rule set (the engine's own DSL decides);
  - Books prices the change (`Books.preview`).
  On golden: R-LEG-1 gives −4,749,600 across NS113/115/117; R-CL-1 flips 14C `needs_ruling → owed`, Δ 0.
- **Checks** (until `engine.rules` lands): compiles = `engine.dsl.validate` on condition and scope; reproduces_case = a case ref changes; no_hard_control; grounded = has grounding or only `case:` scope; author_has_authority = the THREAD D4 table plus `authority_required == author`; no_conflict = no active rule of the same kind and tier with the opposite action over the same scope keys.
- **Confirm** needs the rule's `authority_required` role (403 otherwise). It writes the rule as active, re-decides, writes decisions and entitlements (commits), calls `Books.post_recode` (recode JEs → `adjustment_je_ids`), and refreshes flight files and storm runs (liability = `Books.gl_balance("2140", cohort=run)`). `keep_tail` / `deny_release` rules call `Books.keep_tail` (no cohort scope = all storm cohorts). The scripted rules confirm even before their question is answered, so screens can be built in any order (stub behaviour).
- **Revert** (authority role or Controller) retires the rule, replays without it and posts the reverse recode. **Reject** records a rejection ruling. It retires an active rule (with replay) or marks a proposal rejected. A release-kind rule, or R-CTL-1, yields the R-CTL-1 proposal (the Q3 path). **Hard controls, regulation versions and static cards can't be rejected or reverted (403).**
- **Widen** drops exactly one `case:` scope key (and its condition clause) into a new `proposed` version that `supersedes` the old, with its own replay. 422 when nothing case-scoped is left.
- **`times_cited` is a view:** flight-level rules count once per decision and coupon-level rules once per coupon (D3 note). The origin case counts, so R-CL-1 reads 32 after Herminia (14C + 31). The run event says "31 cases settled under R-CL-1@1, ruling cited · 1 asks again".
- **Herminia (EIDW@2025-01-26)** runs when the clock passes its `meta.storms[].known_at` (27 Jan 06:00Z). Its decisions come from `expected/decisions.json` (FakeEngine-equivalent) until the engine's cause logic lands. With R-CL-1 active, 31 EU-departure vouchers settle and NS30@2025-01-25:23F (BOS→DUB) asks again, matching `expected/questions.json`.

**Books routes**
- Reads go straight to `books.Books`. Errors map to the envelope: NotFound → 404, SoD → 403 `sod_violation`, PeriodLocked/Forbidden → 403 `forbidden`, other BooksError/ValueError → 422.
- **Approve:** judge → 403 `forbidden`, agents → 403 `sod_violation` (before Books), then Books' own SoD (preparer ≠ approver; JEs need the Controller, payouts the Claims Lead). Every denial is logged, committed and streamed. Approval adds a `journal_event` commit and an APPLIED event ("parked, not posted").
- **Month end moves the clock forward to the period's last second** if it is behind (forward-only), which processes the claims received by then, then runs `Books.month_end`. On golden after R-LEG-1 + R-CL-1: Jan close 3,105,000 (6 claims at face value); Feb 3,105,000 − 930,000 + 399,000 = 2,574,000, A/E 1.448, rollforward ties to GL.
- **Lock** needs the Controller (Books enforces; denial logged).
- **Claims are assessed when the clock moves**, not at boot ("6 claims arrived overnight and still unassessed" on day 1). Claims on held / needs-ruling coupons wait and are retried on the next clock move.
- **Stub pipeline:** with no world, the books routes fall back to the stub's fixture handlers.
- **Boot seeds one real denial:** the Drafter tries to approve NS31's journal and Books refuses (`agent.drafter approve_payout → DENIED · SoD`, plan §3 Access tab).

**Trace / blame / audit**
- `/trace?since=` and `/commits?limit=` (newest first) read the event store. `/invariants` appends `INV-T1` (the commit chain verifies).
- **Blame** walks: JE line → entitlement → rules@v (→ ruling quote) → decision → evidence (tier order, struck sources, METAR last). It also accepts coupon, flight, rule and question targets. An unknown target returns an empty chain, never an error. It uses `engine.trace.blame` once that lands.
- **Audit** = `Books.audit` (JE, events, register rows, claims) with decision commits resolved to `Commit`s, the evidence source ids and the JE's own commits.
- `/access/matrix` comes from `engine.acl.matrix()` when present, else the stub's matrix. `/controls` and `/injections` are the static fixture lists. `/eval` reads `eval/proof.json` when it validates, else the stub's placeholder.

## Integration (engine.Engine, engine.trace, engine.acl, engine.miner, llm Reader/Drafter): supersedes parts of D10a/D10b

**Superseded:** D10a's own commit chain (`sc_commits`) is gone, and so are D10b's server-side blame walker and its flip-on-cases replay. `engine.trace.TraceStore` is the one commit store. The server's `sc_*` tables keep only the feed (SSE), versioned docs, the clock and the access log.

**Engine**
- `engine.Engine(world)` runs storms (`run_storm`) and re-decides (`evaluate` / `to_decision`). The composed fallback (`server/compose.py`) is used only on a checkout without an Engine.
- **Every non-static rule doc goes to the engine.** This is the same set `scripts/verify.py` replays with. Static cards (hard controls, Reg 2026/2202) are display only. Only legal-ruling rules can change `extraordinary` (engine), so the R-REG-ART5-3 card is cited, never decisive.
- **Held:** any decision whose outcome is not `auto` (escalated or human/batch review) is held, as in `engine.eu261`.

**Trace**
- All of these are TraceStore commits: sources, METAR obs, the evidence each decision cites (recorded as Facts with span = quote, because the engine's evidence ids are not normalize ids; the real normalize fact is used when the ids match), decisions, per-flight entitlements, Books JEs (`drafted` / `approved`), questions (`asked` / `reminded` / `answered`), rulings, rule events, period locks, access denials, clock moves, LLM calls and drafts.
- The 73k normalize facts are not re-committed at boot: they restate the engine's base world.
- `Store.head()` / `verify_chain()` read the trace's chain in the shared file (for `make verify`). The `sc_*` tables have UPDATE, DELETE and reused-seq (`INSERT OR REPLACE`) ABORT triggers, and `verify_chain` reports a missing one.
- Reset closes the TraceStore, restores `baseline.db` (backup API) and reopens it.

**Replay and lifecycle**
- `would_flip`, confirm and inject all use `TraceStore.replay_run(now, decide_fn, rules_override, preview_fn=Books.preview)`. `decide_fn` is the real Engine over the base world, with only the *injected* facts overlaid.
- Coupon-level rules keep each flight's decision and recompute entitlements only.
- Flight-level rules re-decide only the candidate flights: where the rule's DSL matches the engine's features (cached per clock tick and injected-fact count; features don't depend on the rule set), that cite it, or that are its cases.
- Revert is `TraceStore.revert(..., post_recode_fn=Books.post_recode)` over the flights that cite the rule.
- **Rule drafts:** `llm.drafter.Drafter.propose_rule` (its call becomes an `llm_call` commit) → `engine.rules.checks` (allowlist, grounding, authority, hard controls, reproduces the case) → replay checks. A failure, an `LLMUnavailable` or a timeout falls back to the scripted R-CL-1 / R-LEG-1 / R-CTL-1 bodies for the known patterns; for any other pattern the ruling is applied to its own cases as a human override. Never a 500.
- **Miner (D7):** `engine.miner.mine(world)` at boot. Each clean `shadow` rule is switched on by an explicit onboarding approval from the seeded Claims Lead seat (`claims_lead:onboarding`, a `rule_event` citing "support 41 of 42 · exception: HR-RR-024"), behind the same authority check as any activation (`Runtime.activate_rule`: the wrong role is DENIED and logged). A rule a written policy contradicts stays `proposed`, and the miner's Controller question is asked. The Learns strip is `engine.miner.learned_items(world, curve_lookup=Books.curve)`. With no history to mine (e.g. the mini world), the stub's R-MINED-REDUCE card stands in.

**ACL and sessions**
- Sessions are `engine.acl.issue` / `session_or_judge`.
- Approvals and locks go through `acl.Broker.check` (agents never approve; signed internal sessions only; preparer ≠ approver; payouts need the Claims Lead, JEs and locks the Controller) and then Books' own checks.
- `persona:<role>` principals are refused every approval at the server layer too ("External: a simulated persona…").
- Question packets are redacted per recipient with `Broker.packet`. Blame quotes are redacted with `Broker.redact` for non-PII viewers.
- **Challenge (Justin Q-a):** open to every session (judge, agents, external and persona principals). It is a tier-4 Source plus the Drafter's classification, it routes and never flips, and the served matrix gets an explicit `challenge: write` row for every principal.

**LLM (non-negotiable 2)**
- `/inject` calls the real `llm.reader.Reader().read(source, ReaderContext(flight, tail, flight numbers))` behind an 8 s hard deadline. Its `LlmCallRecord` becomes one `llm_call` commit, and every fact commit cites it.
- `fallback_used` is the Reader's own flag: the regex fallback ran because the LLM was unavailable, timed out or refused. If the Reader itself raises, `FakeReader` (regex) runs, `fallback_used` is true and the exception class is committed.
- The Drafter's `record_for(draft.id)` becomes an `llm_call` commit, and the Draft is committed citing it (`Draft.llm_commit` set).
- **"Why?" explanations are drafted on the flight file's first view, not at boot,** so boot never waits on an LLM. The result is stored, and a template stays on failure.
- Replay never calls an LLM.
- `STORMCHECK_MODE` sets `LLM_MODE` unless that is given explicitly.
- **Personas:** with `STORMCHECK_PERSONAS=1`, `llm.personas.PersonaBench` answers open questions as `persona:<role>` after boot and confirms the rule its ruling drafts. The principal passes through unchanged, and personas never approve or pay.

## D10c · live paths
- **Clock:** `POST /clock` is forward-only (422 otherwise). A move runs what became due: pending storm days (Herminia at `meta.storms[].known_at`), reminders (one per question once it passes `remind_at`) and claims.
- **Claims run in a daily 18:00Z batch, not on arrival.** That keeps day 1 (25 Jan 06:00–18:00Z) at "6 claims arrived overnight, still unassessed", and month-end (which moves the clock to the period's last second) picks them up. Claims on held / needs-ruling coupons wait and are retried on the next batch.
- **Reset (Justin Q-b):** after restoring `baseline.db`, the clock moves to boot + 3 h (09:00Z). Q1, Q2 and Q3 then read "reminded" ("Waiting on Claims Lead 3h · reminder sent") with no scrub. Neither `expected/` nor smoke-1/2 pin the post-reset clock, and day-1 money is unchanged because the claims batch hasn't run. A fresh boot stays at 06:00Z.
- **SSE `/stream`:** events after `Last-Event-ID`, polled from `sc_trace` every 0.5 s, with an sse-starlette ping every 15 s (`STORMCHECK_HEARTBEAT_S`). The generator stops when the client disconnects.
- **Desk:** `world.generate.generate_day` (or the server's one-day adapter over `world.generator.generate_world`, else FakeWorld). The engine's `run_storm` runs on the named airport.
  - Desk days are priced in a scratch in-memory Books, so the demo ledger is never written. Their decisions and entitlements live in `desk_*` docs (outside the demo's lifecycle and replays), their JEs stay off the main chain (scratch ids), and their questions live in the run only.
  - `real_context.metar_source` is `pinned` / `IEM` / `AWC`.
  - Errors are 422 with a plain message: `unknown_airport`, `future_date`, `no_metar`, a WorldError's code; anything unexpected is `upstream`.
- **Inject:** the source gets a tier by kind (tech log 1, manufacturer 2, OCC/CRM 3, claim/email 4). Then the Reader runs. Prompt-injection text yields no facts, and any "approved" in external text goes through `Broker.check(source, approve_payout)` → DENIED (External).
  - **Re-decision:** the affected flights (fact subjects `flight:`, `aircraft:` tail, `coupon:`, or the given flight id) are re-decided by the engine with the facts overlaid. Each gets a **new decision commit**, even when unchanged, linked to the facts, and changes are recoded in Books. Escalations ask the engine's question.
  - **Email / manufacturer text about a decided flight** goes through the challenge path. **Claims / CRM lines** are checked against the coupon: duplicate, limitation (Ireland 6 years), weather (no compensation), UK261 on an EU departure (EU261 applies, paid once), or a chargeback after a refund. A clean owed claim goes to `Books.post_claim`.
  - **Never a 500:** every stage is guarded, failures commit their exception class, and the input becomes a low-confidence Ops question. Text is cleaned: valid UTF-8, no NULs, capped at 20,000 characters.

## Integrity review follow-ups (INV-7, verify, anchor, failed writes)
- **Books sees every re-decision (INV-7).** Every recode (`Lifecycle.post_recode`: confirm, inject, override) passes the re-decided, committed decisions as `decisions=`, so Books' decision view and the register's cause / decision-commit provenance follow them. A flight whose decision changed but none of its coupons did still reaches Books: its coupons go in `before` only (a provenance update, no JE). `TraceStore.revert` posts its recode before the new decisions have commits, so after a revert the server makes one provenance-only `post_recode(ents, [], decisions=…)`.
- **`Store.verify_chain`** returns the broken commits' hashes, then the trace's own `issues` (index rows no commit wrote, rows out of chain order, a published anchor the chain no longer holds: `expected_head` / `expected_count`), then the server tables' missing protections.
- **Anchor:** `GET /api/health` → `anchor {head, count, text: "head <sha12> · N commits"}`. `/api/health`, `/api/commits` and `/api/trace` also send `X-Trace-Head` (full sha) and `X-Trace-Commits`. These are ASCII headers, so the list responses keep their contract shape.
- **A failed trace write is never a success.** `Runtime.record` logs at error level, counts the failure (`Health.ok = false`, `trace_write_failures`) and raises `TraceWriteError`. The app maps it to **503** `{"error":{"code":"upstream"}}`. The live paths' "never a 500" guards re-raise it instead of escalating, because the escalation could not be recorded either; `Live.failure` re-raises it too. It is not user input, so 503, not 422. Reset clears the count (the baseline is restored). At boot, a failure takes the existing stub fallback with `impl.boot_error`.
