# engine/ decisions: miner (D7)

Judgment calls made while implementing `engine/miner.py`, one line of reasoning each. The main `engine/DECISIONS.md` belongs to the other engine lane, so these live here.

## Mining

- **Conditional majority, within a case `kind`.** Each `HistoryCase.kind` (`reroute_reduction`, `cause`, …) is the question that was decided, so candidates are scored only against cases of the same kind. A candidate's decision is the majority decision of the cases its condition covers. Ties go to the decision name that sorts first, and a tie can never reach 95% purity anyway.
- **Candidate clauses:**
  - `f eq v` for every observed value.
  - `f in [values whose cases mostly decided D]` when two or more values qualify. Values are listed most common first, then by JSON, so golden reads `["reroute_partner", "reaccommodated_own"]`, the same as the stub card.
  - Conjunctions of two clauses on different features (`MAX_CLAUSES = 2`), so a purer subset can still be found when the whole kind isn't pure (tested: 17 of 22 overall fails, `band 600` at 12 of 12 passes).
- **Only allowlisted features are mined.** Features outside `dsl.FEATURES`, and non-scalar values, are dropped before mining, so every emitted condition passes `dsl.validate`.
- **Numeric features with no finite domain are never split** (`flight.distance_km`, `pax.arrival_delay_min`). Thresholds would turn noise into policy, and the engine enforces the Art. 7(2) limits itself (`eu261.REDUCTION_LIMIT_MIN`). `flight.band_eur` has a finite domain (250/400/600), so it is mined like an enum.
- **Thresholds:**
  - Support ≥ 8 means cases that are covered **and** decided the majority way.
  - Purity ≥ 95% means support / covered.
  - Both are checked with exact `Fraction`s, so 19 of 20 (95.0%) is kept and 18 of 20 is not.
- **Tautologies are dropped.** A clause that admits the feature's whole domain (e.g. `band_eur in [250, 400, 600]`) says nothing.
- **Choosing a winner per (kind, decision): the most general survivor.** The ranking, in order:
  1. most cases covered;
  2. most support;
  3. fewest clauses;
  4. **selectivity** against the feature's domain;
  5. canonical JSON.

  Selectivity is what breaks the golden tie. `pax.election`, `flight.departs_eu` and `flight.route_region` all cover the same 42 cases at 41 of 42. `pax.election in 2 of 5` excludes 60% of its domain, against 50% for `departs_eu = true` (1 of 2) and 25% for `route_region in 3 of 4`. So the rule is the passenger's election, which is what Art. 7(2) is about.
- **Domains:**
  - From the contracts: `contracts.fields` enums, the `Literal`s on `Entitlement.band_eur`, `FlightDecision.in_window_*` and `Coupon.fare_type`, the `Cause` enum, and CONTRACTS §4 for `route_region`.
  - Booleans are {false, true}.
  - Other strings are an open vocabulary (observed values + 1).
- **One rule per (kind, decision); no sequential covering.** The plan needs one mined policy, and a second disjoint rule for the same decision would be a different story to explain.

## Only policy is mined

- **Law is never mined, whatever its support:** `extraordinary` / `not_extraordinary` (and the `set_*` spellings), and `allow_offset` (statutory floor). Legal rules on law, and the engine already ignores mined `SET_EXTRAORDINARY` rules (`engine/DECISIONS.md`). The reason is kept on the candidate (`settles law`), so the omission is visible.
- **Mineable decisions:** `apply_7_2_reduction` → `R-MINED-REDUCE`, and `deny_offset` → `R-MINED-NO-OFFSET`. Any other decision (e.g. the `no_reduction` exception) has no rule action, so it is reported and skipped. IDs collide only if two kinds mine the same action; the second gets `-2`, in kind order.
- **The 6 golden `cause` precedents stay below support 8,** as `contracts/DECISIONS.md` intends. They would be refused as law even with more cases.

## The proposal

- **Fields:** `kind="mined_policy"`, `tier="mined"`, `scope={}`, `authority_required` from `rules.required_role` (Claims Lead for the 7(2) cut), `title` as on the stub card, `support="41 of 42"`.
- **`status="shadow"`** when every check passes, else `proposed`. The server activates shadow rules at onboarding (`server/runtime.py`), so a rule that fails a check, or that a written policy contradicts, must not be shadow.
- **`recorded_at` = the latest `at` in `history_cases`** (2024-12-30T10:00Z): the miner's knowledge horizon, deterministic, with no clock. It is before every storm `known_at`, so the activated rule is in force for Éowyn and Herminia.
- **`valid_from = None`:** a mined practice describes how cases have been handled, not a dated policy change. This matches the `REDUCE` rule used by the engine's golden tests. An activated mined rule reproduces NS31 = 9,900,000 (tested through `eu261.entitlements`); in shadow it gives 10,320,000.
- **`grounding` points at the case ids, not ruling phrases:**
  - Each condition literal, keyed by `rules.grounding_key` (so `rules.ground` treats it as grounded later), maps to `history HR-RR-001, …` (the 41 supporting ruling ids).
  - `action=apply_7_2_reduction` maps to `41 of 42 past decisions; exception: HR-RR-024`.
  - `origin_example` names the span (by `at`, `2023-11..2024-12`) and the exception.
