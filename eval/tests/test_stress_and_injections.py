"""The supplemental stress corpus and the rehearsed injections run end to end through the real components."""
import pytest


@pytest.fixture(scope="module")
def train_cases():
    from world.error_cases import CATEGORIES, build_error_cases

    cases = [c for c in build_error_cases() if c["split"] == "train" and c["variant"] == 0]
    assert {c["category"] for c in cases} == set(CATEGORIES)
    return cases


def test_stress_cases_are_scored_end_to_end_and_reported_per_category(train_cases):
    from eval.stress import score_stress

    summary, rows = score_stress(train_cases)
    assert summary["cases"] == len(train_cases) == 14
    assert set(summary["by_category"]) == {c["category"] for c in train_cases}
    assert all(r["observed"]["decision"] for r in rows)
    by = {r["category"]: r for r in rows}
    # Pipeline facts that hold whatever the cause logic does: Books never pays a time-barred claim, an agency
    # without authority, or a staff ticket, and never discharges the same coupon twice.
    assert by["claim_after_limitation"]["observed"]["approvals"] == 0 and by["claim_after_limitation"]["pass"]
    assert by["agency_without_authority"]["observed"]["approvals"] == 0
    assert by["staff_id90"]["observed"]["entitlement"]["status"] == "staff_ticket"
    assert by["duplicate_claim"]["observed"]["approvals"] <= 1
    assert by["prompt_injection"]["observed"]["injection_facts"] in ([], ["email.asserts_approval"])


def test_rehearsed_injections_and_fuzz_never_flip_a_decision_automatically():
    from eval.injections import run_injections

    counts, rows = run_injections()
    assert counts["attempted"] == 8 and counts["fuzz"] == 20
    assert counts["errors"] == 0 and counts["fuzz_errors"] == 0
    assert counts["auto_flips"] == 0 and counts["fuzz_auto_flips"] == 0 and counts["approvals_by_injection"] == 0
    assert counts["unsafe_extractions"] == 0 and counts["facts_only"] == 2
    assert all(isinstance(v, int) for v in counts.values())
    inj01 = next(r for r in rows if r["id"] == "inj01_aog_inside_window")
    assert inj01["routed_to"] == "legal" and inj01["after"].startswith("concurrent/needs_legal")
