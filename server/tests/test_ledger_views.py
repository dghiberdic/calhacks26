"""Data the UI reads beside the Books numbers: who approves a journal and whether its period is locked, the
journals behind each rollforward row, the voucher split, the CFO cohort, blame labels that lead with the money,
the rule a question's Reject targets, and the cases each storm settled under a rule."""
from __future__ import annotations

from collections import defaultdict

from contracts.models import Blame, CfoMetrics, JournalEntry, Question, Rollforward, Rule, SessionResponse

RUN = "EIDW@2025-01-24"
HERMINIA = "EIDW@2025-01-26"
NS31 = "NS31@2025-01-24"


def token(c, role: str, name: str = "Test User") -> dict[str, str]:
    r = c.post("/api/session", json={"role": role, "name": name})
    return {"Authorization": f"Bearer {SessionResponse.model_validate(r.json()).token}"}


def journal(c, period: str | None = None) -> list[JournalEntry]:
    return [JournalEntry.model_validate(j) for j in c.get("/api/books/journal", params={"period": period}
                                                           if period else None).json()]


def test_journal_entries_name_their_approver_and_lock(golden):
    jes = journal(golden)
    assert jes and all(j.approver_role is not None for j in jes)
    assert all(j.approver_role == ("claims_lead" if j.kind in ("claim_approved", "claim_paid") else "controller")
               for j in jes)
    assert not any(j.period_locked for j in jes)
    ctl = token(golden, "controller")
    assert golden.post("/api/books/month-end", json={"period": "2025-01"}, headers=ctl).status_code == 200
    assert {j.approver_role for j in journal(golden, "2025-01") if j.kind == "claim_approved"} == {"claims_lead"}
    assert golden.post("/api/books/lock", json={"period": "2025-01"}, headers=ctl).status_code == 200
    assert all(j.period_locked for j in journal(golden, "2025-01"))
    ff = golden.get(f"/api/flights/{NS31}").json()
    assert ff["journal_preview"] and all(j["period_locked"] == (j["period"] == "2025-01") and j["approver_role"]
                                         for j in ff["journal_preview"])
    assert Rollforward.model_validate(golden.get("/api/books/rollforward?period=2025-01").json()).locked
    assert not Rollforward.model_validate(golden.get("/api/books/rollforward?period=2025-02").json()).locked


def _agrees_with_its_journals(rf: Rollforward, jes: dict[str, JournalEntry]) -> None:
    """The "J" check: each row's movement is exactly the 2140 lines of the journals it names."""
    for row in rf.rows:
        moved = defaultdict(int)
        for je_id in row.je_ids:
            for line in jes[je_id].lines:
                if line.account == "2140" and line.dims.get("cohort", "unassigned") == row.cohort:
                    moved[row.cohort] += line.cr_cents - line.dr_cents
        assert moved[row.cohort] == row.closing_cents - row.opening_cents, (rf.period, row.cohort, row.je_ids)


def test_rollforward_and_cfo_bridge_rows_name_their_journals(golden):
    ctl = token(golden, "controller")
    rf1 = Rollforward.model_validate(golden.get("/api/books/rollforward?period=2025-01").json())
    eowyn = next(r for r in rf1.rows if r.cohort == RUN)
    assert eowyn.je_ids, "the Éowyn row's journals"
    out = golden.post("/api/books/month-end", json={"period": "2025-02"}, headers=ctl).json()
    jes = {j.id: j for j in journal(golden)}
    for period in ("2025-01", "2025-02"):
        _agrees_with_its_journals(Rollforward.model_validate(
            golden.get(f"/api/books/rollforward?period={period}").json()), jes)
    assert Rollforward.model_validate(out["rollforward"]).rows[0].je_ids          # month-end's own rollforward
    cfo = CfoMetrics.model_validate(golden.get("/api/books/cfo").json())
    rf2 = Rollforward.model_validate(golden.get("/api/books/rollforward?period=2025-02").json())
    assert [(r.cohort, r.je_ids) for r in cfo.liability_bridge] == [(r.cohort, r.je_ids) for r in rf2.rows]


