# Filip integration requests

## F9 calibration promotion gate — 24 October 2026

The fitted cause candidate (train Jul 2023–Dec 2024; held out Jan–Jun 2025) is in `eval/cache/calibration.json`. Installing it directly at runtime `data/calibration.json` fails the unchanged `test_fake_engine_matches_expected_decisions`, `test_fake_engine_storm_numbers`, and CP1 smoke (NS31 confidence 0.4332, missing voucher calibration, an extra Ops question). It is therefore **not promoted**; existing runtime priors and golden expectations are preserved.

Please resolve the confidence-contract/promotion criteria before enabling the fitted candidate. The candidate exposes limited training coverage; it is not valid to tune against the held-out golden answer just to reach the required 0.90 score. Voucher/release/claim-validity models remain explicitly uncalibrated until feature/outcome rows exist.

`engine.miner` is still absent at the inspected upstream commit; proof replay supplies the historical Art.7(2) fixture policy explicitly and does not claim mining was tested. The real plain-Claude baseline needs the user's API key; nine batch requests can be prepared with `python -m eval.baseline --prepare` without network calls.
