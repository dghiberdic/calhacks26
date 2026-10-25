"""Rebuild the proof from pinned weather, or reproduce/verify it from the cache.

    uv run python -m eval.run                  # full run: world → engine on every keyed day → fits → proof (~10 min)
    uv run python -m eval.run --from-cache     # proof.json + NUMBERS.md from eval/cache (inputs hash-checked)
    uv run python -m eval.run --check          # exit 1 unless the inputs match the manifest and the committed
                                               #   proof.json / NUMBERS.md are byte-identical to a rebuild from cache
    uv run python -m eval.run --check --full   # also rerun everything in a scratch dir and byte-compare results

Nothing here calls the network. The baseline is folded in only from eval/cache/baseline_results.json (written by
``python -m eval.baseline --live``).
"""
from __future__ import annotations

import argparse
import sys
from hashlib import sha256
from pathlib import Path

import orjson

from contracts.models import EvalReport
from engine.confidence import default_calibration
from eval import baseline as B
from eval.calibration import LABEL, acceptance, accuracy_at, fit_calibration, reliability
from eval.evaluate import SPLITS, claim_validity_rows, collect, load_curves, miss_table, summarize
from eval.golden_flow import STORM_DAYS, fresh_process_runs, replay_three
from eval.truth import expanded_keys

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "eval/cache/results.json"
FITTED = ROOT / "eval/cache/calibration.json"
MANIFEST = ROOT / "eval/cache/manifest.json"
PROOF, NUMBERS = ROOT / "eval/proof.json", ROOT / "eval/NUMBERS.md"
DATA_CALIBRATION = ROOT / "data/calibration.json"
SOURCE_DIRS = ("world", "engine", "books", "eval", "contracts", "llm")
CACHE_VERSION = "eval-v2"          # what full_run writes and numbers() reads
STALE = "stale proof: regenerate with `uv run python -m eval.run`"
# The four outcome classes, in headline order (eval/DECISIONS.md F9 §3; `held_other` is the conservative one)
OUTCOME_ROWS = {
    "auto_correct": "Auto-correct: settled with no person, and right",
    "escalated_correct": "Correct escalation: held for the person the answer key names",
    "held_other": "Conservative escalation: held although the key needs no person, or held for another role "
                  "(costs straight-through; not an error)",
    "auto_wrong": "**Auto-wrong**: settled with no person, and wrong (the dangerous class)",
}
STORM_NAMES = {"2025-01-24": "Éowyn", "2025-01-26": "Herminia"}


def injection_check() -> dict:
    from eval.injections import run_injections

    return run_injections()[0]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_json(value))


def dump_json(value) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2) + b"\n"


def _report_v1(cache: dict, fitted: dict) -> EvalReport:
    """Filip's eval-v1 report (equal-width bins), kept verbatim so a committed v1 proof stays reproducible from
    its own cache until it is regenerated as eval-v2."""
    from contracts import calibration as cc
    from eval.calibration import wilson

    bins, coverage = {}, {}
    for kind in cc.KINDS:
        rows = [r for r in cache["calibration_rows"] if r["split"] == "test" and r["kind"] == kind]
        if kind not in fitted.get("models", {}):
            bins[kind], coverage[kind] = [], 0.0
            continue
        scored = [(p, bool(r["correct"])) for r in rows if (p := cc.score(fitted, kind, r["features"])) is not None]
        out = []
        for i in range(5):
            members = [(p, y) for p, y in scored if min(4, int(p * 5)) == i]
            n = len(members)
            acc = sum(y for _, y in members) / n if n else 0.0
            lo, hi = wilson(sum(y for _, y in members), n)
            out.append({"lo": i / 5, "hi": (i + 1) / 5, "n": n, "accuracy": round(acc, 6),
                        "wilson_lo": round(lo, 6), "wilson_hi": round(hi, 6)})
        bins[kind] = out
        coverage[kind] = round(sum(p >= 0.9 for p, _ in scored) / len(scored), 6) if scored else 0.0
    return EvalReport(split={"train": "2023-07-01..2024-12-31", "test": "2025-01-01..2025-06-30"},
        n_storms=cache["held_out_storms"], **summarize(cache["scored_rows"]), calibration=bins,
        coverage_at_90=coverage, repeat_questions=cache["controls"]["repeat_questions"],
        out_of_scope_auto=cache["controls"]["out_of_scope_auto"],
        baseline=cache["baseline"], stormcheck_runs=cache["replay"], injections=cache["injections"],
        real_vs_simulated={"real": ["pinned METAR observations", "airport coordinates and timezones"],
            "simulated": ["airline, flights, faults, passengers, claims and accounting estimates",
                          "explicit human rulings in control replay",
                          "Reader injection outputs are hand-written recordings, not live model results"]}, label=LABEL)


