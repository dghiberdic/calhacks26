# engine/ decisions (lane A, David)

Judgment calls made while implementing, one line of reasoning each. Newest at the bottom of each section.

## D1 · `engine/timeline.py`

**Computed windows on the pinned real METAR.** These come from data and are not hard-coded:

| File | Window (UTC) | Peak | Counting obs |
|---|---|---|---|
| `eidw_2025-01-23_25.csv` | 2025-01-23 23:30 → 2025-01-24 00:30 (minor) | G38 | 2 |
| `eidw_2025-01-23_25.csv` | **2025-01-24 02:30 → 15:00 (main)** | G56 | 24 |
| `eidw_2025-01-26.csv` (Herminia) | **2025-01-26 11:30 → 13:00** | G43 | 3 |

The real data matches every expectation in plan §1.2 and THREAD_DAVID D1. Nothing contradicted the plan.

- **Merge rule: "under 2 h" is strict.** The minor window's last counting obs (00:30, G35) and the main window's first (02:30, G39) are exactly 2 h apart, so they do not merge. That is why the minor window stays separate, as the plan says it should.
- **Edges are inclusive.** A time exactly on `start` or `end` is `in`, with margin 0.
- **`unknown` is checked first.** If no obs falls within ±60 min (inclusive) of `t`, the answer is `unknown` even if a window passed in covers `t`. With gaps under 2 h merged, every point inside a window built from the same obs is under 60 min from a counting obs, so this only matters when the obs and windows passed in disagree.
- **Margin sign.** `margin_min` is positive when outside a window (minutes to the nearest edge of the nearest window), negative when inside (minutes to the nearer edge), and 0 on an edge. It is `None` when there are no windows. This matches CONTRACTS "NS31 is outside the DUB window with margin ≥60" (NS31 STD 16:30Z gives +90). `EndPosition.margin_min` is also `None` when the position is `unknown`.
- **A hole of 2 h or more in the data splits a window.** If obs are missing mid-storm, the counting obs on either side are ≥2 h apart, so they form two windows. Times within 60 min of the last storm obs before the hole read `out` with a small margin (≤60). Times further into the hole read `unknown`. This follows the binding definition literally. D2 should treat a small positive margin as weak evidence of calm.
- **Matching wx codes.** Each present-weather token has its `+`/`-` stripped and is split into 2-letter groups (`-FZRA` → FZ, RA; `+TSRAGR` → TS, RA, GR), and the check is against {SN, FZ, TS, GR}. On real codes this gives the same result as a substring test, and it can't produce cross-group false positives. Recent-weather groups (`RETS`) would count. The pinned days contain none: the IEM `wxcodes` column holds only present weather (`-RA`, `RA`, `-RADZ`).
- **`peak_gust_kt`** is the highest gust of any obs inside the window. When an obs reports no gust, its sustained wind is used instead. A fog-only window can therefore have a small "peak".
- **`obs_count`** is the number of counting obs that formed the window, not every obs inside its span (the main window spans 26 obs, 24 of them counting).
- **Station id.** `load_iem_csv` uses the ICAO at the head of the raw METAR (`KBOS`), because IEM's `station` column uses 3-letter ids for US stations (`BOS`). An explicit `station=` argument wins. Empty cells and IEM's `M` become `None`. Output is sorted by time.
- **Outstations without METAR are `unknown`, never assumed calm.** `departure_position(NS117, [], [])` returns `unknown`. If `world.json` only carries EIDW, every outstation departure end (LHR, CDG, MUC, LIS, FCO, BOS…) is `unknown`. In that case the D2 knock-on rule ("out at both ends") cannot fire without outstation METAR. Lane B: put calm outstation METAR in `world.metar` for at least LIS/FCO/MUC on 2025-01-24, or D2 will have to decide what `unknown` at the outstation means.
- **Naive datetimes raise `ValueError`.** Engine times must be tz-aware UTC.

## Purity (`engine/tests/test_purity.py`)

- The test is an AST scan of `engine/**.py` and `books/**.py`. It skips `books/` until it exists, skips `tests/` dirs and `conftest.py` (test code makes no decisions), and asserts that at least one engine file was scanned.
- **Banned:**
  - any import of `anthropic`, `random`, `secrets`, or `numpy.random`;
  - `datetime.now`, `datetime.utcnow`, `date.today` (including through `import datetime as dt` and `from datetime import datetime as X`), whether called or merely referenced;
  - `time.time`, `time.time_ns`, `uuid.uuid1`, `uuid.uuid4`, `os.urandom`;
  - dynamic imports of the banned modules (`__import__`, `importlib.import_module`).

  `time`, `uuid` and `os.urandom` go a little beyond the letter of rule 1. They are the same wall-clock and randomness sources under other names.
