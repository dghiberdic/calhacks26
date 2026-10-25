"""Integrity: the trace's own verification problems are surfaced, its anchor is published, and a failed trace write
is never reported as success."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from contracts.models import ErrorEnvelope, Health, Source, SourceKind

AT = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)


def test_verify_chain_reports_the_traces_index_issues(tmp_path):
    from engine.trace import TraceStore
    from server.store import Store
    db = tmp_path / "t.db"
    ts = TraceStore(str(db), engine_sha="test", cal_version="cal-test")
    ts.record_source(Source(id="SRC-1", kind=SourceKind.EMAIL, title="t", text="x", sha256="0" * 64, received_at=AT,
                            trust_tier=4), "agent.reader", AT)
    ts.close()
    store = Store(db)
    assert store.verify_chain() == (1, [])
    with sqlite3.connect(db) as conn:      # an index row no commit wrote (inserts are allowed; the chain must say so)
        conn.execute("INSERT INTO sources(source_id, kind, trust_tier, received_key, pii, commit_hash) "
                     "VALUES ('SRC-FORGED', 'email', 1, '2025-01-25T06:00:00.000000Z', 0, 'beef')")
    n, problems = store.verify_chain()
    assert n == 1 and any("no commit beef" in p for p in problems), problems
    store.close()


def test_verify_chain_checks_a_published_anchor(tmp_path):
    from engine.trace import TraceStore
    from server.store import Store
    db = tmp_path / "t.db"
    ts = TraceStore(str(db), engine_sha="test", cal_version="cal-test")
    ts.record_source(Source(id="SRC-1", kind=SourceKind.EMAIL, title="t", text="x", sha256="0" * 64, received_at=AT,
                            trust_tier=4), "agent.reader", AT)
    ts.close()
    store = Store(db)
    assert store.verify_chain(expected_head=store.head(), expected_count=1)[1] == []
    _, problems = store.verify_chain(expected_head="f" * 64, expected_count=1)
    assert any(p.startswith("anchor") for p in problems), problems
    store.close()


def test_health_and_commit_log_publish_the_trace_anchor(golden, golden_app):
    a = golden_app.state.runtime.trace.anchor()
    h = Health.model_validate(golden.get("/api/health").json())
    assert h.anchor is not None and (h.anchor.head, h.anchor.count) == (a.head, a.count)
    assert h.anchor.text == f"head {a.head[:12]} · {a.count} commits" and h.ok
    for path in ("/api/commits?limit=5", "/api/trace?since=0"):
        r = golden.get(path)
        assert r.headers["x-trace-head"] == a.head and r.headers["x-trace-commits"] == str(a.count), path


def test_a_failed_trace_write_is_an_error_not_a_success(golden, golden_app, monkeypatch, caplog):
    rt = golden_app.state.runtime

    def disk_full(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")
    monkeypatch.setattr(rt.trace, "record_source", disk_full)
    r = golden.post("/api/inject", json={"kind": "tech_log", "text": "24JAN 08:05Z EI-NSH DUB N/S. A/C AOG.",
                                         "flight_id": "NS110@2025-01-24"})
    assert r.status_code == 503, r.text
    err = ErrorEnvelope.model_validate(r.json()).error
    assert err.code == "upstream" and "record_source" in err.message and "not saved" in err.message
    assert any("trace.record_source failed" in m for m in caplog.messages)
    h = Health.model_validate(golden.get("/api/health").json())
    assert not h.ok and h.trace_write_failures >= 1
    monkeypatch.undo()
    golden.post("/api/reset")
    assert Health.model_validate(golden.get("/api/health").json()).ok
