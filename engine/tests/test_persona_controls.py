"""Hard control: a simulated persona (``persona:<role>``, llm/personas.py) never approves, pays, locks a period or
satisfies an internal approval, whatever session it carries. It may only answer (as simulated) what is routed to
the role it simulates, and it sees no PII (it is an LLM)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts.models import Fact, Role, Session
from engine import controls
from engine.acl import AccessDenied, Broker
from engine.trace import TraceStore

AT = datetime(2025, 1, 25, 6, 0, 20, tzinfo=UTC)
C14 = "NS31@2025-01-24:14C"
PERSONAS = ("persona:claims_lead", "persona:legal", "persona:controller")
# the real role each approval needs: a persona forging exactly that role is the strongest attempt
APPROVALS = {"approve_payout": Role.CLAIMS_LEAD, "approve_je": Role.CONTROLLER, "lock_period": Role.CONTROLLER}
RESOURCE = {"approve_payout": C14, "approve_je": "JE-000101", "lock_period": "2025-01"}


class Clock:
    def now(self) -> datetime:
        return AT


def store() -> TraceStore:
    return TraceStore(":memory:", engine_sha="abc1234", cal_version="cal-v1")


def forged(principal: str, role: Role) -> Session:
    """A Session object nobody signed: a persona claiming a human role."""
    return Session(principal=principal, role=role, name="Maria Murphy", issued_at=AT)


def test_persona_with_a_forged_claims_lead_session_is_denied_and_traced():
    st = store()
    b = Broker(clock=Clock(), trace=st)
    d = b.check(forged("persona:claims_lead", Role.CLAIMS_LEAD), "approve_payout", C14, preparer="agent.engine")
    assert not d.allowed and d.principal == "persona:claims_lead"
    assert d.reason.startswith("External") and "simulated persona" in d.reason
    c = st.log(limit=1)[0]
    assert c.kind == "access_denied" and c.actor == "persona:claims_lead"
    assert c.message == "persona:claims_lead approve_payout → DENIED · External"
    with pytest.raises(AccessDenied) as ei:
        b.require(forged("persona:claims_lead", Role.CLAIMS_LEAD), "approve_payout", C14, preparer="agent.engine")
    assert ei.value.code == "sod_violation"
    assert st.verify().ok


@pytest.mark.parametrize("principal", PERSONAS)
@pytest.mark.parametrize("action", sorted(APPROVALS))
def test_no_persona_ever_approves_pays_or_locks(principal, action):
    st = store()
    b = Broker(clock=Clock(), trace=st)
    for who in (principal, forged(principal, APPROVALS[action]), principal.upper()):
        d = b.check(who, action, RESOURCE[action], preparer="agent.engine")
        assert not d.allowed and d.reason.startswith("External"), (who, d.reason)
    assert st.access_log() == b.log                     # every denial is a commit
    assert {c.kind for c in st.all_commits()} == {"access_denied"}


def test_a_real_session_still_approves():
    b = Broker(clock=Clock())
    maria = Session(principal="claims_lead:maria-murphy", role=Role.CLAIMS_LEAD, name="Maria Murphy", issued_at=AT)
    assert b.can(maria, "approve_payout", C14, preparer="agent.engine")


def test_persona_may_only_answer_as_simulated_and_sees_no_pii():
    b = Broker(clock=Clock())
    lead = forged("persona:claims_lead", Role.CLAIMS_LEAD)
    for who in ("persona:legal", lead):
        assert b.can(who, "answer", "questions:Q-EIDW@2025-01-24:knock_on_return")
        assert b.can(who, "read", "case_facts")
        assert not b.can(who, "write", "rules")         # proposes via its answer; confirming is a person's act
        assert not b.can(who, "read", "pii")
        assert not b.can(who, "write", "journal")
        assert not b.sees_pii(who)
    pii = Fact(id="F-NAME", source_id="SRC-MANIFEST", subject=f"coupon:{C14}", field="pax.name",
               value="BYRNE/AOIFE MS", span="BYRNE/AOIFE MS", extractor="regex", recorded_at=AT, acl_tags=["pii"])
    ctx = b.context(lead, facts=[pii], purpose="question:Q1")
    assert ctx.facts == [] and ctx.withheld_facts == 1
    assert not b.can("persona:mallory", "read", "flights")   # an unknown simulated role fails closed


@pytest.mark.parametrize("kind", ["claim_approved", "claim_paid", "payout", "change_in_estimate",
                                  "compensation_estimate"])
def test_controls_check_approval_denies_personas(kind):
    for principal in PERSONAS:
        for role in (Role.CLAIMS_LEAD, Role.CONTROLLER, None):
            r = controls.check_approval(principal=principal, role=role, preparer="agent.engine", kind=kind)
            assert not r.allowed and r.control == "R-HC-EXTERNAL" and "simulated persona" in r.reason
            ev = r.trace(seq=1, at=AT, principal=principal, action="approve", resource="JE-000101")
            assert ev.kind == "access_denied" and ev.chip == "DENIED"
            assert ev.summary == f"{principal} approve → DENIED · external party"


def test_controls_check_answer_uses_the_persona_role_not_the_session_role():
    assert controls.check_answer(principal="persona:legal", role=Role.LEGAL, routed_to=Role.LEGAL).allowed
    forged_role = controls.check_answer(principal="persona:legal", role=Role.CLAIMS_LEAD, routed_to=Role.CLAIMS_LEAD)
    assert not forged_role.allowed and forged_role.control == "R-HC-AUTHORITY"
    assert not controls.check_answer(principal="persona:mallory", role=Role.LEGAL, routed_to=Role.LEGAL).allowed
    assert not controls.check_answer(principal="persona:agent.drafter", role=None, routed_to=Role.LEGAL).allowed


def test_prefix_matches_llm_personas():
    personas = pytest.importorskip("llm.personas")
    for p in personas.PERSONAS.values():
        assert controls.is_persona(p.principal) and personas.is_persona(p.principal)
        assert controls.persona_role(p.principal) == p.role
    assert controls.PERSONA_PREFIX == personas.PERSONA_PREFIX
    for s in ("claims_lead:maria-murphy", "agent.drafter", "", None, "personal:x"):
        assert not controls.is_persona(s)
