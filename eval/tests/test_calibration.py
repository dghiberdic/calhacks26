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
    import pytest

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
    middle = bins["cause"][2]
    assert middle["n"] == 2
    assert middle["accuracy"] == 0.5
    assert middle["wilson_lo"] == pytest.approx(0.0945, abs=0.0001)
    assert middle["wilson_hi"] == pytest.approx(0.9055, abs=0.0001)
    assert coverage["cause"] == 0
    assert bins["voucher"] == []