- The injected `clock.now()` / `self.clock.now()` stays allowed. Positive and negative self-tests keep the checker honest.

## D3 · `engine/eu261.py` (+ `engine/geo.py`, `engine/dsl.py`)

- **Status order per coupon:** out_of_scope → staff_ticket → exempt_notice → (decision) no_compensation / held → owed, then the voucher check (owed or needs_ruling). The flight-level question (held) dominates a coupon-level one (an unsigned voucher on a held flight stays `held`).
- **Distances.** `world.meta["distances_km"]` wins when it pins the pair (keys `DUB-BCN`, `BCN-DUB`, `DUBBCN`, `DUB:BCN`, or a flat `{dest: km}`); otherwise great circle with R = 6,371 km from `World.airports`, falling back to the bundled `airportsdata` table for codes the world lacks. Rounded to 0.1 km. airportsdata coordinates give DUB–BCN 1,485.2 km (plan: 1,486), so the margin is 14.8 km with the fallback and exactly 14 with the plan's pinned value. Both read "14 km under the €400 band" (`int`).
- **`band_margin_km`** is the distance to the threshold that would change the band: ≤1,500 → 1,500 − d; intra-EU >1,500 → d − 1,500 (there is no 3,500 km edge intra-EU); other 1,500–3,500 → the nearer of the two edges; >3,500 → d − 3,500. "Intra-EU" means both ends are in EU261 territory (EU27 + IS/LI/NO + CH), so DUB–LHR is not intra-EU.
- **Art. 7(2) reduction** needs all of: a reroute election (`reroute_partner` or `reaccommodated_own`); an arrival delay that does not exceed 2 h / 3 h / 4 h for the coupon's band (≤, "does not exceed"); and an *active* `APPLY_7_2_REDUCTION` rule (e.g. `R-MINED-REDUCE`) whose scope and condition match, in force at `known_at`. A shadow or late-recorded rule gives no reduction (NS31 = 10,320,000 instead of 9,900,000). The rule ref is in `rules_applied`.
- **Art. 5(1)(c) notice:** `pax.notice_days` = (STD − `Flight.notified_at`) in days. (i) ≥14 days is exempt. (ii)/(iii) also need the rerouted *departure* time, which `Election` doesn't carry. `notice_exemption` takes `departure_advance_min` from a caller that knows it. Without it the carrier hasn't shown the condition, so the passenger is **not** exempt (conservative, pro-passenger).
- **Scope (Art. 3):** origin in EU261 territory → (1)(a); else destination in territory on an EU carrier → (1)(b); else `out_of_scope`. Out-of-scope and staff tickets (Art. 3(3)) get `care_due = False`, because the whole Regulation doesn't apply to them. Every in-scope coupon gets `care_due = True`, including extraordinary ones (McDonagh).
- **Refunds (Art. 8):** a known `refund_initiated` **or** `bsp_refund` sets `refund_already_initiated` and `refund_due = 0`. Two refund events on one coupon, or a chargeback after a refund, are flagged in `reason` ("duplicate refund … flagged, not repeated"). Otherwise a `refund` election gives `refund_due = fare + taxes`; a refund voucher election gives 0 (settled by voucher). Refund ≠ waiver: the 32 bot-refunded NS31 coupons stay `owed` €600.
- **Vouchers (Art. 7(3)):** the latest known `voucher_in_lieu_of_compensation` event counts. If signed (`signed_acceptance_sha256` set), the status is `owed` with offset = min(amount, compensation); `compensation_cents` stays gross (Books accrues gross). If unsigned and no voucher rule applies → `needs_ruling` (the engine does not pre-answer Q1). If a voucher rule applies, the strongest wins: `DENY_OFFSET` (R-CL-1) → owed, offset 0; `ALLOW_OFFSET` → owed with offset.
- **Held** (decision `needs_legal`) accrues at the full band amount with no 7(2) reduction, so Books' segment-rate accrual gives the golden knock-on numbers.
- **Only cancelled flights** get entitlements. Delays (Sturgeon ≥3 h) are out of scope for the demo and return [].
- **`rules_applied`** on an entitlement = the decision's rules + the coupon-level rules (reduction, voucher). D5's citation counting has to count flight-level rules once per decision, not per coupon.
- **DSL (`engine/dsl.py`)** was written here because entitlement rules need it; D4 builds precedence/authority/grounding on top. A missing feature reads as `None` (comparisons are false; `exists` false). A type mismatch is false, never an exception. An invalid rule never fires. Scope keys are the allowlisted features plus the context keys `storm`, `cohort`, `flight`, `station`, `segment`, `coupon`. `case:<v>` values constrain like literals (`case:true`/`case:false` parse as booleans).
- **Bitemporal:** a rule fires only if `status == active`, `recorded_at ≤ known_at`, and `valid_from` is None or ≤ the flight date.

