# Evaluation decisions

## 24 October 2026 — measured, reproducible and gated

- Train July 2023–December 2024, score January–June 2025. The runner calls the real `Engine.run_storm` on every represented day, including background days and days without cancellations. Days without cancellations add no coupons to the denominator. Storm-day counts come from the world metadata.
- Per-flight cause/extraordinary labels and per-coupon amounts originate in the team's shared latent world truth. The evaluator expands the compact key in memory, retaining its default/exception semantics and claim coverage. Committed train/test keys and learned curves retain the upstream format. Golden coupon truth comes from immutable fixture facts and explicit fixture policy. The engine never writes its answer key.
- Straight-through is passenger weighted over cancelled-flight coupons: the flight must be auto, entitlement must not be held/needs-ruling, and the coupon must not have an open question. This measures routing, not necessarily correctness. Exact classification accuracy is shown separately.
- Wrong weather codes are counted only on latent internal AOGs, and a catch requires both a recode and the correct cause/extraordinary result. The associated amount is net face cash entitlement, not proven savings.
- Initial preview versus ultimate expectation uses the same 20/27/35% segment rates but independent latent net entitlements. Claimed amounts are a development snapshot through June 2026, not a final realized loss. These denominators and phases must be retained in presentations.
- Golden control replay uses real Engine/TraceStore/Books and explicit simulated human Q1/Q2/Q3 rulings, with the supplied historical reduction policy. Its pre-Legal estimate is €82,146; its post-Legal estimate is €34,650. The Controller keeps the Isha tail and an unconfirmed widening proposal remains inactive. The three-run hash covers canonical decisions, before/after accounting balances and scope outcomes, not randomized sessions or database bytes. It does not claim the unfinished miner or LLM Drafter produced the rules.
- The cause calibration candidate is trained on exact cause AND extraordinary correctness, logistic only, with held-out bins/Wilson intervals. Voucher/release/claim-validity remain uncalibrated rather than fabricating labels or fits. The candidate is at `eval/cache/calibration.json`, not runtime `data/calibration.json`: replacing runtime priors caused three unchanged acceptance failures. The acceptance suite was preserved. Promotion needs a compatible confidence contract and better training coverage.
- Stress corpus: 14 error types × five variants × two splits = 140 explicit schema-valid input worlds, with private expected actions outside `World`. Real pinned weather remains unchanged. This controlled regression set is separate from natural-world accuracy, not 140 independent weather observations. Assignment/direct-payment events are represented as dated finance/claim sources and metadata because World has no typed settlement-notification field. No live payments are executed.
- No API key was available. Baseline status is not-run, not an invented Claude score/spread. `eval.baseline` prepares matched raw inputs, three independent cache keys per storm, and uses the existing capped batch wrapper for a later live run. It rejects missing/duplicate flights in scoring and retains actual provenance, models, request IDs and errors. Its phase is before human rulings, unlike the €34,650 replay.
- Reader injection checks use the existing hand-written cache recordings. They are validation/wiring regressions, not measurements of a live model's injection resistance.
- `eval/cache/manifest.json` hashes metric inputs, independent keys, source modules, dependency lock and pinned data. Cache replay verifies these before writing `proof.json`/`NUMBERS.md`.

## Completion boundary

World F3d and answer-key export are implemented. F3c has explicit error-input coverage and deliberately unobservable natural-world cases in both splits; a full end-to-end score for every claim/assignment error still requires integration. F9 has actual held-out cause metrics, candidate calibration and accounting/control replay. CP3 remains incomplete until genuine model baseline results and the other confidence-kind datasets exist. Model/Drafter/book extensions already assigned elsewhere are not duplicated here.

The held-out figures explicitly separate curated golden cancellations from generated cancellations (which include controlled plants). Including the golden story or controlled plants must never be presented as independent market validation. On integrating upstream 61db69d, the shared generator's planner replaced the local experimental ambiguity draw: it supplies feature-invisible crew faults, unrecorded AOGs and their knock-ons, with unchanged real weather and latent labels. Legacy 2017/18 flights exercise limitation handling but are excluded from 2023–25 cause calibration and test metrics. No upstream acceptance test was weakened during integration.

The exact cause-and-extraordinary accuracy compares the initial output to final latent truth. An unresolved `needs_legal` output counts as a non-match even when routing it to Legal is the correct workflow; the number combines abstentions and misclassifications. It must not be presented as an autonomous error rate.

## PR #6 merge into main: proof regenerated on the merged tree (integration agent)

