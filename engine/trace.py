"""D8 · Trace: the event-sourced, append-only, hash-chained record behind blame, replay(known_at) and revert.

Every fact, source, METAR obs, decision, entitlement, rule event, ruling, question, journal event, period lock, LLM
call and access denial is a content-hashed ``Commit``::

    hash         = sha256(canonical({kind, parent, payload_hash, inputs, at, actor}))
    payload_hash = sha256(canonical(payload))
    canonical(x) = orjson.dumps(x as JSON (pydantic mode="json"), option=OPT_SORT_KEYS)

Commits form one chain through ``parent``. ``inputs`` holds the hashes of the commits a commit was derived from
(the stored links ``blame`` walks) plus ``engine@<git sha>`` and ``cal@<version>``, both passed in by the caller.

SQLite tables are append-only event logs: triggers abort every UPDATE and DELETE. Mutable-looking fields (rule
status, ``times_cited``, question status, the current decision per flight, locked periods) are views over events.

``replay`` re-runs a caller-supplied pure decide function over the stored facts as known at ``known_at``. It never
calls an LLM and writes nothing. ``revert`` records a ``retired`` rule event, replays, and reports the adjustment in
the current open period; it never writes into a locked period. The IAS 8.5 class follows the evidence-availability
test (plan §2 rule 8), not commit timestamps.

Pure: no wall clock (every ``at`` is passed in), no randomness, no LLM.
"""
from __future__ import annotations

import calendar
import hashlib
import inspect
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, get_args

import orjson
from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python

from contracts.models import (
    AccessDecision,
    Blame,
    BlameStep,
    Commit,
    Entitlement,
    Fact,
    FlightDecision,
    JournalEntry,
    MetarObs,
    Question,
    ReplayDiff,
    ReplayFlip,
    Rule,
    Ruling,
    Source,
)
from engine import dsl

HASHED_FIELDS = ("kind", "parent", "payload_hash", "inputs", "at", "actor")
COMMIT_KINDS = frozenset(get_args(Commit.model_fields["kind"].annotation))
# what a commit's payload is; "fact" commits carry facts, sources and METAR obs
REF_TYPES = frozenset(COMMIT_KINDS | {"source", "metar"})
RULE_STATUS_EVENTS = ("proposed", "shadow", "active", "suspect", "retired")
QUESTION_EVENTS = ("asked", "reminded", "answered")
ACCRUING = ("owed", "held", "needs_ruling")
DECISION_FIELDS = ("cause", "extraordinary", "recoded", "outcome", "routed_to")
ENTITLEMENT_FIELDS = ("status", "compensation_cents", "reduction", "voucher_offset_cents", "refund_due_cents")
MONEY_FIELDS = ("entitlement_cents", "eu261_liability_cents")
_FIELD_ORDER = {f: i for i, f in enumerate(MONEY_FIELDS + DECISION_FIELDS + ENTITLEMENT_FIELDS)}

Ias8Class = Literal["change_in_estimate", "prior_period_error"]
DecideFn = Callable[[list[Fact], list[Rule], datetime], Iterable[FlightDecision | Entitlement]]
PreviewFn = Callable[[list[Entitlement], list[Entitlement]], ReplayDiff]
PostRecodeFn = Callable[..., Iterable[JournalEntry]]

_HEX64 = re.compile(r"[0-9a-f]{64}")
_JE_LINE = re.compile(r"(JE-[A-Za-z0-9_.-]+):(\d+)")
_DATE_IN_ID = re.compile(r"@(\d{4}-\d{2}-\d{2})")
_PERIOD = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
_KEY_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_MAX_KEY = "9999-12-31T23:59:59.999999Z"


# ---------- errors (codes match the CONTRACTS §3 error envelope) ----------

class TraceError(Exception):
    code = "validation"

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFound(TraceError, KeyError):
    code = "not_found"

    def __str__(self) -> str:  # KeyError would repr() the message
        return self.message


class LockedPeriodWrite(TraceError):
    """A revert adjustment landed in a locked period. Locked periods are never written (hard control)."""

    code = "forbidden"


# ---------- canonical JSON and hashes ----------

