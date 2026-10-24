"""Domain-review probes (p5, p7, p8, p9) as regressions on the golden world (contracts/fixtures/golden/world.json)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.models import CrmEvent, Extraordinary, Role, Rule, RuleAction, World
from engine import eu261
from engine.confidence import default_calibration
from engine.engine import Engine

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden" / "world.json"
EOWYN = "EIDW@2025-01-24"
NS31 = "NS31@2025-01-24"
REDUCE = Rule(id="R-MINED-REDUCE", version=1, kind="mined_policy", scope={},
              condition={"all": [{"f": "pax.election", "op": "in", "v": ["reroute_partner", "reaccommodated_own"]}]},
              action=RuleAction.APPLY_7_2_REDUCTION, tier="mined", authority_required=Role.CLAIMS_LEAD,
              valid_from=None, recorded_at=datetime(2025, 1, 1, tzinfo=UTC), status="active", support="41 of 42")


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json(GOLDEN.read_bytes())


def known_at(world: World) -> datetime:
    return datetime.fromisoformat(world.meta["storms"][EOWYN]["known_at"].replace("Z", "+00:00"))


def decide(world: World, rules=(REDUCE,)):
    return Engine(world, calibration=default_calibration()).decide_in(world, NS31, list(rules), known_at(world))


@pytest.fixture(scope="module")
def ns31(world):
    d = decide(world)
    return d, {e.coupon_id: e for e in eu261.entitlements(d, world, [REDUCE], d.known_at)}


def test_p9_golden_refund_vouchers_were_chosen_by_the_passenger(world, ns31):
    """The 14 NS31 passengers who elected a refund voucher chose it themselves on the web (plan §1.3 books them to
    2131), so Art. 8 is settled in kind. 14C's service-desk voucher *in lieu of compensation* is unsigned: it is Q1."""
    _, ents = ns31
    vouchers = [e for e in world.elections if e.coupon_id.startswith(NS31 + ":") and e.kind == "voucher"]
    assert len(vouchers) == 14 and {e.recorded_by for e in vouchers} == {"web"}
    assert all(ents[e.coupon_id].refund_due_cents == 0 and "signed agreement" not in ents[e.coupon_id].reason
               for e in vouchers)
    in_lieu = [e for e in world.crm if e.coupon_id == f"{NS31}:14C" and e.kind == "voucher_in_lieu_of_compensation"]
    assert len(in_lieu) == 1 and in_lieu[0].signed_acceptance_sha256 is None
    assert ents[f"{NS31}:14C"].status == "needs_ruling"


@pytest.mark.parametrize("by", ["service-desk", "call-centre", "crm-bot", "occ"])
def test_p9_voucher_recorded_for_the_passenger_needs_a_signed_event(world, by):
    w = world.model_copy(deep=True)
    el = next(e for e in w.elections if e.coupon_id.startswith(NS31 + ":") and e.kind == "voucher")
    el.recorded_by = by
    d = decide(w)
    e = next(x for x in eu261.entitlements(d, w, [REDUCE], d.known_at) if x.coupon_id == el.coupon_id)
    assert e.refund_due_cents == 51_000 and "signed agreement" in e.reason        # golden voucher_issued is unsigned
    for ev in w.crm:
        if ev.coupon_id == el.coupon_id and ev.kind == "voucher_issued":
            ev.signed_acceptance_sha256 = "cd" * 32
    e = next(x for x in eu261.entitlements(d, w, [REDUCE], d.known_at) if x.coupon_id == el.coupon_id)
    assert e.refund_due_cents == 0


def test_p5_chargeback_only_is_not_refunded_again(world):
    w = world.model_copy(deep=True)
    cid = next(e.coupon_id for e in w.elections if e.coupon_id.startswith(NS31 + ":")
               and e.kind == "reaccommodated_own")
    c = next(x for x in w.coupons if x.id == cid)
    w.crm = [x for x in w.crm if x.coupon_id != cid] + [CrmEvent(
        id="CRM-CB-TEST", coupon_id=cid, at=datetime(2025, 1, 24, 20, 0, tzinfo=UTC), kind="chargeback",
        amount_cents=c.fare_cents + c.taxes_cents, actor="acquirer",
        text="Chargeback 4855 goods/services not provided")]
    d = decide(w)
    e = next(x for x in eu261.entitlements(d, w, [REDUCE], d.known_at) if x.coupon_id == cid)
    assert e.refund_due_cents == 0 and e.refund_already_initiated and "duplicate" in e.reason
    assert e.status == "owed"


def test_p7_mined_allow_offset_does_not_offset_14c(world):
    mined_offset = Rule(id="R-MINED-OFFSET", version=1, kind="mined_policy", scope={},
                        condition={"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True}]},
                        action=RuleAction.ALLOW_OFFSET, tier="mined", authority_required=Role.CLAIMS_LEAD,
                        valid_from=None, recorded_at=datetime(2024, 12, 30, tzinfo=UTC), status="active",
                        support="9 of 9")
    d = decide(world, (REDUCE, mined_offset))
    e = next(x for x in eu261.entitlements(d, world, [REDUCE, mined_offset], d.known_at)
             if x.coupon_id.endswith(":14C"))
    assert e.status == "needs_ruling" and e.voucher_offset_cents == 0 and e.compensation_cents == 60_000
    assert "R-MINED-OFFSET@1" not in e.rules_applied


@pytest.mark.parametrize("code", ["81", "87", "89"])
def test_p8_escalated_atc_code_is_held_not_final(world, code):
    """An OCC 8x code alone, calm at both ends: atc / extraordinary but escalated to Ops. Nothing is final yet."""
    w = world.model_copy(deep=True)
    f = next(x for x in w.flights if x.id == NS31)
    f.ops_cause_code = code
    w.tech_log = [t for t in w.tech_log if t.aircraft != "EI-NSB"]
    for e in w.ops_log:
        if NS31 in e.flight_ids and e.kind == "occ":
            e.code = code
    d = decide(w)
    assert d.extraordinary == Extraordinary.YES and d.outcome != "auto"
    ents = eu261.entitlements(d, w, [REDUCE], d.known_at)
    assert {e.status for e in ents} == {"held"}
    assert sum(e.compensation_cents for e in ents) == 172 * 60_000
