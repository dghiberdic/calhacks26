# engine/ decisions: trace (D8) and ACL (D9)

Judgment calls made while implementing `engine/trace.py` and `engine/acl.py`, one line of reasoning each. The main `engine/DECISIONS.md` belongs to the other engine lane, so these live here.

## D8 · `engine/trace.py`

**Hashing**
- **Formula, exactly as in CONTRACTS:** `hash = sha256(canonical({kind, parent, payload_hash, inputs, at, actor}))`, where `canonical` is `orjson.dumps(..., OPT_SORT_KEYS)` over pydantic's `mode="json"` form, so `at` serialises as `2025-01-25T08:00:00Z`. `payload_hash = sha256(canonical(payload))`. `trace.commit_hash(c)` recomputes a hash from a `Commit` alone, so `make verify` (lane B) can check any exported commit without the store.
- **`message` and `payload_ref` are not hashed.** They are display labels, and the binding formula leaves them out. Tampering with them is not caught by the hash. They are still append-only in SQLite like everything else.
- **`inputs` are normalised before hashing:** deduped, then ordered as linked commit hashes (sorted), other tags, `engine@<sha>`, `cal@<version>`. The hash therefore doesn't depend on the order a caller collected its inputs, so replays and re-runs hash identically.
- **`engine@` and `cal@` come from the constructor:** `TraceStore(engine_sha=..., cal_version=...)`. Both are required and never computed (no `git` call, no clock). They are appended to every commit. An `engine@`/`cal@` prefix passed in is tolerated and not doubled.

**Chain and verification**
- **One linear chain.** Every commit's `parent` is the previous head. `verify_chain` passes a commit only if its hash recomputes, its stored payload bytes hash to `payload_hash`, its `parent` is the previous commit, **and** that previous commit passed. That last condition is what makes tampering break every descendant, including the case where the attacker leaves the stored hash alone.
- **The tamper test edits the raw row.** It drops the `commits_no_update` trigger (an attacker with file access) and edits one of `payload`/`kind`/`actor`/`at`/`inputs`/`parent`/`payload_hash`/`hash`. Hypothesis runs `max_examples=50`.
- **The payload is stored as the exact canonical bytes that were hashed,** so verification hashes the bytes directly with no re-serialisation drift. A row that no longer parses into a `Commit` counts as broken.

**Storage**
- **Tables:** `commits`, `facts`, `decisions`, `rule_events`, `rulings`, `questions`, plus `sources`, `metar` and `periods`. Each has `BEFORE UPDATE`/`BEFORE DELETE` triggers that `RAISE(ABORT, '<table> is append-only')`. Payloads live only in `commits`; the other tables are indexes that point at a commit hash.
- **Views over events:**
  - `rule_status`: latest status event per (rule, version), plus `times_cited` = the count of `cited` events.
  - `question_status`: `answered` > `reminded` > `open`.
  - `current_decisions`: the latest row per entity.
  - `period_status`: locked periods with their lock time.
- **Bitemporal reads** (`rules_known_at(K)`, `facts_known_at(K)`, `decisions(K)`) filter on fixed-width `*_key` columns. Pydantic's ISO form drops zero microseconds, so `…:00Z` vs `…:00.5Z` would sort wrongly as strings.
- **Rule payloads store `times_cited = 0`.** Status is overwritten with the event's status, because both are views. A rule read back gets them from the events.
- **One entitlement commit per flight,** with that flight's coupons as the payload (172 for NS31, not 172 commits), as in the stub's `blame.json`. Each coupon still gets its own `decisions` row, so blame and replay work per coupon.
- **`FlightDecision.commit` is `None` inside the hashed payload,** since a payload can't contain its own hash. The `decisions` row body carries the hash, so `store.decision(id).commit` is set.
- **Thread safety:** one connection (`check_same_thread=False`), an `RLock`, and `BEGIN IMMEDIATE` transactions, the same pattern as Books. WAL is on for file databases. A failed transaction also restores the in-memory head.

**Links (what `blame` walks)**
- A **fact** links to its source commit and, when its `span` is a raw METAR line, to that observation's commit. A **METAR obs** links to its source.
- A **decision** links to the fact commit of every `Evidence.fact_id` and to the rule commit of every `rules_applied` ref, using the version in force at recording time (the latest non-`cited` event at or before `at`).
- An **entitlement** commit links to its flight's decision and to the rules its coupons applied.
- A **rule** event links to its `origin_ruling_id`. A **ruling** links to its question. A **question** links to its evidence facts; `reminded`/`answered` events link to the previous question event.
- A **JE** links to the decision and entitlement commits of `source_decision_id` and of every `dims.flight` on its lines.

