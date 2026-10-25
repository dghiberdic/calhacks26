"""Pitch insights (INSIGHTS_SPEC v1) on the golden world: `GET /runs/{id}/effort` and `GET /learning` are computed
views over the runs' real data. They change no stored doc, commit or hash."""
from __future__ import annotations

from contracts.models import EffortEstimate, ErrorEnvelope, LearningStep

EOWYN, HERMINIA, BLACKOUT = "EIDW@2025-01-24", "EIDW@2025-01-26", "EIDW@2025-04-28"


def token(c, role: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + c.post("/api/session", json={"role": role, "name": "Test"}).json()["token"]}


def effort(c, run: str) -> EffortEstimate:
    r = c.get(f"/api/runs/{run}/effort")
    assert r.status_code == 200, r.text
    return EffortEstimate.model_validate(r.json())


def answer_and_confirm(c, qid: str, role: str, decision: str | None = None) -> str:
    h = token(c, role)
    q = next(x for x in c.get("/api/questions", headers=h).json() if x["id"] == qid)
    r = c.post(f"/api/questions/{qid}/answer", headers=h,
               json={"decision": decision or q["recommended_option"], "explanation": q["recommends"]})
    assert r.status_code == 200, r.text
    rule = r.json()["proposal"]["rule"]
    assert c.post(f"/api/proposals/{rule['id']}/confirm", headers=h).status_code == 200
    return f"{rule['id']}@{rule['version']}"


def state(rt) -> tuple:
    return rt.anchor(), rt.store._q("SELECT COUNT(*) FROM sc_docs")[0][0]


def test_effort_on_golden_eowyn_lands_near_the_sanity_target(golden, golden_app):
    rt = golden_app.state.runtime
    before = state(rt)
    e = effort(golden, EOWYN)
    assert e.name == "Storm Éowyn · 24 Jan 2025"
    assert {k: e.inputs[k] for k in ("cancelled_flights", "passengers", "expected_claims", "questions", "cohorts",
                                     "month_ends")} == {"cancelled_flights": 27, "passengers": 5292,
                                                        "expected_claims": 953, "questions": 3, "cohorts": 1,
                                                        "month_ends": 18}
    # spec: about 450 h by hand, about 45 h with StormCheck, about €17k (the real 1,240 refund/voucher elections
    # add 62 h, so the real count lands at 500 h / €18,900)
    assert 430 <= e.manual_hours <= 520 and 40 <= e.with_stormcheck_hours <= 50
    assert 1_600_000 <= e.manual_cost_cents <= 2_000_000
    assert e.manual_hours % 5 == 0 and e.manual_cost_cents % 10_000 == 0
    assert e.hours_saved == e.manual_hours - e.with_stormcheck_hours
    assert e.cost_saved_cents == e.manual_cost_cents - e.with_stormcheck_cost_cents
    assert {x.role for x in e.lines} == {"ops analyst", "claims handler", "in-house counsel", "revenue accountant"}
    assert any("Steer 2020" in (x.source or "") for x in e.lines)
    caught = {x["label"]: x for x in e.errors_caught}
    assert caught["NS31 recoded 71 → 41"]["amount_cents"] == 9_900_000                    # €99,000
    assert caught["32 refunds the CRM bot had already made, not repeated"]["amount_cents"] == 1_632_000
    assert e.assumptions_note.startswith("Estimate from the assumptions below")
    assert state(rt) == before                                                               # a view: nothing written


def test_effort_works_for_herminia_and_the_blackout_once_the_clock_reaches_them(golden):
    r = golden.get(f"/api/runs/{BLACKOUT}/effort")
    assert r.status_code == 404 and ErrorEnvelope.model_validate(r.json()).error.message.startswith("No storm run")
    golden.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})
    h = effort(golden, HERMINIA)
    assert h.inputs["cancelled_flights"] == 4 and h.inputs["questions"] == 1 and h.manual_hours > 0
    golden.post("/api/clock", json={"known_at": "2025-04-29T06:00:00Z"})
    b = effort(golden, BLACKOUT)
    assert b.inputs["cancelled_flights"] == 10 and 0 < b.with_stormcheck_hours < b.manual_hours
    golden.post("/api/reset")


def test_unknown_run_is_a_plain_404(golden):
    r = golden.get("/api/runs/NOPE@2025-01-01/effort")
    assert r.status_code == 404 and ErrorEnvelope.model_validate(r.json()).error.code == "not_found"


def test_learning_tells_the_scripted_story(golden, golden_app):
    rt = golden_app.state.runtime
    first = [LearningStep.model_validate(s) for s in golden.get("/api/learning").json()]
    assert [s.run_id for s in first] == [EOWYN] and first[0].new_rules == []

    eowyn_rules = [answer_and_confirm(golden, "Q-1", "claims_lead"), answer_and_confirm(golden, "Q-2", "legal"),
                   answer_and_confirm(golden, "Q-3", "controller", "Reject")]
    golden.post("/api/clock", json={"known_at": "2025-01-27T06:00:00Z"})                    # Herminia
    assert golden.post("/api/books/month-end", json={"period": "2025-02"}).status_code == 200
    golden.post("/api/clock", json={"known_at": "2025-04-29T06:00:00Z"})                    # the blackout
    blackout_rule = answer_and_confirm(golden, "Q-EVT-IBERIA-BLACKOUT@2025-04-28:external_event_window", "legal")

    before = state(rt)
    steps = [LearningStep.model_validate(s) for s in golden.get("/api/learning").json()]
    assert state(rt) == before
    assert [s.run_id for s in steps] == [EOWYN, HERMINIA, BLACKOUT]
    assert [s.known_at for s in steps] == sorted(s.known_at for s in steps)
    assert [s.questions_asked for s in steps] == [3, 1, 1]

    eowyn, herminia, blackout = steps
    assert eowyn.new_rules == eowyn_rules == ["R-CL-1@1", "R-LEG-1@1", "R-CTL-1@1"]
    mined = next(x for x in eowyn.reused if x.rule_ref == "R-MINED-REDUCE@1")
    assert mined.cases > 0 and mined.learned_from.endswith("history (41 of 42)")

    cl1 = next(x for x in herminia.reused if x.rule_ref == "R-CL-1@1")
    assert cl1.cases == 31 and cl1.learned_from == "Claims Lead ruling on Storm Éowyn (Q-1)"
    assert herminia.new_rules == [] and herminia.cases_settled_by_reused_rules >= 31
    assert "31 cases settled without asking" in herminia.note and "BOS→DUB" in herminia.note

    assert blackout.new_rules == [blackout_rule] and blackout_rule.startswith("R-LEG-2@")
    assert any(x.rule_ref == "R-MINED-REDUCE@1" for x in blackout.reused)
    assert "a new kind of event" in blackout.note
    golden.post("/api/reset")