- Main changed four files after Filip's 61db69d base: `contracts/normalize.py`, `engine/case.py`, `engine/cause.py` and `engine/questions.py`, which add the evidence links. All four are hashed in `cache/manifest.json`, so `eval.run --from-cache` refused to run on the merged tree ("Input hash mismatch").
- We re-ran `LLM_MODE=offline STORMCHECK_MODE=offline python -m eval.run` (full, not cached) on the merged tree. Then we re-ran `--from-cache` so NUMBERS.md comes out in the canonical form. The two runs order the `world_diagnostics` dict differently.
- Results:
  - Every scored row, calibration row, fitted model and answer-key file is byte-identical, and so is every metric in `proof.json` and `NUMBERS.md`.
  - The only change is the three-run canonical replay hash, from `df4e925b…` to `4006d5c9…`. It is still identical across all three runs and still €34,650 × 3.
  - On Filip's own tree, `replay_three` still gives `df4e925b…`. So the change comes from the new decision content on main, not from nondeterminism.
- Nothing was hand-edited. The regenerated `results.json`, `manifest.json`, `proof.json` and `NUMBERS.md` are committed.

## F9 finish (filip-agent/f9-finish), 24 October 2026

1. **Calibration label = "settled alone and right".** y = 1 iff the engine's finding is settled (not `needs_legal`; `needs_ruling` for vouchers) and it matches the key. An abstention is 0.
   - Routing reads the score as exactly this probability: ≥ 0.90 may run with no person.
   - The golden contract requires it: knock-on returns sent to Legal must score < 0.60 (`expected/decisions.json`), and Q-1 and Q-2 < 0.60.
   - The alternative, "a correct escalation = 1", would put Q-2 near 100% while it asks Legal. That contradicts the fixture and the product.
