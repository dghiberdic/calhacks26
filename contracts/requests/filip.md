# Filip integration requests

## F9 held-out miss decomposition: engine classes for David (24 October 2026, filip-agent/f9-finish)

Measured on main c30a7de (engine as of PR #6 merge), seed 0, held-out January–June 2025: 95 cancelled flights (31 curated golden, 64 generated). Filip's metric "cause AND extraordinary equal the latent key" scored 46/95 (48.4%; generated 18/64). We split the 49 misses as follows:

| Class | n | Owner | Fix |
|---|---|---|---|
| (a) scoring: knock-on of an internal root, decided `technical` (both not extraordinary, same money) | 4 | eval | count as a match (C-74/19: the root cause carries) |
| (b) correct escalation scored as wrong: knock-on of a storm-cancelled outbound → Legal (key `expected_route=legal`) | 8 | eval | an escalation to the key's route is a correct outcome |
| (b) correct escalation scored as wrong: concurrent AOG + storm → Legal | 5 | eval | same |
| (b) ambiguous by design (feature-invisible crew/unrecorded-AOG cases and their knock-ons) | 7 | world (by design) | remain misses, reported separately |
| (c) E1 window edge | 6 | engine | below |
| (c) E2 AOG logged inside an *earlier* window makes later out-of-window sectors "concurrent" | 6 | engine | below |
| (c) E3 AOG logged *after* the flight was already cancelled is used as its cause | 2 | engine | below |
| (c) E4 notice ≥ 14 days escalated to Ops | 10 | engine | below |
| (c) E5 bird strike (settled law, C-315/15) escalated to Legal "no precedent" | 1 | engine/rules | below |

After fixing (a) and (b) in eval/: 63/95 (66.3%) are right or correctly escalated, and 32/64 generated. All 31 golden cancellations are right. The train split shows the same classes at larger n: E1 alone covers 56 of 394 train flights (37 `weather_code_contradicted` plus 19 return sectors decided "knock-on → Legal" whose key is weather).

- **E1 window edge (6 test; 56 train).** The flight is weather-coded, and its STD/STA lies 28–45 min outside the strict window. The engine decides `unknown/needs_legal`, pattern `weather_code_contradicted`, and sends it to Ops. The key says weather/extraordinary: the generator's latent weather (world/causes.py `severity`) uses observations within ±45 min of STD/STA, by design ("a sector at its edge can be cancelled"). Examples:
  - `NS108@2025-02-23` DUB–BCN, STD 08:15, EIDW window 05:30–07:30 (margin 45 min);
  - `NS152@2025-02-23` STD 09:30, window from 10:00 (30 min);
  - `NS41@2025-02-15` STA ORD 20:55, KORD window ends 20:27 (28 min).

  Expected: weather/extraordinary, auto or batch review. Actual: Ops question. Suggestion: the spec's own tolerance for `unknown` is ±60 min. Treat a weather code within 60 min of a window edge as weather, with confidence carried by `window_margin_h` and no `sources_disagree`, instead of an Ops escalation.
- **E2 earlier-window AOG → concurrent (6).** `find_cause` returns `concurrent` when `aog.inside_window`, even when the flight itself is out of the window at both ends hours later. The defect is internal per the ATA table. Examples:
  - `NS166@2025-02-23` DUB–FAO, STD 13:40, out at both ends (+130 min). AOG `HPT STG 1 BLADE CRACK` logged 06:50Z inside the 05:30–07:30 window. Expected technical/not_extraordinary (OCC already coded it 41). Actual concurrent → Legal.
  - `NS169@2025-02-23` DUS–DUB 16:45, AOG 07:15Z. Expected not extraordinary (knock-on of an internal AOG). Actual concurrent → Legal.
  - `NS135@2025-02-26` MAN–DUB 18:25, AOG 15:55Z.

  Suggestion: count as concurrent only when the flight itself is in a window at either end (or the defect's ATA class is external/weather-related).
- **E3 post-cancellation AOG (2).** In `NS145@2025-02-23` BHX–DUB, the flight was in the 06:30Z OCC weather batch (RSN 71). The tail's AOG was logged 06:50Z, after the cancellation decision. The engine calls it concurrent → Legal; the key says weather. The second case is `NS147@2025-02-23`. Suggestion: ignore AOGs logged after the flight's OCC cancellation time as causes of that flight.
- **E4 notice ≥ 14 days (10: 5 outbounds plus their returns).** Examples are `NS108@2025-01-30`/`NS109@2025-01-30`, `NS118@2025-03-30`/`NS119@2025-03-30` and `NS108@2025-04-21`. The OCC line says `RSN 09 · SCHEDULE CHANGE (A/C … HEAVY CHECK)`, notified 30 days before. The engine decides the outbound `cause_unknown → Ops` and the return `knock_on (undecided) → Ops`. Art. 5(1)(c)(i) exempts compensation whatever the cause, so the key routes neither to a person. Suggestion: when every coupon's `pax.notice_days ≥ 14`, settle automatically (no compensation; refunds and care still due) and don't open an Ops question. Optionally map code 09 (schedule change) to a known group.
- **E5 bird strike (1).** `NS157@2025-01-30` ARN–DUB (`BIRD STRIKE ON APPROACH`) goes `external_event → Legal`, "no precedent", score 0.50. The key says technical/extraordinary with no route (C-315/15 is settled CJEU law). A regulation-tier card for bird strikes would settle these; otherwise they stay false holds.

Ambiguity quota (Filip's open item): generated cancellations flagged ambiguous are train 25/394 (6.3%) and test 7/64 (10.9%), against the plan's ~5%. Knock-ons of ambiguous roots inherit the flag, which roughly doubles the count. This sits in world/ (plant.py `ambiguous_target`); eval only reports it.

## F9 calibration promotion gate — 24 October 2026

The fitted cause candidate (train Jul 2023–Dec 2024; held out Jan–Jun 2025) is in `eval/cache/calibration.json`. Installing it directly at runtime `data/calibration.json` fails the unchanged `test_fake_engine_matches_expected_decisions`, `test_fake_engine_storm_numbers`, and CP1 smoke (NS31 below the required confidence, missing voucher calibration, an extra Ops question). It is therefore **not promoted**; existing runtime priors and golden expectations are preserved.

Please resolve the confidence-contract/promotion criteria before enabling the fitted candidate. The candidate exposes limited training coverage; it is not valid to tune against the held-out golden answer just to reach the required 0.90 score. Voucher/release/claim-validity models remain explicitly uncalibrated until feature/outcome rows exist.

`engine.miner` is still absent at the inspected upstream commit; proof replay supplies the historical Art.7(2) fixture policy explicitly and does not claim mining was tested. The real plain-Claude baseline needs the user's API key; nine batch requests can be prepared with `python -m eval.baseline --prepare` without network calls.
