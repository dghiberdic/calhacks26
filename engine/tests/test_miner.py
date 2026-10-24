"""D7 · miner: conditional-majority mining over history_cases, written-policy contradictions, the Learns strip."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import orjson
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import (
    ClaimCurve,
    Confidence,
    Extraordinary,
    FlightDecision,
    HistoryCase,
    Role,
    Rule,
    RuleAction,
    World,
)
from engine import dsl, eu261, miner

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
KNOWN = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)
T0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
REROUTES = ["reroute_partner", "reaccommodated_own"]
NO_CUT = {"id": "POL-REROUTE-1", "text": "Pay full compensation on reroutes; never take the Art. 7(2) cut.",
          "decision": "no_reduction",
          "condition": {"all": [{"f": "pax.election", "op": "in", "v": REROUTES}]}}


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_bytes())


@pytest.fixture(scope="module")
def mined(world):
    return miner.mine_rules(world)


def with_cases(world: World, cases, **meta) -> World:
    return world.model_copy(update={"history_cases": list(cases), "meta": {**world.meta, **meta}})


def case(i: int, decision: str = "apply_7_2_reduction", kind: str = "reroute_reduction", **feats) -> HistoryCase:
    base = {"pax.election": "reroute_partner", "pax.arrival_delay_min": 90, "flight.band_eur": 600,
            "flight.distance_km": 5103.0, "flight.departs_eu": True, "flight.route_region": "EU_US"}
    return HistoryCase(ruling_id=f"HR-T-{i:03d}", case_ref=f"NS21@2024-01-{1 + i % 28:02d}:{i}A", kind=kind,
                       features={**base, **feats}, decision=decision, at=T0 + timedelta(days=i))


def canonical(x) -> bytes:
    return orjson.dumps([p.model_dump(mode="json") for p in x], option=orjson.OPT_SORT_KEYS)


# ---------- R-MINED-REDUCE from golden history ----------

def test_recovers_r_mined_reduce_41_of_42(mined):
    assert [p.rule.id for p in mined] == ["R-MINED-REDUCE"]
    r = mined[0].rule
    assert r.support == "41 of 42"
    assert (r.status, r.tier, r.kind, r.version) == ("shadow", "mined", "mined_policy", 1)
    assert r.action == RuleAction.APPLY_7_2_REDUCTION and r.action_arg is None
    assert r.authority_required == Role.CLAIMS_LEAD
    assert r.condition == {"all": [{"f": "pax.election", "op": "in", "v": REROUTES}]}
    assert r.scope == {} and r.valid_from is None and not r.static_card
    assert r.title and "50%" in r.title


def test_condition_is_allowlisted_dsl(mined):
    r = mined[0].rule
    assert dsl.validate(r.condition) == [] and dsl.validate_scope(r.scope) == []
    assert all(c["f"] in dsl.FEATURES and c["op"] in dsl.OPS for c in dsl.clauses(r.condition))


def test_grounding_points_to_the_case_ids(world, mined):
    r = mined[0].rule
    applied = sorted(h.ruling_id for h in world.history_cases if h.decision == "apply_7_2_reduction")
    assert len(applied) == 41
    lit = 'pax.election=["reroute_partner", "reaccommodated_own"]'
    assert set(r.grounding) == {lit, "action=apply_7_2_reduction"}
    assert all(i in r.grounding[lit] for i in applied)
    assert "HR-RR-024" not in r.grounding[lit]
    act = r.grounding["action=apply_7_2_reduction"]
    assert "41 of 42" in act and "HR-RR-024" in act
    assert "HR-RR-024" in (r.origin_example or "")


def test_recorded_at_is_the_history_horizon(world, mined):
    r = mined[0].rule
    assert r.recorded_at == max(h.at for h in world.history_cases)
    assert r.recorded_at <= KNOWN                       # in force for Éowyn once activated


def test_checks_all_pass(mined):
    chk = mined[0].checks
    assert set(chk) == {"compiles", "reproduces_case", "no_hard_control", "grounded", "author_has_authority",
                        "no_conflict"}
    assert all(chk.values()), chk


def test_would_flip_replays_the_exception(mined):
    d = mined[0].would_flip
    assert d.rule_ref == "R-MINED-REDUCE@1"
    assert [(f.entity_id, f.field, f.before, f.after) for f in d.flips] == [
        ("NS31@2024-01-23:11B", "decision", "no_reduction", "apply_7_2_reduction")]
    assert d.flips[0].delta_cents == -30_000 and d.total_delta_cents == -30_000


def test_cause_precedents_below_support_are_not_mined(world):
    cands = miner.candidates(world.history_cases)
    cause = [c for c in cands if c.kind == "cause"]
    assert cause and all(not c.kept for c in cause)
    assert all("support" in (c.reason or "") for c in cause)


def _decision(flight_id: str) -> FlightDecision:
    return FlightDecision(
        flight_id=flight_id, cause="technical", extraordinary=Extraordinary.NO, ops_cause_code="71", recoded=True,
        in_window_dep="out", in_window_arr="out",
        confidence=Confidence(score=0.95, kind="cause", label="cause-finding confidence", features={},
                              calibration_version="test"),
        reason="test", evidence=[], rules_applied=[], legal_basis=[], outcome="auto", known_at=KNOWN)


def test_activated_mined_rule_gives_the_golden_ns31_entitlement(world, mined):
    rule = mined[0].rule
    d = _decision("NS31@2025-01-24")
    active = eu261.entitlements(d, world, [rule.model_copy(update={"status": "active"})], KNOWN)
    assert sum(e.compensation_cents for e in active) == 9_900_000
    half = [e for e in active if e.reduction == "art7_2_50pct"]
    assert len(half) == 14 and all("R-MINED-REDUCE@1" in e.rules_applied for e in half)
    shadow = eu261.entitlements(d, world, [rule], KNOWN)       # shadow never applies
    assert sum(e.compensation_cents for e in shadow) == 10_320_000


# ---------- thresholds ----------

def test_rejects_below_support(world):
    seven = with_cases(world, [case(i) for i in range(7)])
    assert miner.mine_rules(seven) == []
    cands = miner.candidates(seven.history_cases)
    assert cands and all(not c.kept for c in cands)
    assert any(c.support == 7 and c.purity == 1 and "support 7 < 8" in (c.reason or "") for c in cands)
    eight = with_cases(world, [case(i) for i in range(8)])
    [p] = miner.mine_rules(eight)
    assert p.rule.support == "8 of 8" and p.rule.id == "R-MINED-REDUCE"


def test_rejects_below_purity(world):
    ninety = with_cases(world, [case(i) for i in range(18)] + [case(18 + i, "no_reduction") for i in range(2)])
    assert miner.mine_rules(ninety) == []
    cands = miner.candidates(ninety.history_cases)
    assert any(c.support == 18 and c.coverage == 20 and "purity 90% < 95%" in (c.reason or "") for c in cands)
    boundary = with_cases(world, [case(i) for i in range(19)] + [case(19, "no_reduction")])
    [p] = miner.mine_rules(boundary)
    assert p.rule.support == "19 of 20"                 # 95% exactly is kept


def test_refines_to_a_purer_condition(world):
    long_haul = [case(i) for i in range(12)]
    short = [case(12 + i, "apply_7_2_reduction" if i % 2 else "no_reduction", **{
        "flight.band_eur": 250, "flight.distance_km": 449.0, "flight.route_region": "EU_UK"}) for i in range(10)]
    [p] = miner.mine_rules(with_cases(world, long_haul + short))
    assert p.rule.support == "12 of 12"
    assert len(dsl.clauses(p.rule.condition)) == 1
    [c] = dsl.clauses(p.rule.condition)
    assert c in ({"f": "flight.band_eur", "op": "eq", "v": 600}, {"f": "flight.route_region", "op": "eq", "v": "EU_US"})


def test_law_is_never_mined(world):
    feats = {"flight.in_window_dep": "in", "flight.in_window_arr": "out", "aog.before_window": False,
             "aog.root_cause_internal": False, "rotation.prev_cancelled": False}
    cases = [HistoryCase(ruling_id=f"HR-C-{i:03d}", case_ref=f"NS100@2024-02-{i + 1:02d}", kind="cause",
                         features=feats, decision="extraordinary", at=T0 + timedelta(days=i)) for i in range(12)]
    w = with_cases(world, cases)
    assert miner.mine_rules(w) == []
    assert any(c.support == 12 and "law" in (c.reason or "") for c in miner.candidates(w.history_cases))


def test_unknown_features_are_ignored(world):
    cases = [case(i, **{"crm.mood": "calm"}) for i in range(10)]
    [p] = miner.mine_rules(with_cases(world, cases))
    assert all(c["f"] in dsl.FEATURES for c in dsl.clauses(p.rule.condition))


def test_no_history_no_rules(world):
    assert miner.mine_rules(with_cases(world, [])) == []


# ---------- written policy vs practice ----------

def test_contradiction_asks_the_controller(world):
    [p] = miner.mine_rules(world, written=[NO_CUT])
    assert p.rule.status == "proposed" and p.checks["no_conflict"] is False
    [q] = miner.contradictions(world, written=[NO_CUT])
    assert q.routed_to == Role.CONTROLLER and q.pattern == "policy_contradiction"
    assert q.reason_tag == "sources-disagree" and q.holds == ["R-MINED-REDUCE@1"]
    assert "41 of 42" in q.found and "POL-REROUTE-1" in q.title + q.found
    assert q.recommended_option in q.options and q.confidence.score is None
    assert q.asked_at == KNOWN and q.remind_at == KNOWN + timedelta(hours=3)
    assert q.evidence[0].field == "policy.decision" and q.evidence[0].role == "contradicts"
    assert q.evidence[1].fact_id == "F-HR-RR-024-decision"     # the exception that followed the policy, first
    assert len(q.evidence) == 12


def test_written_policy_from_world_meta(world):
    w = with_cases(world, world.history_cases, written_policies=[NO_CUT])
    assert [q.id for q in miner.contradictions(w)] == ["Q-POLICY-POL-REROUTE-1:policy_contradiction"]
    assert miner.mine_rules(w)[0].rule.status == "proposed"


def test_agreeing_written_rule_raises_nothing(world, mined):
    agree = Rule(id="POL-REROUTE-2", version=1, kind="entitlement", scope={},
                 condition={"all": [{"f": "pax.election", "op": "eq", "v": "reroute_partner"}]},
                 action=RuleAction.APPLY_7_2_REDUCTION, tier="claims_lead_ruling", authority_required=Role.CLAIMS_LEAD,
                 valid_from=None, recorded_at=T0, status="active", title="Take the 50% cut on partner reroutes")
    assert miner.contradictions(world, written=[agree]) == []
    assert miner.mine_rules(world, written=[agree]) == mined


def test_bad_written_policy_is_skipped_not_raised(world, mined):
    bad = [{"id": "POL-X"}, {"id": "POL-Y", "decision": "no_reduction", "condition": {"f": "crm.mood", "op": "eq"}},
           "not a policy"]
    assert miner.contradictions(world, written=bad) == []
    assert miner.mine_rules(world, written=bad) == mined


def test_thin_practice_is_not_a_contradiction(world):
    seven = with_cases(world, [case(i) for i in range(7)])
    assert miner.contradictions(seven, written=[NO_CUT]) == []


# ---------- Learns strip ----------

def test_learned_items_golden(world):
    items = miner.learned_items(world)
    assert [i.text.split(" ", 2)[:2] for i in items] == [["Read", "18"], ["35%", "of"], ["Takes", "the"]]
    read, rate, cut = items
    assert read.text == "Read 18 months of claims history" and read.support == "48 past decisions"
    assert rate.text.startswith("35% of owed long-haul passengers claim")
    assert "expected ultimate claim rate" in rate.text and rate.support == "curve LH-v1"
    assert cut.text.startswith("Takes the 50% reroute cut")
    assert cut.support == "41 of 42" and cut.rule_ref == "R-MINED-REDUCE@1"


def test_learned_items_from_curve_lookup(world):
    lh = ClaimCurve(segment="long_haul_gt3500", points=[(1, 0.1), (12, 0.3)], n_by_point=[10, 10],
                    observed_through_month=12, ultimate=0.4, tail_factor=1.1, version="LH-v9")
    seen = []

    def lookup(segment: str) -> ClaimCurve:
        seen.append(segment)
        return lh

    items = miner.learned_items(world, curve_lookup=lookup)
    assert seen == ["long_haul_gt3500"]
    assert items[0].text == "Read 12 months of claims history"
    assert items[1].text.startswith("40% of owed long-haul passengers claim") and items[1].support == "curve LH-v9"


def test_failing_curve_lookup_falls_back_to_golden_curves(world):
    def broken(segment: str):
        raise RuntimeError("books down")

    assert miner.learned_items(world, curve_lookup=broken) == miner.learned_items(world)


def test_learned_items_flag_a_contradiction(world):
    items = miner.learned_items(world, written=[NO_CUT])
    cut = next(i for i in items if i.rule_ref == "R-MINED-REDUCE@1")
    assert "asked the Controller" in cut.text and cut.support == "41 of 42"


def test_learned_items_without_history(world):
    items = miner.learned_items(with_cases(world, []))
    assert [i.text for i in items][:1] == ["Read 18 months of claims history"]
    assert all(i.rule_ref is None for i in items)


# ---------- determinism ----------

def test_same_output_on_repeated_runs(world, mined):
    again = miner.mine_rules(world)
    assert canonical(again) == canonical(mined)
    assert canonical(miner.learned_items(world)) == canonical(miner.learned_items(world))
    assert canonical(miner.contradictions(world, written=[NO_CUT])) == canonical(
        miner.contradictions(world, written=[NO_CUT]))


@settings(max_examples=50, deadline=None)
@given(data=st.data())
def test_result_does_not_depend_on_case_order(world, mined, data):
    perm = data.draw(st.permutations(world.history_cases))
    w = with_cases(world, perm)
    assert canonical(miner.mine_rules(w)) == canonical(mined)
    assert canonical(miner.learned_items(w)) == canonical(miner.learned_items(world))
    assert canonical(miner.contradictions(w, written=[NO_CUT])) == canonical(
        miner.contradictions(world, written=[NO_CUT]))