## D2 · `engine/cause.py`, `engine/ata_table.py`, `engine/case.py`, `engine/engine.py`, `engine/storm.py`

**Inputs.** `FlightCase` is built from the `World` as known at `known_at`:
- METAR obs with `valid > known_at` are dropped. So are tech/ops log lines logged after `known_at`.
- Station obs come from every `world.metar` list keyed `<ICAO>@…`, or obs whose `station` is the ICAO, across all days, so overnight flights see both days.
- `EngineAPI.decide(flight_id, facts, …)` overlays facts on the engine's base world (`Engine(world=…)`). Per (subject, field), only facts recorded by `known_at` count; the best source trust tier wins, then the latest. Understood fields: `flight.ops_cause_code`, `flight.notified_at`, `spare.available_within_h`, `pax.reroute_earliest_offered`, and `aircraft:<tail>` `aog.*`, which becomes a tech-log line. When `contracts/fields.py` lands, the overlay is the only place to align.

**AOG relevance.** A tech-log line counts for a flight when all of these hold:
- same tail, `aog=True`;
- logged within 36 h before STD (and by `known_at`);
- not returned to service by STD (`rts_est` is None or later than STD).

A no-go line (`mel_relief` False or None) beats one with relief; ties go to the latest. **`mel_relief=None` counts as no-go**, because an AOG is no-go unless relief is logged. `mel_relief=True` is not decisive and falls through.

**Rule 1 vs 2, and the "both ends" condition.**
- Rule 1 needs the AOG to be decisive and outside any window, and the flight to be not `in` at either end. An `unknown` far end (no BOS METAR for NS31) does not block it: the aircraft could not fly either way. The cap `capped:window-unknown` is not added, because the tier-1 evidence is decisive.
- An AOG logged *after* a window but before STD also qualifies. The `aog_before_window` feature is then 0, which lowers confidence.
- A decisive AOG with the flight `in` a window at either end is **concurrent** too, not only an AOG logged inside the window. Two causes overlap, so it goes to Legal.

**External or unmatched root cause** (bird, lightning, hail, FOD, de-icing, ash, or no ATA match) gives `technical / needs_legal`, pattern `external_event`, routed to Legal, recoded 71 → 41. The aircraft *was* unserviceable before the storm, so weather is still wrong; whether the event is extraordinary is for Legal.

**Out at both ends, no tier-1 cause.** The OCC code is never trusted alone:
- A weather code (71/72/73/75/76/77) gives `unknown / needs_legal` → Ops. The pattern is `weather_code_contradicted`, the tag `sources-disagree`, and the OCC evidence is `contradicts` but not struck (no winner yet).
- 4x without a tech-log line gives `technical / not_extraordinary` with no recode, low confidence, and batch review or escalation to Ops.
- 6x/94/95 gives `crew` (not extraordinary). 8x gives `atc` (extraordinary, Recital 15). Both have low prior confidence, so a person sees them.
- No code, or an unknown code, gives `unknown` → Ops.

**`unknown` window (rule 5).** It applies when no end is known calm. With one end calm:
- a weather code naming the calm end is a contradiction, not a gap (71 → departure end; 72 → arrival end);
- a recognised non-weather code is taken at its word;
- otherwise it is a gap → Ops, tag `out-of-scope`. No contract tag fits "data gap" exactly.

**Knock-on.**
- The previous rotation is `outbound_pair_id`, else `inbound_flight_id`. It is decided recursively (depth ≤ 3), *including* rules.
- Previous rotation cancelled and extraordinary → `knock_on / needs_legal` → Legal, even when the outstation METAR is `unknown`. The aircraft never got there, so outstation weather at STD is not the cause.
- Previous rotation not extraordinary → `knock_on / not_extraordinary` (C-74/19: the knock-on of an internal cause is not extraordinary).
- Previous rotation undecided → follow it to the same person.

