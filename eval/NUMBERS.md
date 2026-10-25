# StormCheck measured proof

calibrated on synthetic labels; validates the pipeline, not the world.

Every number below is computed by `python -m eval.run` from the pinned corpus. Reproduce it offline with `uv run python -m eval.run --from-cache`; `uv run python -m eval.run --check` fails if anything drifted.

## Headline: held-out January–June 2025 (never seen in training)

95 cancelled flights on 4 storm days plus background days (31 curated golden, 64 generated; 17,593 passengers). Every flight lands in exactly one outcome class:

| Outcome class | Flights | Generated only |
|---|---:|---:|
| Auto-correct: settled with no person, and right | 47 | 19 |
| Correct escalation: held for the person the answer key names | 5 | 2 |
| Conservative escalation: held although the key needs no person, or held for another role (costs straight-through; not an error) | 35 | 35 |
| **Auto-wrong**: settled with no person, and wrong (the dangerous class) | 8 | 8 |

**Auto-precision 85.5%**: of 55 flights settled with no person, 47 were right and 8 wrong. Generated flights only: 70.4% (8 wrong).

Straight-through, reported separately: **58.63%** of passengers (the flight is automatic and the coupon has no hold or question); 57.9% of flights. It measures routing, not correctness.

Ambiguous by design: **7** flights are feature-invisible (hidden crew faults, unrecorded AOGs and their knock-ons). They are counted inside the classes above; 2 of them are auto-wrong.

Plain Claude on the same raw documents (claude-opus-5-5, effort medium, 3 identical runs): on Éowyn (2025-01-24) it scored 77.8% / 77.8% / 100.0% and estimated €34,650 / €82,146 / €34,650, `hash_identical=false`. StormCheck on the same flights: 100.0%, €82,146 / €82,146 / €82,146, `hash_identical=true`. The answer key's latent entitlement × expected ultimate claim rate is €34,650; StormCheck's initial estimate accrues the flights it holds for a ruling. Every storm is in “Plain Claude vs StormCheck” below.

## Detail

Right or correctly escalated: 54.7% of all, 32.8% of generated. Strict cause **and** extraordinary equality with the key (an escalation counts as a miss): 57.9%.

Why flights were not auto-correct (`miss_class`, examples in `cache/results.json`):

| Class | n | generated | examples |
|---|---:|---:|---|
| ambiguous_by_design | 7 | 7 | NS102@2025-02-23, NS148@2025-02-23, NS149@2025-02-23 |
| auto_wrong | 6 | 6 | NS108@2025-01-30, NS166@2025-02-26, NS118@2025-03-30 |
| escalated_correct | 5 | 2 | NS113@2025-01-24, NS117@2025-01-24, NS115@2025-01-24 |
| held_batch_review | 7 | 7 | NS100@2025-02-17, NS150@2025-02-22, NS71@2025-04-21 |
| held_external_event_no_precedent | 1 | 1 | NS157@2025-01-30 |
| held_other | 16 | 16 | NS51@2025-02-17, NS144@2025-02-23, NS146@2025-02-23 |
| held_window_edge | 6 | 6 | NS41@2025-02-15, NS108@2025-02-23, NS152@2025-02-23 |

`held_window_edge` (a weather code just outside the strict window → Ops) and `held_external_event_no_precedent` (only Legal settles a new legal pattern) are deliberate conservative escalations.

- Miscodes caught: 9/9 latent internal AOGs typed as weather were not accepted as weather (4 recoded automatically); face cash entitlement €430,125.00.
- Conservative escalations (`held_other`, reported as `false_holds`): 35.
- Refund drafted for an unsigned, non-web voucher election: 288 coupons, €75,765.00. The key says no refund is due there; the engine treats a voucher as agreed only with a signed acceptance or a web self-service election (Art. 8(1)(a) via 7(3)). That is deliberate legal conservatism, reported as its own category and not as an error. Other coupon refund disagreements: 1662.
- Repeat questions after a ruling, across all held-out days in date order: **0**. Rulings applied from the morning first asked: R-CTL-1@1 (2025-01-24), R-LEG-1@1 (2025-01-24), R-CL-1@1 (2025-01-24). Settled by them in their ground-truth scope: 42; out-of-scope automatic applications: **0**.