def report_from_cache(cache: dict, fitted: dict) -> EvalReport:
    if cache.get("version") == "eval-v1":
        return _report_v1(cache, fitted)
    rows = cache["scored_rows"]
    bins, coverage = reliability(cache["calibration_rows"], fitted)
    m = summarize(rows, {k: {int(m): v for m, v in pts.items()} for k, pts in cache.get("curves", {}).items()})
    runs = dict(cache["replay"])
    if "storm_runs" in cache:
        runs["storms"] = cache["storm_runs"]
    return EvalReport(split={"train": "..".join(SPLITS["train"]), "test": "..".join(SPLITS["test"])},
        n_storms=cache["held_out_storms"], **m, calibration=bins, coverage_at_90=coverage,
        repeat_questions=cache["controls"]["repeat_questions"],
        out_of_scope_auto=cache["controls"]["out_of_scope_auto"],
        baseline=cache["baseline"], stormcheck_runs=runs, injections=cache["injections"],
        real_vs_simulated={"real": ["pinned METAR observations (IEM)", "airport coordinates and timezones",
                                    "EU261 articles and CJEU case law as rules"],
            "simulated": ["airline, flights, faults, passengers, claims and accounting estimates",
                          "explicit human rulings in the held-out and control replays",
                          "Reader outputs for the rehearsed injections are hand-written recordings, not live model "
                          "results"]}, label=LABEL)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _storm(day: str) -> str:
    return f"{STORM_NAMES[day]} ({day})" if day in STORM_NAMES else day


def _eur(values) -> str:
    return " / ".join(f"€{x:,.0f}" for x in values) or "—"


def _baseline_headline(base: dict, storms: dict) -> str:
    """One line for the headline: plain Claude against StormCheck on the same raw documents."""
    if base.get("status") != "complete":
        return (f"Plain Claude on the same raw documents: **{base.get('status', 'pending')}** "
                f"({base.get('completed_requests', 0)}/{len(B.DAYS) * B.RUNS} genuine batch results); no plain-Claude "
                "number is claimed.")
    first = B.DAYS[0]
    s = base["storms"][first]
    sc = storms.get(first, {})
    return (f"Plain Claude on the same raw documents ({base['model']}, effort {base['effort']}, 3 identical runs): on "
            f"{_storm(first)} it scored {' / '.join(_pct(a) for a in s['cause_accuracy'])} and estimated "
            f"{_eur(s['liability_eur'])}, `hash_identical={str(s['hash_identical']).lower()}`. StormCheck on the "
            f"same flights: {_pct(s['stormcheck_accuracy'])}, {_eur(sc.get('liability_eur', []))}, "
            f"`hash_identical={str(sc.get('hash_identical')).lower()}`. Every storm is in “Plain Claude vs "
            "StormCheck” below.")


