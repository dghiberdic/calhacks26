"""F3b: coupons, elections, CRM bot / BSP, service-desk vouchers, claims from €-curves, care costs."""
from __future__ import annotations

import collections
from datetime import timedelta

import pytest

from world import golden
from world import pax as P


def generated(full_world):
    """Records of generated (non-golden, non-legacy) flights only."""
    gids = golden.golden_ids().flights if golden.available() else frozenset()
    w = full_world.world
    legacy = {fid for m in w.meta.get("legacy", []) for fid in m["flights"]}
    flights = {f.id: f for f in w.flights if f.id not in gids and f.id not in legacy}
    coupons = [c for c in w.coupons if c.flight_id in flights]
    cids = {c.id for c in coupons}
    return w, flights, coupons, cids


def test_every_cancelled_flight_has_its_manifest_of_coupons(full_world):
    w, flights, coupons, _ = generated(full_world)
    per = collections.Counter(c.flight_id for c in coupons)
    for f in flights.values():
        assert per.get(f.id, 0) == (f.pax if f.status == "cancelled" else 0), f.id
    assert len({c.id for c in coupons}) == len(coupons)
    srcs = {s.id for s in w.sources}
    assert all(f"SRC-MANIFEST-{f.id}" in srcs for f in flights.values() if f.status == "cancelled")


def test_election_mix_matches_the_plan(full_world):
    w, _, coupons, cids = generated(full_world)
    kinds = collections.Counter(e.kind for e in w.elections if e.coupon_id in cids)
    n = sum(kinds.values())
    assert n == len(coupons)
    for kind, target in (("refund", 0.19), ("voucher", 0.08), ("reaccommodated_own", 0.64), ("reroute_partner", 0.09)):
        assert abs(kinds[kind] / n - target) < 0.03, (kind, kinds[kind] / n)


def test_fares_channels_staff_and_lead_bookers(full_world):
    _, _, coupons, _ = generated(full_world)
    n = len(coupons)
    staff = sum(c.fare_type == "staff_id90" for c in coupons)
    assert 0.005 < staff / n < 0.02
    ch = collections.Counter(c.channel for c in coupons)
    assert 0.6 < ch["direct"] / n < 0.8 and ch["ota"] and ch["agency_gds"]
    assert any(c.lead_booker for c in coupons)
    assert all(c.fare_cents > 0 and c.taxes_cents > 0 for c in coupons)


def test_crm_bot_refunds_direct_coupons_and_bsp_the_rest(full_world):
    w, flights, coupons, cids = generated(full_world)
    cmap = {c.id: c for c in coupons}
    for e in w.crm:
        if e.coupon_id not in cids:
            continue
        c = cmap[e.coupon_id]
        if e.kind == "refund_initiated":
            assert e.actor == "agent.crm_bot" and c.channel == "direct"
            assert e.amount_cents == c.fare_cents + c.taxes_cents
            f = flights[c.flight_id]
            assert ("RSN WX CNL" in e.text) == (f.ops_cause_code in ("71", "72"))
        if e.kind == "bsp_refund":
            planted = "crm_bot_plus_bsp_refund" in full_world.truth.coupons[c.id].get("planted", [])
            assert (c.channel != "direct" or planted) and e.at > flights[c.flight_id].notified_at


def test_service_desk_vouchers_in_lieu_about_60pct_signed(full_world):
    w, _, _, cids = generated(full_world)
    vil = [e for e in w.crm if e.kind == "voucher_in_lieu_of_compensation" and e.coupon_id in cids]
    assert len(vil) > 100
    signed = sum(bool(e.signed_acceptance_sha256) for e in vil) / len(vil)
    assert 0.5 < signed < 0.7
    srcs = {s.id for s in w.sources}
    assert all(f"SRC-{e.id}" in srcs for e in vil)


def test_coupon_truth_follows_flight_truth(full_world):
    w, flights, coupons, _ = generated(full_world)
    tf, tc = full_world.truth.flights, full_world.truth.coupons
    for c in coupons:
        t = tc[c.id]
        ft = tf[c.flight_id]
        if c.fare_type == "staff_id90":
            assert t["status"] == "staff_ticket" and t["compensation_cents"] == 0
        elif ft.extraordinary == "extraordinary":
            assert t["status"] == "no_compensation" and t["compensation_cents"] == 0
        elif t["status"] == "owed":
            band = t["band_eur"] * 100
            assert t["compensation_cents"] == (band // 2 if t["reduction"] == "art7_2_50pct" else band)
            assert t["pay_cents"] == t["compensation_cents"] - t["voucher_offset_cents"]


def test_claims_agencies_overnight_and_uk261(full_world):
    w, flights, coupons, cids = generated(full_world)
    claims = [c for c in w.claims if c.coupon_id in cids]
    truth = full_world.truth.claims
    valid = [c for c in claims if truth[c.id]["valid"]]
    assert valid and len(claims) > len(valid)
    agency = [c for c in valid if c.channel == "agency"]
    assert 0.2 < len(agency) / len(valid) < 0.4
    assert {c.authority for c in agency} <= {"poa", "assignment"}
    cmap = {c.id: c for c in coupons}
    overnight = [c for c in valid if c.received_at - flights[cmap[c.coupon_id].flight_id].sched_dep < timedelta(hours=20)]
    assert overnight
    assert any(c.currency_regime == "UK261" for c in claims)
    srcs = {s.id for s in w.sources}
    assert all(f"SRC-{c.id}" in srcs for c in claims)


def test_claims_reproduce_the_eur_curves_within_1pp_on_the_learn_split(full_world):
    """The generated LH (and medium/short) curves are within ±1 pp of curves.json at every point."""
    from world.answer_key import generated_curves

    curves = generated_curves(full_world, "train")["curves"]
    assert {c["segment"] for c in curves} == {"long_haul_gt3500", "medium_1500_3500", "short_le1500"}
    for c in curves:
        for (m, got), (m2, target), n in zip(c["points"], c["target_points"], c["n_by_point"]):
            assert m == m2 and n > 0
            assert abs(got - target) <= 0.01, (c["segment"], m, got, target)


def test_care_accrual_and_invoice_rows(full_world):
    w, flights, _, _ = generated(full_world)
    care = [c for c in w.care if c.flight_id in flights]
    kinds = collections.Counter((c.kind, c.invoiced) for c in care)
    n_cancel = sum(f.status == "cancelled" for f in flights.values())
    for kind in ("hotel", "meal", "transport"):
        assert kinds[(kind, False)] == n_cancel and kinds[(kind, True)] == n_cancel
    assert all(c.amount_cents >= 0 for c in care)


@pytest.mark.parametrize("delay,band,reduced", [(120, 250, True), (125, 250, False), (240, 600, True), (241, 600, False)])
def test_art7_2_reduction_limits(delay, band, reduced):
    assert (delay <= P.REDUCTION_LIMIT_MIN[band]) is reduced
