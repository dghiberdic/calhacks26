"""D0b: api fixtures are regenerated from golden + fakes (up to date), match the plan, and the 8 injections exist."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from contracts.models import FlightFile, Injection, StormRun

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "contracts" / "fixtures" / "api"
INJ = ROOT / "contracts" / "fixtures" / "injections"
INJECTION_FILES = ["01_aog_inside_window", "02_duplicate_direct_plus_agency", "03_prompt_injection_email",
                   "04_chargeback_after_bot_refund", "05_airbus_hidden_defect_notice", "06_claim_after_limitation",
                   "07_challenge_storm_anyway", "08_uk261_520_on_dub_lhr"]


def test_api_fixtures_are_up_to_date():
    spec = importlib.util.spec_from_file_location("build_api_fixtures", ROOT / "scripts" / "build_api_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0, "run `make stub-fixtures` (scripts/build_api_fixtures.py)"


def test_eight_rehearsed_injections():
    files = sorted(p.stem for p in INJ.glob("*.json"))
    assert files == INJECTION_FILES
    listed = [Injection.model_validate(x) for x in json.loads((API / "injections.json").read_text())]
    for name in files:
        inj = Injection.model_validate_json((INJ / f"{name}.json").read_text())
        assert inj.id == name and inj in listed and inj.expected


def test_storm_fixture_has_the_plan_numbers():
    s = StormRun.model_validate_json((API / "storm_EIDW@2025-01-24.json").read_text())
    c = s.counters
    assert (c["passengers"], c["cancelled"], c["operated"], c["drafted"], c["held"], c["questions"], c["people"]) == (
        5292, 27, 11, 172, 530, 3, 3)
    assert (s.entitlement_cents, s.liability_drafted_cents) == (9_900_000, 8_214_600)
    conf = {q.id: round(q.confidence.score * 100) for q in s.questions}
    assert conf == {"Q-1": 39, "Q-2": 47, "Q-3": 72}
    ns31 = next(r.decision for r in s.flights if r.flight.id == "NS31@2025-01-24")
    assert round(ns31.confidence.score * 100) == 91 and ns31.recode_label == "71 → 41"
    world_ids = {c["id"] for c in json.loads((ROOT / "contracts/fixtures/golden/world.json").read_text())["coupons"]}
    ff = FlightFile.model_validate_json((API / "flight_NS31@2025-01-24.json").read_text())
    assert all(e.coupon_id in world_ids for e in ff.sample_entitlements)
    assert ff.handoff["refunds_already_initiated"] == 32 and ff.handoff["drafter_pii_seen"] == 0


def test_herminia_fixture_after_r_cl_1():
    h = StormRun.model_validate_json((API / "storm_EIDW@2025-01-26.json").read_text())
    (q,) = h.questions
    assert q.pattern == "voucher_in_lieu_unsigned" and q.case_refs[0].startswith("NS30@2025-01-25:")
    assert h.counters["settled_by_rule"] == 31