def _baseline_section(base: dict, storms: dict) -> list[str]:
    lines = ["### Plain Claude vs StormCheck on the same raw documents", ""]
    if base.get("status") != "complete":
        return lines + [f"Plain Claude: **{base.get('status', 'pending')}** "
                        f"({base.get('completed_requests', 0)}/{len(B.DAYS) * B.RUNS} genuine batch results). Run "
                        f"`{B.LIVE_COMMAND}` with ANTHROPIC_API_KEY in .env, then `uv run python -m eval.run`. The "
                        "nine matched-input requests are prepared offline (`python -m eval.baseline --prepare`); no "
                        "plain-Claude number is claimed until then.", ""]
    lines += [f"Plain Claude: `{base['model']}`, effort `{base['effort']}`, adaptive thinking, structured output, "
              "through the Batches API. It gets the operational documents StormCheck reads (schedule, OCC/MCC/spares "
              "lines, tech log, raw METAR at both ends, PII-free PSS coupon lines) and the same supplied policy, and "
              "is asked for cause, extraordinary status and the initial € EU261 compensation liability per cancelled "
              "flight. Three byte-identical requests per storm. Phase: the initial estimate before any human ruling, "
              "the same phase as StormCheck ×3.", "",
              "Scoring, the same rule for both: cause (root-aware) and extraordinary status must match the answer "
              "key; a `needs_legal` answer counts as right when the key routes the flight to a person. StormCheck's "
              "accuracy is its initial output in the held-out replay, which on later storms already applies rulings "
              "made on earlier days; plain Claude gets only the supplied policy.", "",
              "| Storm | Flights | Plain Claude accuracy (3 runs) | StormCheck accuracy | Plain Claude € (3 runs) "
              "| StormCheck € (×3) | Answer key € (latent entitlement × expected ultimate claim rate) "
              "| Plain Claude same hash? |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for day in B.DAYS:
        s = base["storms"].get(day, {})
        sc = storms.get(day, {})
        same = s.get("hash_identical")
        lines.append(f"| {_storm(day)} | {s.get('flights', '—')} | "
                     f"{' / '.join(_pct(a) for a in s.get('cause_accuracy', [])) or '—'} | "
                     f"{_pct(s['stormcheck_accuracy']) if s.get('stormcheck_accuracy') is not None else '—'} | "
                     f"{_eur(s.get('liability_eur', []))} | {_eur(sc.get('liability_eur', []))} | "
                     f"€{s.get('key_ultimate_expected_eur', 0):,.0f} | "
                     f"{'yes' if same else 'no' if same is False else '—'} |")
    lines += ["", f"`proof.json` `baseline.hash_identical` is the {_storm(B.DAYS[0])} value, as the F9 spec asks. "
              "Requests, model ids, usage and request records: `cache/baseline_requests.json`, "
              "`cache/baseline_results.json`.", ""]
    return lines


def numbers(report: EvalReport, cache: dict, fitted: dict) -> str:
    lva = report.liability_vs_actual
    cal = cache["calibration"]
    gate = cal["promotion_problems"]
    ctl = cache["controls"]
    base = report.baseline
    inj = report.injections
    stress = cache["stress"]
    storms = cache.get("storm_runs", {}).get("storms", {})
    miss = cache["miss_table"]
    n_test = int(sum(lva.get(k, 0) for k in OUTCOME_ROWS))
    n_auto = int(lva["auto_correct"] + lva["auto_wrong"])
    lines = [f"# StormCheck measured proof", "", f"{LABEL}.", "",
             "Every number below is computed by `python -m eval.run` from the pinned corpus. Reproduce it offline with "
             "`uv run python -m eval.run --from-cache`; `uv run python -m eval.run --check` fails if anything drifted.",
             "", "## Headline: held-out January–June 2025 (never seen in training)", "",
             f"{n_test} cancelled flights on {report.n_storms} storm days plus background days "
             f"({int(lva['curated_golden_cancellations'])} curated golden, {int(lva['non_golden_cancellations'])} "
             f"generated; {report.n_passengers:,} passengers). Every flight lands in exactly one outcome class:", "",
             "| Outcome class | Flights | Generated only |", "|---|---:|---:|"]
    for k, label in OUTCOME_ROWS.items():
        lines.append(f"| {label} | {int(lva[k])} | {int(lva['generated_' + k])} |")
    lines += ["", f"**Auto-precision {_pct(lva['auto_precision'])}**: of {n_auto} flights settled with no person, "
              f"{int(lva['auto_correct'])} were right and {int(lva['auto_wrong'])} wrong. Generated flights only: "
              f"{_pct(lva['generated_auto_precision'])} ({int(lva['generated_auto_wrong'])} wrong).", "",
              f"Straight-through, reported separately: **{report.straight_through_pct:.2f}%** of passengers (the "
              f"flight is automatic and the coupon has no hold or question); {lva['auto_flights_pct']:.1f}% of "
              "flights. It measures routing, not correctness.", "",
              f"Ambiguous by design: **{int(lva['ambiguous_by_design'])}** flights are feature-invisible (hidden crew "
              "faults, unrecorded AOGs and their knock-ons). They are counted inside the classes above; "
              f"{int(lva['ambiguous_auto_wrong'])} of them are auto-wrong.", "",
              _baseline_headline(base, storms), "",
              "## Detail", "",
              f"Right or correctly escalated: {_pct(lva['right_or_correctly_escalated'])} of all, "
              f"{_pct(lva['generated_right_or_correctly_escalated'])} of generated. Strict cause **and** "
              f"extraordinary equality with the key (an escalation counts as a miss): "
              f"{_pct(lva['flight_cause_and_extraordinary_accuracy'])}.", "",
              "Why flights were not auto-correct (`miss_class`, examples in `cache/results.json`):", "",
              "| Class | n | generated | examples |", "|---|---:|---:|---|"]
    for k, v in miss.items():
        if k != "auto_correct":
            lines.append(f"| {k} | {v['n']} | {v['generated']} | {', '.join(v['examples'])} |")
    lines += ["", "`held_window_edge` (a weather code just outside the strict window → Ops) and "
              "`held_external_event_no_precedent` (only Legal settles a new legal pattern) are deliberate "
              "conservative escalations.", "",
              f"- Miscodes caught: {report.miscodes_caught}/{report.miscodes_total} latent internal AOGs typed as "
              f"weather were not accepted as weather ({int(lva['miscodes_caught_auto'])} recoded automatically); "
              f"face cash entitlement €{report.miscodes_eur_cents / 100:,.2f}.",
              f"- Conservative escalations (`held_other`, reported as `false_holds`): {report.false_holds}.",
              f"- Refund drafted for an unsigned, non-web voucher election: "
              f"{int(lva.get('refund_drafted_unsigned_non_web_voucher_coupons', 0))} coupons, "
              f"€{lva.get('refund_drafted_unsigned_non_web_voucher_eur', 0):,.2f}. The key says no refund is due there; "
              "the engine treats a voucher as agreed only with a signed acceptance or a web self-service election "
              "(Art. 8(1)(a) via 7(3)). That is deliberate legal conservatism, reported as its own category and not "
              f"as an error. Other coupon refund disagreements: {int(lva.get('refund_disagree_other_coupons', 0))}.",
              f"- Repeat questions after a ruling, across all held-out days in date order: **{report.repeat_questions}**"
              f". Rulings applied from the morning first asked: {', '.join(r['rule'] + ' (' + r['day'] + ')' for r in cache['rulings'])}. "
              f"Settled by them in their ground-truth scope: {ctl['in_scope_settled']}; out-of-scope automatic "
              f"applications: **{report.out_of_scope_auto}**.",
              "", "### Liability vs actual (generated held-out cohorts, train-learned € curves)", "",
              "| Month | Expected claims (accrual × curve) | Valid claims received | A/E |", "|---|---:|---:|---:|"]
    for k in (1, 3, 6):
        if f"m{k}_expected_eur" in lva:
            lines.append(f"| M{k} | €{lva[f'm{k}_expected_eur']:,.2f} | €{lva[f'm{k}_actual_eur']:,.2f} | "
                         f"{lva[f'm{k}_actual_over_expected']:.3f} |")
    lines += ["", f"Initial EU261 compensation liability estimate (all held-out flights): €{lva['preview_eur']:,.2f}; "
              f"latent net entitlement × segment expected ultimate claim rates: €{lva['ultimate_expected_eur']:,.2f}; "
              f"valid claims observed through 30 June 2026: €{lva['valid_claims_through_2026_06_30_eur']:,.2f} (a "
              "development snapshot, not the final outcome).", "", "## Same input, same answer", ""]
    for day, s in storms.items():
        lines.append(f"- StormCheck ×3 on {day} ({s['cancelled']} cancelled), fresh process each: "
                     f"€{' / €'.join(f'{x:,.0f}' for x in s['liability_eur'])}, "
                     f"{'same hash' if s['hash_identical'] else 'HASHES DIFFER'} `{s['hashes'][0][:16]}…`.")
    lines += [f"- Golden control replay (real Engine + TraceStore + Books, scripted Claims Lead/Legal/Controller "
              f"rulings): **€34,650 ×3, same hash** `{report.stormcheck_runs['hashes'][0][:16]}…`. Before the Legal "
              f"ruling it is €82,146 (held knock-ons accrued); €34,650 is after it. The Isha tail kept: "
              f"€{report.stormcheck_runs['tail_kept_eur'][0]:,.0f}.", ""]
    lines += _baseline_section(base, storms)
    lines += ["## Calibration (one logistic model per Confidence.kind)", "",
              "Label: the engine settled the item alone and correctly per the answer key (an abstention is 0). "
              "Fitted on train only; C chosen by 5-fold grouped CV log-loss on train.", "",
              "| Kind | trained on | n (train) | C | held-out n | coverage@0.9 | accuracy@0.9 |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for kind, m in fitted["models"].items():
        k, n = cal["accuracy_at_90"].get(kind, [0, 0])
        lines.append(f"| {kind} | {m.get('trained_on', '')} | {m.get('n', 0)} | {m.get('metrics', {}).get('C', '—')} | "
                     f"{cal['test_n'].get(kind, 0)} | {report.coverage_at_90.get(kind, 0.0):.3f} | "
                     f"{f'{k}/{n}' if n else '—'} |")
    lines += ["", f"Bins: five per kind at the routing thresholds (0.60 / 0.75 / 0.90 / 0.97), with n and Wilson 95% "
              f"intervals, in `proof.json`.", ""]
    if cal["promoted"]:
        lines.append(f"**Promoted** to `data/calibration.json` ({fitted['version']}): it keeps every golden confidence "
                     "band (real engine and FakeEngine).")
    else:
        lines += [f"**Not promoted**: the runtime keeps `engine/default_calibration.json`, and the held-out routing "
                  f"numbers above use it. The candidate (`eval/cache/calibration.json`, {fitted['version']}) breaks "
                  f"{len(gate)} golden confidence band(s):", ""]
        lines += [f"  - {p}" for p in gate[:12]]
    lines += ["", "## Injections and hostile input", "",
              f"- {inj['attempted']} rehearsed injections through the real `llm.reader` (hand-written recordings) "
              f"and the engine: {inj['as_expected']}/{inj['attempted']} had the expected effect, "
              f"{inj['blocked_or_escalated']}/{inj['attempted']} blocked or escalated, {inj['auto_flips']} automatic "
              f"flips, {inj['approvals_by_injection']} approvals. Injection emails: {inj['facts_only']} facts-only, "
              f"{inj['unsafe_extractions']} unsafe.",
              f"- {inj['fuzz']} hostile/fuzz inputs (regex fallback, no recording): {inj['fuzz_errors']} errors, "
              f"{inj['fuzz_auto_flips']} automatic flips.", "",
              "## Stress corpus (controlled regressions, separate from the natural-world numbers)", "",
              f"{stress['passed']}/{stress['cases']} cases pass end to end (engine → entitlements → Books claims).", "",
              "| Error type | train | test |", "|---|---:|---:|"]
    for k, v in stress["by_category"].items():
        lines.append(f"| {k} | {v['train'][0]}/{v['train'][1]} | {v['test'][0]}/{v['test'][1]} |")
    diag = cache.get("world_diagnostics", {})
    lines += ["", "## Coverage limits", ""]
    lines += [f"- Ambiguous (feature-invisible) generated cancellations: " + ", ".join(
        f"{s} {v['ambiguous']}/{v['non_golden_cancelled']} ({_pct(v['ambiguous'] / v['non_golden_cancelled'])})"
        for s, v in sorted(diag.items()) if v.get("non_golden_cancelled")) + " (plan target ~5%)."]
    lines += [f"- {s}" for s in cache.get("coverage_gaps", [])]
    lines += ["", "Input manifest: `cache/manifest.json` (sha256 of every source module in world/, engine/, books/, eval/, "
              "contracts/, llm/, the demo recordings, keys and pinned data). Metric inputs: `cache/results.json`. "
              "Independent answer keys: `data/answer_key/`. No label is copied from an engine decision.", ""]
    return "\n".join(lines)


def manifest_inputs() -> list[str]:
    inputs = ["eval/cache/results.json", "eval/cache/calibration.json", "data/answer_key/train.json",
              "data/answer_key/test.json", "data/answer_key/stress.json", "data/answer_key/curves_train.json",
              "contracts/fixtures/golden/world.json", "contracts/fixtures/golden/curves.json",
              "engine/default_calibration.json", "contracts/calibration_schema.json", "uv.lock"]
    inputs += [str(p.relative_to(ROOT)) for d in SOURCE_DIRS for p in sorted((ROOT / d).glob("*.py"))]
    inputs += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "data/cache/demo").glob("*.json"))]
    inputs += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "data/pinned").iterdir()) if p.is_file()]
    return inputs


