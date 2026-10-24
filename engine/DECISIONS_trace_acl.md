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

## D9 · `engine/acl.py`

**The matrix** (`access_matrix()`, `GET /access/matrix`)
- **Principals:** all ten `Role` values.
- **Resources:** `flights`, `ops_logs`, `tech_log`, `sources`, `pii`, `claims`, `case_facts`, `questions`, `journal`, `aggregates`, `rules`, `approve_payout`, `approve_je`, `lock_period`, `desk`, `inject`. These extend the stub fixture's set with `sources`, `questions`, `lock_period`, `desk` and `inject`.
- **Cells:** `read` / `write` / `approve` / `redacted` / `none`. `redacted` means "may read, with PII masked".
- **The thread table, cell by cell:**
  - **Ops:** flights, logs and tech log; sources masked; no PII and no claims.
  - **Reader:** sources incl. PII, and writes (pseudonymous) case facts.
  - **Drafter:** no PII; sources and claims masked.
  - **Claims Lead:** PII and claims (write); approves payouts.
  - **Legal:** case facts; no PII; sources and claims masked.
  - **Controller:** aggregates and journals (write); approves JEs and locks periods; no PII, no tech log, no case facts.
  - **Judge:** read everything masked, plus `desk`/`inject` write.
- **Rows the thread table doesn't cover:**
  - CFO reads flights, aggregates, journals and rules.
  - The engine writes case facts, questions, journals and aggregates, but never PII.
  - The CRM bot reads flights, PII and claims (it contacts passengers).
- **The CFO does not approve JEs.** The stub let it, but `books.Books` requires the Controller and raises `SoDViolation` otherwise. The code is the hard control, so the matrix follows Books.
- **Bare resource ids map by shape:** `SRC-…` → sources, `JE-…` → journal, `R-…` → rules, `Q-…` → questions, a coupon id → case facts, a flight id → flights. `class:id` uses the class. Anything else is an unknown resource and fails closed.

**Decisions and the denial log**
- **API:**
  - `check` returns the `AccessDecision` and appends it to `broker.log`.
  - `can` returns a bool.
  - `require` raises `AccessDenied` (`code` `sod_violation` for approvals, `forbidden` otherwise).
  - `read(principal, resource, obj)` = `require(read)` + `redact`.
  - `can` exists because a pydantic model is always truthy: `if broker.check(...)` would fail open.
- **Every denial becomes an `access_denied` commit** when the broker holds a `TraceStore`. Reasons read `"<Tag>: <why>"`, and the commit message is `"<principal> <action> → DENIED · <Tag>"`, e.g. `agent.drafter approve_payout → DENIED · SoD`. Tags are `SoD`, `External`, `No PII`, `Least privilege`, `Fail closed`.
- **Allowed checks are logged in memory only.** Committing every read would bury the chain; the Access tab's log is denials plus whatever the server chooses to show.
- **Fail closed** on: an unknown principal (any id that isn't a role or `<role>:<slug>`, `None`, `""`), an unknown action, an unknown resource, and a missing clock with no explicit `at`.

**Approvals (hard controls, in this order)**
1. **Agents never approve:** `SoD: agents never approve payouts`.
2. **Only a signed internal `Session` approves.** Anything else is `External`, including a bare string like `"claims_lead:maria-murphy"`, a `Source`, a `Claim`, a `CrmEvent`, a `Fact`, a dict, or free text. When the external text matches `approv(e|ed|al…)`, the reason says so ("email text says 'approved'; external parties never satisfy an internal approval").
   - Reads, by contrast, accept bare role strings, because agents are in-process code that identifies by role.
   - The server must pass verified Sessions for people.
3. **Preparer ≠ approver.** `preparer` is passed by the caller.
4. **The right role:** payouts need the Claims Lead; JEs and period locks need the Controller.

**Redaction** (`redact(principal, obj)`)
- **Who sees PII unchanged:** principals whose `pii` cell is `read` (Reader, Claims Lead, CRM bot), matching `claims_lead:<name>` sessions too.
- **Everyone else, including the judge and unknown principals, gets a copy with:**
  - `Source.text` masked when the source is tagged `pii` or is a claim/email/manifest/PSS/CRM/BSP/challenge document (`sha256` kept, so it stays verifiable);
  - `Fact.value`/`span` masked when tagged `pii`, and `span` masked when it quotes a registered PII source;
  - `Evidence.value`/`quote` masked when from a registered PII source;
  - `Claim.text` and `CrmEvent.text` masked: free text about a passenger can hold a name, which no regex finds;
  - `Coupon.pnr` masked (`pax_ref` is pseudonymous and kept);
  - dict keys like `name`/`email`/`phone`/`iban`/`pnr` masked;
  - e-mail addresses, `+`-prefixed phone numbers and IBANs masked inside every string.
- **IBAN matches are confirmed by the ISO 13616 mod-97 checksum.** Without it, the spaced form matched OCC flight lists ("NS21 NS41 NS51 NS31"). A test runs the mini world's flights, logs, airports and METAR through redaction and expects them unchanged.
- **Models are never mutated.** `model_copy(update=…)` is applied only to the fields that change.
- **`Session.name` and `Airport.name` are left alone:** they are staff and airport names, not passenger PII. Key-based masking applies to free-form dicts only, not to model fields.
- **The mask is the literal `[redacted:pii]`.** The UI's "view as Ops" mask can match on it.

**LLM contexts and escalation packets**
- **`context(principal, facts=, items=, purpose=)`** requires `read` on case facts.
  - For a principal without PII access, personal facts are **withheld entirely** rather than masked: tagged `pii`, or a value or span holding an e-mail, phone number or IBAN.
  - Items are redacted.
  - The result carries `withheld_facts`, and the check is logged as action `context` on the purpose (e.g. `rights_notice:NS31@2025-01-24`).
- **The NS31 test** builds the Drafter context from:
  - the real `eu261.entitlements` (172 coupons, 9,900,000);
  - 172 tagged name facts and 5 untagged e-mail facts;
  - the coupons, CRM events, a claim and the manifest.

  It then asserts `pii_fields(ctx) == []`, 177 withheld, and the € numbers untouched. The Reader context of the same inputs is the positive control.
- **`packet(recipient, obj)`** redacts an escalation packet (a question with its evidence) for its recipient.

**Session tokens**
- **Format:** `issue(role, name, secret, *, at)` → `<base64url(canonical Session JSON)>.<64-hex HMAC-SHA256>`. This is the stub's shape, with the full digest rather than 32 hex chars.
- **`at` is required** (it becomes `issued_at`), because the engine has no clock of its own. The secret is passed in; an empty secret raises on `issue`.
- **Principals:** `<role>:<name-slug>` for people, the bare role for agents and the judge, as in the stub.
- **`verify(token, secret)` raises `InvalidToken` on:**
  - a non-string or malformed token;
  - a signature that is not 64 hex chars;
  - an HMAC mismatch (checked with `hmac.compare_digest`);
  - the wrong secret or an empty secret;
  - an undecodable or invalid payload;
  - a principal that doesn't match its role and name.
- **Role elevation is caught twice:** the edited payload breaks the signature, and the principal check catches a re-signed inconsistent one.
- **`session_or_judge(token, secret, *, at)`** turns no token or any bad token into the read-only judge (CONTRACTS §0).
- **No expiry:** the demo runs on one clock. Add a `max_age` against the injected clock if sessions ever need to lapse.