### Liability vs actual (generated held-out cohorts, train-learned € curves)

| Month | Expected claims (accrual × curve) | Valid claims received | A/E |
|---|---:|---:|---:|
| M1 | €170,997.17 | €126,450.00 | 0.740 |
| M3 | €320,540.04 | €239,700.00 | 0.748 |
| M6 | €454,135.40 | €337,325.00 | 0.743 |

Initial EU261 compensation liability estimate (all held-out flights): €798,038.00; latent net entitlement × segment expected ultimate claim rates: €578,650.00; valid claims observed through 30 June 2026: €438,575.00 (a development snapshot, not the final outcome).

## Same input, same answer

- StormCheck ×3 on 2025-01-24 (27 cancelled), fresh process each: €82,146 / €82,146 / €82,146, same hash `ff1b12de83728efd…`.
- StormCheck ×3 on 2025-01-26 (4 cancelled), fresh process each: €54,180 / €54,180 / €54,180, same hash `c1af4427b7d5e2de…`.
- StormCheck ×3 on 2025-02-26 (14 cancelled), fresh process each: €92,014 / €92,014 / €92,014, same hash `5757b7f52fbbbb72…`.
- Golden control replay (real Engine + TraceStore + Books, scripted Claims Lead/Legal/Controller rulings): **€34,650 ×3, same hash** `f468e14e120590a6…`. Before the Legal ruling it is €82,146 (held knock-ons accrued); €34,650 is after it. The Isha tail kept: €3,600.

### Plain Claude vs StormCheck on the same raw documents

Plain Claude: `claude-opus-5-5`, effort `medium`, adaptive thinking, structured output, through the Batches API. It gets the operational documents StormCheck reads (schedule, OCC/MCC/spares lines, tech log, raw METAR at both ends, PII-free PSS coupon lines) and the same supplied policy, and is asked for cause, extraordinary status and the initial € EU261 compensation liability per cancelled flight. Three byte-identical requests per storm. Phase: the initial estimate before any human ruling, the same phase as StormCheck ×3.

Scoring, the same rule for both: cause (root-aware) and extraordinary status must match the answer key; a `needs_legal` answer counts as right when the key routes the flight to a person. StormCheck's accuracy is its initial output in the held-out replay, which on later storms already applies rulings made on earlier days; plain Claude gets only the supplied policy.

| Storm | Flights | Plain Claude accuracy (3 runs) | StormCheck accuracy | Plain Claude € (3 runs) | StormCheck € (×3) | Answer key € (latent entitlement × expected ultimate claim rate) | Plain Claude same hash? |
|---|---:|---:|---:|---:|---:|---:|---|
| Éowyn (2025-01-24) | 27 | 77.8% / 77.8% / 100.0% | 100.0% | €34,650 / €82,146 / €34,650 | €82,146 / €82,146 / €82,146 | €34,650 | no |
| Herminia (2025-01-26) | 4 | 75.0% / 75.0% / 75.0% | 100.0% | €74,052 / €74,052 / €74,052 | €54,180 / €54,180 / €54,180 | €54,180 | yes |
| 2025-02-26 | 14 | 21.4% / 21.4% / 28.6% | 50.0% | €172,202 / €172,202 / €392,500 | €92,014 / €92,014 / €92,014 | €94,716 | no |

`proof.json` `baseline.hash_identical` is the Éowyn (2025-01-24) value, as the F9 spec asks. Requests, model ids, usage and request records: `cache/baseline_requests.json`, `cache/baseline_results.json`.

## Calibration (one logistic model per Confidence.kind)

Label: the engine settled the item alone and correctly per the answer key (an abstention is 0). Fitted on train only; C chosen by 5-fold grouped CV log-loss on train.

