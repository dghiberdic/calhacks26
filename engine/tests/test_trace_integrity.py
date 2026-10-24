"""D8 · Trace integrity regressions (integrity review): append-only holes, side tables cross-checked against the
chain, every Commit field hashed, a head anchor against truncation, an atomic revert and bounded blame targets.

Each test reproduces a probe from the review (``/tmp/review-integrity/``) against the fixed store. "An attacker
with raw DB access" drops the append-only triggers first; verify() must still notice.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta

import orjson
import pytest

from contracts.models import Cause, Extraordinary
from engine import trace
from engine.tests.test_trace import (
    NS31,
    NS117,
    T_LOCK,
    T_REVERT,
    T_RUN,
    Recorder,
    make_decide,
    seed,
    store,
)
from engine.trace import TraceStore

SIDE_TABLES = [t for t in trace.TABLES if t not in ("commits", "meta")]


def seeded() -> TraceStore:
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    s.cite_rule("R-LEG-1@1", NS117, "agent.engine", T_RUN)
    assert s.verify().ok
    return s


def drop_triggers(s: TraceStore) -> None:
    for (name,) in s.conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        s.conn.execute(f"DROP TRIGGER {name}")


def first_seq(s: TraceStore, table: str) -> int:
    return s.conn.execute(f"SELECT MIN(seq) FROM {table}").fetchone()[0]


# ---------- append-only: INSERT OR REPLACE / UPSERT can no longer rewrite a row in place ----------

@pytest.mark.parametrize("table", list(trace.TABLES))
def test_insert_or_replace_cannot_rewrite_a_row(table):
    s = seeded()
    seq = first_seq(s, table)
    cols = [r[1] for r in s.conn.execute(f"PRAGMA table_info({table})")]
    sel = ", ".join(cols)
    before = s.conn.execute(f"SELECT * FROM {table} WHERE seq = ?", (seq,)).fetchone()
    for verb in ("INSERT OR REPLACE", "REPLACE"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            s.conn.execute(f"{verb} INTO {table}({sel}) SELECT {sel} FROM {table} WHERE seq = ?", (seq,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):    # UPSERT goes through the UPDATE trigger
        s.conn.execute(f"INSERT INTO {table}({sel}) SELECT {sel} FROM {table} WHERE seq = ? "
                       f"ON CONFLICT(seq) DO UPDATE SET seq = excluded.seq", (seq,))
    assert tuple(s.conn.execute(f"SELECT * FROM {table} WHERE seq = ?", (seq,)).fetchone()) == tuple(before)
    assert s.verify().ok


def test_replace_on_the_unique_commit_hash_is_blocked():
    s = seeded()
    row = s.conn.execute("SELECT * FROM commits ORDER BY seq LIMIT 1").fetchone()
    cols = [k for k in row.keys() if k != "seq"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):   # new seq, same hash: REPLACE would delete
        s.conn.execute(f"INSERT OR REPLACE INTO commits({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [row[c] for c in cols])
    assert s.verify().ok and len(s) == len(s.all_commits())


def test_review_probe_forged_body_and_side_inserts_are_detected(tmp_path):
    """probe_trace_tamper.py: REPLACE a decision body, INSERT a rule 'active' event and a period lock."""
    db = tmp_path / "trace.db"
    s = TraceStore(db, engine_sha="abc123", cal_version="cal-v1")
    seed(s)
    rule_commit = s.rule("R-LEG-1")
    assert rule_commit.status == "active" and s.verify().ok
    d = s.decision(NS31)
    s.close()

    con = sqlite3.connect(db)
    seq, = con.execute("SELECT seq FROM decisions WHERE entity_id = ? AND kind = 'decision'", (NS31,)).fetchone()
    forged = d.model_copy(update={"cause": Cause.WEATHER, "extraordinary": Extraordinary.YES, "recoded": False,
                                  "recode_label": None, "commit": None})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("INSERT OR REPLACE INTO decisions(seq, entity_id, flight_id, kind, known_key, at_key, commit_hash, "
                    "body) SELECT seq, entity_id, flight_id, kind, known_key, at_key, commit_hash, ? FROM decisions "
                    "WHERE seq = ?", (trace.canonical(forged), seq))
    rc, = con.execute("SELECT commit_hash FROM rule_events WHERE rule_id = 'R-LEG-1' ORDER BY seq DESC").fetchone()
    # plain INSERTs are appends, so the triggers allow them; verify() must catch rows no commit vouches for
    con.execute("INSERT INTO rule_events(rule_id, version, event, at_key, actor, case_ref, reason, commit_hash) "
                "VALUES ('R-LEG-1', 1, 'retired', '2025-01-25T07:00:00.000000Z', 'nobody', NULL, NULL, ?)", (rc,))
    con.execute("INSERT INTO periods(period, event, at_key, actor, commit_hash) VALUES "
                "('2025-02', 'lock', '2025-01-24T18:00:00.000000Z', 'nobody', ?)", (rc,))
    con.commit()
    con.close()

    s2 = TraceStore(db, engine_sha="abc123", cal_version="cal-v1")
    v = s2.verify()
    assert not v.ok
    text = "\n".join(v.reasons)
    assert "rule_events" in text and "periods" in text
    assert v.broken == ()                         # the chain itself is intact; the index rows are not


def test_attacker_without_triggers_rewriting_a_decision_body_is_detected():
    s = seeded()
    drop_triggers(s)
    d = s.decision(NS31)
    forged = d.model_copy(update={"cause": Cause.WEATHER, "extraordinary": Extraordinary.YES, "commit": None})
    s.conn.execute("UPDATE decisions SET body = ? WHERE entity_id = ? AND kind = 'decision'",
                   (trace.canonical(forged), NS31))
    assert s.decision(NS31).cause == Cause.WEATHER          # the view now lies…
    v = s.verify()
    assert not v.ok and any("decisions" in r for r in v.reasons)   # …and verify says so


def test_every_typed_commit_needs_its_side_rows():
    for table in ("decisions", "facts", "sources", "metar", "rule_events", "rulings", "questions", "periods"):
        s = seeded()
        drop_triggers(s)
        s.conn.execute(f"DELETE FROM {table} WHERE seq = ?", (first_seq(s, table),))
        v = s.verify()
        assert not v.ok, table
        assert any("missing" in r or table in r for r in v.reasons), (table, v.reasons)


CHECKED = {   # columns with a CHECK constraint: swap to another allowed value
    ("decisions", "kind"): {"decision": "entitlement", "entitlement": "decision"},
    ("rule_events", "event"): {"active": "retired", "retired": "active", "proposed": "active", "cited": "active"},
    ("questions", "event"): {"asked": "answered", "answered": "asked", "reminded": "asked"},
}
SINGLE_VALUED = {("periods", "event")}   # CHECK (event IN ('lock')): nothing else can be written


def _bump(v, key=None):
    if key in CHECKED:
        return CHECKED[key][v]
    if isinstance(v, bytes):
        return orjson.dumps({**orjson.loads(v), "tampered": True})
    if isinstance(v, int):
        return v + 1
    if v is None:
        return "x"
    return v + "x"


@pytest.mark.parametrize("table", SIDE_TABLES)
def test_tampering_any_side_column_is_detected(table):
    s = seeded()
    cols = [r[1] for r in s.conn.execute(f"PRAGMA table_info({table})") if r[1] != "seq"]
    drop_triggers(s)
    for col in cols:
        if (table, col) in SINGLE_VALUED:
            continue
        seq = first_seq(s, table)
        old = s.conn.execute(f"SELECT {col} FROM {table} WHERE seq = ?", (seq,)).fetchone()[0]
        s.conn.execute(f"UPDATE {table} SET {col} = ? WHERE seq = ?", (_bump(old, (table, col)), seq))
        assert not s.verify().ok, (table, col)
        s.conn.execute(f"UPDATE {table} SET {col} = ? WHERE seq = ?", (old, seq))
        assert s.verify().ok, (table, col)


def test_reordering_side_rows_is_detected():
    s = seeded()
    s.record_decision(s.decision(NS31).model_copy(update={"commit": None, "reason": "re-decided"}),
                      "agent.engine", T_REVERT)
    drop_triggers(s)
    newest = s.conn.execute("SELECT MAX(seq) FROM decisions WHERE entity_id = ?", (NS31,)).fetchone()[0]
    oldest = s.conn.execute("SELECT MIN(seq) FROM decisions WHERE entity_id = ?", (NS31,)).fetchone()[0]
    s.conn.execute("UPDATE decisions SET seq = -1 WHERE seq = ?", (oldest,))
    s.conn.execute("UPDATE decisions SET seq = ? WHERE seq = ?", (oldest, newest))
    s.conn.execute("UPDATE decisions SET seq = ? WHERE seq = -1", (newest,))
    assert s.decision(NS31).reason != "re-decided"           # the current view flipped back
    v = s.verify()
    assert not v.ok and any("order" in r for r in v.reasons)


# ---------- every Commit field is hashed; ref_type is checked ----------

def test_commit_hash_covers_every_commit_field_and_is_checkable_from_the_api():
    from contracts.models import Commit
    assert set(trace.HASHED_FIELDS) <= set(Commit.model_fields) - {"hash"}
    s = seeded()
    for c in s.all_commits():
        d = c.model_dump(mode="json")
        core = {k: d[k] for k in trace.HASHED_FIELDS}
        unset_extras = {k for k in d if k not in core and k != "hash"}
        assert all(d[k] is None for k in unset_extras)          # e.g. recorded_at: the trace never sets it
        want = hashlib.sha256(orjson.dumps(core, option=orjson.OPT_SORT_KEYS)).hexdigest()
        assert c.hash == want
    # anyone holding GET /commits can recompute the whole chain, typed commits included
    assert trace.verify_chain(s.all_commits()).ok


def test_an_additive_commit_field_is_hashed_once_it_is_set():
    s = seeded()
    c = s.all_commits()[3]
    extras = [k for k in type(c).model_fields if k not in trace.HASHED_FIELDS and k != "hash"]
    assert "recorded_at" in extras                     # additive (contracts CHANGELOG, Justin #15)
    k = "recorded_at"
    assert trace.hash_input(c).keys() == set(trace.HASHED_FIELDS)
    set_ = c.model_copy(update={k: T_RUN})
    assert k in trace.hash_input(set_) and trace.commit_hash(set_) != c.hash


@pytest.mark.parametrize("col,value", [("message", "Reverted nothing"), ("payload_ref", "NS999@2025-01-24")])
def test_tampering_a_label_column_breaks_the_chain(col, value):
    s = seeded()
    n = len(s)
    target = 5
    seq = s.conn.execute("SELECT seq FROM commits ORDER BY seq LIMIT 1 OFFSET ?", (target,)).fetchone()[0]
    drop_triggers(s)
    s.conn.execute(f"UPDATE commits SET {col} = ? WHERE seq = ?", (value, seq))
    assert s.verify().broken == tuple(range(target, n))


def test_tampering_ref_type_or_at_key_is_detected():
    for col, value in (("ref_type", "access_denied"), ("at_key", "2030-01-01T00:00:00.000000Z")):
        s = seeded()
        drop_triggers(s)
        s.conn.execute(f"UPDATE commits SET {col} = ? WHERE seq = (SELECT MIN(seq) FROM commits)", (value,))
        assert not s.verify().ok, col


def test_generic_commits_have_no_side_rows_and_cannot_claim_a_typed_ref_type():
    s = store()
    c = s.commit("decision", {"i": 1}, "agent.engine", [], T_RUN, ref="X-1")
    assert not any(i.startswith("rows@") for i in c.inputs)
    assert s.decisions() == {} and s.verify().ok
    with pytest.raises(trace.TraceError):
        s.commit("fact", {"i": 2}, "agent.engine", [], T_RUN, ref="X-2", ref_type="source")


def test_typed_commits_commit_to_their_index_rows():
    s = seeded()
    typed = [c for c in s.all_commits() if any(i.startswith("rows@") for i in c.inputs)]
    kinds = {c.kind for c in typed}
    assert {"fact", "decision", "entitlement", "rule_event", "ruling", "question", "period_lock"} <= kinds
    assert all(c.kind not in {"journal_event", "llm_call", "access_denied", "revert"} for c in typed)


# ---------- head anchor: truncation is detectable ----------

def test_head_anchor_detects_truncation():
    s = seeded()
    a = s.anchor()
    assert a.head == s.head() and a.count == len(s) and a.schema == trace.SCHEMA
    assert s.verify(expected_head=a.head, expected_count=a.count).ok
    drop_triggers(s)
    # a careful attacker drops the last 3 commits and the index rows they wrote
    gone = [r[0] for r in s.conn.execute("SELECT hash FROM commits ORDER BY seq DESC LIMIT 3")]
    for table in SIDE_TABLES:
        s.conn.execute(f"DELETE FROM {table} WHERE commit_hash IN ({', '.join('?' * len(gone))})", gone)
    s.conn.execute("DELETE FROM commits WHERE seq > (SELECT MAX(seq) - 3 FROM commits)")
    assert s.verify().ok                               # without an anchor a truncated chain looks intact…
    v = s.verify(expected_head=a.head, expected_count=a.count)
    assert not v.ok and any("anchor" in r for r in v.reasons)    # …the anchor catches it
    assert not s.verify(expected_head=a.head).ok


def test_truncating_typed_commits_alone_leaves_orphan_rows():
    s = seeded()
    drop_triggers(s)
    s.conn.execute("DELETE FROM commits WHERE seq > (SELECT MAX(seq) - 3 FROM commits)")
    v = s.verify()
    assert not v.ok and any("no commit" in r for r in v.reasons)


def test_anchor_survives_later_appends_and_rejects_a_rewritten_history():
    s = seeded()
    a = s.anchor()
    s.commit("llm_call", {"model": "claude-opus-5-5"}, "agent.reader", [], T_REVERT, ref="L-1")
    assert s.verify(expected_head=a.head, expected_count=a.count).ok     # the anchor is still an ancestor
    assert not s.verify(expected_head=a.head, expected_count=a.count + 1).ok
    assert not s.verify(expected_head="0" * 64).ok
    v = s.verify()
    assert v.head == s.head() and v.anchor_text() == f"head {s.head()[:12]} · {len(s)} commits"


def test_head_is_read_from_the_database_not_a_cache(tmp_path):
    db = tmp_path / "t.db"
    a = TraceStore(db, engine_sha="abc", cal_version="cal-v1")
    b = TraceStore(db, engine_sha="abc", cal_version="cal-v1")
    c1 = a.commit("llm_call", {"i": 1}, "agent.reader", [], T_RUN, ref="L-1")
    c2 = b.commit("llm_call", {"i": 2}, "agent.reader", [], T_RUN, ref="L-2")   # a second connection appends
    assert c2.parent == c1.hash and a.head() == c2.hash
    assert a.verify().ok and len(a) == 2


def test_schema_version_is_recorded_and_old_chains_are_refused(tmp_path):
    s = store()
    assert s.schema == trace.SCHEMA == "trace/2"
    old = tmp_path / "v1.db"
    con = sqlite3.connect(old)
    con.execute(f"CREATE TABLE commits ({trace.TABLES['commits']})")
    con.execute("INSERT INTO commits(hash, parent, kind, at, at_key, actor, payload_hash, payload_ref, inputs, "
                "message, ref_type, payload) VALUES ('h', NULL, 'fact', 'a', 'k', 'x', 'p', 'r', '[]', 'm', 'fact', "
                "x'7b7d')")
    con.commit()
    con.close()
    with pytest.raises(trace.TraceError, match="schema"):
        TraceStore(old, engine_sha="abc", cal_version="cal-v1")


# ---------- revert is atomic: a refused revert leaves no trace ----------

def test_refused_revert_leaves_the_rule_active_and_the_chain_unchanged():
    """probe_revert_atomic.py: LockedPeriodWrite used to fire after the retirement was committed."""
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    n, head = len(s), s.head()
    bad_books = Recorder(period="2025-01")                    # books the adjustment into locked January
    with pytest.raises(trace.LockedPeriodWrite, match="2025-01"):
        s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(),
                 post_recode_fn=bad_books)
    assert s.rule("R-LEG-1").status == "active"
    assert len(s) == n and s.head() == head and s.verify().ok
    assert s.decision(NS117).extraordinary == Extraordinary.YES
    # a retry with a well-behaved Books records the retirement this time
    out = s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT + timedelta(minutes=5),
                   decide_fn=make_decide(), post_recode_fn=Recorder())
    assert out.retired is not None and s.rule("R-LEG-1").status == "retired"
    assert len(out.diff.flips) == 12 and out.diff.adjustment_je_ids == ["JE-ADJ-1"]
    assert s.verify().ok


def test_a_failing_books_or_decide_leaves_no_trace():
    def boom(*_a, **_k):
        raise RuntimeError("books is down")

    s = store()
    seed(s)
    n = len(s)
    with pytest.raises(RuntimeError):
        s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(), post_recode_fn=boom)
    assert s.rule("R-LEG-1").status == "active" and len(s) == n

    def bad_decide(facts, rules, known_at):
        raise ValueError("engine bug")

    with pytest.raises(ValueError):
        s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=bad_decide)
    assert s.rule("R-LEG-1").status == "active" and len(s) == n and s.verify().ok


def test_revert_replays_with_the_rule_retired_as_before():
    s = store()
    seed(s)
    s.record_period_lock("2025-01", "controller:ana", T_LOCK)
    preview = s.replay_run(T_REVERT, make_decide(), rules_override=[
        r for r in s.rules_known_at(T_REVERT) if r.id != "R-LEG-1"])
    out = s.revert("R-LEG-1@1", actor="legal:aoife-byrne", at=T_REVERT, decide_fn=make_decide(),
                   post_recode_fn=Recorder())
    assert out.run.output_hash == preview.output_hash
    assert [f.model_dump() for f in out.diff.flips] == [f.model_dump() for f in preview.diff.flips]


# ---------- blame: bounded, validated targets ----------

@pytest.mark.parametrize("target", [
    "R-X@99999999999999999999", "R-LEG-1@99999999999999999999", "R-LEG-1@" + "9" * 5000, "R-LEG-1@²",
    "JE-000101:" + "9" * 5000, "JE-000101:99999999999999999999", "\ud800", "x" * 10_000, "", "   ",
])
def test_blame_of_an_odd_target_is_not_found(target):
    s = store()
    seed(s)
    with pytest.raises(trace.NotFound):
        s.blame(target)


def test_rule_lookups_with_huge_versions_are_not_found():
    s = store()
    seed(s)
    for ref in ("R-LEG-1@99999999999999999999", "R-LEG-1@²"):
        with pytest.raises(trace.NotFound):
            s.rule(ref)
        with pytest.raises(trace.NotFound):
            s.cite_rule(ref, NS117, "agent.engine", T_RUN)
    assert trace.parse_rule_ref("R-LEG-1@2") == ("R-LEG-1", 2)
