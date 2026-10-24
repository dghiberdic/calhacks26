import pytest

from eval.evaluate import summarize


def test_metrics_count_passengers_and_only_genuine_weather_miscodes():
    rows = [
        {"split": "test", "day": "2025-02-01", "flight_id": "A", "golden": True, "passengers": 100,
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
    assert m["liability_vs_actual"]["non_golden_cancellations"] == 1
    assert m["liability_vs_actual"]["non_golden_cause_accuracy"] == 0
    assert m["liability_vs_actual"]["curated_golden_cancellations"] == 1


def test_golden_replay_measures_rulings_scope_and_identical_accounting():
    from eval.golden_flow import replay_three

    result, controls = replay_three()
    assert result["liability_eur"] == [34650, 34650, 34650]
    assert result["pre_legal_liability_eur"] == [82146, 82146, 82146]
    assert result["hash_identical"] is True
    assert result["tail_kept_eur"] == [3600, 3600, 3600]
    assert result["unconfirmed_widen_applied"] is False
    assert len(set(result["hashes"])) == 1
    assert controls == {"repeat_questions": 0, "out_of_scope_auto": 0,
                        "in_scope_coupons": 31, "out_of_scope_questions": 1}


def test_cause_matches_carries_an_internal_root_through_its_knock_on():
    from eval.evaluate import cause_matches

    ko_internal = {"cause": "knock_on", "latent": "rotation", "root_latent": "internal_aog"}
    ko_storm = {"cause": "knock_on", "latent": "rotation", "root_latent": "weather_dep"}
    assert cause_matches("technical", ko_internal) and cause_matches("knock_on", ko_internal)
    assert not cause_matches("technical", ko_storm) and not cause_matches("weather", ko_internal)
    assert cause_matches("knock_on", {"cause": "technical", "latent": "internal_aog"})
    assert not cause_matches("knock_on", {"cause": "technical", "latent": "external_hit"})
    assert not cause_matches("concurrent", {"cause": "technical", "latent": "internal_aog"})


def test_an_abstention_is_never_a_settled_answer_and_escalations_are_scored_by_route():
    from eval.evaluate import outcome_class, settled_right

    legal = {"cause": "knock_on", "extraordinary": "extraordinary", "root_latent": "weather_dep",
             "expected_route": "legal"}
    assert not settled_right("knock_on", "needs_legal", legal)
    assert settled_right("knock_on", "extraordinary", legal)
    assert outcome_class("escalated", "legal", False, "legal") == "escalated_correct"
    assert outcome_class("escalated", "ops", False, "legal") == "held_other"
    assert outcome_class("human", None, True, None) == "held_other"
    assert outcome_class("auto", None, True, None) == "auto_correct"
    assert outcome_class("auto", None, False, "legal") == "auto_wrong"


def test_outcome_classes_headline_auto_precision_separately_from_straight_through():
    base = {"split": "test", "day": "2025-02-01", "passengers": 10, "truth_pay_cents": 0, "false_hold": False,
            "preview_cents": 0, "ultimate_cents": 0, "claimed_cents": 0, "miscoded": False, "caught": False,
            "exact": False, "correct": False, "golden": False}
    rows = [dict(base, flight_id="A", outcome_class="auto_correct", auto_passengers=10, correct=True, exact=True),
            dict(base, flight_id="B", outcome_class="auto_wrong", auto_passengers=10, ambiguous=True),
            dict(base, flight_id="C", outcome_class="escalated_correct", auto_passengers=0),
            dict(base, flight_id="D", outcome_class="held_other", auto_passengers=0, false_hold=True)]
    m = summarize(rows)
    lva = m["liability_vs_actual"]
    assert lva["auto_precision"] == 0.5 and lva["auto_wrong"] == 1 and lva["ambiguous_auto_wrong"] == 1
    assert lva["right_or_correctly_escalated"] == 0.5
    assert m["straight_through_pct"] == 50.0 and m["false_holds"] == 1


def test_liability_vs_actual_uses_train_curves_on_generated_cohorts_only():
    from eval.evaluate import liability_vs_actual

    rows = [{"golden": False, "accrual_by_segment": {"long_haul_gt3500": 100_000},
             "claims_by_month": {"1": 9_000, "3": 20_000, "6": 24_000}},
            {"golden": True, "accrual_by_segment": {"long_haul_gt3500": 999_999},
             "claims_by_month": {"1": 1, "3": 1, "6": 1}}]
    out = liability_vs_actual(rows, {"long_haul_gt3500": {1: 0.09, 3: 0.17, 6: 0.24}})
    assert out["m1_expected_eur"] == 90.0 and out["m1_actual_eur"] == 90.0 and out["m1_actual_over_expected"] == 1.0
    assert out["m3_actual_over_expected"] == pytest.approx(20_000 / 17_000, abs=1e-4)


def test_scripted_ruling_is_drafted_by_the_engine_template_with_the_plan_words():
    from datetime import UTC, datetime

    from contracts.fakes import golden_world
    from contracts.models import Confidence, Question, Role, RuleAction
    from eval.evaluate import Scope, scripted_rule

    world = golden_world()
    at = datetime(2025, 1, 25, 11, tzinfo=UTC)
    q = Question(id="Q-1", case_refs=["NS31@2025-01-24:14C"], pattern="voucher_in_lieu_unsigned",
                 routed_to=Role.CLAIMS_LEAD, asked_at=at, title="t", found="f", why_flagged="w", recommends="r",
                 recommended_option="Pay €600 cash; the voucher stays as goodwill", options=[], evidence=[],
                 confidence=Confidence(score=0.39, kind="voucher", label="l", features={}, calibration_version="t"),
                 reason_tag="sources-disagree")
    rule = scripted_rule(q, world, at)
    assert rule.id == "R-CL-1" and rule.action == RuleAction.DENY_OFFSET and rule.status == "active"
    assert rule.scope == {"flight.departs_eu": True} and rule.recorded_at == at and rule.tier == "claims_lead_ruling"
    scope = Scope(world, {})
    assert scope.covers("voucher_in_lieu_unsigned", "NS31@2025-01-24:14C")
    assert not scope.covers("voucher_in_lieu_unsigned", "NS31@2025-01-24:1A")
    assert scope.covers("cohort_release", "EIDW@2024-01-21")
