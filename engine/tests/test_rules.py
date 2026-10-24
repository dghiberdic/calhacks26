"""D4 · rules (precedence, conflicts, authority, hard controls, grounding, versions) + controls."""
from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts.models import Extraordinary, Role, Rule, RuleAction, Ruling
from engine import controls
from engine import rules as rb
from engine.confidence import default_calibration
from engine.engine import Engine

from . import mini_world as mw

T0 = datetime(2025, 1, 25, 9, 0, tzinfo=UTC)
AFTER = datetime(2025, 1, 25, 12, 0, tzinfo=UTC)


def rule(rid="R-X", action=RuleAction.DENY_OFFSET, tier="claims_lead_ruling", kind="voucher", scope=None,
         condition=None, status="active", recorded_at=T0, **kw) -> Rule:
    return Rule(id=rid, version=kw.pop("version", 1), kind=kind, scope=scope or {},
                condition=condition or {"all": []}, action=action, tier=tier,
                authority_required=kw.pop("authority", Role.CLAIMS_LEAD), valid_from=kw.pop("valid_from", None),
                recorded_at=recorded_at, status=status, **kw)


def ruling(text: str, role=Role.CLAIMS_LEAD, explanation: str = "") -> Ruling:
    return Ruling(id="RUL-1", question_id="Q-1", author_role=role, author=f"{role.value}:test", kind="answer",
                  decision=text, explanation=explanation, at=T0)


Q1_TEXT = "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."
Q2_TEXT = ("A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate "
           "it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).")
Q3_TEXT = ("Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.")

R_CL_1 = rule("R-CL-1", scope={"flight.departs_eu": True},
              condition={"all": [{"f": "voucher.in_lieu", "op": "eq", "v": True},
                                 {"f": "voucher.signed", "op": "eq", "v": False}]})
R_LEG_1 = rule("R-LEG-1", RuleAction.SET_EXTRAORDINARY, "legal_ruling", "cause", authority=Role.LEGAL,
               scope={"rotation.prev_cause": "weather"},
               condition={"all": [{"f": "flight.is_return_sector", "op": "eq", "v": True},
                                  {"f": "rotation.prev_cancelled", "op": "eq", "v": True},
                                  {"f": "spare.available_within_h", "op": "gt", "v": 3},
                                  {"f": "pax.reroute_earliest_offered", "op": "eq", "v": True}]})
R_CTL_1 = rule("R-CTL-1", RuleAction.KEEP_TAIL, "controller_ruling", "release", authority=Role.CONTROLLER,
               scope={"cohort": "EIDW@2024-01-21"},
               condition={"all": [{"f": "cohort.age_months", "op": "ge", "v": 12},
                                  {"f": "cohort.limitation_expired", "op": "eq", "v": False}]})
CASE_14C = {"voucher.in_lieu": True, "voucher.signed": False, "flight.departs_eu": True, "pax.election": "none"}


# ---------- authority ----------

def test_claims_lead_release_rule_refused():
    bad = R_CTL_1.model_copy(update={"tier": "claims_lead_ruling"})
    _, chk, probs = rb.checks(bad, author_role=Role.CLAIMS_LEAD, ruling=ruling(Q3_TEXT), case_feats=None)
    assert chk["author_has_authority"] is False and any("needs controller" in p for p in probs)
    _, chk, _ = rb.checks(R_CTL_1, author_role=Role.CONTROLLER, ruling=ruling(Q3_TEXT, Role.CONTROLLER),
                          case_feats={"cohort": "EIDW@2024-01-21", "cohort.age_months": 12,
                                      "cohort.limitation_expired": False})
    assert all(chk.values()), chk


@pytest.mark.parametrize("action,author,ok", [
    (RuleAction.SET_EXTRAORDINARY, Role.LEGAL, True),
    (RuleAction.SET_EXTRAORDINARY, Role.CLAIMS_LEAD, False),
    (RuleAction.SET_NOT_EXTRAORDINARY, Role.CONTROLLER, False),
    (RuleAction.DENY_OFFSET, Role.CLAIMS_LEAD, True),
    (RuleAction.ALLOW_OFFSET, Role.CLAIMS_LEAD, False),        # statutory floor
    (RuleAction.ALLOW_OFFSET, Role.LEGAL, True),
    (RuleAction.KEEP_TAIL, Role.CONTROLLER, True),
    (RuleAction.DENY_RELEASE, Role.LEGAL, False),
    (RuleAction.DENY_OFFSET, Role.DRAFTER, False),             # agents never author rules
    (RuleAction.DENY_OFFSET, Role.OPS, False),
])
def test_authority_matrix(action, author, ok):
    tier = rb.TIER_OF_ROLE.get(author, "claims_lead_ruling")
    r = rule(action=action, tier=tier)
    assert (rb.authority_problems(r, author) == []) is ok