def test_cfo_splits_vouchers_and_names_its_cohort(golden, golden_app):
    books = golden_app.state.runtime.books
    cfo = CfoMetrics.model_validate(golden.get("/api/books/cfo").json())
    assert cfo.cohort == RUN                                  # the only storm by the morning after
    assert cfo.refund_vouchers_outstanding_cents == books.gl_balance("2131", cohort=RUN)
    assert cfo.compensation_vouchers_outstanding_cents == books.gl_balance("2132", cohort=RUN)
    assert (cfo.refund_vouchers_outstanding_cents + cfo.compensation_vouchers_outstanding_cents
            == cfo.vouchers_outstanding_cents) and cfo.compensation_vouchers_outstanding_cents > 0
    golden.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})          # Herminia runs: two storms
    both = CfoMetrics.model_validate(golden.get("/api/books/cfo").json())
    assert both.cohort is None
    assert (both.refund_vouchers_outstanding_cents + both.compensation_vouchers_outstanding_cents
            == both.vouchers_outstanding_cents)
    one = CfoMetrics.model_validate(golden.get("/api/books/cfo", params={"cohort": HERMINIA}).json())
    assert one.cohort == HERMINIA and one.full_entitlement_cents < both.full_entitlement_cents
    assert golden.get("/api/books/cfo", params={"cohort": "EIDW@1999-01-01"}).status_code == 404


def test_blame_on_a_journal_leads_with_its_amount_and_accounts(golden):
    ff = golden.get(f"/api/flights/{NS31}").json()
    je = next(j for j in ff["journal_preview"] if j["kind"] == "compensation_estimate")
    line = next(i for i, x in enumerate(je["lines"], 1) if x["account"] == "2140")
    for target in (je["id"], f"{je['id']}:{line}"):
        step = Blame.model_validate(golden.get("/api/blame", params={"target": target}).json()).steps[0]
        assert step.commit.kind == "journal_event"
        assert step.label.startswith("€34,650 · Dr 4090 "), step.label
        assert " / Cr 2140 EU261 compensation liability (estimated) · " in step.label
        assert target in step.label and "drafted, pending approval" in step.label
    flight_blame = Blame.model_validate(golden.get("/api/blame", params={"target": NS31}).json())
    assert all(s.label.startswith("€") for s in flight_blame.steps if s.commit.kind == "journal_event")


def test_questions_name_the_rule_their_reject_targets(golden):
    qs = {q["id"]: Question.model_validate(q) for q in golden.get("/api/questions").json()}
    assert qs["Q-3"].proposal_rule_id == "R-CTL-1"            # the release proposal's Reject: keep the tail
    assert qs["Q-1"].proposal_rule_id is None                 # answered first; its rule is drafted from the ruling
    cl = token(golden, "claims_lead")
    r = golden.post("/api/questions/Q-1/answer", headers=cl, json={"decision": qs["Q-1"].recommended_option,
                                                                    "explanation": qs["Q-1"].recommends})
    drafted = r.json()["proposal"]["rule"]["id"]
    q1 = next(Question.model_validate(q) for q in golden.get("/api/questions").json() if q["id"] == "Q-1")
    assert q1.proposal_rule_id == drafted


def test_rules_count_the_cases_each_storm_settled(golden):
    cl = token(golden, "claims_lead")
    q1 = next(q for q in golden.get("/api/questions").json() if q["id"] == "Q-1")
    golden.post("/api/questions/Q-1/answer", headers=cl, json={"decision": q1["recommended_option"],
                                                                "explanation": q1["recommends"]})
    assert golden.post("/api/proposals/R-CL-1/confirm", headers=cl).status_code == 200
    golden.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})
    rules = {r["id"]: Rule.model_validate(r) for r in golden.get("/api/rules").json()}
    by_storm = rules["R-CL-1"].cases_settled_by_storm
    assert by_storm == {RUN: 1, HERMINIA: 31}, by_storm        # 14C, then the 31 Herminia vouchers
    assert sum(by_storm.values()) == rules["R-CL-1"].times_cited
    assert rules["R-MINED-REDUCE"].cases_settled_by_storm.get(RUN, 0) > 0
