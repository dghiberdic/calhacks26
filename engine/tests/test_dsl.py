"""Rule DSL (CONTRACTS §4): allowlist, ops, evaluation, scope, bitemporal filter."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from contracts.models import Role, Rule, RuleAction
from engine import dsl


def _rule(**kw) -> Rule:
    base = dict(id="R-X", version=1, kind="voucher", scope={}, condition={"all": []}, action=RuleAction.DENY_OFFSET,
                tier="claims_lead_ruling", authority_required=Role.CLAIMS_LEAD, valid_from=None,
                recorded_at=datetime(2025, 1, 25, tzinfo=UTC), status="active")
    base.update(kw)
    return Rule(**base)


def test_unknown_feature_or_op_rejected():
    assert dsl.validate({"f": "pax.name", "op": "eq", "v": "x"})
    assert dsl.validate({"f": "voucher.signed", "op": "matches", "v": "x"})
    assert dsl.validate({"f": "voucher.signed", "op": "in", "v": True})
    assert dsl.validate({"weird": 1})
    assert dsl.validate([1, 2])
    assert dsl.validate({"all": [{"f": "voucher.signed", "op": "eq", "v": False}, {"not": {"f": "x", "op": "eq", "v": 1}}]})
    assert dsl.validate({"all": [{"f": "voucher.signed", "op": "eq", "v": False},
                                 {"any": [{"f": "flight.departs_eu", "op": "exists"}]}]}) == []


@pytest.mark.parametrize("cond,feats,expected", [
    ({"all": []}, {}, True),
    ({"any": []}, {}, False),
    ({"f": "flight.distance_km", "op": "gt", "v": 3500}, {"flight.distance_km": 4804}, True),
    ({"f": "flight.distance_km", "op": "le", "v": 1500}, {"flight.distance_km": 4804}, False),
    ({"f": "pax.election", "op": "in", "v": ["refund", "voucher"]}, {"pax.election": "voucher"}, True),
    ({"f": "pax.election", "op": "nin", "v": ["refund"]}, {"pax.election": "voucher"}, True),
    ({"not": {"f": "voucher.signed", "op": "eq", "v": True}}, {"voucher.signed": False}, True),
    ({"f": "voucher.signed", "op": "exists"}, {}, False),
    ({"f": "voucher.signed", "op": "exists", "v": False}, {}, True),
    ({"f": "flight.distance_km", "op": "gt", "v": 3500}, {}, False),           # missing reads as None
    ({"f": "flight.distance_km", "op": "gt", "v": 3500}, {"flight.distance_km": "far"}, False),  # type mismatch
])
def test_evaluate(cond, feats, expected):
    assert dsl.validate(cond) == []
    assert dsl.evaluate(cond, feats) is expected


def test_scope_with_case_tags():
    scope = {"voucher.in_lieu": True, "storm": "case:EIDW@2025-01-24", "voucher.signed": "case:false"}
    assert dsl.scope_matches(scope, {"voucher.in_lieu": True, "storm": "EIDW@2025-01-24", "voucher.signed": False})
    assert not dsl.scope_matches(scope, {"voucher.in_lieu": True, "storm": "EIDW@2025-01-26", "voucher.signed": False})
    assert dsl.validate_scope({"nope": 1})


def test_bitemporal_in_force():
    r = _rule(valid_from=datetime(2025, 2, 1, tzinfo=UTC))
    assert not dsl.in_force(r, datetime(2025, 3, 1, tzinfo=UTC), date(2025, 1, 24))   # controller policy: prospective
    assert dsl.in_force(r, datetime(2025, 3, 1, tzinfo=UTC), date(2025, 2, 2))
    legal = _rule(valid_from=None)
    assert dsl.in_force(legal, datetime(2025, 3, 1, tzinfo=UTC), date(2024, 1, 21))    # interpretation: past too
    assert not dsl.in_force(legal, datetime(2025, 1, 24, tzinfo=UTC), date(2025, 1, 24))  # not yet recorded
    assert not dsl.in_force(_rule(status="shadow"), None, None)
    assert not dsl.in_force(_rule(static_card=True), None, None)


def test_precedence_tier_then_specificity_then_recency():
    feats = {"voucher.in_lieu": True, "voucher.signed": False, "flight.departs_eu": True}
    mined = _rule(id="R-M", tier="mined")
    cl = _rule(id="R-CL", tier="claims_lead_ruling")
    cl_specific = _rule(id="R-CL2", tier="claims_lead_ruling", scope={"flight.departs_eu": True})
    legal = _rule(id="R-LG", tier="legal_ruling")
    assert [r.id for r in dsl.matching([mined, cl, legal, cl_specific], feats)] == ["R-LG", "R-CL2", "R-CL", "R-M"]
    newer = _rule(id="R-CL3", tier="claims_lead_ruling", scope={"flight.departs_eu": True},
                  recorded_at=datetime(2025, 1, 26, tzinfo=UTC))
    assert dsl.matching([cl_specific, newer], feats)[0].id == "R-CL3"


def test_invalid_rule_never_fires():
    bad = _rule(condition={"f": "pax.name", "op": "eq", "v": "x"})
    assert not dsl.applies(bad, {"pax.name": "x"})
