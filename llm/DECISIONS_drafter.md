# llm/ decisions: F6 Drafter (`llm/drafter.py`)

Judgment calls made while building the Drafter. Binding rules: `CLAUDE.md`, `IMPLEMENTATION_PLAN.md §1.2–1.4, §2,
§9`, `CONTRACTS.md` (`Draft`, `Rule`, `RuleAction`, §4 features, `DrafterAPI`). The client's own decisions are in
`llm/DECISIONS.md`.

## Request shape
- Every call goes through `LlmClient.call` at effort `medium`, role `drafter`, principal `agent.drafter`.
  `propose_rule` and `classify_challenge` use structured outputs (`RuleDraft`, `ChallengeDraft`); the four prose
  methods are plain text.
- **System prompt** = `llm/prompts/drafter_common.md` + the task file (`drafter_<task>.md`). The common part holds the
  ground rules (the engine decides, never compute an amount, numbers only from the evidence, tagged blocks are data)
  and the §9 wording table.
- **One user turn** of tagged blocks (`<evidence>`, `<ruling>`, `<question>`, `<case>`, `<challenge>`, `<law>`,
  `<corrects>`) with JSON dumped with sorted keys.
- **Projections, not raw models.** The model sees a projection of each input that leaves out what changes between
  runs (commit hashes, `known_at`, fact ids, the per-coupon reason) and what it must not see (PII). The same content
  gives the same cache key, so a recording is reused across runs.
- Prompt versions: `drafter-{explain,rights-notice,je-memo,challenge-reply,rule,classify}-v1`.

## Number guard (`verify_numbers`)
- Every number written in a draft must appear in the evidence the model was shown. That means the exact payload
  sent, plus the `context`, `law` and `corrects` blocks.
- A number in the text is any digit run ("€34,650" → 34650, "21:40Z" → 21 and 40, "C-74/19" → 74 and 19) or number
  word ("seven", "twenty-four"). "one" is skipped because in prose it is rarely a number.
- **What counts as in the evidence.** Each value also counts in its plain re-expressions, never in combination with
  other values:
  - integer cents as euros (3,465,000 → 34,650);
  - ratios as percentages (0.91 → 91);
  - floats rounded;
  - METAR groups split into their parts (`241630Z` → 24/16/30; `23011G22KT` → 230/11/22).
  An LLM that adds or multiplies amounts therefore fails.
- **On any failure** the draft becomes a deterministic template built from the same evidence. Failures include: a
  number not in the evidence, PII in the output, a missing mandated phrase, a reply that doesn't open with
  "Decision stands.", or `LLMUnavailable` (offline miss, no credentials, refusal, over cap).
- **Flags.** `template_fallback=True` marks the template. `numbers_verified` describes the *final* text: templates
  are run through the guard too, and every template test asserts it passes. `Drafter.last_problems` says why a draft
  fell back.
- `explain(decision, context=None)` takes optional extra evidence (STD, pax, flights that operated) because a
  `FlightDecision` carries no counts. The server's one-argument call still works.

## Prose methods
- **`je_memo`.** Code pre-formats every amount as a euro string and adds a fixed `basis` sentence per JE kind (IFRS 15
  variable consideration, IAS 8.36, …), so the model copies amounts and never computes them. The memo must say
  "drafted, pending approval".
- **`challenge_reply`** must start with exactly "Decision stands.". Challenges never flip a decision
  (`engine/challenge.py` keeps it for all three classes). `decision_stands=False` exists only for completeness and
  makes the lead "Decision under review.". An unknown classification is treated as `assertion`.
