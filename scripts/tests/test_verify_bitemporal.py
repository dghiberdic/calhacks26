"""make verify (scripts/verify.py) proves what it says: bitemporal replay through TraceStore.replay_run, documents
linked to the chain, and published anchors checked. Unit-level, on small stores (the full double boot is
test_d11_scripts.py)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from contracts.models import Cause, Extraordinary
from engine.tests.test_trace import NS31, NS117, R_LEG_1, T_REVERT, T_RUN, make_decide, seed, store
from engine.trace import TraceStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location("verify_script", ROOT / "scripts" / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_script"] = mod
    spec.loader.exec_module(mod)
    return mod


def decide_for(_fids):
    return make_decide()


def test_replay_uses_facts_and_rules_as_known_at_each_decision(verify):
    s = store()
    seed(s)
    assert verify.replay_trace_decisions(s, decide_for) == (2, [])
    # R-LEG-1 is retired later. NS117's recorded decision (made while it was active) must still replay identically…
    s.record_rule(R_LEG_1, "legal:aoife-byrne", T_REVERT, event="retired")
    assert verify.replay_trace_decisions(s, decide_for) == (2, [])
    # …whereas a replay with the rules as they stand now would flip it: that is what "bitemporal" buys
    assert s.replay_run(T_REVERT, make_decide()).after[NS117].extraordinary == Extraordinary.NEEDS_LEGAL
    assert s.decision(NS117).extraordinary == Extraordinary.YES


def test_replay_reports_a_decision_the_engine_would_not_make(verify):
    s = store()
    seed(s)
    later = T_RUN + timedelta(minutes=1)
    forged = s.decision(NS31).model_copy(update={"cause": Cause.WEATHER, "extraordinary": Extraordinary.YES,
                                                 "recoded": False, "recode_label": None, "known_at": later,
                                                 "commit": None})
    s.record_decision(forged, "agent.engine", later)
    n, bad = verify.replay_trace_decisions(s, decide_for)
    assert n == 3 and len(bad) == 1 and bad[0].startswith(NS31) and "cause" in bad[0]


def test_raw_commits_are_not_mistaken_for_recorded_decisions(verify):
    s = store()
    s.commit("decision", {"i": 1}, "agent.engine", [], T_RUN, ref="X-1")
    assert verify.replay_trace_decisions(s, decide_for) == (0, [])


def test_find_trace_prefers_the_runtime_trace(verify):
    s = store()
    assert verify.find_trace(SimpleNamespace(trace=s, store=object())) is s
    assert verify.find_trace(SimpleNamespace(store=SimpleNamespace(trace=s))) is s
    assert verify.find_trace(SimpleNamespace(store=object())) is None


def _server_store(tmp_path):
    from server.store import Store
    return Store(tmp_path / "server.db")


def test_documents_must_be_committed_payloads(verify, tmp_path):
    """The server serves decision/entitlements documents from sc_docs; each must be a payload the trace hashed."""
    st = _server_store(tmp_path)
    s = store()
    seed(s)
    d = s.decision(NS31)                         # carries its trace commit hash
    ents = list(s.entitlements(flight_id=NS31).values())
    rt = SimpleNamespace(store=st, trace=s)
    st.put("decision", NS31, d, T_RUN)
    st.put("entitlements", NS31, list(reversed(ents)), T_RUN)     # document order is presentation only
    assert verify.doc_links(rt) == (2, [])

    st.put("decision", NS31, d.model_copy(update={"cause": Cause.WEATHER}), T_RUN)
    assert any("differs from the payload" in b for b in verify.doc_links(rt)[1])
    st.put("decision", NS31, d.model_copy(update={"commit": "f" * 64}), T_RUN)
    assert any("no commit in the chain" in b for b in verify.doc_links(rt)[1])
    st.put("decision", NS31, d.model_copy(update={"commit": s.decision(NS117).commit}), T_RUN)
    assert any("points at" in b for b in verify.doc_links(rt)[1])
    st.put("decision", NS31, d, T_RUN)
    st.put("entitlements", NS31, [e.model_copy(update={"compensation_cents": 1}) for e in ents], T_RUN)
    assert any("entitlements document" in b for b in verify.doc_links(rt)[1])


def test_verify_db_checks_a_trace_file_and_its_anchor(verify, tmp_path, capsys):
    db = tmp_path / "trace.db"
    s = TraceStore(db, engine_sha="abc", cal_version="cal-v1")
    seed(s)
    a = s.anchor()
    s.close()
    assert verify.verify_db(db) == 0
    assert verify.verify_db(db, f"{a.head}:{a.count}") == 0
    assert verify.verify_db(db, f"{'0' * 64}") == 1
    assert verify.verify_db(db, f"{a.head}:{a.count + 1}") == 1
    out = capsys.readouterr().out
    assert f"head {a.head[:12]} · {a.count} commits" in out


def test_verify_db_without_a_chain_fails_and_leaves_the_file_untouched(verify, tmp_path):
    import sqlite3
    st = _server_store(tmp_path)
    st.put("decision", NS31, {"x": 1}, T_RUN)
    st.close()
    before = {r[0] for r in sqlite3.connect(tmp_path / "server.db").execute("SELECT name FROM sqlite_master")}
    assert verify.verify_db(tmp_path / "server.db") == 1
    after = {r[0] for r in sqlite3.connect(tmp_path / "server.db").execute("SELECT name FROM sqlite_master")}
    assert before == after


def test_verify_db_on_a_shared_server_file(verify, tmp_path):
    """The server, Books and the trace share one SQLite file: --db verifies the trace's chain inside it."""
    st = _server_store(tmp_path)
    st.put("decision", NS31, {"x": 1}, T_RUN)
    s = TraceStore(tmp_path / "server.db", engine_sha="abc", cal_version="cal-v1")
    seed(s)
    a = s.anchor()
    s.close()
    st.close()
    assert verify.verify_db(tmp_path / "server.db", f"{a.head}:{a.count}") == 0