**Spares.** Spare evidence and the `spare.available_within_h` feature appear only for non-technical causes, so a legal rule conditioned on spares can never fire on a technical cause. A test shows that changing NS31's spares text leaves its decision byte-identical. The value is parsed from "STD+4h20" (4.33 h) or "available within N h".

**Cause rules.**
- Only `SET_EXTRAORDINARY` / `SET_NOT_EXTRAORDINARY` rules of tier `hard_control`, `regulation` or `legal_ruling` can settle `extraordinary`. A mined or Claims Lead rule never can.
- The strongest matching rule (dsl precedence) is cited. If it disagrees with the engine, it is applied: a legal interpretation wins.
- `ROUTE_TO` from any ruling tier re-routes an unsettled case.

**Confidence (default priors, `engine/default_calibration.json`).**
- Hand-set so that in-window weather is ≥0.92 even 0 min inside the edge, NS31 is 0.909 ("91%"), knock-ons are 0.37–0.50, and gaps or contradictions are <0.2.
- `in_window_*` is 1 for `in`, else 0. `window_margin_h` is |deciding margin| / 60, capped at 4.
- `precedent_count` = history cases whose `kind` equals the pattern, + 10 × matching ruling rules, capped at 10. A binding ruling counts as a full set of precedents, so a knock-on settled by R-LEG-1 scores ≥0.90.
- `data/calibration.json` overrides when present. Tests pin the default.

**Routing outcome.**
- `needs_legal` is always `escalated` to the finding's person.
- Score <0.60 → `escalated`. 0.60–0.90 → `human` (batch review; the contract has no "batch" value). Score `None` → `human`.
- ≥0.90 → `auto`, unless the per-flight *expected* liability (accruing compensation × segment ultimate rate, as Books computes it) is ≥ €50k. That case is `human`, routed to the Controller.
- NS31: €34,650 < €50k → auto.

**`window_margin_min`** is non-negative, matching the stub: the |margin| at the end that sits in a window, else the smaller known out-margin. `in_window_*` says which side.

**Question ids.** There is one question per (pattern, storm). Here storm = the run's id, or for a lone `decide`, the window's `<ICAO>@<start date>`.
- For the world's *primary* storm (`meta.primary_storm`, else the earliest of `meta.storms`), ids are short and match the stub, the demo script and `server/tests`: `Q-1` voucher in lieu, `Q-2` knock-on returns, `Q-3` cohort release, `Q-4…Q-12` the other patterns (`engine.engine.PATTERN_NO`).
- Every other storm gets `Q-<storm>:<pattern>`, so a later run or a desk world never overwrites the hero's questions in a store. A world with no `meta.storms` (e.g. a desk world) always gets qualified ids.
- The cohort question is `Q-3` whenever the world lists storms and has exactly one opening-balance cohort; otherwise it is `Q-<cohort>:cohort_release`. The mini world declares `meta.storms` so it behaves like golden.

**`run_storm`.**
- Flights are those with STD at the station, or STA at the station, inside the station's *local* day (overnight inbounds included).
- METAR shown runs from the local day −6 h to +6 h.
- Counters: `drafted` = owed coupons; `held` = held + needs_ruling coupons; `rules_cited` = decision rules + coupon-level rules not already on the decision.
- `entitlement_cents` = owed + needs_ruling compensation. `liability_drafted_cents` is the engine's preview of Books' day-1 number (same rates, rounded per flight × segment, half away from zero).
- A day with no window gets `message = "max gust N kt · no storm window"`.
- **`aog.before_window`** is relative to *the flight's* storm window, i.e. the window it sits in at either end, else the nearest window to either end (`FlightCase.window`). Comparing against any window at the AOG station was wrong on Herminia: Éowyn's window had ended 32 h before EI-NSF's AOG, which made a pre-Herminia AOG read as "after a window". An AOG logged inside the flight's window, or inside any window at its own station, is `inside_window`.
- **Golden world check (`test_golden_engine.py`, before `expected/` lands):**
  - Éowyn: 23 weather auto, NS31 technical 71 → 41 auto at 0.909, 3 knock-ons to Legal (0.37–0.50, one question).
  - Questions are knock-on (Legal), 14C (Claims Lead, 0.39 sources-disagree) and the Isha release (Controller, 0.72), so "3 questions · 3 people".
  - Money: entitlement 9,900,000 and drafted 8,214,600, with R-MINED-REDUCE active.
  - Herminia: NS106 recoded 71 → 41, NS110 and NS30@01-25 technical. R-CL-1 settles exactly the 31 EU-departure vouchers; the BOS→DUB one asks again.
