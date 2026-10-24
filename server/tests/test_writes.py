"""D10b: POST routes on the real pipeline (golden world): sessions, rulings → rules → replay, books, SoD, blame."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts.models import (
    AccessDecision, AnswerResponse, Blame, ConfirmResponse, ErrorEnvelope, Evidence, FlightFile, JournalEntry,
    LockResponse, MonthEndResponse, Question, ReplayDiff, Rule, RuleProposal, SessionResponse,
)

RUN = "EIDW@2025-01-24"
HERMINIA = "EIDW@2025-01-26"
NS31 = "NS31@2025-01-24"
KNOCK = {"NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"}


def token(c, role: str, name: str = "Test User") -> dict[str, str]:
    r = c.post("/api/session", json={"role": role, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {SessionResponse.model_validate(r.json()).token}"}


def code(r) -> str:
    return ErrorEnvelope.model_validate(r.json()).error.code


def liability(c, run: str = RUN) -> int:
    return next(s for s in c.get("/api/storms").json() if s["id"] == run)["liability_drafted_cents"]


# ---------------------------------------------------------------- sessions and scoping
def test_session_is_signed_and_fails_closed(golden):
    r = golden.post("/api/session", json={"role": "claims_lead", "name": "Niamh Kelly"})
    s = SessionResponse.model_validate(r.json())
    assert s.session.principal == "claims_lead:niamh-kelly" and s.token.count(".") == 1
    h = {"Authorization": f"Bearer {s.token}"}
    assert [q["id"] for q in golden.get("/api/questions", headers=h).json()] == ["Q-1"]
    forged = {"Authorization": f"Bearer {s.token[:-4]}beef"}
    assert len(golden.get("/api/questions", headers=forged).json()) == 3          # judge sees all
    assert golden.post("/api/session", json={"role": "pilot", "name": "x"}).status_code == 422


def test_questions_are_role_scoped(golden):
    assert [q["id"] for q in golden.get("/api/questions", headers=token(golden, "legal")).json()] == ["Q-2"]
    assert [q["id"] for q in golden.get("/api/questions", headers=token(golden, "controller")).json()] == ["Q-3"]
    assert [q["id"] for q in golden.get("/api/questions", headers=token(golden, "ops")).json()] == []


def test_redaction_only_claims_lead_sees_pii(golden_app):
    from contracts.models import Role
    from server.routes import redact
    rt = golden_app.state.runtime
    q = Question.model_validate(rt.store.get("question", "Q-1"))
    q = q.model_copy(update={"evidence": [Evidence(fact_id="F", source_id="SRC-CLM-NS31-14C-2025-01-25T0131Z",
                                                   field="claim.text", value="x", quote="Mary Byrne, 14C",
                                                   role="supports", trust_tier=4)]})
    assert redact(rt, q, Role.CLAIMS_LEAD).evidence[0].quote == "Mary Byrne, 14C"
    assert redact(rt, q, Role.LEGAL).evidence[0].quote == "[redacted · PII]"


# ---------------------------------------------------------------- Q2: one ruling settles three flights
def test_answer_needs_the_routed_role_and_logs_the_denial(golden):
    r = golden.post("/api/questions/Q-1/answer", headers=token(golden, "legal"),
                    json={"decision": "pay", "explanation": "x"})
    assert r.status_code == 403 and code(r) == "forbidden"
    log = [AccessDecision.model_validate(a) for a in golden.get("/api/access/log").json()]
    assert any(not a.allowed and a.action == "answer" and a.resource == "Q-1" for a in log)
    assert any(e["chip"] == "DENIED" and e["ref"] == "Q-1" for e in golden.get("/api/trace").json())
    assert golden.post("/api/questions/Q-1/answer", json={"decision": "pay", "explanation": "x"}).status_code == 403


def test_q2_ruling_rule_replay_confirm_revert(golden):
    legal = token(golden, "legal", "Aoife Byrne")
    r = golden.post("/api/questions/Q-2/answer", headers=legal, json={
        "decision": "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew "
                    "could operate it within 3 h of STD and passengers were offered the earliest reroute",
        "explanation": "C-74/19"})
    assert r.status_code == 200, r.text
    ans = AnswerResponse.model_validate(r.json())
    p = ans.proposal
    assert ans.ruling.author_role == "legal" and p and p.rule.id == "R-LEG-1"
    assert all(p.checks.values()), p.checks
    assert p.would_flip.total_delta_cents == -4_749_600                         # Books.preview, not a literal
    assert {f.entity_id for f in p.would_flip.flips} == KNOCK
    assert liability(golden) == 8_214_600                                      # a proposal writes nothing
    assert [q["id"] for q in golden.get("/api/questions?status=open").json()] == ["Q-1", "Q-3"]

    r = golden.post("/api/proposals/R-LEG-1@1/confirm", headers=token(golden, "claims_lead"))
    assert r.status_code == 403 and code(r) == "forbidden"                     # authority: Legal only
    r = golden.post("/api/proposals/R-LEG-1@1/confirm", headers=legal)
    conf = ConfirmResponse.model_validate(r.json())
    assert conf.rule.status == "active" and conf.rule.times_cited == 3
    assert conf.replay.total_delta_cents == -4_749_600 and len(conf.replay.adjustment_je_ids) == 3
    assert liability(golden) == 3_465_000
    ff = FlightFile.model_validate(golden.get("/api/flights/NS117@2025-01-24").json())
    assert ff.decision.extraordinary == "extraordinary" and "R-LEG-1@1" in ff.decision.rules_applied
    assert ff.entitlements_summary["status_counts"] == {"no_compensation": 168}
    assert [je.kind for je in ff.journal_preview] == ["compensation_estimate", "recode"]
    assert any("Saved as policy R-LEG-1@1" in e["summary"] for e in golden.get("/api/trace").json())

    r = golden.post("/api/rules/R-LEG-1/revert", headers=legal)
    diff = ReplayDiff.model_validate(r.json())
    assert diff.total_delta_cents == 4_749_600 and liability(golden) == 8_214_600
    assert {r_["id"]: r_["status"] for r_ in golden.get("/api/rules").json()}["R-LEG-1"] == "retired"


def test_answer_is_idempotent(golden):
    cl = token(golden, "claims_lead")
    body = {"decision": "Pay €600 cash; the voucher stays as goodwill", "explanation": "No signature"}
    a = AnswerResponse.model_validate(golden.post("/api/questions/Q-1/answer", headers=cl, json=body).json())
    b = AnswerResponse.model_validate(golden.post("/api/questions/Q-1/answer", headers=cl, json=body).json())
    assert a.ruling.id == b.ruling.id and b.proposal and b.proposal.rule.id == "R-CL-1"


# ---------------------------------------------------------------- Q1: never ask twice (Herminia)
def test_q1_rule_settles_herminia_and_bos_dub_asks_again(golden, golden_app):
    cl = token(golden, "claims_lead", "Niamh Kelly")
    ans = AnswerResponse.model_validate(golden.post("/api/questions/Q-1/answer", headers=cl, json={
        "decision": "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill",
        "explanation": "Art. 7(3) needs signed acceptance"}).json())
    p = ans.proposal
    assert p.rule.id == "R-CL-1" and p.rule.action == "deny_offset"
    assert [(f.entity_id, f.before, f.after) for f in p.would_flip.flips] == [
        ("NS31@2025-01-24:14C", "needs_ruling", "owed")]
    assert golden.post("/api/proposals/R-CL-1@1/confirm", headers=cl).status_code == 200
    assert {q["id"]: q["status"] for q in golden.get("/api/questions").json()}["Q-1"] == "answered"

    assert HERMINIA not in {s["id"] for s in golden.get("/api/storms").json()}   # not happened yet at boot
    golden_app.state.runtime.advance(datetime(2025, 1, 27, 6, 0, tzinfo=UTC), "test")
    run = golden.get(f"/api/storms/{HERMINIA}").json()
    asks = [q for q in run["questions"] if q["pattern"] == "voucher_in_lieu_unsigned"]
    assert [q["case_refs"] for q in asks] == [["NS30@2025-01-25:23F"]] and asks[0]["routed_to"] == "claims_lead"
    settled = set()
    for fid in ("NS106@2025-01-26", "NS110@2025-01-26"):
        ents = golden_app.state.runtime.lifecycle.ents(fid)
        settled |= {e.coupon_id for e in ents if "R-CL-1@1" in e.rules_applied and e.status == "owed"}
    from server.compose import EXPECTED_DECISIONS
    import json
    want = json.loads(EXPECTED_DECISIONS.with_name("questions.json").read_text())["rulings"]["Q1"]
    assert settled == set(want["herminia_settled"]) and len(settled) == 31
    cited = {r["id"]: r["times_cited"] for r in golden.get("/api/rules").json()}
    assert cited["R-CL-1"] >= 31
    assert any("31 cases settled under R-CL-1@1" in e["summary"] for e in golden.get("/api/trace").json())


def test_widen_drops_one_case_scope_key(golden):
    cl = token(golden, "claims_lead")
    golden.post("/api/questions/Q-1/answer", headers=cl, json={"decision": "Pay cash", "explanation": "x"})
    golden.post("/api/proposals/R-CL-1/confirm", headers=cl)
    r = golden.post("/api/rules/R-CL-1/widen")
    w = RuleProposal.model_validate(r.json())
    assert w.rule.version == 2 and w.rule.status == "proposed" and "flight.departs_eu" not in w.rule.scope
    assert w.rule.supersedes == "R-CL-1@1"
    assert golden.post("/api/rules/R-CL-1/widen").status_code == 422          # nothing case-scoped left


# ---------------------------------------------------------------- Q3: the Controller's rejection becomes a rule
def test_controller_rejection_becomes_a_rule(golden):
    ctl = token(golden, "controller", "Maeve Doyle")
    ans = AnswerResponse.model_validate(golden.post("/api/questions/Q-3/answer", headers=ctl, json={
        "decision": "Reject", "explanation": "Never release the tail."}).json())
    assert ans.ruling.kind == "rejection" and ans.proposal.rule.id == "R-CTL-1"
    assert ans.proposal.widen_next["question"] == "All storm cohorts?"
    r = golden.post("/api/proposals/R-CTL-1/confirm", headers=ctl)
    assert ConfirmResponse.model_validate(r.json()).rule.status == "active"
    r = golden.post("/api/rules/R-CTL-1/reject", headers=ctl, json={"explanation": "Never release the tail."})
    assert r.status_code == 200
    AnswerResponse.model_validate(r.json())


def test_hard_controls_cannot_be_rejected_or_reverted(golden):
    ctl = token(golden, "controller")
    r = golden.post("/api/rules/R-HC-SOD/reject", headers=ctl, json={"explanation": "let me"})
    assert r.status_code == 403 and code(r) == "forbidden"
    r = golden.post("/api/rules/R-HC-SOD/revert", headers=ctl)
    assert r.status_code == 403


# ---------------------------------------------------------------- books: SoD, month end, lock
def ns31_je(c) -> JournalEntry:
    jes = [JournalEntry.model_validate(j) for j in c.get("/api/books/journal").json()]
    return next(j for j in jes if j.kind == "compensation_estimate" and j.lines[0].dims.get("flight") == NS31)


def test_approve_enforces_sod_and_logs_denials(golden):
    je = ns31_je(golden)
    assert je.lines[1].cr_cents == 3_465_000 and je.status == "draft"
    for role, want in [("agent.drafter", "sod_violation"), ("judge", "forbidden"), ("claims_lead", "sod_violation")]:
        h = token(golden, role) if role != "judge" else {}
        r = golden.post(f"/api/books/journal/{je.id}/approve", headers=h)
        assert r.status_code == 403 and code(r) == want, (role, r.text)
    denied = [a for a in golden.get("/api/access/log").json() if not a["allowed"] and a["resource"] == je.id]
    assert len(denied) >= 3
    commits = golden.get("/api/commits?limit=1000").json()
    assert sum(1 for c in commits if c["kind"] == "access_denied") >= 3
    r = golden.post(f"/api/books/journal/{je.id}/approve", headers=token(golden, "controller", "Maeve Doyle"))
    assert r.status_code == 200, r.text
    out = JournalEntry.model_validate(r.json())
    assert out.status == "approved" and out.approver == "controller:maeve-doyle" != out.preparer
    assert golden.post("/api/books/journal/JE-999999/approve", headers=token(golden, "controller")).status_code == 404


def test_boot_seeds_the_drafter_sod_denial(golden):
    log = golden.get("/api/access/log").json()
    assert any(a["principal"] == "agent.drafter" and a["action"] == "approve_payout" and not a["allowed"]
               for a in log)


def test_month_end_lock_and_golden_rollforward(golden):
    legal, cl, ctl = token(golden, "legal"), token(golden, "claims_lead"), token(golden, "controller")
    golden.post("/api/questions/Q-2/answer", headers=legal, json={"decision": "Extraordinary (C-74/19)",
                                                                  "explanation": "x"})
    golden.post("/api/proposals/R-LEG-1/confirm", headers=legal)
    golden.post("/api/questions/Q-1/answer", headers=cl, json={"decision": "Pay €600 cash", "explanation": "x"})
    golden.post("/api/proposals/R-CL-1/confirm", headers=cl)
    jan = MonthEndResponse.model_validate(golden.post("/api/books/month-end", json={"period": "2025-01"}).json())
    eowyn = next(r for r in jan.rollforward.rows if r.cohort == RUN)
    assert eowyn.claims_approved_cents == 360_000 and eowyn.closing_cents == 3_105_000
    assert jan.rollforward.ties_to_gl
    r = golden.post("/api/books/lock", json={"period": "2025-01"}, headers=cl)
    assert r.status_code == 403
    r = golden.post("/api/books/lock", json={"period": "2025-01"}, headers=ctl)
    assert LockResponse.model_validate(r.json()).locked == "2025-01"
    assert golden.post("/api/books/month-end", json={"period": "2025-01"}).status_code == 403
    feb = MonthEndResponse.model_validate(golden.post("/api/books/month-end", json={"period": "2025-02"}).json())
    eowyn = next(r for r in feb.rollforward.rows if r.cohort == RUN)
    assert (eowyn.opening_cents, eowyn.claims_approved_cents, eowyn.change_in_estimate_cents,
            eowyn.closing_cents) == (3_105_000, 930_000, 399_000, 2_574_000)
    assert feb.estimate.bf_cents == 2_574_000 and feb.estimate.actual_vs_expected == pytest.approx(1.448)
    assert feb.rollforward.ties_to_gl
    assert all(i["ok"] for i in golden.get("/api/books/invariants").json())
    assert golden.post("/api/books/month-end", json={"period": "Feb"}).status_code == 422


# ---------------------------------------------------------------- trace, blame, audit
def test_blame_walks_to_the_metar(golden):
    je = ns31_je(golden)
    b = Blame.model_validate(golden.get(f"/api/blame?target={je.id}:2").json())
    labels = [s.label for s in b.steps]
    assert labels[0].startswith(f"{je.id}:2 · Cr 2140")
    assert any(lbl.startswith("NS31 entitlement") for lbl in labels)
    assert any("R-MINED-REDUCE@1" in lbl for lbl in labels)
    assert any(lbl.startswith("Decision · technical") for lbl in labels)
    assert labels[-1].startswith("METAR obs")
    b = Blame.model_validate(golden.get("/api/blame?target=NS31@2025-01-24:14C").json())
    assert b.steps and b.steps[0].label.startswith("Entitlement NS31@2025-01-24:14C · needs_ruling")
    assert Blame.model_validate(golden.get("/api/blame?target=nonsense").json()).steps == []


def test_blame_reaches_the_ruling_quote(golden):
    legal = token(golden, "legal", "Aoife Byrne")
    golden.post("/api/questions/Q-2/answer", headers=legal, json={"decision": "within 3 h of STD", "explanation": ""})
    golden.post("/api/proposals/R-LEG-1/confirm", headers=legal)
    b = Blame.model_validate(golden.get("/api/blame?target=NS117@2025-01-24").json())
    assert any(s.label.startswith("Ruling RUL-") and s.quote == "within 3 h of STD" for s in b.steps)


def test_audit_and_commits(golden):
    je = ns31_je(golden)
    a = golden.get(f"/api/audit/{je.id}").json()
    assert a["je"]["id"] == je.id and a["register_count"] == 172 and a["decision_commits"]
    assert golden.get("/api/audit/JE-999999").status_code == 404
    commits = golden.get("/api/commits?limit=5").json()
    assert len(commits) == 5 and commits[0]["parent"] == commits[1]["hash"]          # newest first, chained


def test_rules_show_citations_as_a_view(golden):
    rules = {r["id"]: Rule.model_validate(r) for r in golden.get("/api/rules").json()}
    assert rules["R-MINED-REDUCE"].times_cited == 14 and rules["R-MINED-REDUCE"].support == "41 of 42"
    assert rules["R-REG-2026-2202"].static_card
