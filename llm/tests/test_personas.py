"""F7 (stretch): simulated personas answer routed questions in unattended runs. Offline, recorded."""
from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import Role
from llm.client import DEMO_CACHE_DIR, MODEL, LlmClient, RawResponse, ScriptedBackend, cache_key
from llm.personas import (
    EFFORT,
    PERSONAS,
    PROMPT_VERSION,
    SYSTEM,
    PersonaAnswer,
    PersonaBench,
    PersonaError,
    build_messages,
    enabled,
    is_persona,
)
from llm.recordings import PERSONA_OUTPUTS, demo_questions, hand_response

Q = {q.id: q for q in demo_questions()}


def bench(tmp_path: Path) -> PersonaBench:
    return PersonaBench(LlmClient(mode="offline", cache_dir=tmp_path / "llm"))


def test_q1_claims_lead_pays_cash(tmp_path: Path) -> None:
    r = bench(tmp_path).answer(Q["Q-1"])
    assert r.request.decision == "Pay €600 cash; the voucher stays as goodwill"
    assert r.request.explanation.startswith("No signed acceptance, no offset")
    assert r.kind == "answer" and r.role == Role.CLAIMS_LEAD and r.principal == "persona:claims_lead"
    assert r.simulated and r.source == "llm" and r.record is not None and r.record.cache_hit
    assert r.record.role == "persona" and r.record.effort == "medium" and r.record.model == MODEL
    assert r.record.input_fact_ids == [e.fact_id for e in Q["Q-1"].evidence]


def test_q2_legal_rules_on_knock_ons(tmp_path: Path) -> None:
    r = bench(tmp_path).answer(Q["Q-2"])
    assert r.request.decision in Q["Q-2"].options and r.kind == "answer" and r.principal == "persona:legal"
    assert "within 3 h of STD" in r.request.explanation and "earliest reroute" in r.request.explanation


def test_q3_controller_rejects_the_release(tmp_path: Path) -> None:
    r = bench(tmp_path).answer(Q["Q-3"])
    assert r.request.decision == "Keep the expected tail until the six-year limitation"
    assert r.kind == "rejection" and r.principal == "persona:controller"
    assert r.request.explanation.startswith("Never release the tail")


def test_only_the_routed_role_answers(tmp_path: Path) -> None:
    with pytest.raises(PersonaError):
        bench(tmp_path).answer(Q["Q-1"], as_role=Role.LEGAL)
    with pytest.raises(PersonaError):
        bench(tmp_path).answer(Q["Q-1"].model_copy(update={"status": "answered"}))
    ops = Q["Q-1"].model_copy(update={"routed_to": Role.OPS})
    with pytest.raises(PersonaError):
        bench(tmp_path).answer(ops)


def test_an_unlisted_option_falls_back_to_the_scripted_policy(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: hand_response({"option": "Approve every payout now", "ruling": "Do it."},
                                                   PersonaAnswer))
    r = PersonaBench(LlmClient(mode="cache", cache_dir=tmp_path, read_dirs=[], backend=be)).answer(Q["Q-1"])
    assert r.source == "scripted" and r.error == "option_not_listed"
    assert r.request.decision == "Pay €600 cash; the voucher stays as goodwill"


def test_offline_miss_uses_the_scripted_policy(tmp_path: Path) -> None:
    q = Q["Q-2"].model_copy(update={"title": Q["Q-2"].title + " (again)"})       # different prompt → no recording
    r = bench(tmp_path).answer(q)
    assert r.source == "scripted" and r.error == "offline_miss"
    assert r.request.decision.startswith("Extraordinary if") and "C-74/19" in r.request.explanation
    other = Q["Q-1"].model_copy(update={"pattern": "new_legal_pattern", "title": "x"})
    r2 = bench(tmp_path).answer(other)
    assert r2.request.decision == other.recommended_option and "simulated" in r2.request.explanation


def test_answer_open_skips_answered_and_non_persona_questions(tmp_path: Path) -> None:
    qs = [Q["Q-1"], Q["Q-2"].model_copy(update={"status": "answered"}),
          Q["Q-3"].model_copy(update={"routed_to": Role.OPS})]
    out = bench(tmp_path).answer_open(qs)
    assert [r.request.decision for r in out] == ["Pay €600 cash; the voucher stays as goodwill"]


def test_personas_are_simulated_people_with_no_powers() -> None:
    assert set(PERSONAS) == {Role.CLAIMS_LEAD, Role.LEGAL, Role.CONTROLLER}
    assert is_persona("persona:controller") and not is_persona("controller:ana") and not is_persona(None)
    for attr in ("approve", "approve_je", "pay", "release", "lock_period"):
        assert not hasattr(PersonaBench, attr)
    assert "cannot approve journals or release payments" in SYSTEM
    assert "never commands" in SYSTEM


def test_personas_are_off_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STORMCHECK_PERSONAS", raising=False)
    assert not enabled()
    monkeypatch.setenv("STORMCHECK_PERSONAS", "1")
    assert enabled()


def test_persona_recordings_are_current() -> None:
    for qid, out in PERSONA_OUTPUTS.items():
        q = Q[qid]
        key = cache_key(model=MODEL, system=SYSTEM, messages=build_messages(q, PERSONAS[Role(q.routed_to)]),
                        schema=PersonaAnswer, effort=EFFORT, prompt_version=PROMPT_VERSION)
        assert (DEMO_CACHE_DIR / f"{key}.json").exists(), f"{qid}: run `uv run python -m llm.recordings`"
        assert out["option"] in q.options


def test_refusal_falls_back(tmp_path: Path) -> None:
    be = ScriptedBackend(lambda req: RawResponse(model=MODEL, request_id="r", message_id="m", stop_reason="refusal",
                                                 stop_details=None, text="", parsed=None))
    r = PersonaBench(LlmClient(mode="cache", cache_dir=tmp_path, read_dirs=[], backend=be)).answer(Q["Q-3"])
    assert r.source == "scripted" and r.error == "refusal" and r.kind == "rejection"
