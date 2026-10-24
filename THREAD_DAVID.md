# Thread: David, Engine & API (v2)

**Mission:** the deterministic "judgment and decision engine" and the HTTP surface. You:
- decide facts (windows, cause, entitlement);
- apply versioned rules;
- route the 1% to the right person;
- keep an event-sourced, hash-chained trace with `blame`/replay;
- serve everything the web needs.

**Size:** about 30 agent-hours, run as **two lanes in parallel**. Each lane gets its own Claude Code session and git worktree:
- **Lane A** owns `engine/`.
- **Lane B** owns `contracts/`, `server/`, `scripts/`, `.githooks/`, `Makefile`, `pyproject.toml`, `uv.lock`.

Lanes never edit each other's directories. **Branches:** `david/a-<wp>`, `david/b-<wp>`. Land with `scripts/land.sh`.

**You consume** `WorldAPI`, `ReaderAPI`, `DrafterAPI` and `BooksAPI` (Filip) through `contracts/fakes.py` until his real implementations land (`*_IMPL=real`).
**You provide** `EngineAPI` (for Filip's eval) and the HTTP API (for Justin).

## Setup (each lane, once)
```bash
git worktree add ../sc-david-a -b david/a-engine origin/main   # lane B: ../sc-david-b -b david/b-contracts
cd ../sc-david-a && uv sync && git config core.hooksPath .githooks && export STORMCHECK_OWNER=david
uv run pytest -q
```

---

## Lane B: contracts, server and ops (critical path first)

### D0a · Stub server + minimum contracts. **Deadline Sat 01:45 (CP0a).** Land on `main` immediately.
- `contracts/models.py` and `interfaces.py` are already in the plan commit. Don't change them except additively.
- `contracts/stub_app.py`: every route from CONTRACTS §3, each with `response_model=`.
  - Serve **hand-written** fixtures for `/storms`, `/storms/{id}`, `/flights/{id}` and `/questions`. Write them in `contracts/fixtures/api/` now, from plan §1.2–1.4: NS31, two weather flights and NS117, using the real numbers.
  - Every other GET returns a minimal valid model. POSTs return plausible canned models.
  - SSE replays `trace.json` on a 2 s timer.
- `make stub` (port 8001), `make openapi` (writes `contracts/openapi.json` from the stub).
- `contracts/tests/test_fixtures.py`: every file in `fixtures/api` validates against its model.
- `contracts/tests/test_stub.py`: every route returns 200 or 201 with a valid body.

### D0b · Golden fixture + shared helpers. **Deadline Sat 04:00 (CP0b).**
- `scripts/build_golden.py` writes `contracts/fixtures/golden/world.json` **exactly** per plan §1.2–1.4 and CONTRACTS §5. It uses:
  - the real METAR CSVs already committed;
  - distances from OurAirports. If a band in the plan differs, fix the plan table and log it in CHANGELOG;
  - 5,292 coupons with elections;
  - CRM events: 32 bot `refund_initiated` between 06:02 and 09:40Z, one BSP+bot duplicate, one chargeback, and 14C's in-lieu voucher (unsigned);
  - 6 overnight claims, care costs, the OCC/MCC/spares logs, and the AMOS tech log line verbatim;
  - 8 messy documents, including the prompt-injection email;
  - the Herminia mini-day, the Isha opening balance, ≥42 `history_cases`, and `curves.json`.
- `expected/*.json` comes from the plan's numbers, **never** from the engine. Add `expected/SHA256SUMS` and a test that checks it.
- `contracts/fields.py`: the field registry. `normalize.py::world_to_facts`. `parse.py`: typed re-parse from spans, for times (`21:40Z`), ATA codes, tails, € amounts and dates.
- `contracts/calibration_schema.json` and `engine/default_calibration.json`. The latter lives in Lane A's directory, so Lane B writes it into `contracts/` and Lane A copies it.
- `contracts/fakes.py`: FakeReader, FakeDrafter, FakeBooks, FakeWorld, FakeEngine.
- `scripts/build_api_fixtures.py` regenerates **every** `fixtures/api/*.json` from golden plus fakes. These must look realistic, because Justin designs against them. Include `injections.json` with the 8 scenarios.
- **Tests:**
  - golden validates;
  - golden numbers: `sum(NS31 entitlements)=9,900,000`;
  - 5,292 coupons;
  - NS31 STD is ≥60 min after the window end computed by a reference function in the test;
  - every Fact field produced by `normalize` is registered in `fields.py`.

### D10a · Thin real server. **Deadline Sat 06:00.**
- `server/app.py` (FastAPI):
  - Boots the golden world, runs `EngineAPI.run_storm` (Lane A's real engine as far as it exists, `FakeEngine` otherwise), and posts to Books (`BOOKS_IMPL`).
  - Serves `/storms`, `/storms/{id}` and `/flights/{id}` for real. Every other route falls back to the stub handlers.
- SQLite event store in WAL mode. Append-only triggers. `data/baseline.db` is snapshotted after boot.
- `make dev` runs it on :8000. It serves `web/dist` at `/` if that exists.

### D10b · Full API (POST routes) on the real engine + Books
- Session tokens: `POST /session` returns an HMAC-signed principal. Fail closed.
- answer, confirm, reject, widen, revert, approve, month-end, lock.
- `/blame?target=`, `/audit/{je_id}`, `/commits`, `/trace`, `/rules`.
- The access log, `/controls` (the SOC 2 mapping list from plan §3), and `/injections`.
- **Tests:** each endpoint validates against its model. **OpenAPI superset test:** the real server's OpenAPI ⊇ the stub's `openapi.json`.

### D10c · Live paths: SSE, desk, inject, challenge, clock, reset
- **`/stream`:** `fastapi.sse` (or sse-starlette, no GZip), resumable via `Last-Event-ID`, 15 s heartbeat.
- **`/desk`:** `WorldAPI.generate_day` → `run_storm`. Map `WorldError` to a **422** with a plain message.
  - A day with no storm returns a `StormRun` with `message="max gust 18 kt · no storm window"`.
  - Use the airport's local date (`Airport.tz`).
- **`/inject`:** `ReaderAPI.extract` with an **8 s timeout**, falling back to `FakeReader` (labelled `fallback_used`).
  - Then facts → re-decide the affected flights or coupons → Books → trace events.
  - An unresolved subject becomes an Ops question. Never return a 500.
- **`/flights/{id}/challenge`:** `DrafterAPI.classify_challenge`. Challenge facts are tier 4. The engine decides between "decision stands", Legal, or Ops.
- **`/clock`:** forward-only `Clock`, which drives the reminders and claim timing.
- **`/reset`:** copy `data/baseline.db` over the live DB.
- **`STORMCHECK_MODE=live|cache|offline`.**
- **Tests:**
  - 20 fuzz injections never return a 500;
  - every one of the 8 rehearsed injections produces its `expected` outcome;
  - `/desk` for `EGLL 2024-01-21` returns within 5 s on pinned METAR.

### D11 · Integration, verification and demo hardening
- **`make verify`:** recompute every commit hash and replay every decision offline. Report "N commits verified · replay identical".
- `make demo` (one process on :8000) and `make demo-offline` (no network; pinned METAR; `LLM_MODE=offline`).
- `scripts/smoke_cp1.sh`, `smoke_cp2.sh`, `smoke_cp3.sh`, per plan §7.
- `scripts/land.sh`, `scripts/check_owners.py` and the `.githooks/pre-commit` owner and gitleaks check, if they weren't already in the plan commit.
- **Write `STATUS.md` hourly:** what's green, what's blocked.

---

## Lane A: engine (pure, deterministic; no `anthropic`, no `now()`, no `random`; AST test enforces it)

### D1 · `engine/timeline.py`: windows at both ends
- `storm_windows(obs)` per the binding definition: gust ≥35, or sknt ≥30, or vsby <0.5, or wx in {SN, FZ, TS, GR}. Merge gaps under 2 h.
- `position(flight, station_obs, t) -> in|out|unknown`. Return `unknown` when there's no obs within ±60 min.
- Margins in minutes. Compute at departure using STD and at arrival using STA.
- **Tests (real golden CSV):**
  - main window is 02:30–15:00Z ±30 min;
  - the minor 23:30Z window is detected separately;
  - NS31 is out by ≥60 min;
  - NS101–NS111 have STA in window;
  - NS113/115/117 are out at both ends;
  - hypothesis: shuffling the obs doesn't change the windows;
  - a gap → `unknown`.

### D2 · `engine/cause.py` + `engine/ata_table.py`
- `ata_table.py` classifies a tech-log defect as internal or external:
  - Internal: pump/EDP leak, actuator, sensor, avionics, etc., matched on ATA chapter plus keywords.
  - External, routed to `needs_legal`: bird, lightning, hail, FOD, de-icing, or no match.
- **Cause logic**, in priority order:
  1. An AOG with no MEL relief, logged before the window, with internal root cause, while the flight is out of window at both ends: `technical / not_extraordinary`. **A recode requires positive tier-1 evidence**, i.e. the tech log.
  2. An AOG inside the window: `concurrent / needs_legal`.
  3. In window at either end with no AOG: `weather / extraordinary`.
  4. A return sector whose outbound pair was cancelled for weather, and which is out of window at both ends: `knock_on / needs_legal`, unless an active legal rule applies.
  5. `unknown` window: `unknown / needs_legal` routed to Ops at <0.6.
- **Evidence** is ranked by trust tier. The losing source is `struck` (e.g. OCC code `71`). `recode_label` reads e.g. "71 → 41".
- `legal_basis` cites Art. 5(3), C-549/07, C-257/14 and C-74/19 as relevant.
- **Spares are never a feature for technical-cause flights.**
- **Tests:** `expected/decisions.json`, comparing `(cause, extraordinary, recoded, outcome, routed_to)` **exactly**. Confidence by band: NS31 ≥0.90, knock-ons <0.60. Never compare the `reason` text.

### D3 · `engine/eu261.py`
- **Scope (Art. 3):** EU departure, or arrival in the EU on an EU carrier. `fare_type=staff_id90` gives `staff_ticket`, with no compensation.
- **Notice exemptions (Art. 5(1)(c)):**
  - ≥14 days → exempt.
  - 7–14 days, rerouted to leave ≤2h earlier and arrive <4h later → exempt.
  - <7 days, rerouted to leave ≤1h earlier and arrive <2h later → exempt.
- **Bands (Art. 7(1)):**
  - ≤1,500 km → €250.
  - Intra-EU >1,500 km → €400.
  - Other flights 1,500–3,500 km → €400.
  - Over 3,500 km → €600.
  - Also compute `band_margin_km`.
- **50% reduction (Art. 7(2)):** applied only when the mined policy rule `R-MINED-REDUCE` is active and the rerouted arrival is within 2h/3h/4h for the respective band.
- **Vouchers:** an offset needs `signed_acceptance_sha256`. An unsigned in-lieu voucher gives **`needs_ruling`** (the engine does **not** pre-answer Q1). A UK261 claim on a DUB departure is paid once under EU261.
- **CRM refunds:** a `refund_initiated` event sets `refund_already_initiated` and `refund_due=0`. A BSP duplicate is flagged.
- **Care is always due.** An extraordinary flight gets compensation 0 with status `no_compensation`.
- **Tests:**
  - NS31 = 9,900,000;
  - 14C is `needs_ruling` with compensation 60,000 and offset 0;
  - BCN band margin is 14 km;
  - a staff ticket gives no compensation;
  - notice ≥14 days → exempt.

### D6 · `engine/confidence.py` + `engine/routing.py`
- **Confidence:** a logistic model per `Confidence.kind`, with coefficients from `data/calibration.json` and a fallback to the default file. **No model for the kind → `score=None` (uncalibrated).**
- **Caps:** reported in `caps`, never folded into the score.
- **Thresholds:** ≥0.90 is auto, **subject to the materiality gate** (<€50k and ≥0.90). 0.60–0.90 goes to batch review. Below 0.60, route to a person.
- **Routing:**

  | Case | Goes to |
  |---|---|
  | Cause/legal patterns, concurrent causes | Legal |
  | Voucher and claim disputes | Claims Lead |
  | Releases and changes in estimate | Controller |
  | Data gaps / `unknown` | Ops |

- **Pattern grouping:** one Question per (pattern, storm). It covers all `case_refs` (e.g. NS113/115/117).
- **Reminders:** `remind_at = asked_at + 3h`, driven by the Clock.
- **Tests:** NS31 ≥0.90; knock-on question <0.60 tagged `no-precedent` covering 3 flights; Q1 <0.60 tagged `sources-disagree`.

### D4 · `engine/rules.py` + `engine/controls.py`
- **DSL** over the allowlisted features only (CONTRACTS §4). `action` is a `RuleAction` enum.
- **Precedence:** `hard_control > regulation > legal > controller > claims_lead > mined`, then specificity (constrained scope keys), then `recorded_at`.
- **Conflicts:** an equal-tier conflict is escalated and gets `checks.no_conflict=false`.
- **Authority:**

  | Role | May author |
  |---|---|
  | claims_lead | voucher/claim rules |
  | legal | cause/extraordinary rules |
  | controller | release/estimate rules |
  | anyone | **never** a rule that touches a hard control |

  A `statutory_floor` control means only Legal may lower EU261 compensation.
- **Grounding:** every literal in `condition` **and** `scope` must map to a phrase in the ruling. Ungrounded scope keys are copied from the case as `case:<v>`.
- **Versioning:** immutable versions. `rules_known_at(K)`. `valid_from = None` for legal interpretations.
- **Hard controls** (code): SoD; payouts need claims_lead; locked periods; materiality; external parties can't satisfy an approval.
- **Tests:**
  - "requesters approve own payouts" → refused;
  - a claims_lead-authored release rule → refused;
  - an ungrounded threshold → flagged;
  - hypothesis: shuffling rule order doesn't change the result.

### D8 · `engine/trace.py`: event store, blame, replay, revert
- **Append-only event tables** with views for status fields.
- **Commit hash** = sha256 of `canonical(kind, parent, payload_hash, inputs, at, actor)`, where `inputs` include `engine@<git sha>` and `cal@<version>`.
- **`blame(target)`** walks: entitlement or JE line → decision → rule@v → ruling (author and quote) → facts → span → METAR obs.
- **`replay(known_at, rules_override=None)`:** re-run the pure `decide` over stored facts. **Never call the LLM.** Return a `ReplayDiff`, using `BooksAPI.preview` for the € deltas.
- **`revert(rule)`:** the rule event becomes `retired`, then replay, then `BooksAPI.post_recode`.
- **IAS 8.5 class:**
  - Decisive evidence `received_at ≤ lock` that went unused → `prior_period_error`, booked as an out-of-period adjustment in the current period.
  - New claims or a new ruling → `change_in_estimate`.
- **Tests:**
  - tampering breaks every descendant commit (hypothesis);
  - replay is hash-identical when run twice;
  - a revert never writes a locked period;
  - AST bans on `anthropic`, `datetime.now` and `random` in `engine/` and `books/`.

### D5 · `engine/lifecycle.py`: never ask twice
1. **`answer`** creates a `Ruling`.
2. **`DrafterAPI.propose_rule`** drafts the rule.
3. **Verify:** compiles · reproduces the case · grounded (condition and scope) · author has authority · no hard control · no conflict.
4. **`preview` + replay** gives the `RuleProposal`.
5. **`confirm`** activates it and re-decides open items. `times_cited` increments as an event.

Two more operations:
- **`reject(proposal or rule, explanation)`:** the rejection ruling becomes a rule proposal (the Q3 path).
- **`widen(rule)`:** exactly **one rung** (case scope → all storm cohorts / all EU departures).

**Tests:**
- **Q1:** ruling gives `R-CL-1` scoped `departs_eu`. On Herminia, 31 cases are auto-settled, cited 31×, and the BOS→DUB case **asks again**.
- **Q2:** one ruling settles NS113, NS115 and NS117. The € delta is −4,749,600.
- **Q3:** the rejection gives `R-CTL-1` (keep tail 360,000), then a "widen to all storm cohorts?" proposal.

### D9 · `engine/acl.py`: broker for people AND agents
- **Matrix by principal:**

  | Principal | Access |
  |---|---|
  | Ops | flights/logs, no PII |
  | Reader | sources incl. PII; emits pseudonymous facts |
  | Drafter | no PII; names are merged in code after drafting |
  | Claims Lead | PII for claims |
  | Legal | case facts without PII |
  | Controller | aggregates + JEs |
  | Judge | demo read + desk/inject |

- `broker.read(principal, resource)`. LLM contexts are built only from allowed facts. Escalation packets are redacted per recipient.
- A denial writes an `access_denied` commit plus a trace event (e.g. `agent.drafter approve_payout → DENIED · SoD`).
- **Tests:** redaction; SoD denial; an email saying "approved" never approves; the Drafter context for NS31 rights notices contains 0 PII fields.

### D7 · `engine/miner.py` (frequency mining only)
- From `world.history_cases`: conditional-majority mining with support ≥8 and purity ≥95%.
- Emits `RuleProposal`s in `shadow` with `support` (e.g. "41 of 42"): `R-MINED-REDUCE`.
- Also emits the `LearnedItem`s for the Storm Run "Learns" strip. The claim-rate item comes from `BooksAPI.curve`.
- **Tests:** it recovers `R-MINED-REDUCE` from golden history with support 41/42.

---

## Definition of done
- **Lane B:** CP0a, CP0b and D10a on time. Then CP2 live paths, CP3 offline plus `make verify`.
- **Lane A:** golden decisions, entitlements and lifecycle tests green by CP1/CP2.

## Agent rules for this thread
- Take the next task in your lane. Write its tests first, then make them pass, then run the full lane suite, then commit (`engine: D3 eu261 bands`) and run `scripts/land.sh`.
- **Never stop between tasks to ask.** Log judgment calls in `engine/DECISIONS.md` or `server/DECISIONS.md` and continue.
- Stuck for more than 20 minutes: write `BLOCKED: <why>` in your lane's `TASKS.md` and move on.
- Never weaken an acceptance test. Never edit `contracts/fixtures/golden/expected/`. Never touch other threads' directories.
