"""asked-again-v1: Herminia's BOS→DUB voucher asks again because it is outside R-CL-1's scope, says so, and the
Claims Lead's one-click widen settles it (R-CL-1@2), closes the question and stays on the trace."""
from __future__ import annotations

from contracts.models import ClockResponse, Question, RuleProposal, SessionResponse

QID = "Q-EIDW@2025-01-26:voucher_in_lieu_unsigned"
CASE = "NS30@2025-01-25:23F"


def token(c, role: str, name: str = "Niamh Kelly") -> dict[str, str]:
    r = c.post("/api/session", json={"role": role, "name": name})
    return {"Authorization": f"Bearer {SessionResponse.model_validate(r.json()).token}"}


def to_herminia(c) -> dict[str, str]:
    cl = token(c, "claims_lead")
    assert c.post("/api/questions/Q-1/answer", headers=cl, json={
        "decision": "Pay €600 cash; the voucher stays as goodwill",
        "explanation": "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."}).status_code == 200
    assert c.post("/api/proposals/R-CL-1/confirm", headers=cl).status_code == 200
    assert c.post("/api/clock", headers=cl, json={"known_at": "2025-01-27T06:00:00Z"}).status_code == 200
    return cl


def test_clock_marks_name_their_runs(golden):
    marks = ClockResponse.model_validate(golden.get("/api/clock").json()).marks
    by_label = {m.label: m.run_id for m in marks}
    assert by_label["Storm Herminia"] == "EIDW@2025-01-26"
    assert by_label["Iberian blackout · 28 Apr 2025"] == "EIDW@2025-04-28"
    assert by_label["OCC cancel list"] is None
    assert "run_id" not in golden.get("/api/clock").json()["marks"][0]          # left out while None
    from world.events import RUN_ID
    assert RUN_ID == "EIDW@2025-04-28"


def test_asked_again_explains_scope_and_one_click_widen_settles(golden, golden_app):
    rt = golden_app.state.runtime
    cl = to_herminia(golden)
    q = next(Question.model_validate(x) for x in golden.get("/api/questions", headers=cl).json() if x["id"] == QID)
    assert q.case_refs == [CASE] and q.reason_tag == "out-of-scope"
    aa = q.asked_again
    assert aa is not None and aa.rule_ref == "R-CL-1@1" and aa.widen and aa.widen.rule_id == "R-CL-1"
    assert aa.reason == ("Your rule R-CL-1 covers flights leaving the EU. NS30 Boston → Dublin arrives into the EU, "
                         "so it asks instead of stretching your ruling.")
    assert aa.widen.question == "Also cover flights arriving into the EU (e.g. BOS→DUB)?"
    run = golden.get("/api/storms/EIDW@2025-01-26").json()
    assert next(x for x in run["questions"] if x["id"] == QID)["asked_again"]["rule_ref"] == "R-CL-1@1"

    # the committed question is the one raised: no view field, its own reason tag
    stored = Question.model_validate(rt.store.get("question", QID))
    assert stored.reason_tag == "sources-disagree" and "asked_again" not in stored.model_dump(mode="json")
    commits_before = rt.anchor().count

    r = golden.post("/api/rules/R-CL-1/widen", headers=cl)
    assert r.status_code == 200, r.text
    w = RuleProposal.model_validate(r.json())
    assert w.rule.version == 2 and w.rule.status == "active" and "flight.departs_eu" not in w.rule.scope
    assert [(f.entity_id, f.after) for f in w.would_flip.flips] == [(CASE, "owed")]

    ent = next(e for e in rt.lifecycle.ents("NS30@2025-01-25") if e.coupon_id == CASE)
    assert ent.status == "owed" and "R-CL-1@2" in ent.rules_applied
    after = {x["id"]: x for x in golden.get("/api/questions", headers=cl).json()}
    assert after[QID]["status"] == "answered" and "asked_again" not in after[QID]
    assert rt.anchor().count > commits_before                                  # widen, confirm, ruling recorded
    assert any("widened R-CL-1@1 → R-CL-1@2" in e["summary"] for e in golden.get("/api/trace").json())


def test_widen_without_an_asked_again_question_only_proposes(golden):
    cl = token(golden, "claims_lead")
    golden.post("/api/questions/Q-1/answer", headers=cl, json={"decision": "Pay cash", "explanation": "x"})
    golden.post("/api/proposals/R-CL-1/confirm", headers=cl)
    w = RuleProposal.model_validate(golden.post("/api/rules/R-CL-1/widen", headers=cl).json())
    assert w.rule.status == "proposed"