- **The Isha release question is in every run** whose `known_at` month-close puts the cohort at ≥ M12 with ≥3 quiet months and no keep-tail/deny-release rule. It has one id (`Q-3` on golden), so the server can de-duplicate it across runs. It disappears once R-CTL-1 is in force.
- **`expected/` acceptance** (`test_expected.py`) runs both golden storms with R-MINED-REDUCE active. It checks:
  - decisions compared exactly on the five fields plus `recode_label`, with confidence by band (`min` inclusive, `max` exclusive);
  - operated flights have no decision;
  - NS31 entitlements coupon by coupon;
  - questions by pattern (role, tag, refs, holds, kind, band, "€600" in the recommended option);
  - golden numbers.

## D6 · `engine/confidence.py`, `engine/routing.py`, `engine/questions.py`, `engine/challenge.py`

**Confidence.**
- One logistic per `Confidence.kind`. A missing or malformed model (feature/coef length mismatch) gives `score=None`, and the outcome is `human`: an uncalibrated decision is never automatic.
- Missing features read as 0. Caps are passed through, de-duplicated, and never change the score (tested).
- Default priors include a `release` model (age, months since last claim, precedents) tuned to the plan's 72% for Isha at M12 with 3 quiet months. There is no `claim_validity` model, so it is uncalibrated.

**Voucher confidence (Q1).** Features are `in_lieu`, `signed`, `sources_disagree`, `precedent_count`.
- `sources_disagree` = 1 when the CRM voucher text says "accepted" but there is no signature hash, or when a claim on the coupon says the passenger never agreed.
- On golden 14C both hold: 0.389, tag `sources-disagree`.
- `precedent_count` counts `history_cases` of kind `voucher_in_lieu_unsigned` (none on golden).

**Thresholds.** ≥0.90 auto (0.90 itself is auto), 0.60–0.90 `human` (batch review), <0.60 `escalated`. The materiality gate is `liability ≥ 5,000,000` → `human` to the Controller, so exactly €50k is *not* auto ("< €50k AND ≥ 0.90").

**Question content.**
- Holds are the flight ids (flight patterns), coupon ids (vouchers) or cohort ids.
- `holds_cents` is the accrued liability held for flight patterns (Q2: 4,749,600), the compensation at stake for vouchers (Q1: 60,000), and the balance for a cohort (Q3: 360,000).
- The question's confidence is the weakest of its cases.
- A knock-on with prior precedents but no matching rule becomes `new-legal-pattern` instead of `no-precedent`.

**Reminders.** `remind_at = asked_at + 3 h`. `status_at(q, now, answered)` is the view: answered > reminded (now ≥ remind_at) > open. The server's Clock supplies `now`.

**Challenges (`engine/challenge.py`).** Challenge facts are tier 4 and never flip a decision; `decision_stands` is always true.
- `assertion` cites the decision's tier-1/2 evidence (struck evidence excluded) plus the departures from the same origin that operated between the window end and STD + 2 h. On golden that is 11 departures, the plan's "everyone else flew".
- `new_legal_pattern` → Legal question `Q-<flight>:new_legal_pattern`, tag `new-legal-pattern`. Confidence is the decision's features with `sources_disagree = 1` (NS31: 0.45, plan says 52%, both < 0.6) plus cap `capped:challenge-tier-4`.
- `new_fact` → Ops question `Q-<flight>:challenge_new_fact`.
- The Drafter writes the reply prose; the server assembles `ChallengeResponse`.

## D4 · `engine/rules.py`, `engine/controls.py`

**Authority, by action first and kind second.**
- Legal: `set_extraordinary`, `set_not_extraordinary`, `allow_offset`.
- Claims Lead: `deny_offset`, `apply_7_2_reduction`.
- Controller: `keep_tail`, `deny_release`.
- `route_to` goes by kind: cause/entitlement/regime → Legal, voucher → Claims Lead, release/routing → Controller.
- The author must also match the rule's tier (claims_lead → `claims_lead_ruling`, …).
- Agents, Ops, CFO and the judge never author rules. Nobody authors a `hard_control` or `regulation` rule (code and regulation versions only). Mined rules have no human author and may only carry mined policy.

