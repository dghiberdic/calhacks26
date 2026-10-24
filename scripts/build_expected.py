#!/usr/bin/env python3
"""D0b: write contracts/fixtures/golden/expected/*.json + SHA256SUMS from the PLAN's numbers.

Sources: IMPLEMENTATION_PLAN.md §1.2–1.4 and CONTRACTS.md §5. Nothing here imports or calls engine/ or books/.
The only world input is the golden world's construction (which coupon took which election), read from world.json.

expected/ is frozen once written: this script refuses to overwrite it unless --force, and contracts/tests checks
SHA256SUMS. Changing a golden number needs a CHANGELOG entry and telling everyone (CONTRACTS §5).

Usage: uv run python scripts/build_expected.py [--force]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.models import Rollforward, RollforwardRow, World  # noqa: E402

GOLDEN = ROOT / "contracts" / "fixtures" / "golden"
OUT = GOLDEN / "expected"
EOWYN, HERMINIA, ISHA = "EIDW@2025-01-24", "EIDW@2025-01-26", "EIDW@2024-01-21"
NS31 = "NS31@2025-01-24"
KNOCK = ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"]

# ---------------------------------------------------------------- CONTRACTS §5 golden numbers (cents)
GOLDEN_NUMBERS: dict[str, Any] = {
    "_about": "CONTRACTS.md §5 golden numbers (cents) and plan §1.3; tests assert them. Change only via CHANGELOG.",
    "total_passengers": 5292,
    "cancelled": 27, "operated": 11, "weather": 23, "knock_on": 3, "technical": 1,
    "ns31_entitlement_cents": 9_900_000,
    "ns31_day1_liability_cents": 3_465_000,
    "storm_day1_liability_cents": 8_214_600,
    "knock_on_accruals_cents": {"NS113@2025-01-24": 1_922_400, "NS115@2025-01-24": 1_987_200,
                                "NS117@2025-01-24": 840_000},
    "after_r_leg_1_liability_cents": 3_465_000,
    "r_leg_1_delta_cents": -4_749_600,
    "ns31_jan_claims_cents": 360_000, "ns31_jan_claims_count": 6, "jan_close_cents": 3_105_000,
    "ns31_feb_claims_cents": 930_000, "ns31_feb_claims_count": 16, "feb_before_reestimate_cents": 2_175_000,
    "feb_expected_at_m1_cents": 891_000, "feb_actual_to_date_cents": 1_290_000,
    "feb_change_in_estimate_cents": 399_000,
    "feb_close_cents": 2_574_000,
    "actual_vs_expected_feb": 1.448,
    "sensitivity_5pp_cents": 495_000,
    "care_accrued_cents": 22_700_000, "care_invoiced_cents": 22_130_000, "care_reversal_cents": 570_000,
    "refund_clearing_2125_after_books_cents": 0,
    "isha_tail_kept_cents": 360_000,
    "isha_entitlement_cents": 6_000_000, "isha_claimed_pct_m12": 0.29,
    "expected_ultimate_claim_rate": {"long_haul_gt3500": 0.35, "medium_1500_3500": 0.27, "short_le1500": 0.20},
    "cfo_bridge": {"cash_basis_cents": 0, "full_entitlement_cents": 9_900_000, "drafted_liability_cents": 3_465_000,
                   "sensitivity_5pp_cents": 495_000},
    "herminia": {"in_lieu_unsigned_eu_departures": 31, "in_lieu_unsigned_non_eu": 1, "settled_after_r_cl_1": 31,
                 "r_cl_1_cited": 31, "asks_again": 1},
    "q2_rule_cited": 3,
    "repeat_questions": 0,
}

# ---------------------------------------------------------------- decisions (plan §1.2; compare the 5-tuple exactly)
AUTO = {"outcome": "auto", "routed_to": None, "confidence": {"min": 0.90}}


def weather() -> dict[str, Any]:
    return {"cause": "weather", "extraordinary": "extraordinary", "recoded": False, "recode_label": None, **AUTO}


def technical(recode: str | None) -> dict[str, Any]:
    return {"cause": "technical", "extraordinary": "not_extraordinary", "recoded": recode is not None,
            "recode_label": recode, **AUTO}


KNOCK_DECISION = {"cause": "knock_on", "extraordinary": "needs_legal", "recoded": False, "recode_label": None,
                  "outcome": "escalated", "routed_to": "legal", "confidence": {"max": 0.60}}


def decisions(world: World) -> dict[str, Any]:
    g = world.meta["groups"]
    eowyn: dict[str, Any] = {}
    for fid in g["outbound_weather"] + g["return_weather"] + g["overnight_inbound"]:
        eowyn[fid] = weather()
    for fid in g["knock_on"]:
        eowyn[fid] = dict(KNOCK_DECISION)
    eowyn[NS31] = technical("71 → 41")
    herminia = {"NS106@2025-01-26": technical("71 → 41"),
                "NS110@2025-01-26": technical(None), "NS30@2025-01-25": technical(None),
                "NS114@2025-01-26": weather()}
    assert len(eowyn) == 27
    return {
        "_about": ("Expected flight decisions by construction of the golden world (plan §1.2). Compare "
                   "(cause, extraordinary, recoded, outcome, routed_to) exactly; recode_label exactly where given; "
                   "confidence by band only (min/max); never the reason text. Operated flights have no decision."),
        "compare": ["cause", "extraordinary", "recoded", "outcome", "routed_to"],
        "storms": {EOWYN: dict(sorted(eowyn.items())), HERMINIA: dict(sorted(herminia.items()))},
        "operated": {EOWYN: sorted(g["operated"]), HERMINIA: sorted(g["h_operated"])},
    }


# ---------------------------------------------------------------- questions (plan §1.4)
def questions(world: World) -> dict[str, Any]:
    h = world.meta["herminia"]
    return {
        "_about": ("Expected escalations (plan §1.4). Match by pattern, not by question id. One question per "
                   "(pattern, storm). Confidence by band; plan_confidence is the plan's illustrative value."),
        "storms": {
            EOWYN: [
                {"key": "Q1", "pattern": "voucher_in_lieu_unsigned", "routed_to": "claims_lead",
                 "reason_tag": "sources-disagree", "case_refs": [f"{NS31}:14C"], "confidence_kind": "voucher",
                 "confidence": {"max": 0.60}, "plan_confidence": 0.39, "holds": [f"{NS31}:14C"],
                 "holds_cents": 60_000, "recommended_option_contains": "€600"},
                {"key": "Q2", "pattern": "knock_on_return", "routed_to": "legal", "reason_tag": "no-precedent",
                 "case_refs": KNOCK, "confidence_kind": "cause", "confidence": {"max": 0.60},
                 "plan_confidence": 0.47, "holds": KNOCK, "holds_cents": 4_749_600},
                {"key": "Q3", "pattern": "cohort_release", "routed_to": "controller",
                 "reason_tag": "release-proposal", "case_refs": [ISHA], "confidence_kind": "release",
                 "confidence": {"min": 0.60, "max": 0.90}, "plan_confidence": 0.72, "holds": [ISHA],
                 "holds_cents": 360_000, "trigger": "Isha cohort at M12 (2025-01 month end); a release proposal"},
            ],
        },
        "rulings": {
            "Q1": {"rule": "R-CL-1@1", "author_role": "claims_lead", "action": "deny_offset",
                   "scope_features_hint": ["voucher.in_lieu", "voucher.signed", "flight.departs_eu"],
                   "decision": "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
                   "herminia_settled": h["in_lieu_unsigned_eu_departures"],
                   "herminia_asks_again": {"pattern": "voucher_in_lieu_unsigned", "routed_to": "claims_lead",
                                           "case_refs": h["in_lieu_unsigned_non_eu"]},
                   "times_cited_on_herminia": 31,
                   "times_cited_after_herminia": 32},     # 14C itself + the 31 Herminia cases (as Q2 counts its 3)
            "Q2": {"rule": "R-LEG-1@1", "author_role": "legal", "action": "set_extraordinary",
                   "scope_features_hint": ["flight.is_return_sector", "rotation.prev_cancelled", "spare.available_within_h",
                                      "pax.reroute_earliest_offered"],
                   "settles": KNOCK, "times_cited": 3, "delta_cents": -4_749_600,
                   "liability_after_cents": 3_465_000},
            "Q3": {"rule": "R-CTL-1@1", "author_role": "controller", "ruling_kind": "rejection",
                   "action": "keep_tail", "keeps_cents": 360_000, "widen_next": "all storm cohorts"},
        },
        "challenges": {
            "storm_anyway": {"text": "The storm would have grounded it anyway", "classification": "assertion",
                             "decision_stands": True},
            "hidden_defect": {"text": "Airbus operator notice: hidden defect in this EDP batch",
                              "classification": "new_legal_pattern", "decision_stands": True, "routed_to": "legal",
                              "confidence": {"max": 0.60}, "plan_confidence": 0.52},
        },
        "repeat_questions": 0,
    }


# ---------------------------------------------------------------- NS31 entitlements (per coupon, by construction)
def entitlements_ns31(world: World) -> dict[str, Any]:
    el = {e.coupon_id: e for e in world.elections}
    refunded = {e.coupon_id for e in world.crm if e.kind in ("refund_initiated", "bsp_refund")}
    rows = []
    for c in sorted((c for c in world.coupons if c.flight_id == NS31), key=lambda c: c.id):
        e = el[c.id]
        reduced = e.kind in ("reroute_partner", "reaccommodated_own") and (e.arrival_delay_min or 10**6) <= 240
        rows.append({"coupon_id": c.id, "election": e.kind, "compensation_cents": 30_000 if reduced else 60_000,
                     "reduction": "art7_2_50pct" if reduced else "none",
                     "status": "needs_ruling" if c.id.endswith(":14C") else "owed",
                     "voucher_offset_cents": 0, "refund_already_initiated": c.id in refunded,
                     "refund_due_cents": 0, "care_due": True})
    total = sum(r["compensation_cents"] for r in rows)
    assert total == 9_900_000 and len(rows) == 172
    return {
        "_about": ("NS31 entitlements (plan §1.3): 158 × €600 + 14 × €300 (Art. 7(2)(c), with R-MINED-REDUCE "
                   "active) = €99,000. 14C is needs_ruling until Q1 (compensation 60,000, offset 0)."),
        "flight_id": NS31, "distance_km": 4804, "band_eur": 600, "band_margin_km": 1304,
        "requires_rules": ["R-MINED-REDUCE"],
        "summary": {"coupons": 172, "compensation_cents": total,
                    "status_counts": {"owed": 171, "needs_ruling": 1},
                    "reduction_counts": {"none": 158, "art7_2_50pct": 14},
                    "refund_already_initiated": sum(r["refund_already_initiated"] for r in rows),
                    "refund_due_cents": 0, "voucher_offset_cents": 0,
                    "without_r_mined_reduce_cents": 10_320_000},
        "coupons": rows,
    }


# ---------------------------------------------------------------- NS31 journals (plan §1.3; parked drafts)
def lines(*ls: tuple[str, int, int]) -> list[dict[str, Any]]:
    return [{"account": a, "dr_cents": dr, "cr_cents": cr} for a, dr, cr in ls]


def journal_ns31() -> dict[str, Any]:
    day1 = [
        {"kind": "compensation_estimate", "memo_has": "35%", "lines": lines(("4090", 3_465_000, 0),
                                                                            ("2140", 0, 3_465_000))},
        {"kind": "refund", "memo_has": "2125", "lines": lines(("2100", 1_440_000, 0), ("2110", 192_000, 0),
                                                             ("2125", 0, 1_632_000))},
        {"kind": "voucher", "lines": lines(("2100", 630_000, 0), ("2110", 84_000, 0), ("2131", 0, 714_000))},
        {"kind": "reroute_fim", "lines": lines(("2100", 630_000, 0), ("2110", 84_000, 0), ("2160", 0, 714_000))},
        {"kind": "voucher_in_lieu", "coupon": f"{NS31}:14C", "lines": lines(("4090", 30_000, 0), ("2132", 0, 30_000))},
    ]
    for je in day1:
        assert sum(x["dr_cents"] for x in je["lines"]) == sum(x["cr_cents"] for x in je["lines"])
    return {
        "_about": "NS31 journals per plan §1.3 (drafts, pending approval; StormCheck never posts beyond approved).",
        "external": [{"kind": "refund", "posted_by": "agent.crm_bot", "status": "posted",
                      "lines": lines(("2125", 1_632_000, 0), ("1110", 0, 1_632_000))}],
        "day1": day1,
        "jan": {"claims_approved": {"count": 6, "each": lines(("2140", 60_000, 0), ("2141", 0, 60_000)),
                                    "total_cents": 360_000},
                "payouts": {"count": 6, "each": lines(("2141", 60_000, 0), ("1000", 0, 60_000)), "gated": True,
                            "needs": "claims_lead"}},
        "feb": {"claims_approved": {"count": 16, "total_cents": 930_000, "face_values": {"60000": 15, "30000": 1}},
                "change_in_estimate": {"kind": "change_in_estimate", "ias8_class": "change_in_estimate",
                                       "needs": "controller",
                                       "lines": lines(("4090", 399_000, 0), ("2140", 0, 399_000))}},
        "balances": {"2140_day1_ns31": 3_465_000, "2140_jan_close_ns31": 3_105_000, "2140_feb_close_ns31": 2_574_000,
                     "2125_after_books": 0},
        "q1_after_r_cl_1": {"14C_claim_approved": lines(("2140", 60_000, 0), ("2141", 0, 60_000)),
                            "voucher_stays_goodwill": True},
    }


# ---------------------------------------------------------------- 2140 rollforward Feb 2025 (plan §1.3)
def rollforward_feb() -> dict[str, Any]:
    rows = [
        RollforwardRow(cohort=EOWYN, opening_cents=3_105_000, new_cents=0, claims_approved_cents=930_000,
                       change_in_estimate_cents=399_000, closing_cents=2_574_000,
                       unclaimed_entitlement_cents=9_900_000 - 360_000 - 930_000),
        RollforwardRow(cohort=ISHA, opening_cents=360_000, new_cents=0, claims_approved_cents=0,
                       change_in_estimate_cents=0, closing_cents=360_000,
                       unclaimed_entitlement_cents=6_000_000 - 1_740_000),
    ]
    rf = Rollforward(period="2025-02", rows=rows, closing_total_cents=2_934_000, gl_balance_cents=2_934_000,
                     ties_to_gl=True)
    doc = rf.model_dump(mode="json")
    doc["_about"] = ("2140 rollforward for Feb 2025 after the scripted flow: day-1 post; R-LEG-1 in Jan; 6 Jan claims; "
                     "Q3 rejected → R-CTL-1 (Isha tail kept); 16 Feb claims; Feb month end (BF). Sign convention as "
                     "books/DECISIONS.md: claims positive magnitudes, changes signed.")
    return doc


def sums(paths: list[Path]) -> str:
    return "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(paths))


def main(argv: list[str]) -> int:
    if OUT.exists() and any(OUT.iterdir()) and "--force" not in argv:
        print("expected/ already exists and is frozen (CONTRACTS §5). Use --force only with a CHANGELOG entry.")
        return 1
    world = World.model_validate_json((GOLDEN / "world.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    docs = {"golden_numbers.json": GOLDEN_NUMBERS, "decisions.json": decisions(world),
            "questions.json": questions(world), "entitlements_NS31.json": entitlements_ns31(world),
            "journal_NS31.json": journal_ns31(), "rollforward_2025-02.json": rollforward_feb()}
    paths = []
    for name, doc in docs.items():
        p = OUT / name
        p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
    (OUT / "SHA256SUMS").write_text(sums(paths), encoding="utf-8")
    print(f"wrote {len(paths)} files + SHA256SUMS to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