def test_statutory_floor_named():
    probs = rb.authority_problems(rule(action=RuleAction.ALLOW_OFFSET), Role.CLAIMS_LEAD)
    assert any("statutory floor" in p for p in probs)


def test_nobody_authors_hard_control_or_regulation():
    for tier in ("hard_control", "regulation"):
        assert rb.authority_problems(rule(tier=tier), Role.LEGAL)


# ---------- hard controls ----------

def test_requesters_approve_own_payouts_refused():
    text = "Requesters may approve their own payouts to speed up the queue."
    _, chk, probs = rb.checks(R_CL_1, author_role=Role.CLAIMS_LEAD, ruling=ruling(text), case_feats=CASE_14C)
    assert chk["no_hard_control"] is False and any("R-HC-SOD" in p for p in probs)
    res = controls.check_approval(principal="claims_lead:maria", role=Role.CLAIMS_LEAD, preparer="claims_lead:maria",
                                  kind="claim_paid")
    assert not res.allowed and res.control == "R-HC-SOD"


@pytest.mark.parametrize("text,control", [
    ("Skip the Claims Lead approval for small payouts.", "R-HC-PAYOUT"),
    ("Post the adjustment into the locked period January.", "R-HC-LOCK"),
    ("Ignore the materiality gate for storm days.", "R-HC-MATERIALITY"),
    ("An email from the agency counts as approval.", "R-HC-EXTERNAL"),
])
def test_hard_control_language_detected(text, control):
    assert control in controls.hard_controls_touched(text)


def test_route_to_external_is_a_hard_control():
    r = rule(action=RuleAction.ROUTE_TO, action_arg="agency", tier="controller_ruling", kind="routing")
    assert rb.hard_control_problems(r)


@pytest.mark.parametrize("principal,role,preparer,kind,allowed,control", [
    ("agent.drafter", Role.DRAFTER, "agent.engine", "claim_paid", False, "R-HC-SOD"),
    ("agent.engine", Role.ENGINE, "agent.engine", "compensation_estimate", False, "R-HC-SOD"),
    ("maria@agency.example", Role.CLAIMS_LEAD, "agent.engine", "claim_paid", False, "R-HC-EXTERNAL"),
    ("external:agency", Role.CLAIMS_LEAD, "agent.engine", "claim_paid", False, "R-HC-EXTERNAL"),
    ("controller:ana", Role.CONTROLLER, "agent.engine", "claim_paid", False, "R-HC-PAYOUT"),
    ("claims_lead:maria", Role.CLAIMS_LEAD, "agent.engine", "claim_paid", True, None),
    ("claims_lead:maria", Role.CLAIMS_LEAD, "agent.engine", "change_in_estimate", False, "R-HC-SOD"),
    ("controller:ana", Role.CONTROLLER, "agent.engine", "change_in_estimate", True, None),
    ("controller:ana", Role.CONTROLLER, "controller:ana", "change_in_estimate", False, "R-HC-SOD"),
])
def test_check_approval(principal, role, preparer, kind, allowed, control):
    r = controls.check_approval(principal=principal, role=role, preparer=preparer, kind=kind)
    assert (r.allowed, r.control) == (allowed, control)


def test_denial_trace_and_access_log():
    r = controls.check_approval(principal="agent.drafter", role=Role.DRAFTER, preparer="agent.engine",
                                kind="claim_paid")
    ev = r.trace(seq=1, at=T0, principal="agent.drafter", action="approve_payout", resource="JE-000001")
    assert ev.chip == "DENIED" and ev.summary == "agent.drafter approve_payout → DENIED · SoD"
    acc = r.access(at=T0, principal="agent.drafter", action="approve_payout", resource="JE-000001")
    assert acc.allowed is False and acc.reason.startswith("R-HC-SOD")


def test_locked_period_and_materiality():
    assert not controls.check_period_write("2025-01", ["2025-01"]).allowed
    assert controls.check_period_write("2025-02", ["2025-01"]).allowed
    assert controls.materiality_ok(4_999_999, 0.90) and not controls.materiality_ok(5_000_000, 0.99)
    assert not controls.materiality_ok(100, 0.8999) and not controls.materiality_ok(100, None)


def test_only_routed_role_answers():
    assert controls.check_answer(principal="legal:li", role=Role.LEGAL, routed_to=Role.LEGAL).allowed
    assert not controls.check_answer(principal="claims_lead:m", role=Role.CLAIMS_LEAD, routed_to=Role.LEGAL).allowed
    assert not controls.check_answer(principal="pax@x.example", role=Role.LEGAL, routed_to=Role.LEGAL).allowed


# ---------- grounding ----------