**Statutory floor.** "Lower EU261 compensation" means going below what the Regulation itself gives:
- `allow_offset` (offsetting without Art. 7(3) signed consent) and `set_extraordinary` are Legal only.
- The Art. 7(2) reduction is the statute's own reduction, and the engine enforces its limits, so a Claims Lead / mined policy may apply it. That keeps R-MINED-REDUCE's `authority_required = claims_lead`, as on the stub card.

**Hard-control screening.** A proposal fails `no_hard_control` when:
- its tier is `hard_control`; or
- it routes to a non-internal party; or
- the ruling text, rule title, scope or condition matches the hard-control phrases in `controls._HC_PATTERNS`: SoD ("approve their own", "requesters approve"…), payout bypass, locked-period writes, materiality bypass, or external approval.

The checks themselves are code in `controls.py`:
- `check_approval`: agents never approve; external or unknown principals never satisfy an approval; preparer ≠ approver; payouts need the Claims Lead; everything else needs the Controller (same split as Books).
- `check_period_write`, `materiality_ok` and `check_answer` (only the routed role, never an agent or external party).
- Each result renders as an `AccessDecision`, or as a `TraceEvent` such as "agent.drafter approve_payout → DENIED · SoD".

**Grounding.**
- Literals map to phrases through a per-(feature, value) lexicon, a per-feature numeric unit table ("within 3 h of STD", "M12", "4,804 km") and the action lexicon ("no offset", "Never release the tail").
- Keys follow the stub: numbers → `"3"`; others → `"voucher.signed=false"`; the action → `"action=deny_offset"`. Phrases are verbatim substrings of the ruling.
- An ungrounded scope key is copied from the case as `case:<v>`, which still constrains and is the rung `widen` removes. An ungrounded condition literal or action fails `grounded`.
- On golden text: R-CL-1 grounds `voucher.signed=false` → "No signed acceptance" and copies `flight.departs_eu` from the case as `case:true`, unless the ruler says "leaving the EU". R-LEG-1 grounds "within 3 h of STD". R-CTL-1 grounds "M12" and "until the six-year limitation", and copies the cohort from the case.

**Conflicts.**
- `resolve()` returns a conflict, applying nothing, when the strongest applicable rule has an equal-tier, equal-specificity rival with the opposite action (`set_extraordinary` ↔ `set_not_extraordinary`, `allow_offset` ↔ `deny_offset`).
- In the engine, conflicting Legal rulings make the case `needs_legal` → Legal, pattern `rule_conflict`, cap `capped:rule-conflict`. Conflicting voucher rules leave the coupon `needs_ruling`.
- A proposal whose action opposes an active same-tier rule with an overlapping scope gets `no_conflict = False`.
- Shuffling the rule order never changes the result (hypothesis).

**Cause rules in the engine (changed with D4).**
- Only a `legal_ruling` may settle or override `extraordinary`.
- Regulation and hard-control cards are only *cited* when they agree. The stub's R-REG-ART5-3 card ("in window at either end → extraordinary") would otherwise have flipped every concurrent-AOG case to "extraordinary".
- `route_to` rules apply only from ruling tiers (claims_lead / controller / legal), never from the `R-HC-*` display cards, which carry `route_to` with an empty condition.

**Versions (`RuleBook`).**
- Append-only events: `version` (immutable `Rule` snapshot, version number assigned on add, `supersedes` = the previous version), `status` and `cite`.
- `rules_known_at(K)` replays the events up to K. A version is shown `retired` while a newer version is active, so retiring (reverting) the newer version brings the older one back. To retire a rule entirely, retire each version.
- `times_cited` is Σ cite events. The server and trace own persistence; `RuleBook` is the pure view.

## D5 · `engine/lifecycle.py`

**Store.** `Lifecycle(engine, world, trace, books=, drafter=)` keeps rules, rulings, question events, decisions and citations in `engine.trace.TraceStore`.
- `rules_at(t)` = the latest active version per rule id as known at t.
- `record_run(decisions, ents, at)` records a run and one `cited` event per case per rule: flight-level rules once per decision, coupon-level rules once per coupon not already cited on its decision. Only rules the trace knows are cited.
- The server can call `record_run` for every storm it runs.