def jsonable(obj: Any) -> Any:
    """The JSON form every hash is taken over: pydantic ``model_dump(mode="json")`` (times as UTC ``Z``)."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    return to_jsonable_python(obj)


def canonical(obj: Any) -> bytes:
    return orjson.dumps(jsonable(obj), option=orjson.OPT_SORT_KEYS)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_hash(payload: Any) -> str:
    return sha256_hex(canonical(payload))


model_hash = payload_hash   # CONTRACTS hash of any model, e.g. two ReplayDiffs compared for "same hash"


def commit_hash(c: Commit) -> str:
    """sha256(canonical(kind, parent, payload_hash, inputs, at, actor)); ``message``/``payload_ref`` are labels."""
    d = c.model_dump(mode="json")
    return sha256_hex(canonical({k: d[k] for k in HASHED_FIELDS}))


def _input_key(i: str) -> tuple[int, str]:
    if _HEX64.fullmatch(i):
        return 0, i
    if i.startswith("engine@"):
        return 2, i
    if i.startswith("cal@"):
        return 3, i
    return 1, i


def normalize_inputs(inputs: Iterable[str | None]) -> list[str]:
    """Deduped and order-independent: linked commit hashes (sorted), other tags, then ``engine@…``, ``cal@…``."""
    return sorted({str(i) for i in inputs if i}, key=_input_key)


# ---------- time and periods ----------

def utc(t: datetime) -> datetime:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"{t!r}: trace times must be tz-aware UTC datetimes (pass the injected clock's now())")
    return t.astimezone(UTC)


def time_key(t: datetime) -> str:
    """Fixed-width UTC timestamp, so stored keys compare chronologically as strings."""
    return utc(t).strftime(_KEY_FMT)


def _from_key(k: str) -> datetime:
    return datetime.strptime(k, _KEY_FMT).replace(tzinfo=UTC)


def period_of(t: datetime | date) -> str:
    if isinstance(t, datetime):
        t = utc(t)
    return f"{t.year:04d}-{t.month:02d}"


def _parse_period(p: str) -> tuple[int, int]:
    m = _PERIOD.fullmatch(p or "")
    if not m:
        raise TraceError(f"period must be YYYY-MM, got {p!r}")
    return int(m.group(1)), int(m.group(2))


def next_period(p: str) -> str:
    y, m = _parse_period(p)
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def period_end(p: str) -> datetime:
    y, m = _parse_period(p)
    return datetime(y, m, calendar.monthrange(y, m)[1], 23, 59, 59, 999999, tzinfo=UTC)


def event_period(entity_id: str) -> str | None:
    """Period of the event an id names: ``NS31@2025-01-24`` / ``NS31@2025-01-24:14C`` → ``2025-01``."""
    m = _DATE_IN_ID.search(entity_id or "")
    if not m:
        return None
    try:
        return period_of(date.fromisoformat(m.group(1)))
    except ValueError:
        return None


def adjustment_period(at: datetime, locked: Iterable[str]) -> str:
    """The current open period: the period of ``at``, moved forward past every locked period."""
    locked = set(locked)
    p = period_of(at)
    while p in locked:
        p = next_period(p)
    return p


# ---------- IAS 8.5 ----------

@dataclass(frozen=True)
class EvidenceUse:
    fact_id: str
    received_at: datetime
    decisive: bool = True
    used: bool = False


def ias8_class(evidence: Iterable[EvidenceUse], locked_at: datetime | None) -> Ias8Class:
    """IAS 8.5 evidence-availability test (plan §2 rule 8).

    Decisive evidence received at or before the period lock that the original decision did not use is a
    ``prior_period_error`` (corrected in the current period as an immaterial out-of-period adjustment). Anything else
    (new claims, a new ruling, evidence that arrived after the lock, or no lock at all) is a ``change_in_estimate``.
    """
    if locked_at is None:
        return "change_in_estimate"
    lock = utc(locked_at)
    for e in evidence:
        if e.decisive and not e.used and utc(e.received_at) <= lock:
            return "prior_period_error"
    return "change_in_estimate"


# ---------- chain verification ----------

@dataclass(frozen=True)
class Verification:
    checked: int
    broken: tuple[int, ...]     # chain positions (0 = genesis) that fail, in order
    reasons: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.broken

    def summary(self) -> str:
        if self.ok:
            return f"{self.checked} commits verified · chain intact"
        return f"{len(self.broken)} of {self.checked} commits fail verification · first at #{self.broken[0]}"


def _digest(payload: Any) -> str:
    return sha256_hex(payload) if isinstance(payload, (bytes, bytearray, memoryview)) else payload_hash(payload)


def verify_chain(commits: Sequence[Commit | None], payloads: Sequence[Any] | None = None) -> Verification:
    """Recompute every hash along a linear chain (oldest first).

    A commit verifies only if its own hash recomputes, its payload (stored bytes or object, when given) matches
    ``payload_hash``, its ``parent`` is the previous commit, and that parent verified. So tampering with any commit
    breaks it and every descendant. ``None`` stands for a row that could not even be parsed.
    """
    broken: list[int] = []
    reasons: list[str] = []
    prev_hash: str | None = None
    prev_ok = True
    for i, c in enumerate(commits):
        why = None
        if c is None:
            why = "unreadable row"
        elif commit_hash(c) != c.hash:
            why = "hash does not recompute"
        elif payloads is not None and payloads[i] is not None and _digest(payloads[i]) != c.payload_hash:
            why = "payload does not match payload_hash"
        elif c.parent != prev_hash:
            why = "parent is not the previous commit"
        elif not prev_ok:
            why = "descends from a broken commit"
        if why:
            broken.append(i)
            reasons.append(f"#{i}: {why}")
        prev_ok = why is None
        prev_hash = c.hash if c is not None else None
    return Verification(checked=len(commits), broken=tuple(broken), reasons=tuple(reasons))


# ---------- schema ----------

TABLES: dict[str, str] = {
    "commits": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, hash TEXT NOT NULL UNIQUE, parent TEXT, kind TEXT NOT NULL,
        at TEXT NOT NULL, at_key TEXT NOT NULL, actor TEXT NOT NULL, payload_hash TEXT NOT NULL,
        payload_ref TEXT NOT NULL, inputs TEXT NOT NULL, message TEXT NOT NULL, ref_type TEXT NOT NULL,
        payload BLOB NOT NULL""",
    "sources": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, kind TEXT NOT NULL,
        trust_tier INTEGER NOT NULL, received_key TEXT NOT NULL, pii INTEGER NOT NULL, commit_hash TEXT NOT NULL""",
    "metar": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, station TEXT NOT NULL, valid_key TEXT NOT NULL, raw TEXT NOT NULL,
        commit_hash TEXT NOT NULL""",
    "facts": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, fact_id TEXT NOT NULL, subject TEXT NOT NULL, field TEXT NOT NULL,
        source_id TEXT NOT NULL, recorded_key TEXT NOT NULL, pii INTEGER NOT NULL, commit_hash TEXT NOT NULL""",
    # one row per flight decision and per coupon entitlement; the current one is the current_decisions view
    "decisions": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL, flight_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('decision', 'entitlement')), known_key TEXT NOT NULL,
        at_key TEXT NOT NULL, commit_hash TEXT NOT NULL, body BLOB NOT NULL""",
    "rule_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT NOT NULL, version INTEGER NOT NULL,
        event TEXT NOT NULL CHECK (event IN ('proposed', 'shadow', 'active', 'suspect', 'retired', 'cited')),
        at_key TEXT NOT NULL, actor TEXT NOT NULL, case_ref TEXT, reason TEXT, commit_hash TEXT NOT NULL""",
    "rulings": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, ruling_id TEXT NOT NULL, question_id TEXT, author_role TEXT NOT NULL,
        author TEXT NOT NULL, kind TEXT NOT NULL, at_key TEXT NOT NULL, commit_hash TEXT NOT NULL""",
    "questions": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL,
        event TEXT NOT NULL CHECK (event IN ('asked', 'reminded', 'answered')), routed_to TEXT NOT NULL,
        at_key TEXT NOT NULL, commit_hash TEXT NOT NULL""",
    "periods": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, event TEXT NOT NULL CHECK (event IN ('lock')),
        at_key TEXT NOT NULL, actor TEXT NOT NULL, commit_hash TEXT NOT NULL""",
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS commits_ref ON commits(payload_ref, ref_type)",
    "CREATE INDEX IF NOT EXISTS sources_id ON sources(source_id)",
    "CREATE INDEX IF NOT EXISTS metar_raw ON metar(raw)",
    "CREATE INDEX IF NOT EXISTS facts_id ON facts(fact_id, recorded_key)",
    "CREATE INDEX IF NOT EXISTS decisions_entity ON decisions(entity_id, kind, at_key)",
    "CREATE INDEX IF NOT EXISTS decisions_flight ON decisions(flight_id, kind)",
    "CREATE INDEX IF NOT EXISTS rule_events_rule ON rule_events(rule_id, version, event)",
    "CREATE INDEX IF NOT EXISTS rulings_id ON rulings(ruling_id)",
    "CREATE INDEX IF NOT EXISTS questions_id ON questions(question_id)",
]

VIEWS: dict[str, str] = {
    "rule_status": """
        SELECT e.rule_id, e.version, e.event AS status, e.at_key AS status_at, e.commit_hash,
          (SELECT COUNT(*) FROM rule_events c
            WHERE c.rule_id = e.rule_id AND c.version = e.version AND c.event = 'cited') AS times_cited
        FROM rule_events e
        JOIN (SELECT rule_id, version, MAX(seq) AS seq FROM rule_events WHERE event != 'cited'
              GROUP BY rule_id, version) m ON m.seq = e.seq""",
    "question_status": """
        SELECT q.question_id,
          CASE WHEN EXISTS (SELECT 1 FROM questions a WHERE a.question_id = q.question_id AND a.event = 'answered')
                 THEN 'answered'
               WHEN EXISTS (SELECT 1 FROM questions r WHERE r.question_id = q.question_id AND r.event = 'reminded')
                 THEN 'reminded'
               ELSE 'open' END AS status,
          q.routed_to, q.at_key, q.commit_hash
        FROM questions q
        JOIN (SELECT question_id, MAX(seq) AS seq FROM questions GROUP BY question_id) m ON m.seq = q.seq""",
    "current_decisions": """
        SELECT d.* FROM decisions d
        JOIN (SELECT entity_id, kind, MAX(seq) AS seq FROM decisions GROUP BY entity_id, kind) m ON m.seq = d.seq""",
    "period_status": """
        SELECT period, 'locked' AS status, MIN(at_key) AS locked_at FROM periods WHERE event = 'lock'
        GROUP BY period""",
}


def init_schema(conn: sqlite3.Connection) -> None:
    for name, cols in TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
        for op in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {name}_no_{op.lower()} BEFORE {op} ON {name} "
                f"BEGIN SELECT RAISE(ABORT, '{name} is append-only'); END")
    for sql in INDEXES:
        conn.execute(sql)
    for name, sql in VIEWS.items():
        conn.execute(f"CREATE VIEW IF NOT EXISTS {name} AS {sql}")


# ---------- replay / revert results ----------

@dataclass(frozen=True)
class ReplayRun:
    """A replay with its before/after state. ``diff`` is what the API returns; nothing here was written."""
    diff: ReplayDiff
    before: dict[str, FlightDecision]
    after: dict[str, FlightDecision]
    before_entitlements: dict[str, Entitlement]
    after_entitlements: dict[str, Entitlement]
    ias8_class: Ias8Class
    decisive_received_at: datetime | None     # latest receipt among the unused decisive evidence (prior-period error)
    output_hash: str                          # sha256 over the re-decided outputs: identical on every replay

    def changed_flights(self) -> list[str]:
        return sorted(f for f, a in self.after.items() if _changed(self.before.get(f), a, DECISION_FIELDS))

    def changed_coupons(self) -> list[str]:
        return sorted(c for c, a in self.after_entitlements.items()
                      if _changed(self.before_entitlements.get(c), a, ENTITLEMENT_FIELDS))