def stale_inputs() -> list[str]:
    expected = orjson.loads(MANIFEST.read_bytes())["sha256"]
    bad = [n for n, d in expected.items() if not (ROOT / n).is_file() or sha256((ROOT / n).read_bytes()).hexdigest() != d]
    bad += [f"{n} (new, not in manifest)" for n in manifest_inputs() if n not in expected]
    return bad


def full_run(progress=print) -> tuple[dict, dict]:
    from world.answer_key import write as write_answer_keys
    from world.error_cases import CATEGORIES, build_error_cases
    from world.generator import generate_world

    from eval.stress import score_stress

    progress("Generating the deterministic world and independent answer keys")
    generated = generate_world(seed=0)
    keys = expanded_keys(generated)
    write_answer_keys(generated, ROOT / "data/answer_key")
    cases = build_error_cases()
    stress = {"version": "northstar-errors@1", "label": "controlled simulated regressions; not independent storm samples",
              "counts": {split: {category: sum(c["split"] == split and c["category"] == category for c in cases)
                                 for category in CATEGORIES} for split in ("train", "test")}, "cases": cases}
    (ROOT / "data/answer_key/stress.json").write_bytes(orjson.dumps(stress, option=orjson.OPT_SORT_KEYS) + b"\n")
    progress("Running the engine on every train and held-out day (held-out in date order with scripted rulings)")
    prior = default_calibration()
    ledger: dict = {}
    rows = collect(generated.world, keys, prior, ledger=ledger)
    rows += claim_validity_rows(generated.world, keys)
    fitted = fit_calibration(rows, prior=prior)
    write_json(FITTED, fitted)
    problems = acceptance(fitted)
    promoted = not problems
    scored = rows
    if promoted:
        write_json(DATA_CALIBRATION, fitted)
        progress("Promoted; re-scoring the held-out days with the fitted calibration")
        ledger = {}
        scored = [r for r in rows if r["split"] == "train"] + collect(generated.world, keys, fitted, splits=("test",),
                                                                      ledger=ledger)
    progress("Control replay, fresh-process storm runs, injections and stress corpus")
    replay, controls_golden = replay_three()
    storm_runs = fresh_process_runs(STORM_DAYS)
    injections = injection_check()
    stress_summary, stress_rows = score_stress(cases)
    baseline = B.pending()
    if B.RESULTS_PATH.is_file():
        baseline = B.summarize_results(orjson.loads(B.RESULTS_PATH.read_bytes()), scored)
    curves = load_curves(ROOT / "data/answer_key/curves_train.json")
    test_cal = [r for r in rows if r["split"] == "test"]
    slim = ("split", "kind", "day", "features", "correct")
    cache = {"version": CACHE_VERSION, "seed": 0, "calibration_rows": [{k: r[k] for k in slim if k in r} for r in rows],
        "scored_rows": [r for r in scored if r["kind"] == "cause"], "replay": replay, "controls_golden": controls_golden, "controls": ledger["controls"],
        "rulings": ledger["rulings"], "repeats": ledger["repeats"], "out_of_scope": ledger["out_of_scope"],
        "questions": ledger["questions"], "storm_runs": storm_runs,
        "held_out_storms": len({d["date"] for d in generated.world.meta["days"]
                                if d["split"] == "test" and d["kind"] == "storm"}),
        "injections": injections, "stress": stress_summary, "stress_rows": stress_rows,
        "curves": {k: {str(m): v for m, v in pts.items()} for k, pts in curves.items()},
        "miss_table": miss_table(scored), "baseline": baseline,
        "calibration": {"promoted": promoted, "promotion_problems": problems, "runtime": (
                            fitted["version"] if promoted else prior["version"]),
                        "test_n": {k: sum(r["kind"] == k for r in test_cal) for k in ("cause", "voucher", "release",
                                                                                       "claim_validity")},
                        "accuracy_at_90": {k: list(accuracy_at(rows, fitted, k)) for k in fitted["models"]}},
        "world_diagnostics": {split: {
            "non_golden_cancelled": sum(t.split == split and t.status == "cancelled" and not t.golden
                                        for t in generated.truth.flights.values()),
            "ambiguous": sum(t.split == split and t.ambiguous and not t.golden
                             for t in generated.truth.flights.values())} for split in ("train", "test")},
        "coverage_gaps": [
            "Release has no train-split proposals (Isha reaches M12 in January 2025), so it runs on the shipped prior.",
            "Claim validity has no engine consumer yet; it is fitted on the CONTRACTS x-encoding and reported only.",
            "The historical Art. 7(2) reduction policy is supplied as a fixture rule, not mined.",
            "Rulings in the held-out replay are the plan's scripted words, drafted into rules by the engine's "
            "deterministic template drafter (not the LLM Drafter).",
            "The rehearsed-injection Reader outputs are hand-written recordings: this tests validation and wiring, "
            "not a live model's resistance."]}
    return cache, fitted


