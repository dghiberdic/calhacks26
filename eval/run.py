"""Run ``python -m eval.run`` to rebuild proof from pinned weather; --from-cache verifies metrics offline."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import orjson

from contracts.models import EvalReport
from engine.confidence import default_calibration
from eval.calibration import LABEL, fit_calibration, reliability
from eval.evaluate import collect, summarize
from eval.golden_flow import replay_three
from world.answer_key import build_answer_key, write_answer_keys
from world.error_cases import CATEGORIES, build_error_cases
from world.generator import generate_world

ROOT = Path(__file__).resolve().parents[1]


def injection_check() -> dict:
    from llm.client import LlmClient
    from llm.demo_inputs import READER_DOCS
    from llm.reader import Reader, ReaderContext

    docs = [d for d in READER_DOCS if d.label in {"messy_injection_email", "inj03_prompt_injection_email"}]
    with TemporaryDirectory() as cache:
        reader = Reader(LlmClient(mode="offline", cache_dir=cache))
        passed = 0
        for d in docs:
            result = reader.read(d.source, ReaderContext(**(d.context or {})))
            passed += bool(result.facts) and all(f.field == "email.asserts_approval" and
                f.subject.startswith("source:") for f in result.facts)
    return {"attempted": len(docs), "facts_only": passed, "unsafe_extractions": len(docs) - passed}


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2) + b"\n")


def report_from_cache(cache: dict, fitted: dict) -> EvalReport:
    rows = cache["scored_rows"]
    bins, coverage = reliability(cache["calibration_rows"], fitted)
    m = summarize(rows)
    return EvalReport(split={"train": "2023-07-01..2024-12-31", "test": "2025-01-01..2025-06-30"},
        n_storms=cache["held_out_storms"], **m, calibration=bins, coverage_at_90=coverage,
        repeat_questions=cache["controls"]["repeat_questions"],
        out_of_scope_auto=cache["controls"]["out_of_scope_auto"],
        baseline=cache["baseline"], stormcheck_runs=cache["replay"], injections=cache["injections"],
        real_vs_simulated={"real": ["pinned METAR observations", "airport coordinates and timezones"],
            "simulated": ["airline, flights, faults, passengers, claims and accounting estimates",
                          "explicit human rulings in control replay",
                          "Reader injection outputs are hand-written recordings, not live model results"]}, label=LABEL)


def numbers(report: EvalReport, cache: dict, fitted: dict) -> str:
    m = report.liability_vs_actual
    status = cache.get("coverage_gaps", [])
    return f"""# StormCheck measured proof

{LABEL}.

Run `LLM_MODE=offline STORMCHECK_MODE=offline python -m eval.run --from-cache` to reproduce the report.
Run without `--from-cache` to regenerate the world and execute the real engine on the pinned corpus.

## Held-out results

- Test period: January–June 2025; {report.n_storms} storm days plus background days.
- Cancelled-flight coupon denominator: {report.n_passengers:,} passengers, including curated golden scenarios.
- Passenger straight-through: {report.straight_through_pct:.2f}%. A coupon counts only when its flight is auto and it has no held/ruling entitlement or coupon question.
- Cause **and** extraordinary classification exact accuracy: {m['flight_cause_and_extraordinary_accuracy']:.2%}.
- Curated golden cancellations: {m['curated_golden_cancellations']:.0f}; independently generated cancellations: {m['non_golden_cancellations']:.0f}. Accuracy on the generated subset alone: {m['non_golden_cause_accuracy']:.2%}. This small generated subset cannot establish broad generalization.
- Latent internal-AOG weather miscodes caught: {report.miscodes_caught}/{report.miscodes_total}; underlying face cash entitlement €{report.miscodes_eur_cents / 100:,.2f}.
- False flight holds: {report.false_holds}; an escalated flight whose latent key does not require an authority ruling.
- Initial engine estimate: €{m['preview_eur']:,.2f}; latent net entitlement × segment ultimate rates: €{m['ultimate_expected_eur']:,.2f}.
- Valid claimed face amounts observed through 30 June 2026: €{m['valid_claims_through_2026_06_30_eur']:,.2f}. This is an observed development horizon, not the final actual outcome.

## Control replay and accounting phase

Three independent real Engine + TraceStore + Books runs produced **€34,650 × 3**, with identical canonical decision/accounting hashes: `{report.stormcheck_runs['hashes'][0]}`.
Before the simulated Legal ruling the estimate is **€82,146**, including held knock-ons. €34,650 is the estimate **after** that ruling; it must not be described as the whole storm's initial estimate.
The replay supplied the historical Art. 7(2) reduction policy explicitly. It does not benchmark automatic policy mining or LLM rule drafting.
After confirmed Q1/Q2/Q3 rulings, repeated questions: {report.repeat_questions}. The EU-departure voucher rule settled {cache['controls']['in_scope_coupons']} new coupons; the non-EU departure still produced {cache['controls']['out_of_scope_questions']} question. Out-of-scope automatic applications: {report.out_of_scope_auto}. The Controller replay kept the €{report.stormcheck_runs['tail_kept_eur'][0]:,.0f} Isha tail; an unconfirmed proposal to widen its scope was not activated.

## Calibration and model comparison

