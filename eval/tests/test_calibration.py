import math

import pytest


def test_fitted_models_use_training_rows_only_and_leave_missing_kinds_uncalibrated():
    from eval.calibration import fit_calibration

    training = [
        {"kind": "cause", "split": "train", "features": {"sources_disagree": 0}, "correct": True},
        {"kind": "cause", "split": "train", "features": {"sources_disagree": 0}, "correct": True},
        {"kind": "cause", "split": "train", "features": {"sources_disagree": 1}, "correct": False},
        {"kind": "cause", "split": "train", "features": {"sources_disagree": 1}, "correct": False},
    ]
    held_out = {"kind": "cause", "split": "test", "features": {"sources_disagree": 99}, "correct": True}
    fitted = fit_calibration(training + [held_out])
    assert fitted == fit_calibration(training)
    assert fitted["models"]["cause"]["n"] == 4
    assert set(fitted["models"]) == {"cause"}


def test_reliability_uses_held_out_rows_and_reports_wilson_intervals():
    from eval.calibration import reliability

    fitted = {"version": "test", "models": {"cause": {
        "features": ["sources_disagree"], "coef": [0.0], "intercept": 0.0,
    }}}
    rows = [
        {"kind": "cause", "split": "train", "features": {}, "correct": False},
        {"kind": "cause", "split": "test", "features": {}, "correct": True},
        {"kind": "cause", "split": "test", "features": {}, "correct": False},
    ]
    bins, coverage = reliability(rows, fitted)
    assert len(bins["cause"]) == 5
    ask = bins["cause"][0]                       # p = 0.5 lands below the 0.60 ask threshold
    assert (ask["lo"], ask["hi"]) == (0.0, 0.6)
    assert ask["n"] == 2
    assert ask["accuracy"] == 0.5
    assert ask["mean_score"] == 0.5
    assert ask["wilson_lo"] == pytest.approx(0.0945, abs=0.0001)
    assert ask["wilson_hi"] == pytest.approx(0.9055, abs=0.0001)
    assert sum(b["n"] for b in bins["cause"]) == 2
    assert coverage["cause"] == 0
    assert bins["voucher"] == []


@pytest.mark.parametrize(("k", "n", "lo", "hi"), [
    (5, 10, 0.2366, 0.7634),        # textbook: p̂ = .5, n = 10, z = 1.96
    (10, 10, 0.7225, 1.0),
    (0, 10, 0.0, 0.2775),
    (81, 100, 0.7222, 0.8749),
    (1, 1, 0.2065, 1.0),
])
def test_wilson_matches_reference_values(k, n, lo, hi):
    from eval.calibration import wilson

    assert wilson(k, n) == pytest.approx((lo, hi), abs=1e-4)


def test_wilson_closed_form_symmetry_and_empty():
    from eval.calibration import Z95, wilson

    for k, n in [(3, 7), (40, 41), (199, 412), (2, 2000)]:
        p = k / n
        centre = (p + Z95 ** 2 / (2 * n)) / (1 + Z95 ** 2 / n)
        half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / (1 + Z95 ** 2 / n)
        lo, hi = wilson(k, n)
        assert lo == pytest.approx(max(0.0, centre - half), abs=1e-12)
        assert hi == pytest.approx(min(1.0, centre + half), abs=1e-12)
        assert 0.0 <= lo <= p <= hi <= 1.0
    lo, hi = wilson(3, 11)
    lo2, hi2 = wilson(8, 11)
    assert lo == pytest.approx(1 - hi2) and hi == pytest.approx(1 - lo2)
    assert wilson(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_bins_are_cut_at_the_routing_thresholds():
    from eval.calibration import BIN_EDGES, _bin
    from engine.routing import AUTO_THRESHOLD, BATCH_THRESHOLD

    assert BATCH_THRESHOLD in BIN_EDGES and AUTO_THRESHOLD in BIN_EDGES
    assert [_bin(p) for p in (0.0, 0.59, 0.6, 0.749, 0.75, 0.899, 0.9, 0.969, 0.97, 1.0)] == \
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_regularisation_is_chosen_on_train_days_only_and_kinds_without_rows_keep_the_prior():
    from engine.confidence import default_calibration
    from eval.calibration import C_GRID, fit_calibration

    rows = []
    for day in range(12):
        for i in range(6):
            bad = (day + i) % 4 == 0
            rows.append({"kind": "cause", "split": "train", "day": f"2024-01-{day + 1:02d}",
                         "features": {"in_window_dep": 0.0 if bad else 1.0, "sources_disagree": float(bad)},
                         "correct": not bad if i else bad})
    test_rows = [dict(r, split="test", correct=not r["correct"]) for r in rows]
    fitted = fit_calibration(rows + test_rows, prior=default_calibration())
    assert fitted == fit_calibration(rows, prior=default_calibration())       # held-out rows never matter
    m = fitted["models"]["cause"]
    assert m["metrics"]["C"] in C_GRID and m["n"] == len(rows) and m["trained_on"] == "2023-07-01..2024-12-31"
    for kind in ("voucher", "release"):                                        # no train rows: shipped prior
        assert fitted["models"][kind]["trained_on"] == "prior" and fitted["models"][kind]["n"] == 0
        assert fitted["models"][kind]["coef"] == default_calibration()["models"][kind]["coef"]
    assert "claim_validity" not in fitted["models"]                            # no prior, no rows: uncalibrated


def test_promotion_gate_accepts_the_shipped_prior_and_rejects_a_file_missing_a_scored_kind():
    from engine.confidence import default_calibration
    from eval.calibration import acceptance

    assert acceptance(default_calibration()) == []
    only_cause = {"version": "t", "models": {"cause": default_calibration()["models"]["cause"]}}
    problems = acceptance(only_cause)
    assert "missing model: voucher" in problems and "missing model: release" in problems
    flat = {"version": "t", "models": {k: {"features": ["precedent_count"], "coef": [0.0], "intercept": 0.0}
                                      for k in ("cause", "voucher", "release")}}
    assert any("NS31@2025-01-24" in p for p in acceptance(flat))             # p = 0.5 everywhere breaks bands
