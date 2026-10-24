# StormCheck measured proof

calibrated on synthetic labels; validates the pipeline, not the world.

Run `LLM_MODE=offline STORMCHECK_MODE=offline python -m eval.run --from-cache` to reproduce the report.
Run without `--from-cache` to regenerate the world and execute the real engine on the pinned corpus.

## Held-out results

- Test period: January–June 2025; 4 storm days plus background days.
- Cancelled-flight coupon denominator: 17,593 passengers, including curated golden scenarios.
- Passenger straight-through: 28.02%. A coupon counts only when its flight is auto and it has no held/ruling entitlement or coupon question.
- Cause **and** extraordinary classification exact accuracy: 48.42%.
- Curated golden cancellations: 31; generated cancellations (including controlled plants): 64. Accuracy on the generated subset alone: 28.12%. Simulated plants and curated examples cannot establish broad generalization.
- Latent internal-AOG weather miscodes caught: 7/9; underlying face cash entitlement €341,600.00.
- False flight holds: 40; an escalated flight whose latent key does not require an authority ruling.
- Initial engine estimate: €826,616.00; latent net entitlement × segment ultimate rates: €578,650.00.
- Valid claimed face amounts observed through 30 June 2026: €438,575.00. This is an observed development horizon, not the final actual outcome.

## Control replay and accounting phase

Three independent real Engine + TraceStore + Books runs produced **€34,650 × 3**, with identical canonical decision/accounting hashes: `4006d5c9a106053e99a5da5237e799af50d68db40a8ea16f20b87c96b33a4bd9`.
Before the simulated Legal ruling the estimate is **€82,146**, including held knock-ons. €34,650 is the estimate **after** that ruling; it must not be described as the whole storm's initial estimate.
The replay supplied the historical Art. 7(2) reduction policy explicitly. It does not benchmark automatic policy mining or LLM rule drafting.
After confirmed Q1/Q2/Q3 rulings, repeated questions: 0. The EU-departure voucher rule settled 31 new coupons; the non-EU departure still produced 1 question. Out-of-scope automatic applications: 0. The Controller replay kept the €3,600 Isha tail; an unconfirmed proposal to widen its scope was not activated.

## Calibration and model comparison

Logistic models fitted only on training rows: cause.
The fitted candidate is in `eval/cache/calibration.json`. It is **not promoted** to `data/calibration.json`: it fails unchanged golden/demo confidence checks (NS31 below the required confidence, uncalibrated voucher confidence, an extra Ops question). The demo keeps its existing priors. No confidence threshold or expected fixture was weakened.
Each fitted kind has five held-out reliability bins with counts and Wilson 95% intervals in `proof.json`. Missing kinds remain explicitly uncalibrated; empty bins are not evidence of accuracy.
Plain-Claude baseline: **not_run_missing_credentials**, 0 completed runs. No live API key was available. There is no measured claim that Claude is less accurate or nondeterministic. `python -m eval.baseline --prepare` writes the nine matched-input requests; `--live` runs through the shared capped Batches wrapper when credentials are supplied.
Reader prompt-injection regression: 2/2 facts-only results against **hand-written** cache recordings. This tests validation and wiring, not live model resistance.

## Coverage limits

- Cause calibration only: voucher, release and claim-validity correctness datasets are not fitted.
- The supplemental stress corpus has five input cases per error type per split (140 total); it is separate from natural-world accuracy and is not yet a full scored end-to-end claim benchmark.
- The fitted candidate fails golden/demo confidence acceptance and has not been promoted to runtime data/calibration.json.
- Repeat-question and scope metrics cover the explicit golden Q1/Q2/Q3 replay, not every held-out flight.
- Historic reduction policy is supplied, not learned by the unfinished policy miner.
- No paid baseline or live model outputs were available; CP3 is not complete.
Ambiguous generated cancellations by split (the shared world's hidden faults and knock-ons): {'test': {'ambiguous': 7, 'non_golden_cancelled': 64}, 'train': {'ambiguous': 25, 'non_golden_cancelled': 394}}.
The fitted cause model is synthetic development data, not a production guarantee. All outputs remain drafts requiring the repository's existing role approvals.

Input manifest: `cache/manifest.json`. Metric inputs and controls: `cache/results.json`. Independent answer keys: `data/answer_key/`. No labels are copied from engine decisions.