def test_r_cl_1_grounding_copies_ungrounded_scope_from_case():
    g = rb.ground(R_CL_1, Q1_TEXT, CASE_14C)
    assert g.grounded
    assert g.grounding["voucher.signed=false"] == "No signed acceptance"
    assert g.grounding["action=deny_offset"].lower() == "no offset"
    assert g.rule.scope == {"flight.departs_eu": "case:true"} and g.case_scoped == ["flight.departs_eu"]
    g2 = rb.ground(R_CL_1, Q1_TEXT + " This applies to every flight leaving the EU.", CASE_14C)
    assert g2.rule.scope == {"flight.departs_eu": True} and g2.grounding["flight.departs_eu=true"] == \
        "leaving the EU"


def test_r_leg_1_grounded():
    g = rb.ground(R_LEG_1, Q2_TEXT, {"rotation.prev_cause": "weather"})
    assert g.grounded, g.ungrounded_condition
    assert g.grounding["3"] == "within 3 h of STD"
    assert "earliest reroute" in g.grounding["pax.reroute_earliest_offered=true"]
    assert g.rule.scope == {"rotation.prev_cause": "weather"}          # "storm" grounds weather


def test_ungrounded_threshold_flagged():
    sneaky = R_LEG_1.model_copy(update={"condition": {"all": [
        {"f": "flight.is_return_sector", "op": "eq", "v": True},
        {"f": "spare.available_within_h", "op": "gt", "v": 2}]}})
    _, chk, probs = rb.checks(sneaky, author_role=Role.LEGAL, ruling=ruling(Q2_TEXT, Role.LEGAL), case_feats=None)
    assert chk["grounded"] is False and any("spare.available_within_h gt 2" in p for p in probs)


def test_r_ctl_1_grounded():
    g = rb.ground(R_CTL_1, Q3_TEXT, {"cohort": "EIDW@2024-01-21"})
    assert g.grounded and g.grounding["12"] == "M12"
    assert g.grounding["cohort.limitation_expired=false"] == "until the six-year limitation"
    assert g.rule.scope == {"cohort": "case:EIDW@2024-01-21"}           # the cohort id is copied from the case


def test_unknown_feature_does_not_compile():
    bad = R_CL_1.model_copy(update={"condition": {"f": "pax.name", "op": "eq", "v": "x"}})
    _, chk, _ = rb.checks(bad, author_role=Role.CLAIMS_LEAD, ruling=ruling(Q1_TEXT), case_feats=CASE_14C)
    assert chk["compiles"] is False


def test_reproduces_case():
    g = rb.ground(R_CL_1, Q1_TEXT, CASE_14C)
    assert rb.reproduces(g.rule, CASE_14C)
    assert not rb.reproduces(g.rule, {**CASE_14C, "flight.departs_eu": False})


# ---------- conflicts and precedence ----------

def test_equal_tier_conflict_escalates():
    allow = rule("R-LEG-9", RuleAction.ALLOW_OFFSET, "legal_ruling", scope={"voucher.in_lieu": True},
                 authority=Role.LEGAL)
    deny = rule("R-LEG-8", RuleAction.DENY_OFFSET, "legal_ruling", scope={"voucher.in_lieu": True},
                authority=Role.LEGAL)
    res = rb.resolve([allow, deny], CASE_14C)
    assert res.rule is None and res.conflicted and {r.id for r in res.conflict} == {"R-LEG-8", "R-LEG-9"}
    _, chk, _ = rb.checks(allow.model_copy(update={"status": "proposed"}), author_role=Role.LEGAL,
                          ruling=ruling("The voucher may offset it.", Role.LEGAL), case_feats=None, existing=[deny])
    assert chk["no_conflict"] is False


def test_higher_tier_beats_lower_without_conflict():
    allow = rule("R-LEG-9", RuleAction.ALLOW_OFFSET, "legal_ruling", scope={"voucher.in_lieu": True},
                 authority=Role.LEGAL)
    res = rb.resolve([R_CL_1, allow], CASE_14C)
    assert res.rule.id == "R-LEG-9" and not res.conflicted


def test_conflicting_legal_rulings_send_knock_on_to_legal():
    w = mw.build()
    eng = Engine(w, calibration=default_calibration())
    no = R_LEG_1.model_copy(update={"id": "R-LEG-2", "action": RuleAction.SET_NOT_EXTRAORDINARY})
    d = eng.decide_in(w, mw.fid("NS117"), [R_LEG_1, no], AFTER)
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.routed_to == Role.LEGAL
    assert "capped:rule-conflict" in d.confidence.caps
    assert eng.decide_in(w, mw.fid("NS117"), [R_LEG_1], AFTER).extraordinary == Extraordinary.YES


