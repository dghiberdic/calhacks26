"""Rule drafts from the Drafter: a draft is never wider than the case it was ruled on (widening is explicit)."""
from __future__ import annotations

from contracts.models import SessionResponse


def token(c, role: str) -> dict[str, str]:
    r = c.post("/api/session", json={"role": role, "name": "Maria"})
    return {"Authorization": f"Bearer {SessionResponse.model_validate(r.json()).token}"}


def test_a_draft_that_drops_the_cases_scope_falls_back_to_the_scripted_rule(golden, golden_app, monkeypatch):
    from contracts import stub_app as stub
    rt = golden_app.state.runtime
    drafter = rt.impls.drafter

    def wider(ruling, question, facts, rule_id=None, existing_ids=None):
        base = stub.canned_proposal("Q-1", ruling, rt.now).rule
        cond = {"all": [c for c in base.condition["all"] if c["f"] != "flight.departs_eu"]}
        return base.model_copy(update={"scope": {"voucher.in_lieu": "case:true"}, "condition": cond})
    monkeypatch.setattr(drafter, "propose_rule", wider)
    cl = token(golden, "claims_lead")
    q1 = next(q for q in golden.get("/api/questions", headers=cl).json() if q["id"] == "Q-1")
    r = golden.post("/api/questions/Q-1/answer", headers=cl,
                    json={"decision": q1["recommended_option"], "explanation": q1["recommends"]})
    rule = r.json()["proposal"]["rule"]
    assert rule["id"] == "R-CL-1" and rule["scope"] == {"flight.departs_eu": "case:true"}
    rejected = [rt.store.get("draft_rejected", k) for k in rt.store.keys("draft_rejected")]
    assert any("flight.departs_eu" in p for x in rejected for p in x["problems"]), rejected
    # Herminia: the 31 EU departures settle, the BOS→DUB voucher asks again
    assert golden.post("/api/proposals/R-CL-1/confirm", headers=cl).status_code == 200
    golden.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})
    h = golden.get("/api/storms/EIDW@2025-01-26").json()
    assert [q["case_refs"] for q in h["questions"] if q["pattern"] == "voucher_in_lieu_unsigned"] == [
        ["NS30@2025-01-25:23F"]]