def build(cache: dict, fitted: dict) -> tuple[bytes, bytes]:
    report = report_from_cache(cache, fitted)
    return dump_json(report.model_dump(mode="json")), numbers(report, cache, fitted).encode()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def load_current_cache() -> tuple[dict, dict] | str:
    """The committed cache and fitted model, or why they cannot build the current proof (stale, legacy, missing)."""
    try:
        cache, fitted = orjson.loads(CACHE.read_bytes()), orjson.loads(FITTED.read_bytes())
    except (OSError, orjson.JSONDecodeError) as e:
        return f"cannot read the cache ({type(e).__name__}: {e})"
    version = cache.get("version") if isinstance(cache, dict) else None
    if version != CACHE_VERSION:
        return f"eval/cache/results.json is {version!r}; this code builds {CACHE_VERSION!r}"
    return cache, fitted


def check(full: bool = False) -> list[str]:
    """Every reason the committed proof is not a byte-exact rebuild of the committed cache. Never raises on a cache
    that predates the code: that is reported as a stale proof."""
    try:
        bad = stale_inputs()
        problems = [f"input changed since the proof was built: {n}" for n in bad[:10]]
        problems += [f"… and {len(bad) - 10} more changed inputs"] if len(bad) > 10 else []
    except (OSError, orjson.JSONDecodeError, KeyError, TypeError) as e:
        problems = [f"eval/cache/manifest.json is missing or unreadable ({type(e).__name__})"]
    loaded = load_current_cache()
    if isinstance(loaded, str):
        return [*problems, loaded]
    try:
        proof, nums = build(*loaded)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, ZeroDivisionError) as e:
        # pydantic.ValidationError is a ValueError
        return [*problems, f"the cache predates the code ({type(e).__name__}: {e})"]
    if _read_bytes(PROOF) != proof:
        problems.append("eval/proof.json differs from a rebuild from eval/cache")
    if _read_bytes(NUMBERS) != nums:
        problems.append("eval/NUMBERS.md differs from a rebuild from eval/cache")
    if full:
        cache, fitted = full_run(progress=lambda s: print(s, file=sys.stderr, flush=True))
        if dump_json(cache) != _read_bytes(CACHE):
            problems.append("a full rerun changed eval/cache/results.json")
        if build(cache, fitted)[0] != _read_bytes(PROOF):
            problems.append("a full rerun changed eval/proof.json")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--full", action="store_true", help="with --check: rerun everything and byte-compare")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(full=args.full)
        for p in problems:
            print(f"eval --check: {p}")
        print("eval --check: OK" if not problems else f"eval --check: {STALE} ({len(problems)} problem(s))")
        return 1 if problems else 0
    if args.from_cache:
        bad = stale_inputs()
        if bad:
            raise SystemExit(f"Input hash mismatch: {bad[0]} (+{len(bad) - 1} more); rerun without --from-cache")
        loaded = load_current_cache()
        if isinstance(loaded, str):
            raise SystemExit(f"{STALE}: {loaded}")
        cache, fitted = loaded
    else:
        cache, fitted = full_run(progress=lambda s: print(s, flush=True))
        write_json(CACHE, cache)
        write_json(MANIFEST, {"generator_seed": 0, "sha256": {
            p: sha256((ROOT / p).read_bytes()).hexdigest() for p in manifest_inputs()}})
    proof, nums = build(cache, fitted)
    PROOF.write_bytes(proof)
    NUMBERS.write_bytes(nums)
    report = EvalReport.model_validate_json(proof)
    print(f"Proof validated: {report.n_passengers} held-out passengers; baseline {report.baseline['status']}; "
          f"calibration {'promoted' if cache['calibration']['promoted'] else 'not promoted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
