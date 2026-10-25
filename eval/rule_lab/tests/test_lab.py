"""Exercise the isolated lab through its report boundary, using the real engine."""

from pathlib import Path

from eval.rule_lab.runner import run_lab


def test_scoped_ruling_settles_32_cases_without_changing_protected_cases_or_inputs():
    golden = Path(__file__).resolve().parents[3] / "contracts/fixtures/golden/world.json"
    original = golden.read_bytes()
    report = run_lab("scoped")
    assert report["verdict"] == "ready_for_review"
    assert report["summary"]["intended_cases"] == 32
    assert report["summary"]["failed_checks"] == 0
    assert all(c["passed"] for c in report["cases"])
    original_case = next(c for c in report["cases"] if c["id"] == "original-ruling")
    assert original_case["before"]["status"] == "needs_ruling"
    assert original_case["after"]["status"] == "owed"
    assert original_case["after"]["cash_cents"] == 60_000
    non_eu = next(c for c in report["cases"] if c["id"] == "non-eu-boundary")
    assert non_eu["after"]["status"] == "needs_ruling"
    assert report["candidate"]["status"] == "proposed"
    assert report["isolation"]["activated_rules"] == 0
    assert golden.read_bytes() == original


def test_removing_eu_scope_is_blocked_even_when_existing_proposal_gates_pass():
    report = run_lab("broader_scope")
    assert report["verdict"] == "blocked"
    assert all(c["passed"] for c in report["checks"] if c["group"] == "existing_engine")
    case = next(c for c in report["cases"] if c["id"] == "non-eu-boundary")
    assert not case["passed"]
    assert case["before"]["status"] == "needs_ruling"
    assert case["after"]["status"] == "owed"
    assert case["after"]["cash_cents"] == 60_000


def test_missing_consent_guard_is_blocked_even_though_engine_protects_signed_offset():
    report = run_lab("missing_guard")
    assert report["verdict"] == "blocked"
    signed = next(c for c in report["cases"] if c["id"] == "signed-consent")
    assert signed["before"] == signed["after"]
    assert signed["after"]["voucher_offset_cents"] == 30_000
    assert signed["after"]["cash_cents"] == 30_000
    assert signed["candidate_matches"] is True
    assert signed["expected_match"] is False
    assert signed["passed"] is False


def test_agent_authored_candidate_stops_before_simulation():
    report = run_lab("wrong_authority")
    assert report["verdict"] == "blocked"
    gate = next(c for c in report["checks"] if c["id"] == "engine:author_has_authority")
    assert not gate["passed"]
    assert report["cases"] == []
    assert report["simulation_ran"] is False


def test_passing_rule_preserves_accounting_controls_and_binds_repeatable_evidence():
    first = run_lab("scoped")
    second = run_lab("scoped")
    accounting = first["accounting"]
    assert accounting["liability_before_cents"] == 8_214_600
    assert accounting["liability_after_cents"] == 8_214_600
    assert accounting["new_entries_on_retry"] == 0
    assert accounting["unbalanced_entries"] == 0
    assert accounting["agent_approval_blocked"] is True
    assert accounting["approved_entries"] == 0
    assert len(first["fingerprints"]["test_pack_sha256"]) == 64
    assert first["fingerprints"] == second["fingerprints"]
    assert first == second


def test_protected_results_have_independent_amount_oracles():
    report = run_lab("scoped")
    protected = {c["id"]: c for c in report["cases"] if c["group"] == "protected"}
    assert protected["signed-consent"]["expected_result"] == {
        "status": "owed",
        "cash_cents": 30_000,
        "voucher_offset_cents": 30_000,
    }
    assert protected["staff-fare"]["expected_result"]["cash_cents"] == 0
    assert protected["early-notice"]["expected_result"]["status"] == "exempt_notice"