- **`checks` come from `rules.checks`.** That function has no ruling text, so the title grounds the action ("50%"), and the first supporting case is the reproduce-case. The miner keeps its own rule, because `rules.ground` would overwrite the case-id grounding of the action with the phrase "50%". `no_conflict` is forced false when a written policy disagrees.
- **`would_flip` replays the rule against the history it came from.** Each exception becomes a flip `decision: no_reduction → apply_7_2_reduction` on its `case_ref`. For the 7(2) cut, Δ = −50% of the band (HR-RR-024: −30,000), and only if the statute allows the cut on that case (reroute election, delay ≤ the band's limit). Otherwise the engine wouldn't cut, so nothing flips. Replaying live entitlements is Books' `preview`, not the miner's job.

## Written policy vs practice

- **Where written policy comes from:** `world.meta["written_policies"]` plus `written=`. Each entry may be:
  - a `Rule`; its action maps to a decision (`APPLY_7_2_REDUCTION` → `apply_7_2_reduction`, …);
  - a `Rule`-shaped dict;
  - a plain mapping `{id, text, decision, condition?, scope?, kind?}`. This form exists because "never take the cut" (`no_reduction`) has no `RuleAction`.

  An entry that doesn't parse, or whose DSL doesn't validate, is skipped, never raised (binding rule 8).
- **What the policy speaks to:**
  - The cases of its `kind` if given.
  - Otherwise the kinds where its decision or an opposite decision (`OPPOSITES`) was ever taken. So a "no reduction" policy is still compared with the reroute cases even when no case was ever decided `no_reduction`.
  - In both cases, only cases matching its scope and condition count.
- **What counts as a disagreement: an established practice,** with the same thresholds as mining (support ≥ 8, purity ≥ 95%), whose decision differs from the policy's. Thin or mixed practice raises nothing: no question without evidence.
- **The Controller question:**
  - One per contradicted policy: `Q-POLICY-<id>:policy_contradiction`, `pattern="policy_contradiction"`, `reason_tag="sources-disagree"`, routed to the Controller.
  - `holds` = the mined rules it keeps at `proposed`; `holds_cents = 0` (no cash is held, only a rule).
  - `recommended_option` = keep the written policy: a mined practice is a habit until someone with authority adopts it.
  - Evidence: the policy (tier 2, `contradicts`), then the exceptions, then supporting cases (12 in total).
  - `confidence.score = None` ("uncalibrated": no model exists for this kind of question). `kind="claim_validity"` is the nearest allowed `Confidence.kind`, and the cap chip is `capped:sources-disagree`.
  - `asked_at` = `asked_at=`, else `world.meta.known_at` (onboarding), else the history horizon. `remind_at` = +3 h (`questions.remind_at`).

## Learns strip

- **Items, in order:**
  1. `Read {M} months of claims history` (support `{n} past decisions`). M is the long-haul curve's `observed_through_month` (18), else the span of the case dates.
  2. `{ultimate}% of owed long-haul passengers claim (expected ultimate claim rate: history to M18 + tail judgment)` (support `curve LH-v1`). The qualifier comes from the wording table (§9: never "learned 35%" alone).
  3. One line per mined proposal: `Takes the 50% reroute cut (Art. 7(2)) when a reroute arrives within the band's limit`, support `41 of 42`, `rule_ref R-MINED-REDUCE@1`. A contradicted rule's line adds "· written policy disagrees: asked the Controller".
- **Where the curve comes from:** `curve_lookup(segment)` (e.g. `BooksAPI.curve`) if given. A lookup that raises or returns nothing falls back to `contracts/fixtures/golden/curves.json` (read once, cached), so the strip never breaks on Books. Only long-haul is shown: it is the hero cohort.
- **The routing line is omitted.** The stub's fourth line ("Asks Legal about…") is not mined, and the strip's Escalates card comes from `questions`.

## Determinism

- Cases are sorted canonically before anything else, and every output list is sorted. Ids, the horizon and the exceptions are derived from sorted data. `mine_rules`, `contradictions` and `learned_items` are therefore byte-identical under any permutation of `history_cases` (hypothesis, `max_examples=50`) and on repeated runs.
- No `anthropic`, no `now()`, no `random`. `engine/tests/test_purity.py` scans `miner.py` like every other engine file.
