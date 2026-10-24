"""D0b: expected/ is frozen (SHA256SUMS), well-formed, internally consistent, and agrees with the golden world."""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import get_args

import pytest

from contracts.models import Cause, Extraordinary, FlightDecision, Question, Role, Rollforward, World

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts" / "fixtures" / "golden"
EXP = GOLDEN / "expected"
EOWYN, HERMINIA = "EIDW@2025-01-24", "EIDW@2025-01-26"


def load(name: str):
    return json.loads((EXP / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_text(encoding="utf-8"))


def test_sha256sums_cover_and_match_every_expected_file():
    listed = {}
    for line in (EXP / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    files = {p.name for p in EXP.iterdir() if p.name != "SHA256SUMS"}
    assert set(listed) == files, "every expected/ file is listed in SHA256SUMS (and nothing else)"
    for name, digest in listed.items():
        assert hashlib.sha256((EXP / name).read_bytes()).hexdigest() == digest, f"expected/{name} was edited"


def test_golden_numbers_reconcile():
    g = load("golden_numbers.json")
    r = lambda pct, base: int(Fraction(pct).limit_denominator(1000) * base)  # noqa: E731
    assert g["ns31_entitlement_cents"] == 158 * 60_000 + 14 * 30_000 == 9_900_000
    assert g["ns31_day1_liability_cents"] == r(0.35, 9_900_000) == 3_465_000
    k = g["knock_on_accruals_cents"]
    assert k == {"NS113@2025-01-24": 178 * 40_000 * 27 // 100, "NS115@2025-01-24": 184 * 40_000 * 27 // 100,
                 "NS117@2025-01-24": 168 * 25_000 * 20 // 100}
    assert g["storm_day1_liability_cents"] == 3_465_000 + sum(k.values()) == 8_214_600
    assert g["r_leg_1_delta_cents"] == -sum(k.values()) == -4_749_600
    assert g["after_r_leg_1_liability_cents"] == g["storm_day1_liability_cents"] + g["r_leg_1_delta_cents"]
    assert g["jan_close_cents"] == 3_465_000 - g["ns31_jan_claims_cents"] == 3_105_000
    assert g["ns31_feb_claims_cents"] == 15 * 60_000 + 30_000
    assert g["feb_before_reestimate_cents"] == g["jan_close_cents"] - g["ns31_feb_claims_cents"]
    assert g["feb_close_cents"] == r(0.35 - 0.09, 9_900_000) == 2_574_000
    assert g["feb_change_in_estimate_cents"] == g["feb_close_cents"] - g["feb_before_reestimate_cents"] == 399_000
    assert g["feb_expected_at_m1_cents"] == r(0.09, 9_900_000)
    assert g["feb_actual_to_date_cents"] == 360_000 + 930_000
    assert round(g["feb_actual_to_date_cents"] / g["feb_expected_at_m1_cents"], 3) == g["actual_vs_expected_feb"]
    assert g["sensitivity_5pp_cents"] == r(0.05, 9_900_000)
    assert g["care_accrued_cents"] - g["care_invoiced_cents"] == g["care_reversal_cents"] == 570_000
    assert g["isha_tail_kept_cents"] == r(0.35 - 0.29, g["isha_entitlement_cents"])
    assert g["weather"] + g["knock_on"] + g["technical"] == g["cancelled"] == 27


def test_decisions_shape_and_counts(world: World):
    d = load("decisions.json")
    causes, exts = {c.value for c in Cause}, {e.value for e in Extraordinary}
    outcomes = set(get_args(FlightDecision.model_fields["outcome"].annotation))
    roles = {r.value for r in Role}
    for storm, rows in d["storms"].items():
        for fid, row in rows.items():
            assert row["cause"] in causes and row["extraordinary"] in exts and row["outcome"] in outcomes
            assert row["routed_to"] is None or row["routed_to"] in roles
            assert isinstance(row["recoded"], bool) and (row["recode_label"] is not None) == row["recoded"]
            assert set(row) >= set(d["compare"])
    eowyn = d["storms"][EOWYN]
    cancelled = {i for i in world.meta["storms"][EOWYN]["flight_ids"]
                 if next(f for f in world.flights if f.id == i).status == "cancelled"}
    assert set(eowyn) == cancelled
    from collections import Counter
    assert Counter(r["cause"] for r in eowyn.values()) == {"weather": 23, "knock_on": 3, "technical": 1}
    assert eowyn["NS31@2025-01-24"]["recode_label"] == "71 → 41" and eowyn["NS31@2025-01-24"]["confidence"] == {"min": 0.9}
    assert all(r["routed_to"] == "legal" and r["confidence"] == {"max": 0.6} for r in eowyn.values()
               if r["cause"] == "knock_on")
    herminia_cancelled = {i for i in world.meta["storms"][HERMINIA]["flight_ids"]
                          if next(f for f in world.flights if f.id == i).status == "cancelled"}
    assert set(d["storms"][HERMINIA]) == herminia_cancelled


def test_questions_match_world_and_models(world: World):
    q = load("questions.json")
    tags = set(get_args(Question.model_fields["reason_tag"].annotation))
    roles = {r.value for r in Role}
    qs = q["storms"][EOWYN]
    assert [x["key"] for x in qs] == ["Q1", "Q2", "Q3"]
    assert {x["routed_to"] for x in qs} == {"claims_lead", "legal", "controller"}, "3 questions · 3 people"
    for x in qs:
        assert x["reason_tag"] in tags and x["routed_to"] in roles
        lo, hi = x["confidence"].get("min", 0.0), x["confidence"].get("max", 1.0)
        assert lo <= x["plan_confidence"] < hi
    q1 = q["rulings"]["Q1"]
    h = world.meta["herminia"]
    assert q1["herminia_settled"] == h["in_lieu_unsigned_eu_departures"] and len(q1["herminia_settled"]) == 31
    assert q1["herminia_asks_again"]["case_refs"] == h["in_lieu_unsigned_non_eu"]
    assert q["rulings"]["Q2"]["delta_cents"] == load("golden_numbers.json")["r_leg_1_delta_cents"]


def test_ns31_entitlements_match_world(world: World):
    e = load("entitlements_NS31.json")
    rows = e["coupons"]
    assert len(rows) == 172 == e["summary"]["coupons"]
    assert sum(r["compensation_cents"] for r in rows) == 9_900_000 == e["summary"]["compensation_cents"]
    assert {r["coupon_id"] for r in rows} == {c.id for c in world.coupons if c.flight_id == "NS31@2025-01-24"}
    r14 = next(r for r in rows if r["coupon_id"].endswith(":14C"))
    assert (r14["status"], r14["compensation_cents"], r14["voucher_offset_cents"]) == ("needs_ruling", 60_000, 0)
    assert sum(r["refund_already_initiated"] for r in rows) == 32
    assert e["summary"]["without_r_mined_reduce_cents"] == 172 * 60_000


def test_journal_ns31_balances():
    j = load("journal_NS31.json")
    entries = [*j["external"], *j["day1"], {"lines": j["feb"]["change_in_estimate"]["lines"]}]
    for je in entries:
        assert sum(x["dr_cents"] for x in je["lines"]) == sum(x["cr_cents"] for x in je["lines"])
    clearing = sum(x["dr_cents"] - x["cr_cents"] for je in [*j["external"], *j["day1"]] for x in je["lines"]
                   if x["account"] == "2125")
    assert clearing == 0 == j["balances"]["2125_after_books"]
    atl = sum(x["dr_cents"] for je in j["day1"] for x in je["lines"] if x["account"] == "2100")
    assert atl == 1_440_000 + 630_000 + 630_000


def test_rollforward_feb_is_a_valid_tying_rollforward():
    doc = load("rollforward_2025-02.json")
    doc.pop("_about")
    rf = Rollforward.model_validate(doc)
    for r in rf.rows:
        assert (r.opening_cents + r.new_cents - r.claims_approved_cents - r.settled_in_kind_cents
                - r.derecognised_cents + r.change_in_estimate_cents + r.recode_cents + r.out_of_period_cents
                == r.closing_cents)
    assert sum(r.closing_cents for r in rf.rows) == rf.closing_total_cents == rf.gl_balance_cents and rf.ties_to_gl
    eowyn = next(r for r in rf.rows if r.cohort == EOWYN)
    assert (eowyn.opening_cents, eowyn.claims_approved_cents, eowyn.change_in_estimate_cents, eowyn.closing_cents) == (
        3_105_000, 930_000, 399_000, 2_574_000)