2. **Cause match carries the root.** A knock-on of an internal root (AOG, crew, notice, concurrent) and that root's own cause name the same obligation (C-74/19). `technical` therefore matches a key `knock_on` whose root is internal, and vice versa. Extraordinary status must still match exactly.
3. **Four outcome classes** (coordinator, 24 Oct): `auto_correct`, `auto_wrong` (the dangerous one), `escalated_correct` (held for the key's `expected_route`) and `held_other` (costs straight-through, not an error).
   - The headline is auto-precision, with straight-through reported separately.
   - "Ambiguous by design" is its own line.
   - `false_holds` = `held_other`.
   - Batch review (`outcome="human"`) counts as held.
4. **Deliberate conservatism** is labelled, never called an error:
   - `held_window_edge`: a weather code 28–45 min outside the strict window → Ops;
   - `held_external_event_no_precedent`: only Legal settles a new legal pattern;
   - a refund drafted for an unsigned, non-web voucher election. It gets its own coupon count and € amount.
5. **Regularisation is chosen on train only.** The grid is C ∈ {0.01, 0.1, 1, 10, 100, 1000}, scored by 5-fold `GroupKFold` log-loss with world days as groups.
   - The grid was fixed before looking at any golden result.
   - The golden promotion gate is pass/fail only and never feeds back into C or the features.
6. **Kinds without usable train rows keep the shipped prior** (`trained_on: "prior"`, `n: 0`, with the train row counts in `metrics`).
   - Release has no train-split proposals: Isha reaches M12 in January 2025.
   - In train, every in-lieu voucher is unsigned and asked, or signed and offset, so vouchers can be one-class until rulings exist. The prior then stays.
   - Claim validity is fitted on the CONTRACTS x-encoding against the key's `valid`. It has no engine consumer.
7. **Promotion gate.** `eval.calibration.acceptance` replays the golden expected decisions and question bands with the candidate file, for the real engine (every golden storm) and for FakeEngine (the contracts tests). The candidate goes to `data/calibration.json` only when the problem list is empty.
   - The full test suite and `make smoke-1` are then run by hand before committing.
   - When the candidate is not promoted, the held-out routing numbers use the runtime prior, because that is what ships.
8. **Held-out replay with rulings.** Held-out days run in date order. When the plan §1.4 patterns (voucher, knock-on, cohort release) are first asked, the plan's words become a rule, drafted by the engine's own deterministic `template_rule` and active from the same morning (known_at + 2 h).
   - Repeat question = a later question with a ruled pattern that has a case inside the ruling's ground-truth scope (from the key and the World, never the engine).
   - Out-of-scope auto = a settlement citing the ruling on a case outside that scope.
   - Train days never see a ruling.
9. **Reliability bins** are cut at the routing thresholds: 0.60 / 0.75 / 0.90 / 0.97. All five bins are kept, and an empty bin reports n = 0 with the whole [0, 1] Wilson interval. Each bin carries `mean_score`.
10. **StormCheck ×3** runs on Éowyn, Herminia and 2025-02-26 (the held-out storms with the most interest; 2025-02-23 is scored too). Each run is a fresh interpreter with PYTHONHASHSEED 1..3 that regenerates the world from the seed. The hash is the canonical sha256 of the whole StormRun. It is the initial estimate before any ruling, the same phase as the baseline. The €34,650 ×3 golden replay is kept, labelled as after the rulings.
11. **Baseline inputs carry no PII.** Operational sources only (schedule, OCC, MCC, tech log, spares, regulation, manufacturer), plus PII-free PSS coupon lines: seat, fare type, channel, election, delay, in-lieu voucher amount and signed flag, bot refund.
    - Excluded: PSS/manifest extracts (they carry PNRs and `pax_ref`) and claim/email/CRM free text.
    - The three replicates are byte-identical requests with distinct cache keys (`prompt_version` run-k).
    - "Pending" is the status until genuine `live-batch` results exist. Hand-written, scripted or offline responses never count.
12. **Injections** run end to end: the real `llm.reader` (offline; the rehearsed docs replay hand-written recordings, and fuzz inputs take the regex fallback) feeds `Engine.decide` on golden.
    - `inj01` must escalate to Legal; the other seven must leave the decision unchanged.
    - An automatic flip is the failure mode.
13. **The stress corpus** (140 cases) runs Engine → entitlements → Books post_storm/post_claim. Each case is checked against the generator's own expectation, and the score is reported apart from the natural-world numbers.
    - `duplicate_refund` is judged on INV-4/INV-4b and GL 2125 only. INV-7b fails on every mini-world, because there is no lifecycle commit to link.
    - Known case-design issue: the `knock_on_return` cases put the return's STA inside the DUB window, so the engine calls it weather. The case is not "calm at both ends" as its docstring claims. It is reported, not fixed (world/ is not this lane).
14. **`--check`** = manifest freshness (now also llm/ and the demo recordings) plus a byte-compare of `proof.json`/`NUMBERS.md` against a rebuild from the cache. It is fast, and smoke-3 can call it. `--check --full` also reruns everything and byte-compares. pytest does not fail on an engine change, so David's agents are not blocked.
15. **Legacy shim.** `report_from_cache` reproduces an `eval-v1` cache with Filip's original equal-width bins, so the committed v1 proof stays reproducible until the single final regeneration (eval-v2).

## Live Claude runs and the final proof (filip-agent/live-proof), 24–25 October 2026

1. **`--check` never crashes.** A cache that predates the code (no `version`, `eval-v1`, or an `eval-v2` tag with an
   older shape), a missing cache or a missing manifest is reported as "stale proof: regenerate" with exit 1. So is
   `--from-cache` on such a cache. Only the first 10 changed inputs are listed.
2. **Plain-Claude baseline, run live** (`eval.baseline --live`, one capped batch, 9/9 genuine `live-batch`
   results, about $3.40). `max_tokens` went from 16,000 to 32,000 before the run, because adaptive thinking counts
   toward it. One 2025-02-26 run used 25,591 output tokens and would have been cut off at 16,000. `max_tokens` is not
   in the cache key.
3. **Baseline scoring.** One function (`baseline.right`) scores plain Claude and StormCheck's initial held-out output
   on the same flights. Per storm, the summary also carries StormCheck's preview € and the key's latent entitlement ×
   expected ultimate claim rate. StormCheck's accuracy comes from the held-out replay, which on later storms already
   applies earlier rulings; NUMBERS.md says so. `baseline.hash_identical` in proof.json is the Éowyn value (F9 spec);
   every storm's value is in `baseline.storms` and the NUMBERS table. The result is reported whatever it is.
4. **`test_proof`** asserted the pending state (`runs == 0`, `hash_identical is None`). It now asserts what makes a
   published baseline legitimate: either nothing is claimed, or status complete with 3 runs, a boolean
   `hash_identical` and 9 genuine `live-batch` records (`claude-opus-5-5`, a real message id, output tokens > 0).
5. **Live Reader/Drafter recordings were not adopted.** Re-recorded live into a scratch dir (32 Reader + persona, 11
   Drafter; under $1). With them swapped into `data/cache/demo/`, 20 llm tests fail, so the hand-written recordings
   stay. The live outputs and fact-level comparisons are kept in `cache/live_recordings/` for reference:
   - Reader: 23 of 29 documents give exactly the hand-written facts, and every kept span is verbatim. The 8 golden
     documents also fail `provenance == "hand-written"`. Real differences: `techlog_ns31` and inj01 lose `station`
     (live span "STN DUB" fails the verifier, so it is dropped), `defect_text` keeps a trailing period, `bot_mail_3a`
     misses `crm.rights_email_sent`, the MCC forward quotes a different verbatim defect phrase, the OCC handover adds
     two warning facts, and the CRM bot template quotes the refund sentence too.
   - Drafter: every draft is `numbers_verified`, with no template fallback. It still differs from the tests: Q-1's rule
     drops the `voucher.in_lieu` condition, Q-2's condition differs, the challenge reply omits "16:30Z", the explain
     test fails, and the corrected rights notice lacks "That was wrong".
   - Personas: Q-1 and Q-3 chose options other than the scripted ones.
   - No test was changed to fit. No recorded file contains an API key (grep `sk-ant-`: 0 files).