@dataclass(frozen=True)
class RevertOutcome:
    diff: ReplayDiff
    ias8_class: Ias8Class
    adjustment_period: str
    retired: Commit | None        # None when the rule was already retired
    commit: Commit                # the revert commit
    journal: tuple[JournalEntry, ...]
    run: ReplayRun


# ---------- small helpers ----------

def _val(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    return jsonable(v)


def _changed(before: BaseModel | None, after: BaseModel, fields: Sequence[str]) -> bool:
    if before is None:
        return True
    return any(_val(getattr(before, f)) != _val(getattr(after, f)) for f in fields)


def _field_flips(entity_id: str, before: BaseModel | None, after: BaseModel, fields: Sequence[str]) -> list[ReplayFlip]:
    out = []
    for f in fields:
        b = _val(getattr(before, f)) if before is not None else None
        a = _val(getattr(after, f))
        if b != a:
            out.append(ReplayFlip(entity_id=entity_id, field=f, before=b, after=a))
    return out


def _due(e: Entitlement | None) -> int:
    if e is None or e.status not in ACCRUING:
        return 0
    return max(int(e.compensation_cents) - int(e.voucher_offset_cents), 0)


def parse_rule_ref(ref: str) -> tuple[str, int | None]:
    """``R-CL-1@2`` → (``R-CL-1``, 2); ``R-CL-1`` → (``R-CL-1``, None = latest version)."""
    rid, sep, v = (ref or "").strip().rpartition("@")
    if sep and v.isdigit():
        return rid, int(v)
    return (ref or "").strip(), None


def eur(cents: int) -> str:
    """``€34,650`` / ``€34,650.50`` / ``−€600``."""
    c = int(cents)
    whole, frac = divmod(abs(c), 100)
    return ("−" if c < 0 else "") + f"€{whole:,}" + (f".{frac:02d}" if frac else "")


def _default_ref(payload: Any) -> str:
    for attr in ("id", "coupon_id", "flight_id"):
        v = payload.get(attr) if isinstance(payload, Mapping) else getattr(payload, attr, None)
        if isinstance(v, str) and v:
            return v
    return payload_hash(payload)[:16]


def _call_with_supported(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``fn(*args)`` plus whichever keyword arguments its signature accepts (e.g. Books.post_recode)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


# ---------- labels ----------

_STATUS_WORDS = {
    "owed": "owed", "no_compensation": "no compensation; refunds and care still due", "held": "held for Legal",
    "needs_ruling": "needs a ruling", "exempt_notice": "exempt (notice)", "out_of_scope": "out of scope",
    "staff_ticket": "staff ticket",
}
_EXT_WORDS = {"extraordinary": "extraordinary", "not_extraordinary": "not extraordinary", "needs_legal": "needs Legal"}
_JE_STATUS = {"draft": "drafted, pending approval", "approved": "approved · parked, not posted", "posted": "posted"}


def _fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif v is None:
        s = "null"
    else:
        s = v if isinstance(v, str) else orjson.dumps(v).decode()
    return s if len(s) <= 80 else s[:77] + "…"


def _hhmm(iso: str | None) -> str:
    if not iso:
        return "?"
    t = datetime.fromisoformat(iso).astimezone(UTC)
    return f"{t:%H:%M}Z"


def _confidence_words(conf: Mapping[str, Any] | None) -> str:
    if not conf:
        return ""
    label = conf.get("label") or "confidence"
    score = conf.get("score")
    return f"{label} {round(score * 100)}%" if isinstance(score, (int, float)) else f"{label} uncalibrated"


def _decision_message(d: FlightDecision) -> str:
    parts = [d.flight_id.split("@")[0], d.cause.value, _EXT_WORDS.get(d.extraordinary.value, d.extraordinary.value)]
    if d.recoded and d.recode_label:
        parts.append(f"recoded {d.recode_label}")
    if d.confidence.score is not None:
        parts.append(f"{d.confidence.score:.2f}")
    return " · ".join(parts)


class _Row:
    """A commits row plus its decoded payload."""

    def __init__(self, r: sqlite3.Row):
        self.row = r
        self.hash: str = r["hash"]
        self.ref_type: str = r["ref_type"]
        self.payload: Any = orjson.loads(r["payload"])

    def commit(self) -> Commit:
        return _commit_of(self.row)


def _commit_of(r: sqlite3.Row) -> Commit:
    return Commit.model_validate({
        "hash": r["hash"], "parent": r["parent"], "kind": r["kind"], "at": r["at"], "actor": r["actor"],
        "payload_hash": r["payload_hash"], "payload_ref": r["payload_ref"], "inputs": orjson.loads(r["inputs"]),
        "message": r["message"]})


BLAME_RANK = {"journal_event": 0, "entitlement": 1, "decision": 2, "revert": 3, "rule_event": 4, "ruling": 5,
              "question": 6, "fact": 7, "llm_call": 8, "source": 9, "metar": 10}


# ---------- the store ----------

class TraceStore:
    """``TraceStore(db_path, engine_sha=..., cal_version=...)``; ``":memory:"`` works for tests.

    ``engine_sha`` (the engine's git sha) and ``cal_version`` are passed in, never computed, and ride on every
    commit's ``inputs`` as ``engine@<sha>`` and ``cal@<version>``.
    """

    def __init__(self, db_path: str | Path = ":memory:", *, engine_sha: str, cal_version: str):
        engine_sha = str(engine_sha or "").strip().removeprefix("engine@")
        cal_version = str(cal_version or "").strip().removeprefix("cal@")
        if not engine_sha:
            raise ValueError("engine_sha must be passed in (the engine's git sha); the trace never computes it")
        if not cal_version:
            raise ValueError("cal_version must be passed in (e.g. 'cal-v1')")
        self.engine_sha = engine_sha
        self.cal_version = cal_version
        self.base_inputs = (f"engine@{engine_sha}", f"cal@{cal_version}")
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:" and "mode=memory" not in self.db_path:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._depth = 0
        self._head: str | None = None
        with self._tx():
            init_schema(self.conn)
        self._head = self._q1("SELECT hash FROM commits ORDER BY seq DESC LIMIT 1")

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._depth == 0
            head = self._head if outer else None
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                    self._head = head
                raise
            self._depth -= 1
            if outer:
                self.conn.execute("COMMIT")

    def _q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(args)).fetchall()

    def _q1(self, sql: str, args: Iterable[Any] = ()) -> Any:
        rows = self._q(sql, args)
        return rows[0][0] if rows else None

    def _append(self, kind: str, payload: Any, actor: str, inputs: Iterable[str | None], at: datetime, *, ref: str,
                message: str, ref_type: str) -> Commit:
        """Append one commit at the head of the chain. Call inside ``_tx``."""
        if kind not in COMMIT_KINDS:
            raise TraceError(f"unknown commit kind {kind!r}")
        if ref_type not in REF_TYPES:
            raise TraceError(f"unknown ref_type {ref_type!r}")
        if not actor:
            raise TraceError("every commit needs an actor")
        at = utc(at)
        body = canonical(payload)
        c = Commit(hash="", parent=self._head, kind=kind, at=at, actor=str(actor), payload_hash=sha256_hex(body),
                   payload_ref=str(ref), inputs=normalize_inputs([*inputs, *self.base_inputs]), message=message)
        c = c.model_copy(update={"hash": commit_hash(c)})
        self.conn.execute(
            "INSERT INTO commits(hash, parent, kind, at, at_key, actor, payload_hash, payload_ref, inputs, message, "
            "ref_type, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c.hash, c.parent, c.kind, c.model_dump(mode="json")["at"], time_key(at), c.actor, c.payload_hash,
             c.payload_ref, orjson.dumps(c.inputs).decode(), c.message, ref_type, body))
        self._head = c.hash
        return c

    # ------------------------------------------------------------------ commits

    def commit(self, kind: str, payload: Any, actor: str, inputs: Iterable[str], at: datetime, *,
               ref: str | None = None, message: str = "", ref_type: str | None = None) -> Commit:
        """Append a commit. ``inputs`` = hashes of the commits this one derives from (plus any tags)."""
        ref = ref or _default_ref(payload)
        with self._tx():
            return self._append(kind, payload, actor, inputs, at, ref=ref, message=message or f"{kind} {ref}",
                                ref_type=ref_type or kind)

    def head(self) -> str | None:
        return self._head

    def __len__(self) -> int:
        return int(self._q1("SELECT COUNT(*) FROM commits") or 0)

    def get(self, commit_hash_: str) -> Commit:
        rows = self._q("SELECT * FROM commits WHERE hash = ?", [commit_hash_])
        if not rows:
            raise NotFound(f"no commit {commit_hash_}", hash=commit_hash_)
        return _commit_of(rows[0])

    def payload(self, commit_hash_: str) -> Any:
        raw = self._q1("SELECT payload FROM commits WHERE hash = ?", [commit_hash_])
        if raw is None:
            raise NotFound(f"no commit {commit_hash_}", hash=commit_hash_)
        return orjson.loads(raw)

    def log(self, limit: int | None = 100, *, kind: str | None = None) -> list[Commit]:
        """Newest first (``GET /commits?limit=``)."""
        sql = "SELECT * FROM commits" + (" WHERE kind = ?" if kind else "") + " ORDER BY seq DESC"
        args: list[Any] = [kind] if kind else []
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [_commit_of(r) for r in self._q(sql, args)]

    def all_commits(self) -> list[Commit]:
        """Oldest first: the chain in order."""
        return [_commit_of(r) for r in self._q("SELECT * FROM commits ORDER BY seq")]

    def verify(self) -> Verification:
        """Recompute every payload hash and commit hash along the stored chain (``make verify``)."""
        commits: list[Commit | None] = []
        payloads: list[Any] = []
        for r in self._q("SELECT * FROM commits ORDER BY seq"):
            try:
                commits.append(_commit_of(r))
            except (ValidationError, ValueError, TypeError, orjson.JSONDecodeError):
                commits.append(None)
            payloads.append(bytes(r["payload"]) if r["payload"] is not None else b"")
        return verify_chain(commits, payloads)

    # ------------------------------------------------------------------ links

    def _source_commit(self, source_id: str | None) -> str | None:
        if not source_id:
            return None
        return self._q1("SELECT commit_hash FROM sources WHERE source_id = ? ORDER BY seq DESC LIMIT 1", [source_id])

    def _fact_commit(self, fact_id: str) -> str | None:
        return self._q1("SELECT commit_hash FROM facts WHERE fact_id = ? ORDER BY seq DESC LIMIT 1", [fact_id])

    def _metar_by_raw(self, raw: str | None) -> str | None:
        if not raw:
            return None
        return self._q1("SELECT commit_hash FROM metar WHERE raw = ? ORDER BY seq DESC LIMIT 1", [raw.strip()])

    def _rule_version(self, rule_id: str, version: int | None) -> int | None:
        if version is not None:
            return version
        return self._q1("SELECT MAX(version) FROM rule_events WHERE rule_id = ?", [rule_id])

    def _rule_commit(self, ref: str, at_key: str = _MAX_KEY) -> str | None:
        rid, v = parse_rule_ref(ref)
        v = self._rule_version(rid, v)
        if v is None:
            return None
        return self._q1("SELECT commit_hash FROM rule_events WHERE rule_id = ? AND version = ? AND event != 'cited' "
                        "AND at_key <= ? ORDER BY seq DESC LIMIT 1", [rid, v, at_key])

    def _ruling_commit(self, ruling_id: str | None) -> str | None:
        if not ruling_id:
            return None
        return self._q1("SELECT commit_hash FROM rulings WHERE ruling_id = ? ORDER BY seq DESC LIMIT 1", [ruling_id])

    def _question_commit(self, question_id: str | None) -> str | None:
        if not question_id:
            return None
        return self._q1("SELECT commit_hash FROM questions WHERE question_id = ? ORDER BY seq DESC LIMIT 1",
                        [question_id])

    def _entity_commit(self, entity_id: str, kind: str) -> str | None:
        return self._q1("SELECT commit_hash FROM decisions WHERE entity_id = ? AND kind = ? ORDER BY seq DESC "
                        "LIMIT 1", [entity_id, kind])

    def _flight_entitlement_commit(self, flight_id: str) -> str | None:
        return self._q1("SELECT commit_hash FROM decisions WHERE flight_id = ? AND kind = 'entitlement' "
                        "ORDER BY seq DESC LIMIT 1", [flight_id])

    # ------------------------------------------------------------------ typed recorders

    def record_source(self, source: Source, actor: str, at: datetime, inputs: Iterable[str] = ()) -> Commit:
        with self._tx():
            c = self._append("fact", source, actor, inputs, at, ref=source.id, ref_type="source",
                             message=f"source {source.kind.value} · {source.title} (tier {source.trust_tier})")
            self.conn.execute(
                "INSERT INTO sources(source_id, kind, trust_tier, received_key, pii, commit_hash) VALUES (?,?,?,?,?,?)",
                (source.id, source.kind.value, source.trust_tier, time_key(source.received_at),
                 int("pii" in source.acl_tags), c.hash))
        return c

    def record_metar(self, obs: Iterable[MetarObs], actor: str, at: datetime, *,
                     source_id: str | None = None) -> list[Commit]:
        """One commit per observation, linked to its source when ``source_id`` is recorded."""
        out: list[Commit] = []
        with self._tx():
            src = self._source_commit(source_id)
            for o in sorted(obs, key=lambda o: (o.station, o.valid, o.raw)):
                valid = utc(o.valid)
                c = self._append("fact", o, actor, [src], at, ref=f"{o.station}@{valid:%Y-%m-%dT%H:%MZ}",
                                 ref_type="metar", message=f"METAR {o.station} {valid:%d %b %H:%MZ}")
                self.conn.execute("INSERT INTO metar(station, valid_key, raw, commit_hash) VALUES (?,?,?,?)",
                                  (o.station, time_key(valid), o.raw.strip(), c.hash))
                out.append(c)
        return out

    def record_fact(self, fact: Fact, actor: str, at: datetime, inputs: Iterable[str] = ()) -> Commit:
        return self.record_facts([fact], actor, at, inputs)[0]

    def record_facts(self, facts: Iterable[Fact], actor: str, at: datetime,
                     inputs: Iterable[str] = ()) -> list[Commit]:
        """Each fact links to its source commit and, when its span is a raw METAR line, to that observation."""
        inputs = list(inputs)
        out: list[Commit] = []
        with self._tx():
            for f in facts:
                links = [*inputs, self._source_commit(f.source_id), self._metar_by_raw(f.span)]
                c = self._append("fact", f, actor, links, at, ref=f.id, ref_type="fact",
                                 message=f"fact {f.subject} · {f.field}")
                self.conn.execute(
                    "INSERT INTO facts(fact_id, subject, field, source_id, recorded_key, pii, commit_hash) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (f.id, f.subject, f.field, f.source_id, time_key(f.recorded_at), int("pii" in f.acl_tags), c.hash))
                out.append(c)
        return out

    def record_decision(self, decision: FlightDecision, actor: str, at: datetime,
                        inputs: Iterable[str] = ()) -> Commit:
        """Links the evidence facts and the rules applied (the version in force when recorded)."""
        with self._tx():
            key = time_key(at)
            links = list(inputs)
            links += [self._fact_commit(e.fact_id) for e in decision.evidence]
            links += [self._rule_commit(r, key) for r in decision.rules_applied]
            payload = decision.model_copy(update={"commit": None})
            c = self._append("decision", payload, actor, links, at, ref=decision.flight_id, ref_type="decision",
                             message=_decision_message(decision))
            self.conn.execute(
                "INSERT INTO decisions(entity_id, flight_id, kind, known_key, at_key, commit_hash, body) "
                "VALUES (?,?,?,?,?,?,?)",
                (decision.flight_id, decision.flight_id, "decision", time_key(decision.known_at), key, c.hash,
                 canonical(decision.model_copy(update={"commit": c.hash}))))
        return c

    def record_entitlements(self, ents: Iterable[Entitlement], actor: str, at: datetime,
                            inputs: Iterable[str] = ()) -> list[Commit]:
        """One commit per flight (payload: its coupons' entitlements), linked to the flight's decision and rules."""
        by_flight: dict[str, list[Entitlement]] = {}
        for e in ents:
            by_flight.setdefault(e.flight_id, []).append(e)
        out: list[Commit] = []
        inputs = list(inputs)
        with self._tx():
            key = time_key(at)
            for fid in sorted(by_flight):
                group = sorted(by_flight[fid], key=lambda e: e.coupon_id)
                links = [*inputs, self._entity_commit(fid, "decision")]
                links += [self._rule_commit(r, key) for r in sorted({r for e in group for r in e.rules_applied})]
                total = sum(_due(e) for e in group)
                c = self._append("entitlement", group, actor, links, at, ref=fid, ref_type="entitlement",
                                 message=f"{fid.split('@')[0]} · {len(group)} entitlements · {eur(total)} full "
                                         f"Art. 7 entitlement")
                self.conn.executemany(
                    "INSERT INTO decisions(entity_id, flight_id, kind, known_key, at_key, commit_hash, body) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [(e.coupon_id, fid, "entitlement", key, key, c.hash, canonical(e)) for e in group])
                out.append(c)
        return out

    def record_rule(self, rule: Rule, actor: str, at: datetime, *, event: str | None = None,
                    inputs: Iterable[str] = (), reason: str = "", case_ref: str | None = None) -> Commit:
        """A rule status event (``proposed``/``shadow``/``active``/``suspect``/``retired``); links its ruling."""
        ev = event or rule.status
        if ev not in RULE_STATUS_EVENTS:
            raise TraceError(f"unknown rule event {ev!r}; citations go through cite_rule")
        ref = dsl.ref(rule)
        with self._tx():
            payload = rule.model_copy(update={"status": ev, "times_cited": 0})   # both are views over events
            c = self._append("rule_event", payload, actor, [*inputs, self._ruling_commit(rule.origin_ruling_id)], at,
                             ref=ref, ref_type="rule_event", message=f"{ref} {ev}" + (f" · {reason}" if reason else ""))
            self.conn.execute(
                "INSERT INTO rule_events(rule_id, version, event, at_key, actor, case_ref, reason, commit_hash) "
                "VALUES (?,?,?,?,?,?,?,?)", (rule.id, rule.version, ev, time_key(at), actor, case_ref, reason, c.hash))
        return c

    def cite_rule(self, rule_ref: str, case_ref: str, actor: str, at: datetime) -> Commit:
        """``times_cited`` is the count of these events."""
        rid, v = parse_rule_ref(rule_ref)
        v = self._rule_version(rid, v)
        target = self._rule_commit(f"{rid}@{v}") if v is not None else None
        if target is None:
            raise NotFound(f"no rule {rule_ref}", rule_ref=rule_ref)
        ref = f"{rid}@{v}"
        with self._tx():
            c = self._append("rule_event", {"rule": ref, "case_ref": case_ref}, actor, [target], at, ref=ref,
                             ref_type="rule_event", message=f"{ref} cited · {case_ref}")
            self.conn.execute(
                "INSERT INTO rule_events(rule_id, version, event, at_key, actor, case_ref, reason, commit_hash) "
                "VALUES (?,?,?,?,?,?,?,?)", (rid, v, "cited", time_key(at), actor, case_ref, None, c.hash))
        return c

    def record_ruling(self, ruling: Ruling, actor: str, at: datetime, inputs: Iterable[str] = ()) -> Commit:
        with self._tx():
            c = self._append("ruling", ruling, actor, [*inputs, self._question_commit(ruling.question_id)], at,
                             ref=ruling.id, ref_type="ruling",
                             message=f"{ruling.author_role.value} {ruling.author} ruled"
                                     + (f" on {ruling.question_id}" if ruling.question_id else "")
                                     + f": {ruling.decision}")
            self.conn.execute(
                "INSERT INTO rulings(ruling_id, question_id, author_role, author, kind, at_key, commit_hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (ruling.id, ruling.question_id, ruling.author_role.value, ruling.author, ruling.kind, time_key(at),
                 c.hash))
        return c

    def record_question(self, question: Question, actor: str, at: datetime, *, event: str = "asked",
                        inputs: Iterable[str] = ()) -> Commit:
        """``asked`` links the evidence facts; ``reminded``/``answered`` link the previous question event."""
        if event not in QUESTION_EVENTS:
            raise TraceError(f"unknown question event {event!r}")
        with self._tx():
            links = list(inputs)
            if event == "asked":
                links += [self._fact_commit(e.fact_id) for e in question.evidence]
            else:
                prev = self._question_commit(question.id)
                if prev is None:
                    raise NotFound(f"question {question.id} was never asked", question_id=question.id)
                links.append(prev)
            status = {"asked": "open"}.get(event, event)
            score = question.confidence.score
            c = self._append("question", question.model_copy(update={"status": status}), actor, links, at,
                             ref=question.id, ref_type="question",
                             message=f"{question.id} {event} → {question.routed_to.value} · {question.pattern}"
                                     + (f" · {score:.2f}" if score is not None else "")
                                     + f" · {question.reason_tag}")
            self.conn.execute(
                "INSERT INTO questions(question_id, event, routed_to, at_key, commit_hash) VALUES (?,?,?,?,?)",
                (question.id, event, question.routed_to.value, time_key(at), c.hash))
        return c

    def record_journal(self, je: JournalEntry, actor: str, at: datetime, *, event: str = "drafted",
                       inputs: Iterable[str] = ()) -> Commit:
        """A JE event; links the decision and entitlements of every flight the entry is built from."""
        flights = sorted({*(ln.dims["flight"] for ln in je.lines if ln.dims.get("flight")),
                          *([je.source_decision_id] if je.source_decision_id else [])})
        with self._tx():
            links = list(inputs)
            for fid in flights:
                links += [self._entity_commit(fid, "decision"), self._flight_entitlement_commit(fid)]
            dr = sum(ln.dr_cents for ln in je.lines)
            c = self._append("journal_event", je, actor, links, at, ref=je.id, ref_type="journal_event",
                             message=f"{je.id} {event} · {je.kind} · {je.period} · {eur(dr)}")
        return c

    def record_period_lock(self, period: str, actor: str, at: datetime) -> Commit:
        _parse_period(period)
        with self._tx():
            c = self._append("period_lock", {"period": period, "locked_by": actor}, actor, [], at, ref=period,
                             ref_type="period_lock", message=f"Period {period} locked")
            self.conn.execute("INSERT INTO periods(period, event, at_key, actor, commit_hash) VALUES (?,?,?,?,?)",
                              (period, "lock", time_key(at), actor, c.hash))
        return c

    def record_llm_call(self, payload: Mapping[str, Any], actor: str, at: datetime, inputs: Iterable[str] = (), *,
                        ref: str | None = None, message: str | None = None) -> Commit:
        """Plan §2 rule 2: prompt hash, ``response.model``, request id, principal, input fact ids."""
        model = payload.get("model") or payload.get("response_model") or "?"
        return self.commit("llm_call", dict(payload), actor, inputs, at, ref=ref or _default_ref(payload),
                           message=message or f"{actor} · {model}", ref_type="llm_call")

    def record_access_denied(self, decision: AccessDecision, *, message: str | None = None,
                             inputs: Iterable[str] = ()) -> Commit:
        tag = decision.reason.split(":", 1)[0].strip() or "denied"
        msg = message or f"{decision.principal} {decision.action} → DENIED · {tag}"
        return self.commit("access_denied", decision, decision.principal, inputs, decision.at,
                           ref=decision.resource or "-", message=msg, ref_type="access_denied")

    # ------------------------------------------------------------------ views

    def sources(self) -> dict[str, Source]:
        rows = self._q("SELECT c.payload FROM sources s JOIN commits c ON c.hash = s.commit_hash ORDER BY s.seq")
        out: dict[str, Source] = {}
        for r in rows:
            src = Source.model_validate(orjson.loads(r[0]))
            out[src.id] = src
        return out

    def facts_known_at(self, known_at: datetime) -> list[Fact]:
        """Facts with ``recorded_at <= known_at``; the latest version per fact id, in recording order."""
        rows = self._q(
            "SELECT c.payload FROM facts f JOIN commits c ON c.hash = f.commit_hash WHERE f.seq IN "
            "(SELECT MAX(seq) FROM facts WHERE recorded_key <= ? GROUP BY fact_id) ORDER BY f.seq",
            [time_key(known_at)])
        return [Fact.model_validate(orjson.loads(r[0])) for r in rows]

    def rules_known_at(self, known_at: datetime | None = None) -> list[Rule]:
        """Every rule version as known at ``known_at`` (all events when None), status and times_cited as views."""
        key = time_key(known_at) if known_at is not None else _MAX_KEY
        rows = self._q(
            "SELECT e.rule_id, e.version, e.event, c.payload FROM rule_events e JOIN commits c ON c.hash = e.commit_hash "
            "WHERE e.seq IN (SELECT MAX(seq) FROM rule_events WHERE event != 'cited' AND at_key <= ? "
            "GROUP BY rule_id, version) ORDER BY e.rule_id, e.version", [key])
        cited = {(r[0], r[1]): r[2] for r in self._q(
            "SELECT rule_id, version, COUNT(*) FROM rule_events WHERE event = 'cited' AND at_key <= ? "
            "GROUP BY rule_id, version", [key])}
        return [Rule.model_validate({**orjson.loads(r["payload"]), "status": r["event"],
                                     "times_cited": cited.get((r["rule_id"], r["version"]), 0)}) for r in rows]

    def rule(self, rule_ref: str, known_at: datetime | None = None) -> Rule:
        rid, v = parse_rule_ref(rule_ref)
        hits = [r for r in self.rules_known_at(known_at) if r.id == rid and (v is None or r.version == v)]
        if not hits:
            raise NotFound(f"no rule {rule_ref}", rule_ref=rule_ref)
        return max(hits, key=lambda r: r.version)

    def question(self, question_id: str) -> Question:
        rows = self._q("SELECT s.status, c.payload FROM question_status s JOIN commits c ON c.hash = s.commit_hash "
                       "WHERE s.question_id = ?", [question_id])
        if not rows:
            raise NotFound(f"no question {question_id}", question_id=question_id)
        return Question.model_validate({**orjson.loads(rows[0]["payload"]), "status": rows[0]["status"]})

    def questions(self, status: str | None = None) -> list[Question]:
        ids = [r[0] for r in self._q("SELECT question_id FROM question_status ORDER BY question_id")]
        qs = [self.question(i) for i in ids]
        return [q for q in qs if status is None or q.status == status]

    def _current(self, kind: str, known_at: datetime | None, flight_id: str | None = None) -> list[bytes]:
        key = time_key(known_at) if known_at is not None else _MAX_KEY
        sql = ("SELECT body FROM decisions WHERE seq IN (SELECT MAX(seq) FROM decisions WHERE kind = ? AND at_key <= ? "
               + ("AND flight_id = ? " if flight_id else "") + "GROUP BY entity_id) ORDER BY entity_id")
        return [r[0] for r in self._q(sql, [kind, key, *([flight_id] if flight_id else [])])]

    def decisions(self, known_at: datetime | None = None) -> dict[str, FlightDecision]:
        """The latest recorded decision per flight (as recorded by ``known_at`` when given)."""
        out = {}
        for body in self._current("decision", known_at):
            d = FlightDecision.model_validate(orjson.loads(body))
            out[d.flight_id] = d
        return out

    def decision(self, flight_id: str) -> FlightDecision | None:
        body = self._q1("SELECT body FROM current_decisions WHERE entity_id = ? AND kind = 'decision'", [flight_id])
        return FlightDecision.model_validate(orjson.loads(body)) if body is not None else None

    def entitlements(self, flight_id: str | None = None, known_at: datetime | None = None) -> dict[str, Entitlement]:
        out = {}
        for body in self._current("entitlement", known_at, flight_id):
            e = Entitlement.model_validate(orjson.loads(body))
            out[e.coupon_id] = e
        return out

    def locked_periods(self) -> dict[str, datetime]:
        """Period → when it was locked (first lock event)."""
        return {r[0]: _from_key(r[1]) for r in self._q("SELECT period, locked_at FROM period_status ORDER BY period")}

    def _locks(self, extra: Mapping[str, datetime] | Iterable[str] | None) -> dict[str, datetime]:
        """Recorded locks, plus any passed in (e.g. ``Books.locked_periods()``). A lock passed without a time is
        taken as locked at the end of its period."""
        locks = self.locked_periods()
        if extra is None:
            return locks
        items = extra.items() if isinstance(extra, Mapping) else ((p, None) for p in extra)
        for p, at in items:
            t = utc(at) if at is not None else period_end(p)
            locks[p] = min(locks.get(p, t), t)
        return dict(sorted(locks.items()))

    def access_log(self) -> list[AccessDecision]:
        rows = self._q("SELECT payload FROM commits WHERE ref_type = 'access_denied' ORDER BY seq")
        return [AccessDecision.model_validate(orjson.loads(r[0])) for r in rows]

    # ------------------------------------------------------------------ replay

    def _received_at(self, facts: Iterable[Fact]) -> dict[str, datetime]:
        """When each fact's information reached us: its source's ``received_at``, else the fact's ``recorded_at``."""
        recv = {r[0]: _from_key(r[1]) for r in self._q(
            "SELECT source_id, MIN(received_key) FROM sources GROUP BY source_id")}
        return {f.id: recv.get(f.source_id, utc(f.recorded_at)) for f in facts}

    @staticmethod
    def _run(decide_fn: DecideFn, facts: list[Fact], rules: list[Rule], known_at: datetime
             ) -> tuple[dict[str, FlightDecision], dict[str, Entitlement]]:
        decs: dict[str, FlightDecision] = {}
        ents: dict[str, Entitlement] = {}
        for out in decide_fn(list(facts), list(rules), known_at):
            if isinstance(out, FlightDecision):
                decs[out.flight_id] = out
            elif isinstance(out, Entitlement):
                ents[out.coupon_id] = out
            else:
                raise TraceError(f"decide_fn yielded {type(out).__name__}; expected FlightDecision or Entitlement")
        return dict(sorted(decs.items())), dict(sorted(ents.items()))

    def replay(self, known_at: datetime, decide_fn: DecideFn, rules_override: Iterable[Rule] | None = None,
               preview_fn: PreviewFn | None = None, *, rule_ref: str = "replay",
               locks: Mapping[str, datetime] | Iterable[str] | None = None) -> ReplayDiff:
        return self.replay_run(known_at, decide_fn, rules_override, preview_fn, rule_ref=rule_ref, locks=locks).diff

    def replay_run(self, known_at: datetime, decide_fn: DecideFn, rules_override: Iterable[Rule] | None = None,
                   preview_fn: PreviewFn | None = None, *, rule_ref: str = "replay",
                   locks: Mapping[str, datetime] | Iterable[str] | None = None) -> ReplayRun:
        """Re-run the pure ``decide_fn(facts, rules, known_at)`` over the facts recorded by ``known_at`` and the rules
        as known then (or ``rules_override``), and diff it against what was on record at ``known_at``.

        Never calls an LLM, never writes. ``preview_fn`` (``BooksAPI.preview``) prices the € delta; without it the
        delta is the change in gross entitlement still due. The class is IAS 8.5 (see ``_ias8``).
        """
        known_at = utc(known_at)
        facts = self.facts_known_at(known_at)
        rules = (sorted(rules_override, key=lambda r: (r.id, r.version)) if rules_override is not None
                 else self.rules_known_at(known_at))
        after_d, after_e = self._run(decide_fn, facts, rules, known_at)
        on_record_d = self.decisions(known_at)
        on_record_e = self.entitlements(known_at=known_at)
        before_d = {f: on_record_d[f] for f in after_d if f in on_record_d}
        before_e = {c: on_record_e[c] for c in after_e if c in on_record_e}

        flips: list[ReplayFlip] = []
        for fid, a in after_d.items():
            flips += _field_flips(fid, before_d.get(fid), a, DECISION_FIELDS)
        changed_e = [c for c, a in after_e.items() if _changed(before_e.get(c), a, ENTITLEMENT_FIELDS)]
        for c in changed_e:
            flips += _field_flips(c, before_e.get(c), after_e[c], ENTITLEMENT_FIELDS)
        if changed_e and preview_fn is not None:
            pv = preview_fn([before_e[c] for c in after_e if c in before_e], list(after_e.values()))
            flips += list(pv.flips)
            total = int(pv.total_delta_cents)
        else:
            per_flight: dict[str, list[int]] = {}
            for c in changed_e:
                b, a = before_e.get(c), after_e[c]
                s = per_flight.setdefault(a.flight_id, [0, 0])
                s[0] += _due(b)
                s[1] += _due(a)
            money = [ReplayFlip(entity_id=f, field="entitlement_cents", before=b, after=a, delta_cents=a - b)
                     for f, (b, a) in sorted(per_flight.items()) if a != b]
            flips += money
            total = sum(f.delta_cents for f in money)
        flips.sort(key=lambda f: (f.entity_id, _FIELD_ORDER.get(f.field, len(_FIELD_ORDER)), f.field))

        locked = self._locks(locks)
        diff = ReplayDiff(rule_ref=rule_ref, known_at=known_at, flips=flips, total_delta_cents=total,
                          locked_periods_untouched=sorted(locked), adjustment_je_ids=[])
        cls, decisive_at = self._ias8(decide_fn, facts, before_d, after_d, locked)
        output_hash = payload_hash({"decisions": list(after_d.values()), "entitlements": list(after_e.values())})
        return ReplayRun(diff=diff, before=before_d, after=after_d, before_entitlements=before_e,
                         after_entitlements=after_e, ias8_class=cls, decisive_received_at=decisive_at,
                         output_hash=output_hash)

    def _ias8(self, decide_fn: DecideFn, facts: list[Fact], before: dict[str, FlightDecision],
              after: dict[str, FlightDecision], locked: Mapping[str, datetime]) -> tuple[Ias8Class, datetime | None]:
        """IAS 8.5 evidence-availability test for every flipped decision whose event period is locked.

        Counterfactual: re-decide with only the information available at the lock (facts whose source was received
        by then) and the rules as known then. If that already gives the new outcome, the new outcome's supporting
        evidence was decisive and available; any of it the recorded decision did not use makes a prior-period error.
        Otherwise the change needed something new (a later claim, ruling or document): a change in estimate.
        """
        flipped = [f for f, a in after.items() if f in before and _changed(before[f], a, DECISION_FIELDS)]
        by_lock: dict[str, list[str]] = {}
        for fid in flipped:
            p = event_period(fid)
            if p in locked:
                by_lock.setdefault(p, []).append(fid)
        if not by_lock:
            return "change_in_estimate", None
        received = self._received_at(facts)
        decisive_at: list[datetime] = []
        cls: Ias8Class = "change_in_estimate"
        for period, fids in sorted(by_lock.items()):
            lock_at = locked[period]
            available = [f for f in facts if received[f.id] <= lock_at]
            cf, _ = self._run(decide_fn, available, self.rules_known_at(lock_at), lock_at)
            avail_ids = {f.id for f in available}
            for fid in fids:
                if fid not in cf or _changed(cf[fid], after[fid], DECISION_FIELDS):
                    continue                     # the new outcome needed information from after the lock
                used = {e.fact_id for e in before[fid].evidence}
                uses = [EvidenceUse(e.fact_id, received[e.fact_id], decisive=True, used=e.fact_id in used)
                        for e in after[fid].evidence
                        if e.role == "supports" and not e.struck and e.fact_id in avail_ids]
                if ias8_class(uses, lock_at) == "prior_period_error":
                    cls = "prior_period_error"
                    decisive_at += [u.received_at for u in uses if not u.used]
        return cls, (max(decisive_at) if decisive_at else None)

    # ------------------------------------------------------------------ revert

    def revert(self, rule_ref: str, *, actor: str, at: datetime, decide_fn: DecideFn,
               preview_fn: PreviewFn | None = None, post_recode_fn: PostRecodeFn | None = None,
               locks: Mapping[str, datetime] | Iterable[str] | None = None, reason: str = "",
               persist: bool = True) -> RevertOutcome:
        """Record a ``retired`` rule event, replay at ``at``, and report the adjustment in the current open period.

        ``post_recode_fn`` is ``BooksAPI.post_recode(before, after, known_at)``; ``evidence_received_at`` and
        ``rule_ref`` are passed too when its signature takes them. Every JE it returns must sit in an open period,
        else ``LockedPeriodWrite``: a revert never writes into a locked period. With ``persist`` the re-decided
        flights and coupons and the adjustment JEs are recorded, linked to the revert commit.
        """
        at = utc(at)
        rule = self.rule(rule_ref)
        if rule.tier == "hard_control" or rule.static_card:
            raise TraceError(f"{dsl.ref(rule)} is a hard control (code) or a display card; it cannot be reverted",
                             rule_ref=rule_ref)
        ref = dsl.ref(rule)
        with self._lock:
            retired = None
            if rule.status != "retired":
                retired = self.record_rule(rule, actor, at, event="retired", reason=reason or "reverted")
            run = self.replay_run(at, decide_fn, preview_fn=preview_fn, rule_ref=ref, locks=locks)
            locked = self._locks(locks)
            period = adjustment_period(at, locked)
            jes: list[JournalEntry] = []
            coupons = run.changed_coupons()
            if post_recode_fn is not None and coupons:
                before = [run.before_entitlements[c] for c in coupons if c in run.before_entitlements]
                after = [run.after_entitlements[c] for c in coupons]
                ev_at = run.decisive_received_at if run.ias8_class == "prior_period_error" else None
                jes = list(_call_with_supported(post_recode_fn, before, after, at, evidence_received_at=ev_at,
                                                rule_ref=ref))
            bad = sorted({je.period for je in jes if je.period in locked})
            if bad:
                raise LockedPeriodWrite(f"revert of {ref}: an adjustment landed in locked period {', '.join(bad)}; "
                                        f"it belongs in {period}", periods=bad, adjustment_period=period)
            diff = run.diff.model_copy(update={"adjustment_je_ids": [je.id for je in jes]})
            n = len({f.entity_id for f in diff.flips})
            msg = (f"Reverted {ref} · flips {n} · Δ {eur(diff.total_delta_cents)}"
                   + (f" · {', '.join(sorted(locked))} locked, untouched" if locked else "")
                   + (" · prior-period error, corrected in current period (immaterial)"
                      if run.ias8_class == "prior_period_error" else " · change in estimate (IAS 8.36)")
                   + f" · {period}")
            link = retired.hash if retired else self._rule_commit(ref)
            rc = self.commit("revert", {"rule_ref": ref, "diff": diff, "ias8_class": run.ias8_class,
                                        "adjustment_period": period, "reason": reason},
                             actor, [link], at, ref=ref, message=msg, ref_type="revert")
            if persist:
                for fid in run.changed_flights():
                    self.record_decision(run.after[fid], actor, at, inputs=[rc.hash])
                if coupons:
                    self.record_entitlements([run.after_entitlements[c] for c in coupons], actor, at,
                                             inputs=[rc.hash])
                for je in jes:
                    self.record_journal(je, je.preparer or actor, at, inputs=[rc.hash])
        return RevertOutcome(diff=diff, ias8_class=run.ias8_class, adjustment_period=period, retired=retired,
                             commit=rc, journal=tuple(jes), run=run)

    # ------------------------------------------------------------------ blame

    def _row(self, h: str) -> _Row | None:
        rows = self._q("SELECT * FROM commits WHERE hash = ?", [h])
        return _Row(rows[0]) if rows else None

    def _by_ref(self, ref: str, ref_type: str | None = None) -> str | None:
        if ref_type:
            return self._q1("SELECT hash FROM commits WHERE payload_ref = ? AND ref_type = ? ORDER BY seq DESC "
                            "LIMIT 1", [ref, ref_type])
        return self._q1("SELECT hash FROM commits WHERE payload_ref = ? ORDER BY seq DESC LIMIT 1", [ref])

    def _resolve(self, target: str) -> tuple[str, tuple[str, Any] | None]:
        t = (target or "").strip()
        if _HEX64.fullmatch(t) and self._row(t) is not None:
            return t, None
        m = _JE_LINE.fullmatch(t)
        if m:
            h = self._by_ref(m.group(1), "journal_event")
            if h:
                return h, ("je_line", int(m.group(2)))
        if t.startswith("JE-"):
            h = self._by_ref(t, "journal_event")
            if h:
                return h, None
        h = self._entity_commit(t, "entitlement")
        if h:
            return h, ("coupon", t)
        h = self._entity_commit(t, "decision") or self._by_ref(t, "entitlement")
        if h:
            return h, None
        rid, v = parse_rule_ref(t)
        if self._rule_version(rid, v) is not None:
            h = self._rule_commit(t)
            if h:
                return h, None
        h = (self._question_commit(t) or self._ruling_commit(t) or self._fact_commit(t) or self._source_commit(t)
             or self._by_ref(t))
        if h:
            return h, None
        raise NotFound(f"nothing to blame for {target!r}", target=target)

    def blame(self, target: str, *, max_steps: int = 100) -> Blame:
        """Walk the stored links from ``target`` (a JE line ``JE-…:n``, JE, coupon entitlement, flight decision,
        rule ref, ruling, question, fact, source or commit hash) down to the evidence:

        JE line → entitlement → decision → rule@v → ruling (author + quote) → question → facts (span) → source →
        METAR obs. Steps are ordered by that stage, then by distance from the target.
        """
        root, focus = self._resolve(target)
        seen: dict[str, _Row] = {}
        order: list[str] = []
        queue = [root]
        while queue:
            h = queue.pop(0)
            if h in seen:
                continue
            row = self._row(h)
            if row is None:
                continue
            seen[h] = row
            order.append(h)
            queue += [i for i in orjson.loads(row.row["inputs"]) if _HEX64.fullmatch(i) and i not in seen]
        pos = {h: i for i, h in enumerate(order)}
        rest = sorted(order[1:], key=lambda h: (BLAME_RANK.get(seen[h].ref_type, len(BLAME_RANK)), pos[h]))
        chain = [root, *rest][:max_steps]
        spans: dict[str, str] = {}
        for h in chain:
            r = seen[h]
            if r.ref_type == "fact" and r.payload.get("span"):
                spans.setdefault(r.payload.get("source_id"), r.payload["span"])
        tiers = {r[0]: r[1] for r in self._q("SELECT source_id, trust_tier FROM sources")}
        kinds = {r[0]: r[1] for r in self._q("SELECT source_id, kind FROM sources")}
        steps = [self._step(seen[h], focus if h == root else None, spans, tiers, kinds) for h in chain]
        return Blame(target=target, steps=steps)

    def _step(self, r: _Row, focus: tuple[str, Any] | None, spans: Mapping[str, str], tiers: Mapping[str, int],
              kinds: Mapping[str, str]) -> BlameStep:
        p, c = r.payload, r.commit()
        label, quote = c.message, None
        if r.ref_type == "journal_event":
            status = _JE_STATUS.get(p.get("status"), p.get("status"))
            if focus and focus[0] == "je_line":
                n = focus[1]
                lines = p.get("lines") or []
                if not 1 <= n <= len(lines):
                    raise NotFound(f"{p.get('id')} has no line {n}", target=f"{p.get('id')}:{n}")
                ln = lines[n - 1]
                side, amt = ("Dr", ln.get("dr_cents", 0)) if ln.get("dr_cents") else ("Cr", ln.get("cr_cents", 0))
                label = f"{p['id']}:{n} · {side} {ln['account']} {ln['account_name']} {eur(amt)} · {status}"
            else:
                label = f"{p['id']} · {p['kind']} · {p['period']} · {status}"
                if p.get("ias8_class") not in (None, "none"):
                    label += f" · {p['ias8_class'].replace('_', ' ')}"
        elif r.ref_type == "entitlement":
            ents = p if isinstance(p, list) else [p]
            if focus and focus[0] == "coupon":
                e = next((x for x in ents if x.get("coupon_id") == focus[1]), None) or ents[0]
                label = (f"Entitlement {e['coupon_id']} · {eur(e['compensation_cents'])} · "
                         f"{_STATUS_WORDS.get(e['status'], e['status'])}")
                if e.get("reduction") == "art7_2_50pct":
                    label += " · 50% reroute cut (Art. 7(2))"
                if e.get("voucher_offset_cents"):
                    label += f" · voucher offset {eur(e['voucher_offset_cents'])}"
                label += f" · {e['article']}"
            else:
                fid = ents[0]["flight_id"] if ents else c.payload_ref
                total = sum(_due(Entitlement.model_validate(x)) for x in ents)
                label = f"Entitlements {fid} · {len(ents)} coupons · {eur(total)} full Art. 7 entitlement"
        elif r.ref_type == "decision":
            label = (f"Decision {p['flight_id']} · {p['cause']} · "
                     f"{_EXT_WORDS.get(p['extraordinary'], p['extraordinary'])}")
            if p.get("recoded") and p.get("recode_label"):
                label += f" · recoded {p['recode_label']}"
            cw = _confidence_words(p.get("confidence"))
            if cw:
                label += f" · {cw}"
        elif r.ref_type == "rule_event":
            if "rule" in p and "case_ref" in p:
                label = f"{p['rule']} cited · {p['case_ref']}"
            else:
                label = (f"{p['id']}@{p['version']} · {p.get('title') or p['action']} · "
                         f"{p['tier'].replace('_', ' ')} · {p['status']}")
                if p.get("support"):
                    label += f" · {p['support']}"
        elif r.ref_type == "ruling":
            label = f"Ruling {p['id']} · {p['author_role']} {p['author']} · {p['kind']}: {p['decision']}"
            quote = p.get("explanation")
        elif r.ref_type == "question":
            label = f"{p['id']} → {p['routed_to']} · {p['pattern']} · {p['reason_tag']}"
            cw = _confidence_words(p.get("confidence"))
            if cw:
                label += f" · {cw}"
        elif r.ref_type == "fact":
            src = p.get("source_id")
            label = f"Fact · {p['subject']} · {p['field']} = {_fmt_value(p.get('value'))}"
            if src in tiers:
                label += f" · {kinds[src]} tier {tiers[src]}"
            quote = p.get("span")
        elif r.ref_type == "source":
            label = (f"Source · {p['kind']} · {p['title']} (tier {p['trust_tier']}) · received "
                     f"{p['received_at']}")
            quote = spans.get(p["id"])
        elif r.ref_type == "metar":
            wind = [f"gust {p['gust']} kt"] if p.get("gust") is not None else []
            wind += [f"sustained {p['sknt']} kt"] if p.get("sknt") is not None else []
            label = " · ".join([f"METAR {p['station']} {_hhmm(p.get('valid'))}", *wind])
            quote = p.get("raw")
        elif r.ref_type == "llm_call":
            label = f"LLM call · {p.get('model') or p.get('response_model') or '?'} · {c.actor}"
        return BlameStep(commit=c, label=label, quote=quote)