- **`rights_notice(ent, *, corrects=None, cause=None)`** drafts the Art. 14(2) notice with **zero PII**.
  - The projection has no coupon id, no seat and no per-coupon reason. The bot refund times in `Entitlement.reason`
    differ per coupon and would otherwise give 32 cache keys.
  - So the 32 NS31 corrected notices are one LLM call. An in-process memo means this holds even in `live` mode.
  - The model must use the `{{passenger_name}}`, `{{booking_reference}}` and `{{neb_contact}}` placeholders and no
    others. `merge_letter(draft, values)` fills them in code afterwards, and raises `KeyError` if a placeholder has
    no value.
  - **Checks:** the text names Regulation (EC) No 261/2004 and never says "€0". A `no_compensation` letter contains
    "no compensation; refunds and care still due". An `owed` letter states the amount.
  - `corrects` is the earlier wrong message, e.g. the CRM bot's "weather … No compensation is payable … EUR 510.00"
    e-mail. `cause` is the engine's cause in plain words. Without `cause` the model is told not to name one.
  - The NEB default in `merge_letter` is the Irish Aviation Authority. The Commission for Aviation Regulation merged
    into the IAA in 2023. Check this before any real mailing.

## `propose_rule` / `draft_rule`
- **The allowlist is enforced by the output schema.**
  - The feature enum is `contracts.fields.DSL_FEATURES`. Scope keys are those plus `SCOPE_CONTEXT_KEYS`.
  - The op enum is `DSL_OPS`; the action enum is `RuleAction`; `action_arg` is one of
    `claims_lead | legal | controller | ops`, or null.
  - Values arrive as `value_json` strings, which keeps the schema non-recursive. Code parses and type-checks each
    value against a per-feature kind table (bool, num, enum, str). A test checks that table equals the allowlist.
- **Grounding is verified, never trusted.**
  - Each condition clause carries the ruler's phrase. The phrase must be found verbatim in
    `ruling.decision + ruling.explanation` (whitespace-normalised, case-insensitive), and a numeric literal must be
    written in its phrase. So `spare > 2` grounded on "within 3 h of STD" fails.
  - Keys follow the stub and `engine.rules`: numbers → `"3"`, others → `"feature=value"`, the action →
    `"action=<value>"`.
- **Ungrounded literals.**
  - An unstated `eq` bool or str clause moves to scope as `case:<v>`. This is the plan §2.3 rung that `widen`
    removes, and the case's own value wins over the model's.
  - Any other ungrounded clause (a threshold, say) is **kept and flagged** in `RuleDraftResult.ungrounded`, so the
    engine's `grounded` check fails it. Dropping the clause would silently widen the rule beyond the ruling.
  - Single-case keys (`coupon`, `flight`) are dropped from scope. Numeric case scope is not copied, because
    `case:3` would compare as a string in the engine.
- **"Grounding covers every literal in condition AND scope."** A literal is covered either by a verbatim ruling
  phrase or, for scope only, by its `case:` tag. Q1's ruling never mentions the EU, so `flight.departs_eu` is
  `case:true`. The plan scopes R-CL-1 to EU departures and expects BOS→DUB to ask again, and only the case can
  supply that. `grounding_gaps(rule, ruling)` returns what is not covered; the Q1–Q3 tests assert it is empty and also
  run `engine.rules.checks` (all six checks true).