**decide_fn for replay.** `Lifecycle.decide_fn(flight_ids)` overlays the stored facts on the base world (`engine.case.overlay_facts`) and re-decides those flights plus their entitlements.
- The overlay ignores facts that only restate the world, so replaying `contracts.normalize.world_to_facts(golden)` (73,517 facts) gives byte-identical decisions for all 27 Éowyn flights (checked).
- `aog.defect_text` (the registry's name) is accepted as the tech-log text.

**Drafting.**
- An injected `DrafterAPI.propose_rule` drafts. If there is none, or its draft does not compile, `template_rule` builds one from the ruling's own words for the known patterns:
  - voucher → `deny_offset` (or `allow_offset` if the ruling says "offset the voucher"), condition `in_lieu ∧ ¬signed`, scope `flight.departs_eu` from the case;
  - knock-on → `set_extraordinary` (or `set_not_extraordinary`), `is_return_sector ∧ prev_cancelled`, plus `spare > N` when the ruling says "within N h" and `reroute_earliest_offered` when it says "earliest reroute", scope `rotation.prev_cause` from the case;
  - cohort release → `keep_tail` (or `deny_release`), `age ≥ M<n>` plus `limitation_expired = false` when "limitation" is said, scope `cohort`.
- Ops patterns (data gaps, contradictions, crew/ATC, challenge facts) produce no rule: an Ops answer is a fact, not a policy.
- The engine always sets `id` (`R-CL-n` / `R-LEG-n` / `R-CTL-n`, next free number), `version`, `tier` (from the author's role), `authority_required`, `origin_*`, `recorded_at` and `status=proposed`.
- `valid_from` is None for interpretations (Legal, and Claims Lead voucher rulings, so R-CL-1 settles 14C on the flight it came from). It is `at` for Controller release policy (prospective; the cohort check passes no flight date).

**Verify + preview.**
- `engine.rules.checks` grounds the rule (ungrounded scope → `case:`) and runs all six checks.
- `would_flip` = `TraceStore.replay(at, decide_fn(on-record flights), rules_override = rules in force + the candidate active, preview_fn = BooksAPI.preview)`. Only flights already on record are re-decided: a later storm whose METAR isn't known yet is never pre-decided.
- Release rules (`keep_tail`, `deny_release`) don't change flights. Their preview is one flip per matching opening-balance cohort: `release_proposed_cents` balance → 0, Δ 0. Nothing booked changes; the proposal was gated. R-CTL-1 keeps 360,000.

**Confirm.**
- Refused (`validation`) unless every check passed. Refused (`forbidden`, with an `access_denied` commit) unless the confirmer holds the authority.
- Then: record `active`, `replay_run`, `BooksAPI.post_recode(before, after)` for changed coupons, record the re-decided decisions/entitlements linked to the rule commit, and cite.
- Results: Q2 settles NS113/115/117 (Δ −4,749,600, Éowyn 2140 → 3,465,000, cited 3×). Q1 settles 14C (cited 1×). On Herminia, `record_run` cites R-CL-1 31× and BOS→DUB asks again.
- **`times_cited` for R-CL-1 is therefore 32** (14C + 31). `expected/questions.json` says `times_cited_after_herminia: 31`, but `q2_rule_cited: 3` counts the question's own cases. Counting the origin case is the only reading consistent with both, so the tests assert "+31 on Herminia" and the plan beat "31 settled, ruling cited" holds.

**Reject.**
- `reject(question, explanation)` records a `rejection` ruling against the question's recommended option and drafts from the explanation. That is the Q3 path: "Never release the tail…" → R-CTL-1 `keep_tail`, scope `cohort: case:EIDW@2024-01-21`, `widen_next = {"remove": "cohort", "question": "All storm cohorts?"}`.
- `reject(rule_ref, explanation)` retires a proposed/active rule and drafts a new proposal from the rejection, if the origin question is known.

**Widen.**
- Exactly one rung: drop the first `case:` scope key and any condition clause on that feature, giving a new version (`supersedes` = the old ref).
- The widened rule is re-checked with the original ruling's words and the confirmer's role.
- `widen_next` names the next case key, or None. Widening a rule with no case keys is a `validation` error.
- R-LEG-1's `rotation.prev_cause` is grounded by "storm" in Legal's text, so it is a literal, not `case:`, and R-LEG-1 cannot be widened. That differs from the stub's canned card.
