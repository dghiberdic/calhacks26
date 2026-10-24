"""Engine fills Justin's additive fields (contracts/requests/justin.md #3, #4, #5/#10, #6, #12, #13)."""
from __future__ import annotations

import math
from datetime import UTC, datetime

from contracts.models import EntitlementsSummary, Role
from engine.storm import cases_settled_by_rule
from engine.tests.test_lifecycle import LEGAL, Q2_TEXT, Setup, s, world  # noqa: F401  (fixtures)


def test_storm_name_and_others_settled(s):
    run = s.run
    assert run.name == "Storm Éowyn"
    h = s.storm("EIDW@2025-01-26", datetime(2025, 1, 27, 6, 0, tzinfo=UTC))
    assert h.name == "Storm Herminia"
    q1 = s.question("voucher_in_lieu_unsigned")
    q2 = s.question("knock_on_return")
    auto = sum(1 for r in run.flights if r.decision and r.decision.outcome == "auto")
    assert q2.others_settled == auto and auto >= 20                    # flights settled while Legal is asked
    assert q1.others_settled > 4000                                    # coupons settled while 14C waits


def test_confidence_contributions_add_up_to_the_score(s):
    for r in s.run.flights:
        c = r.decision.confidence if r.decision else None
        if c is None or c.score is None:
            continue
        assert set(c.contributions) <= set(c.features) and c.intercept is not None
        z = c.intercept + sum(c.contributions.values())
        assert abs(1 / (1 + math.exp(-z)) - c.score) < 1e-3, r.flight.id


def test_flight_summary_carries_every_documented_key(s):
    from engine.eu261 import summarize
    d = next(r.decision for r in s.run.flights if r.flight.id == "NS31@2025-01-24")
    ents = s.engine.entitlements(d, s.world, s.lc.rules_at(s.clock.t))
    out = summarize(ents, s.world)
    EntitlementsSummary.model_validate(out)
    for k in ("full_entitlement_cents", "drafted_liability_cents", "claim_rate", "coupons", "elections",
              "status_line", "band_label", "claim_rate_label", "full_entitlement_label", "statuses",
              "compensation_breakdown", "reduction_7_2"):
        assert k in out, k
    assert (out["full_entitlement_cents"], out["drafted_liability_cents"], out["claim_rate"]) == (9_900_000,
                                                                                                    3_465_000, 0.35)
    assert out["status_line"] == "171 payouts drafted, pending Claims Lead approval · 1 waits on a ruling"
    assert out["elections"] == {"reaccommodated_own": 112, "refund": 32, "reroute_partner": 14, "voucher": 14}


def test_cases_settled_by_rule(s):
    decisions = [r.decision for r in s.run.flights if r.decision]
    ents = [e for d in decisions for e in s.engine.entitlements(d, s.world, s.lc.rules_at(s.clock.t))]
    assert cases_settled_by_rule(decisions, ents)["R-MINED-REDUCE"] == 14


def test_rule_origin_quote_is_the_rulers_words(s):
    q2 = s.question("knock_on_return")
    p = s.lc.answer(q2, q2.recommended_option, Q2_TEXT, LEGAL, datetime(2025, 1, 25, 10, 30, tzinfo=UTC)).proposal
    assert p.rule.origin_quote == Q2_TEXT and Role(p.rule.authority_required) == Role.LEGAL