| Kind | trained on | n (train) | C | held-out n | coverage@0.9 | accuracy@0.9 |
|---|---|---:|---:|---:|---:|---:|
| cause | 2023-07-01..2024-12-31 | 394 | 10.0 | 95 | 0.453 | 42/43 |
| claim_validity | 2023-07-01..2024-12-31 | 4699 | 100.0 | 1562 | 0.181 | 278/283 |
| release | prior | 0 | — | 0 | 0.000 | — |
| voucher | 2023-07-01..2024-12-31 | 24 | 1.0 | 67 | 0.299 | 20/20 |

Bins: five per kind at the routing thresholds (0.60 / 0.75 / 0.90 / 0.97), with n and Wilson 95% intervals, in `proof.json`.

**Not promoted**: the runtime keeps `engine/default_calibration.json`, and the held-out routing numbers above use it. The candidate (`eval/cache/calibration.json`, cal-synthetic-v2-3d59393a4a73) breaks 15 golden confidence band(s):

  - real NS118@2025-01-24.outcome: 'human' != 'auto'
  - real NS118@2025-01-24.routed_to: 'ops' != None
  - real NS118@2025-01-24.confidence 0.897 outside {'min': 0.9}
  - real NS41@2025-01-24.outcome: 'human' != 'auto'
  - real NS41@2025-01-24.routed_to: 'ops' != None
  - real NS41@2025-01-24.confidence 0.8988 outside {'min': 0.9}
  - real NS51@2025-01-24.outcome: 'human' != 'auto'
  - real NS51@2025-01-24.routed_to: 'ops' != None
  - real NS51@2025-01-24.confidence 0.8958 outside {'min': 0.9}
  - real NS114@2025-01-26.outcome: 'human' != 'auto'
  - real NS114@2025-01-26.routed_to: 'ops' != None
  - real NS114@2025-01-26.confidence 0.8903 outside {'min': 0.9}

## Injections and hostile input

- 8 rehearsed injections through the real `llm.reader` (hand-written recordings) and the engine: 8/8 had the expected effect, 8/8 blocked or escalated, 0 automatic flips, 0 approvals. Injection emails: 2 facts-only, 0 unsafe.
- 20 hostile/fuzz inputs (regex fallback, no recording): 0 errors, 0 automatic flips.

## Stress corpus (controlled regressions, separate from the natural-world numbers)

120/140 cases pass end to end (engine → entitlements → Books claims).

| Error type | train | test |
|---|---:|---:|
| agency_without_authority | 5/5 | 5/5 |
| assignment_then_direct_payment | 5/5 | 0/5 |
| claim_after_limitation | 5/5 | 5/5 |
| concurrent_causes | 0/5 | 5/5 |
| duplicate_claim | 5/5 | 5/5 |
| duplicate_refund | 5/5 | 5/5 |
| knock_on_return | 5/5 | 5/5 |
| manifest_mismatch | 5/5 | 5/5 |
| miscoded_technical | 5/5 | 0/5 |
| notice_14_days | 5/5 | 5/5 |
| prompt_injection | 5/5 | 5/5 |
| staff_id90 | 5/5 | 5/5 |
| unsigned_voucher | 5/5 | 0/5 |
| wrong_regime | 5/5 | 5/5 |

## Coverage limits

- Ambiguous (feature-invisible) generated cancellations: test 7/64 (10.9%), train 25/394 (6.3%) (plan target ~5%).
- Release has no train-split proposals (Isha reaches M12 in January 2025), so it runs on the shipped prior.
- Claim validity has no engine consumer yet; it is fitted on the CONTRACTS x-encoding and reported only.
- The historical Art. 7(2) reduction policy is supplied as a fixture rule, not mined.
- Rulings in the held-out replay are the plan's scripted words, drafted into rules by the engine's deterministic template drafter (not the LLM Drafter).
- The rehearsed-injection Reader outputs are hand-written recordings: this tests validation and wiring, not a live model's resistance.

Input manifest: `cache/manifest.json` (sha256 of every source module in world/, engine/, books/, eval/, contracts/, llm/, the demo recordings, keys and pinned data). Metric inputs: `cache/results.json`. Independent answer keys: `data/answer_key/`. No label is copied from an engine decision.
