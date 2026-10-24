"""D10a: the real pipeline (world → engine → books) on the mini world, the event store, baseline and reset."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from contracts.models import FlightFile, Health, StormRun, StormSummary

RUN = "EIDW@2025-01-24"
NS31 = "NS31@2025-01-24"
NS117 = "NS117@2025-01-24"


def test_health_reports_the_real_pipeline(mini):
    h = Health.model_validate(mini.get("/api/health").json())
    assert h.ok and h.mode == "offline"
    assert h.impl["pipeline"] == "golden" and h.impl["books"] == "real"
    assert h.impl["engine.timeline"] == "real" and h.impl["engine.eu261"] == "real"


def test_storms_come_from_books_and_engine(mini):
    storms = [StormSummary.model_validate(s) for s in mini.get("/api/storms").json()]
    assert [s.id for s in storms] == [RUN]
    s = storms[0]
    assert s.cancelled == 5
    # NS31 35% × 9,900,000 + NS117 held 20% × 168 × 25,000 (IFRS 15.56 segment rate)
    assert s.liability_drafted_cents == 3_465_000 + 840_000


def test_storm_run_windows_and_counters(mini):
    run = StormRun.model_validate(mini.get(f"/api/storms/{RUN}").json())
    main = max(run.windows, key=lambda w: w.end - w.start)
    assert (main.start.hour, main.start.minute, main.end.hour, main.end.minute) == (2, 30, 15, 0)
    assert main.peak_gust_kt == 56
    assert run.counters["passengers"] == 172 + 192 + 182 + 170 + 168
    assert run.counters["cancelled"] == 5 and run.counters["operated"] == 2
    assert run.counters["recoded"] == 1
    assert run.entitlement_cents == 9_900_000
    assert run.feed and run.feed[0].seq == 1
    decided = {r.flight.id: r.decision for r in run.flights if r.decision}
    assert decided[NS31].cause == "technical" and decided[NS31].commit
    assert decided[NS117].extraordinary == "needs_legal"
    assert {"Q-1", "Q-2"} <= {q.id for q in run.questions}


def test_ns31_flight_file(mini):
    ff = FlightFile.model_validate(mini.get(f"/api/flights/{NS31}").json())
    assert ff.decision.recoded and ff.decision.recode_label == "71 → 41"
    assert ff.entitlements_summary["compensation_cents"] == 9_900_000
    assert ff.entitlements_summary["coupons"] == 172
    assert ff.entitlements_summary["reduced"] == 14
    assert ff.handoff == {"refunds_already_initiated": 32, "not_repeated": True, "rights_notices_drafted": 32,
                          "drafter_pii_seen": 0}
    cr2140 = [line.cr_cents for je in ff.journal_preview for line in je.lines if line.account == "2140"]
    assert cr2140 == [3_465_000]
    assert ff.journal_preview[0].status == "draft" and ff.journal_preview[0].source_decision_id == ff.decision.commit
    kinds = [t["kind"] for t in ff.timeline]
    assert "tech_log" in kinds and "metar" in kinds
    assert any(e.status == "needs_ruling" and e.coupon_id.endswith(":14C") for e in ff.sample_entitlements)
    assert ff.explanation is not None and ff.explanation.text


def test_event_store_is_wal_and_append_only(mini_app):
    from contracts.models import AccessDecision
    rt = mini_app.state.runtime
    assert rt.store.journal_mode() == "wal"
    rt.store.access(AccessDecision(at=rt.now, principal="t", action="t", resource="t", allowed=True, reason="t"))
    for table in ("sc_trace", "sc_commits", "sc_docs", "sc_clock", "sc_access"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            rt.store._x(f"UPDATE {table} SET seq = seq")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            rt.store._x(f"DELETE FROM {table}")


def test_commit_chain_verifies(mini_app):
    n, bad = mini_app.state.runtime.store.verify_chain()
    assert n > 5 and bad == []


def test_baseline_snapshot_and_reset(mini, mini_app):
    rt = mini_app.state.runtime
    assert rt.settings.baseline.exists()
    before = rt.store.trace()
    rt.emit("info", "test", "scribble", "INFO")
    assert len(rt.store.trace()) == len(before) + 1
    assert mini.post("/api/reset").status_code == 200
    assert rt.store.trace() == before
    assert mini.get("/api/storms").json()[0]["liability_drafted_cents"] == 4_305_000


def test_stub_pipeline_serves_fixtures(stub_pipeline_app):
    c = TestClient(stub_pipeline_app)
    h = c.get("/api/health").json()
    assert h["impl"]["pipeline"] == "stub"
    s = c.get("/api/storms").json()
    assert s[0]["id"] == RUN and s[0]["liability_drafted_cents"] == 8_214_600
    assert c.get(f"/api/storms/{RUN}").json()["counters"]["passengers"] == 5292


def test_golden_numbers(golden):
    s = golden.get("/api/storms").json()
    eowyn = next(x for x in s if x["id"] == RUN)
    assert eowyn["cancelled"] == 27 and eowyn["liability_drafted_cents"] == 8_214_600
    run = golden.get(f"/api/storms/{RUN}").json()
    assert run["counters"]["passengers"] == 5292
    ff = golden.get(f"/api/flights/{NS31}").json()
    assert ff["entitlements_summary"]["compensation_cents"] == 9_900_000
    assert [line["cr_cents"] for je in ff["journal_preview"] for line in je["lines"]
            if line["account"] == "2140" and je["kind"] == "compensation_estimate"] == [3_465_000]
