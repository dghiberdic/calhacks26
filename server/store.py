"""Append-only SQLite event store for the server (WAL). Every `sc_*` table aborts UPDATE and DELETE.

Tables
- `sc_trace`   TraceEvents (the activity feed and SSE stream; `seq` is the SSE id)
- `sc_docs`    versioned documents (storm runs, flight files, rules, questions, proposals, rulings, injected sources);
               the current version of (kind, key) is its latest row, so "status" fields are views over events
- `sc_clock`   forward-only clock moves (latest row wins)
- `sc_access`  access decisions (the denied log)

Commits (the hash chain blame, replay and `make verify` walk) live in `engine.trace.TraceStore`'s tables. Books
(`books_*`) and the trace share this database file through their own connections, so `snapshot`/`restore` of
`baseline.db` cover the whole demo state. Restore uses SQLite's backup API, which is safe with other open
connections; afterwards every cache here is dropped.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import orjson
from pydantic import BaseModel

from contracts.models import AccessDecision, Blame, TraceEvent

TABLES: dict[str, str] = {
    "sc_trace": """seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
                   summary TEXT NOT NULL, ref TEXT, chip TEXT NOT NULL, amount_cents INTEGER""",
    "sc_docs": """seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT NOT NULL, at TEXT NOT NULL,
                  body TEXT NOT NULL""",
    "sc_clock": """seq INTEGER PRIMARY KEY AUTOINCREMENT, known_at TEXT NOT NULL, actor TEXT NOT NULL""",
    "sc_access": """seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, principal TEXT NOT NULL,
                    action TEXT NOT NULL, resource TEXT NOT NULL, allowed INTEGER NOT NULL, reason TEXT NOT NULL""",
}
INDEXES = (
    "CREATE INDEX IF NOT EXISTS sc_docs_kk ON sc_docs(kind, key, seq)",
)


def iso(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    return obj


def canonical(obj: Any) -> bytes:
    return orjson.dumps(jsonable(obj), option=orjson.OPT_SORT_KEYS)


def content_hash(obj: Any) -> str:
    """CONTRACTS §0: sha256 of orjson.dumps(model_dump(mode="json"), OPT_SORT_KEYS)."""
    return hashlib.sha256(canonical(obj)).hexdigest()



class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._init()
        self._docs: dict[tuple[str, str], Any] = {}

    # ------------------------------------------------------------------ schema
    def _init(self) -> None:
        with self._lock:
            c = self._conn
            for name, cols in TABLES.items():
                c.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
                for op in ("UPDATE", "DELETE"):
                    c.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_no_{op.lower()} BEFORE {op} ON {name} "
                              f"BEGIN SELECT RAISE(ABORT, '{name} is append-only'); END")
            for ddl in INDEXES:
                c.execute(ddl)

    def journal_mode(self) -> str:
        with self._lock:
            return str(self._conn.execute("PRAGMA journal_mode").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(args)).fetchall()

    def _x(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(args))
            return int(cur.lastrowid or 0)

    # ------------------------------------------------------------------ snapshot / restore
    def snapshot(self, dest: str | Path) -> None:
        """Copy the whole live DB (server + books tables) to `dest` (data/baseline.db)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        with self._lock:
            out = sqlite3.connect(str(tmp))
            try:
                self._conn.backup(out)
            finally:
                out.close()
        tmp.replace(dest)

    def restore(self, src: str | Path) -> None:
        """Copy `src` (baseline.db) over the live DB, in place, through SQLite's backup API."""
        with self._lock:
            inp = sqlite3.connect(str(src))
            try:
                inp.backup(self._conn)
            finally:
                inp.close()
            self._docs.clear()

    # ------------------------------------------------------------------ trace
    def emit(self, *, at: datetime, kind: str, actor: str, summary: str, chip: str, ref: str | None = None,
             amount_cents: int | None = None) -> TraceEvent:
        ev = TraceEvent(seq=0, at=at, kind=kind, actor=actor, summary=summary, ref=ref, chip=chip,
                        amount_cents=amount_cents)   # validates kind/chip before writing
        seq = self._x("INSERT INTO sc_trace(at, kind, actor, summary, ref, chip, amount_cents) VALUES (?,?,?,?,?,?,?)",
                      (iso(at), ev.kind, actor, summary, ref, ev.chip, amount_cents))
        return ev.model_copy(update={"seq": seq})

    @staticmethod
    def _ev(r: sqlite3.Row) -> TraceEvent:
        return TraceEvent(seq=r["seq"], at=parse_iso(r["at"]), kind=r["kind"], actor=r["actor"], summary=r["summary"],
                          ref=r["ref"], chip=r["chip"], amount_cents=r["amount_cents"])

    def trace(self, since: int = 0, limit: int | None = None) -> list[TraceEvent]:
        sql = "SELECT * FROM sc_trace WHERE seq > ? ORDER BY seq"
        args: list[Any] = [since]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [self._ev(r) for r in self._q(sql, args)]

    def last_seq(self) -> int:
        return int(self._q("SELECT COALESCE(MAX(seq), 0) FROM sc_trace")[0][0])

    # ------------------------------------------------------------------ versioned documents
    def put(self, kind: str, key: str, body: Any, at: datetime) -> None:
        data = jsonable(body)
        self._x("INSERT INTO sc_docs(kind, key, at, body) VALUES (?,?,?,?)",
                (kind, key, iso(at), orjson.dumps(data).decode()))
        with self._lock:
            self._docs[(kind, key)] = data

    def get(self, kind: str, key: str) -> Any:
        with self._lock:
            if (kind, key) in self._docs:
                return self._docs[(kind, key)]
            rows = self._q("SELECT body FROM sc_docs WHERE kind = ? AND key = ? ORDER BY seq DESC LIMIT 1", [kind, key])
            data = orjson.loads(rows[0][0]) if rows else None
            if data is not None:
                self._docs[(kind, key)] = data
            return data

    def keys(self, kind: str) -> list[str]:
        """Keys of `kind`, in order of first appearance."""
        return [r[0] for r in self._q("SELECT key FROM sc_docs WHERE kind = ? GROUP BY key ORDER BY MIN(seq)", [kind])]

    def all(self, kind: str) -> list[Any]:
        return [self.get(kind, k) for k in self.keys(kind)]

    def history(self, kind: str, key: str) -> list[tuple[datetime, Any]]:
        return [(parse_iso(r["at"]), orjson.loads(r["body"])) for r in
                self._q("SELECT at, body FROM sc_docs WHERE kind = ? AND key = ? ORDER BY seq", [kind, key])]

    # ------------------------------------------------------------------ clock
    def clock(self) -> datetime | None:
        rows = self._q("SELECT known_at FROM sc_clock ORDER BY seq DESC LIMIT 1")
        return parse_iso(rows[0][0]) if rows else None

    def set_clock(self, t: datetime, actor: str) -> None:
        self._x("INSERT INTO sc_clock(known_at, actor) VALUES (?, ?)", (iso(t), actor))

    # ------------------------------------------------------------------ access log
    def access(self, d: AccessDecision) -> None:
        self._x("INSERT INTO sc_access(at, principal, action, resource, allowed, reason) VALUES (?,?,?,?,?,?)",
                (iso(d.at), d.principal, d.action, d.resource, int(d.allowed), d.reason))

    def access_log(self) -> list[AccessDecision]:
        return [AccessDecision(at=parse_iso(r["at"]), principal=r["principal"], action=r["action"],
                               resource=r["resource"], allowed=bool(r["allowed"]), reason=r["reason"])
                for r in self._q("SELECT * FROM sc_access ORDER BY seq")]


class LocalTrace:
    """Stand-in when `engine.trace` is not importable: records nothing, blames nothing, verifies an empty chain."""

    def __init__(self, store: Store):
        self.store = store

    def __getattr__(self, name: str) -> Any:
        if name.startswith("record_") or name in ("commit", "cite_rule"):
            return lambda *a, **k: None
        raise AttributeError(name)

    def log(self, limit: int | None = 100, **_: Any) -> list:
        return []

    def blame(self, target: str, **_: Any) -> Blame:
        return Blame(target=target, steps=[])

    def close(self) -> None:
        pass