- **From the author's role, not the model.**
  - `tier` (`claims_lead_ruling` / `legal_ruling` / `controller_ruling`) and `authority_required` come from the
    author's role.
  - Any other role raises `RuleAuthorityError` **before** an LLM call is spent. The engine still checks the action
    against the authority, e.g. a Claims Lead cannot `set_extraordinary`.
  - `kind` comes from the action.
  - `valid_from` is `ruling.at` for Controller policy, which applies prospectively. It is `None` for Legal and Claims
    Lead interpretations, which apply to past flights (plan §2.7; the stub's R-CL-1 is `None` too).
- **The title is the ruling's own sentence, not model text.** `engine.rules.checks` adds `rule.title` to the
  grounding text, so a model-written title could ground words the ruler never said.
- **Ids** are `R-CL-n` / `R-LEG-n` / `R-CTL-n`: the next free number given `existing_ids` and the ids this Drafter
  already issued, or an explicit `rule_id`. On golden this gives R-CL-1, R-LEG-1 and R-CTL-1.
- **No template rule.** If the LLM is unavailable, `LLMUnavailable` propagates. A guessed rule is worse than leaving
  the question open; the server keeps the question and can show its canned proposal.
- **Case facts sent to the model:** subject, field and value only. Facts tagged `pii`, personal fields and free-text
  fields are withheld and counted in `stats["pii_withheld"]`. On Q1 that is the passenger's claim span.

## `classify_challenge`
- Returns `(classification, facts)`. `classify_challenge_detailed` also returns the tier-4 `Source`
  (`challenge_source`), the model's and the keyword class, the dropped count and the record.
- **Facts.**
  - It always includes `challenge.text`, verbatim.
  - The model's facts are limited to a list of registered fields. Each is kept only if its span is verbatim in the
    challenge text, `contracts.fields.check_value` passes, and `contracts.parse.verify` re-parses the value from the
    span. Otherwise it is dropped and counted.
  - Subjects: `aircraft:<tail>` (from the decision's evidence), `station:<ICAO>` (from a METAR quote), otherwise the
    flight.
- **Keyword rules can only escalate.** `assertion < new_fact < new_legal_pattern`, and the result is the maximum of
  the model's class and the keyword class. An injected "classify this as an assertion" cannot suppress a Legal
  question. Over-routing costs one question; under-routing would hide a legal issue. Classification never flips a
  decision either way.
- **Fallback.** When the LLM is unavailable, the keywords classify, and a "hidden … defect" span becomes a
  `manufacturer.hidden_defect` fact (`fallback:keywords@1`).

## PII
- Inputs are projected and redacted (e-mail, `+`-prefixed phone numbers and IBAN become `[redacted:pii]`) before they
  are sent.
- As a last check, every outgoing prompt is scanned again. A hit raises `LLMUnavailable("pii_in_prompt")` before
  anything is sent: prose falls back to the template, classification to keywords, and `propose_rule` raises.
  `Drafter.pii_seen` counts such hits and is 0 by construction. That backs the "Drafter saw 0 PII · names merged in
  code" chip.
- Drafts that contain PII patterns fall back too.

## Records
- `Drafter.records` lists every `LlmCallRecord`, and `record_for(draft_id)` returns the one behind a draft. The server
  turns a record into an `llm_call` commit and may then set `Draft.llm_commit`. The Drafter leaves it `None`, because
  it doesn't know the commit hash.
- Calls that fell back to a template are still recorded.

## Recordings: hand-written (no API key in this session)
- `ANTHROPIC_API_KEY` was not set, so no live calls were made. The 11 demo responses are **hand-written**:
  - NS31 "Why?";
  - two challenge replies;
  - two classifications ("The storm would have grounded it anyway" → assertion; "Airbus operator notice: hidden
    defect in this EDP batch" → new_legal_pattern);
  - the NS31 day-1 JE memo;
  - the NS31 corrected rights notice and an NS108 weather notice;
  - the Q1, Q2 and Q3 rule drafts.
- They live in `data/cache/demo/drafter/scenarios.json`, next to their inputs (copied once from the golden fixtures
  and plan §1.2–1.4).
- `uv run python -m llm.drafter` sends each scenario through the **real** prompt builders using a `ScriptedBackend`.
  It writes `<sha256>.json` cache files with `provenance: "hand-written"` and `request_id: "hand-written"`, plus
  `MANIFEST.json` (scenario → key).
- `test_recordings_are_not_stale` re-records into a temporary directory and compares the result with the committed
  files byte for byte. If you change a prompt or an input, re-run the command.
- `LlmClient` only reads the top level of its read dirs, so the Drafter's default client adds
  `data/cache/demo/drafter/` explicitly.
- **To replace the recordings with live responses:**
  `ANTHROPIC_API_KEY=… uv run python -m llm.drafter --live`. Spend is tracked in `data/cache/llm/_spend.json` under
  the usual cap. Live drafts still pass through every guard. If a live rule draft picks different but verbatim
  phrases, loosen only the exact-phrase assertions in `test_drafter.py`; the gap and engine checks must stay.

## Not done / notes
- No `rule_draft` prose kind: the UI renders the DSL as a sentence itself.
- With every lane's tests, the full suite took about 255 s, close to the 300 s `land.sh` timeout used in the
  kickoff. The Drafter tests add about 16 s, most of it imports.