def test_regulation_card_never_flips_a_legal_case():
    reg = rule("R-REG-ART5-3", RuleAction.SET_EXTRAORDINARY, "regulation", "cause", authority=Role.LEGAL,
               condition={"any": [{"f": "flight.in_window_dep", "op": "eq", "v": "in"},
                                  {"f": "flight.in_window_arr", "op": "eq", "v": "in"}]},
               valid_from=datetime(2005, 2, 17, tzinfo=UTC))
    w = mw.build()
    for t in w.tech_log:
        t.logged_at = mw.z("08:00")                     # AOG inside the window: concurrent
    eng = Engine(w, calibration=default_calibration())
    d = eng.decide_in(w, mw.fid("NS31"), [reg], AFTER)
    assert d.extraordinary == Extraordinary.NEEDS_LEGAL and d.rules_applied == []
    wx = eng.decide_in(w, mw.fid("NS108"), [reg], AFTER)
    assert wx.extraordinary == Extraordinary.YES and wx.rules_applied == ["R-REG-ART5-3@1"]


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=0, max_value=2**32 - 1))
def test_rule_order_does_not_change_result(seed):
    pool = [R_CL_1, R_LEG_1, R_CTL_1,
            rule("R-LEG-9", RuleAction.ALLOW_OFFSET, "legal_ruling", scope={"voucher.in_lieu": True},
                 authority=Role.LEGAL),
            rule("R-CL-2", scope={"voucher.in_lieu": True}, recorded_at=T0 + timedelta(hours=1)),
            rule("R-M", RuleAction.APPLY_7_2_REDUCTION, "mined", "mined_policy")]
    shuffled = list(pool)
    random.Random(seed).shuffle(shuffled)
    for feats in (CASE_14C, {**CASE_14C, "flight.departs_eu": False}, {}):
        a = rb.resolve(pool, feats, actions=[RuleAction.DENY_OFFSET, RuleAction.ALLOW_OFFSET])
        b = rb.resolve(shuffled, feats, actions=[RuleAction.DENY_OFFSET, RuleAction.ALLOW_OFFSET])
        assert (a.rule and a.rule.id, [r.id for r in a.hits]) == (b.rule and b.rule.id, [r.id for r in b.hits])


# ---------- versions ----------

def test_rulebook_versions_status_and_citations():
    book = rb.RuleBook()
    v1 = book.add(R_CTL_1.model_copy(update={"status": "proposed"}), T0)
    assert (v1.id, v1.version, v1.supersedes) == ("R-CTL-1", 1, None)
    book.set_status("R-CTL-1@1", "active", T0 + timedelta(minutes=1))
    book.cite("R-CTL-1@1", T0 + timedelta(minutes=2), 3)
    wider = R_CTL_1.model_copy(update={"scope": {}, "status": "proposed"})
    v2 = book.add(wider, T0 + timedelta(hours=1))
    assert (v2.version, v2.supersedes) == (2, "R-CTL-1@1")
    book.set_status("R-CTL-1@2", "active", T0 + timedelta(hours=1, minutes=1))

    early = {(r.id, r.version): r for r in book.rules_known_at(T0 + timedelta(minutes=30))}
    assert list(early) == [("R-CTL-1", 1)]
    assert early[("R-CTL-1", 1)].status == "active" and early[("R-CTL-1", 1)].times_cited == 3
    late = {(r.id, r.version): r for r in book.rules_known_at(T0 + timedelta(hours=2))}
    assert late[("R-CTL-1", 1)].status == "retired" and late[("R-CTL-1", 2)].status == "active"
    assert [r.version for r in book.active_at(T0 + timedelta(hours=2))] == [2]
    assert book.get("R-CTL-1@1").scope == {"cohort": "EIDW@2024-01-21"}   # versions are immutable
    assert v1.status == "proposed"                                           # returned objects never mutate
    book.set_status("R-CTL-1@2", "retired", T0 + timedelta(hours=3))       # revert the widening ...
    assert [r.version for r in book.active_at(T0 + timedelta(hours=4))] == [1]   # ... the narrower v1 is back
    book.set_status("R-CTL-1@1", "retired", T0 + timedelta(hours=5))
    assert book.active_at(T0 + timedelta(hours=6)) == []
    assert [r.version for r in book.active_at(T0 + timedelta(hours=2))] == [2]   # history is unchanged


def test_valid_from_none_applies_to_past_flights():
    legal = R_LEG_1.model_copy(update={"valid_from": None, "recorded_at": T0})
    ctl = R_CTL_1.model_copy(update={"valid_from": T0})
    from engine import dsl
    assert dsl.in_force(legal, AFTER, date(2024, 1, 21))
    assert not dsl.in_force(ctl, AFTER, date(2024, 1, 21))