Logistic models fitted only on training rows: {', '.join(sorted(fitted['models'])) or 'none'}.
The fitted candidate is in `eval/cache/calibration.json`. It is **not promoted** to `data/calibration.json`: it fails unchanged golden/demo confidence checks (NS31 below the required confidence, uncalibrated voucher confidence, an extra Ops question). The demo keeps its existing priors. No confidence threshold or expected fixture was weakened.
Each fitted kind has five held-out reliability bins with counts and Wilson 95% intervals in `proof.json`. Missing kinds remain explicitly uncalibrated; empty bins are not evidence of accuracy.
Plain-Claude baseline: **{report.baseline['status']}**, {report.baseline['runs']} completed runs. No live API key was available. There is no measured claim that Claude is less accurate or nondeterministic. `python -m eval.baseline --prepare` writes the nine matched-input requests; `--live` runs through the shared capped Batches wrapper when credentials are supplied.
Reader prompt-injection regression: {report.injections['facts_only']}/{report.injections['attempted']} facts-only results against **hand-written** cache recordings. This tests validation and wiring, not live model resistance.

## Coverage limits

{chr(10).join('- ' + s for s in status)}
Ambiguous generated cancellations by split (deliberately hidden crew failures with weather/OCC records): {cache.get('world_diagnostics', {})}.
The fitted cause model is synthetic development data, not a production guarantee. All outputs remain drafts requiring the repository's existing role approvals.

Input manifest: `cache/manifest.json`. Metric inputs and controls: `cache/results.json`. Independent answer keys: `data/answer_key/`. No labels are copied from engine decisions.
"""


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--from-cache", action="store_true")
    args = parser.parse_args()
    cache_path = ROOT / "eval/cache/results.json"
    # Promotion is a separate gate: the fitted candidate currently fails the golden confidence contract.
    # Never silently replace runtime priors or weaken that acceptance fixture to make a fit look successful.
    cal_path = ROOT / "eval/cache/calibration.json"
    if args.from_cache:
        cache = orjson.loads(cache_path.read_bytes())
        fitted = orjson.loads(cal_path.read_bytes())
        expected = orjson.loads((ROOT / "eval/cache/manifest.json").read_bytes())
        for name, digest in expected["sha256"].items():
            if sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Input hash mismatch: {name}")
    else:
        print("Generating deterministic world and independent answer keys", flush=True)
        generated = generate_world(seed=0)
        keys = {split: build_answer_key(generated, split) for split in ("train", "test")}
        write_answer_keys(generated, ROOT / "data/answer_key")
        cases = build_error_cases()
        stress = {"version": "northstar-errors@1", "label": "controlled simulated regressions; not independent storm samples",
                  "counts": {split: {category: sum(c["split"] == split and c["category"] == category for c in cases)
                                     for category in CATEGORIES} for split in ("train", "test")}, "cases": cases}
        stress_path = ROOT / "data/answer_key/stress.json"
        stress_path.write_bytes(orjson.dumps(stress, option=orjson.OPT_SORT_KEYS) + b"\n")
        print("Collecting train/test engine decisions", flush=True)
        calibration_rows = collect(generated.world, keys, default_calibration())
        fitted = fit_calibration(calibration_rows)
        write_json(cal_path, fitted)
        print("Re-running with training-only fitted calibration", flush=True)
        scored_rows = collect(generated.world, keys, fitted)
        replay, controls = replay_three()
        cache = {"version": "eval-v1", "seed": 0, "calibration_rows": calibration_rows,
            "scored_rows": scored_rows, "replay": replay, "controls": controls,
            "held_out_storms": len({d["date"] for d in generated.world.meta["days"]
                                    if d["split"] == "test" and d["kind"] == "storm"}),
            "injections": injection_check(),
            "world_diagnostics": {split: {
                "non_golden_cancelled": sum(t.split == split and t.status == "cancelled" and not t.golden
                                             for t in generated.truth.flights.values()),
                "ambiguous": sum(t.split == split and t.ambiguous and not t.golden
                                 for t in generated.truth.flights.values())} for split in ("train", "test")},
            "baseline": {"model": "claude-opus-5-5", "status": "not_run_missing_credentials", "runs": 0,
                         "liability_eur": [], "cause_accuracy": [], "hash_identical": None},
            "coverage_gaps": [
                "Cause calibration only: voucher, release and claim-validity correctness datasets are not fitted.",
                "The supplemental stress corpus has five input cases per error type per split (140 total); it is separate from natural-world accuracy and is not yet a full scored end-to-end claim benchmark.",
                "The fitted candidate fails golden/demo confidence acceptance and has not been promoted to runtime data/calibration.json.",
                "Repeat-question and scope metrics cover the explicit golden Q1/Q2/Q3 replay, not every held-out flight.",
                "Historic reduction policy is supplied, not learned by the unfinished policy miner.",
                "No paid baseline or live model outputs were available; CP3 is not complete."]}
        write_json(cache_path, cache)
        inputs = ["eval/cache/results.json", "eval/cache/calibration.json", "data/answer_key/train.json",
                  "data/answer_key/test.json", "data/answer_key/stress.json", "contracts/fixtures/golden/world.json",
                  "uv.lock"]
        inputs += [str(p.relative_to(ROOT)) for directory in ("world", "engine", "books", "eval")
                   for p in sorted((ROOT / directory).glob("*.py"))]
        inputs += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "data/pinned").iterdir()) if p.is_file()]
        write_json(ROOT / "eval/cache/manifest.json", {"generator_seed": 0,
            "sha256": {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs}})
    report = report_from_cache(cache, fitted)
    write_json(ROOT / "eval/proof.json", report.model_dump(mode="json"))
    (ROOT / "eval/NUMBERS.md").write_text(numbers(report, cache, fitted))
    print(f"Proof validated: {report.n_passengers} held-out passengers; baseline {report.baseline['status']}")


if __name__ == "__main__":
    main()