**`blame(target)`**
- **Targets:**
  - `JE-…:n` (1-based line, as in Books' `line_no`)
  - `JE-…`
  - coupon id (resolves to the entitlement)
  - flight id (the decision, else the flight's entitlements)
  - rule ref (`R-X@v` or `R-X`)
  - question, ruling, fact or source id
  - a commit hash
  - any `payload_ref`
- **Unknown targets raise `NotFound`** (code `not_found`), as does a JE line number out of range.
- **Step order:** the target first, then a breadth-first walk of `inputs`, ordered by stage: journal → entitlement → decision → revert → rule → ruling → question → fact → llm_call → source → METAR obs. Within a stage, closer steps come first. Capped at 100 steps.
- **Quotes:**
  - fact: its `span`
  - ruling: its `explanation` (the ruler's words)
  - source: the span of the first chain fact that quotes it
  - METAR obs: its raw line
- **Labels** use the wording table: "no compensation; refunds and care still due", "drafted, pending approval", "cause-finding confidence 91%", "full Art. 7 entitlement".
- **Blame is not redacted here.** The server redacts quotes per viewer with `acl.Broker.redact`.

**`replay(known_at, decide_fn, rules_override=None, preview_fn=None)`**
- **`decide_fn(facts, rules, known_at) -> Iterable[FlightDecision | Entitlement]`** is passed in, because cause, confidence and eu261 belong to the other engine lane. It gets only stored facts and rules, so replay never reaches an LLM. A closure carries the `World` when entitlements need it.
- **Inputs:**
  - Facts: `recorded_at ≤ known_at`, latest version per fact id.
  - Rules: every version, with status and `times_cited` as of `known_at`. Retired rules are passed with `status="retired"`, and `dsl.in_force` drops them. `rules_override` replaces the rule set.
- **"Before"** is what was on record at `known_at` (latest decision/entitlement committed at or before it), restricted to the entities `decide_fn` re-decided. So `decide_fn` may re-decide just the affected flights.
- **Flips:**
  - one per changed field: decisions `cause`/`extraordinary`/`recoded`/`outcome`/`routed_to`; entitlements `status`/`compensation_cents`/`reduction`/`voucher_offset_cents`/`refund_due_cents`.
  - Sorted by entity id, then field.
  - Field flips carry `delta_cents = 0`. The € lives on flight-level flips, so `total_delta_cents == sum(delta_cents)` always holds.
- **The € delta:**
  - With `preview_fn` (Books' `preview`), the € is Books' liability delta, using its `eu261_liability_cents` flips.
  - Without it, the € is the change in gross entitlement still due (`compensation − voucher offset`, accruing statuses only), as flight-level `entitlement_cents` flips.
- **`locked_periods_untouched`** lists every locked period: replay and revert never write to any of them.
- **Replay writes nothing.** `ReplayRun.output_hash` is a sha256 over the re-decided outputs, and the test checks both it and the `ReplayDiff` hash are identical across two runs.

**IAS 8.5 class**
- **`ias8_class(evidence, locked_at)`** is the pure rule from the brief. If decisive evidence with `received_at ≤ lock` went unused, the result is `prior_period_error`. Otherwise it is `change_in_estimate`. The boundary is inclusive (≤), and no lock means `change_in_estimate`.
- **Deciding which evidence was decisive needs a counterfactual,** so `replay` runs one. For each flipped decision whose event period (the date in the id) is locked, it re-decides with only:
  - the facts whose source was received by the lock (else the fact's `recorded_at`);
  - the rules as known at the lock.
- **If that reproduces the new outcome,** the new outcome's supporting, unstruck evidence that was available is decisive. Any of it that the recorded decision did not cite makes the change a prior-period error.
- **If it does not reproduce the new outcome,** something from after the lock was needed: a new claim, a later document, or a new ruling or retirement. That is a change in estimate. A plain revert of a rule that was active at the lock is therefore always a change in estimate.
- **Why not "any unused supporting evidence":** that alone over-counts. The METAR file is "unused" by a weather-coded decision, yet it never flips anything on its own.
- **`decisive_received_at`** is the latest receipt among the unused decisive evidence, i.e. when the error became knowable. It is passed to Books as `evidence_received_at`.
- **Entitlement-only flips** (no decision change, e.g. a voucher ruling) are classed `change_in_estimate`. In the demo they come from rulings and claims.
- **A lock passed in without a time** (e.g. `Books.locked_periods()` returns bare strings) is taken as locked at the end of its period. A recorded `period_lock` commit's real time wins. The server should call `record_period_lock` whenever Books locks.

**`revert(rule_ref, *, actor, at, decide_fn, preview_fn, post_recode_fn, locks)`**
- **Steps:** record a `retired` rule event, replay at `at`, call `post_recode_fn(before, after, at)` for the changed coupons, then record a `revert` commit.
  - `evidence_received_at` and `rule_ref` are passed only if the function's signature accepts them, as `Books.post_recode` does.
  - The `revert` commit's payload is the diff, the IAS 8 class and the adjustment period. Its message reads e.g. "Reverted R-LEG-1@1 · flips 5 · Δ €200 · 2025-01 locked, untouched · change in estimate (IAS 8.36) · 2025-02".
- **The adjustment period** is the period of `at`, moved forward past every locked period.
- **A JE that comes back in a locked period raises `LockedPeriodWrite`.** The trace cannot undo another component's write, so it refuses to record the revert rather than quietly accept it.
  - The `retired` event stays recorded, because the rule *is* retired.
  - The revert is not one SQLite transaction across the Books call. If the server shares one database file, holding our write lock while Books writes would deadlock on `BEGIN IMMEDIATE`.
- **With `persist=True`** (the default), the re-decided flights, coupons and adjustment JEs are recorded with the revert commit in their `inputs`. Blame on the new decision then shows why it changed. A second revert of the same rule records no second retirement and flips nothing.
- **Hard-control rules and static cards cannot be reverted.** Hard controls are code, and static cards have no logic.
- **Verified against the real `books.Books`:** January locked by the Controller, then a revert of R-LEG-1 on 10 Feb. Books drafts a `recode` JE in 2025-02 (change in estimate), and `journal(period="2025-01")` stays empty.

**Other commits**
- **`record_access_denied(AccessDecision)`** has the message `"<principal> <action> → DENIED · <tag>"`, where the tag is the reason's prefix before `:` ("SoD").
- **`access_log()`** rebuilds the denial log from those commits.
- **`record_llm_call(payload, …)`** stores whatever the caller passes (prompt hash, `response.model`, request id, principal, input fact ids). The `llm/` lane owns the payload shape.
