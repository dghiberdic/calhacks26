from eval.evaluate import summarize


def test_metrics_count_passengers_and_only_genuine_weather_miscodes():
    rows = [
        {"split": "test", "day": "2025-02-01", "flight_id": "A", "passengers": 100,
         "auto_passengers": 80, "correct": True, "miscoded": True, "caught": True,
         "truth_pay_cents": 6000000, "false_hold": False, "preview_cents": 2100000,
         "ultimate_cents": 2100000, "claimed_cents": 1000000},
        {"split": "test", "day": "2025-02-01", "flight_id": "B", "passengers": 50,
         "auto_passengers": 0, "correct": False, "miscoded": False, "caught": False,
         "truth_pay_cents": 0, "false_hold": True, "preview_cents": 500000,
         "ultimate_cents": 0, "claimed_cents": 0},
        {"split": "train", "day": "2024-01-01", "flight_id": "C", "passengers": 999,
         "auto_passengers": 999, "correct": True, "miscoded": True, "caught": True,
         "truth_pay_cents": 999, "false_hold": False, "preview_cents": 999,
         "ultimate_cents": 999, "claimed_cents": 999},
    ]
    m = summarize(rows)
    assert m["n_passengers"] == 150
    assert m["straight_through_pct"] == 53.333333
    assert (m["miscodes_caught"], m["miscodes_total"], m["miscodes_eur_cents"]) == (1, 1, 6000000)
    assert m["false_holds"] == 1
    assert m["liability_vs_actual"]["preview_eur"] == 26000
    assert m["liability_vs_actual"]["ultimate_expected_eur"] == 21000


def test_golden_replay_measures_rulings_scope_and_identical_accounting():
    from eval.golden_flow import replay_three

    result, controls = replay_three()
    assert result["liability_eur"] == [34650, 34650, 34650]
    assert result["pre_legal_liability_eur"] == [82146, 82146, 82146]
    assert result["hash_identical"] is True
    assert len(set(result["hashes"])) == 1
    assert controls == {"repeat_questions": 0, "out_of_scope_auto": 0,
                        "in_scope_coupons": 31, "out_of_scope_questions": 1}
