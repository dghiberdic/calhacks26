"""F3c: planted errors (≥5 of each type per split), ambiguity, history, answer key, curves (from ground truth)."""
from __future__ import annotations

import collections

import orjson
import pytest

from world import answer_key as AK
from world import golden
from world import plant as PL
from world.generator import generated_history


@pytest.fixture(scope="module")
def keys(full_world):
    return AK.build(full_world)


@pytest.mark.parametrize("split", ["train", "test"])
def test_at_least_five_of_every_planted_type_per_split(keys, split):
    planted = keys[split]["planted"]
    missing = {t: planted.get(t, 0) for t in PL.ALL_TYPES if planted.get(t, 0) < PL.TARGET}
    assert not missing, missing


@pytest.mark.parametrize("split", ["train", "test"])
def test_about_five_percent_of_cancellations_are_feature_invisible(keys, split):
    flights = keys[split]["flights"]
    cancelled = [f for f in flights.values() if f["status"] == "cancelled"]
    amb = [f for f in cancelled if f.get("ambiguous")]
    assert 0.03 <= len(amb) / len(cancelled) <= 0.10
    assert all(f.get("note") for f in amb)


@pytest.mark.parametrize("split", ["train", "test"])
def test_committed_answer_key_is_reproducible(keys, split):
    committed = orjson.loads((AK.OUT_DIR / f"{split}.json").read_bytes())
    assert committed == orjson.loads(orjson.dumps(keys[split], option=orjson.OPT_SORT_KEYS))


def test_committed_curves_are_the_generated_ones(full_world):
    committed = orjson.loads((AK.OUT_DIR / "curves_train.json").read_bytes())
    assert committed == orjson.loads(orjson.dumps(AK.generated_curves(full_world)))
    lh = next(c for c in committed["curves"] if c["segment"] == "long_haul_gt3500")
    assert lh["n_by_point"][0] > 0
    for (m, got), (_, target) in zip(lh["points"], lh["target_points"]):
        assert abs(got - target) <= 0.01, (m, got, target)


def test_every_cancelled_flight_has_cause_and_extraordinary_and_coupons(keys):
    for split in ("train", "test"):
        k = keys[split]
        for fid, f in k["flights"].items():
            if f["status"] == "cancelled":
                assert f["cause"] and f["extraordinary"] in ("extraordinary", "not_extraordinary"), fid
                assert fid in k["coupons"], fid
                assert k["coupons"][fid]["n"] >= 1


@pytest.mark.skipif(not golden.available(), reason="golden not landed")
def test_golden_ns31_truth_is_the_plan_entitlement(keys):
    k = keys["test"]
    c = k["coupons"]["NS31@2025-01-24"]
    rows = [c["exceptions"].get(seat, c["default"]) for seat in _seats(c["n"])]
    assert sum(r.get("compensation_cents", 0) for r in rows) == 9_900_000
    assert k["flights"]["NS31@2025-01-24"]["recode_expected"] is True
    assert k["coupons"]["NS31@2025-01-24"]["exceptions"]["14C"]["handling"] == "pay_cash_voucher_stays_goodwill"
    for fid in ("NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"):
        assert k["coupons"][fid]["default"]["status"] == "no_compensation"
    assert k["storms"]["EIDW@2025-01-24"]["passengers_cancelled"] == 5292


def _seats(n):
    out, row = [], 1
    while len(out) < n:
        out += [f"{row}{c}" for c in "ABCDEF"]
        row += 1
    return out[:n]


def test_claim_truth_pays_each_coupon_once(full_world):
    covered = collections.Counter()
    tc = full_world.truth.coupons
    for cid, t in full_world.truth.claims.items():
        if t["valid"]:
            assert t["pay_cents"] == sum(tc[c]["pay_cents"] for c in t["covers"]), cid
            covered.update(t["covers"])
        else:
            assert t["pay_cents"] == 0 and t["covers"] == []
    assert max(covered.values()) == 1


def test_planted_claims_have_the_right_verdict(full_world):
    by_tag = collections.defaultdict(list)
    for t in full_world.truth.claims.values():
        for tag in t["planted"]:
            by_tag[tag].append(t)
    assert all(not t["valid"] for t in by_tag["claim_after_limitation"])
    assert all(not t["valid"] for t in by_tag["agency_authority_none"])
    assert all(not t["valid"] for t in by_tag["injection_email"])
    uk = by_tag["uk261_520_dub_lhr"]
    tc = full_world.truth.coupons
    # EU261's €250 band applies (not £520); pay = the coupon's true amount (7(2) half or net of a signed voucher)
    assert uk and all(t["valid"] and tc[t["coupon_id"]]["band_eur"] == 250
                      and t["pay_cents"] == tc[t["coupon_id"]]["pay_cents"] <= 25000 for t in uk)
    for tag in ("duplicate_direct_agency", "duplicate_two_agencies", "assignment_then_direct_payment"):
        verdicts = collections.Counter(t["valid"] for t in by_tag[tag])
        assert verdicts[True] >= 5 and verdicts[False] >= 5, tag


def test_generated_history_hides_the_41_of_42_policy(full_world):
    hist = generated_history(full_world.world, full_world.truth, 0)
    rr = [h for h in hist if h.kind == "reroute_reduction"]
    assert len(rr) == 42
    assert collections.Counter(h.decision for h in rr) == {"apply_7_2_reduction": 41, "no_reduction": 1}
    assert {"pax.election", "pax.arrival_delay_min", "flight.band_eur"} <= set(rr[0].features)
    assert any(h.kind == "cause" for h in hist)


@pytest.mark.skipif(not golden.available(), reason="golden not landed")
def test_embedded_world_keeps_goldens_own_history(full_world):
    ids = {h.ruling_id for h in full_world.world.history_cases}
    assert ids == set(golden.golden_ids().history)
