"""Books: deterministic EU261 compensation accounting (IFRS 15 variable consideration) on append-only SQLite.

Implements `contracts.interfaces.BooksAPI`. No LLM, no wall clock (the injected `clock` stamps `recorded_at` only),
no randomness. Money is integer euro cents; rates are exact fractions, rounded half away from zero once per amount.
See books/DECISIONS.md for every judgment call.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, get_args

from contracts.models import (
    CfoMetrics,
    Claim,
    ClaimCurve,
    Entitlement,
    EstimateCard,
    FlightDecision,
    InvariantResult,
    JournalEntry,
    JournalLine,
    OpeningBalance,
    ReplayDiff,
    ReplayFlip,
    Role,
    Rollforward,
    RollforwardRow,
    Session,
    World,
)

from . import store
from .coa import ACCOUNTS, DEBIT_NORMAL
from .curves import Curve, load_curves, normalize_segment, segment_of_band
from .errors import BooksError, Forbidden, NotFound, PeriodLocked, SoDViolation
from .money import apply_rate, eur, pct, round_half_up
from .periods import (
    age_months,
    date_in_id,
    end_of_day_iso,
    iso,
    limitation_expiry,
    months_between,
    next_period,
    parse_period,
    period_end,
    period_of,
    period_start,
    to_utc,
    utc_date,
)

PREPARER = Role.ENGINE.value                      # "agent.engine"
ACCRUING = ("owed", "held", "needs_ruling")       # IFRS 15.56: held / needs-Legal items accrue too
HELD = ("held", "needs_ruling")
PAYOUT_KINDS = frozenset({"claim_approved", "claim_paid"})
JE_KINDS = frozenset(get_args(JournalEntry.model_fields["kind"].annotation))
IAS8_CLASSES = frozenset(get_args(JournalEntry.model_fields["ias8_class"].annotation))
UNASSIGNED = "unassigned"
SENSITIVITY = Fraction(5, 100)                    # ±5 pp on the ultimate
RELEASE_MIN_AGE = 12
RELEASE_MIN_QUIET_MONTHS = 3
CONSTRAINT_NOTE = (
    "IFRS 15.50–58 variable consideration (IFRIC Sept 2019): EU261 compensation is a reduction of passenger "
    "revenue, estimated on € claim curves (expected ultimate claim rate, history to M18 + tail judgment) and "
    "constrained under IFRS 15.56; held / needs-Legal items accrue at their segment rate until resolved."
)
_ACCR_SQL = "('owed','held','needs_ruling')"
_REG_COLS = (
    "coupon_id", "flight_id", "cohort", "segment", "band_eur", "distance_km", "status", "compensation_cents",
    "reduction", "voucher_offset_cents", "voucher_signed_sha256", "election", "article", "rules_applied",
    "decision_commit", "cause", "recoded", "confidence", "claim_ids", "settlement", "je_ids", "event_date",
    "limitation_expiry", "reason", "known_at", "recorded_at",
)
_REG_JSON = ("rules_applied", "claim_ids", "je_ids")


def _accrues(status: str, comp: int) -> int:
    return comp if status in ACCRUING and comp > 0 else 0


@dataclass
class _Seg:
    entitlement: int = 0
    pax: int = 0
    actual: int = 0
    book: int = 0


@dataclass
class _FlightDelta:
    flight_id: str
    cohort: str
    by_segment: dict[str, tuple[int, int]] = field(default_factory=dict)   # seg -> (before, after) liability
    coupons: list[str] = field(default_factory=list)

    @property
    def before(self) -> int:
        return sum(b for b, _ in self.by_segment.values())

    @property
    def after(self) -> int:
        return sum(a for _, a in self.by_segment.values())

    @property
    def delta(self) -> int:
        return self.after - self.before


class Books:
    """`Books(db_path, clock)`; `":memory:"` works for tests."""

    def __init__(self, db_path: str | Path = ":memory:", clock: Any = None, curves_path: str | Path | None = None):
        if clock is None or not callable(getattr(clock, "now", None)):
            raise ValueError("Books needs an injected clock with .now()")
        self.clock = clock
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:" and "mode=memory" not in self.db_path:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._depth = 0
        with self._tx():
            store.init_schema(self._conn)
        self._curves, self.curves_source = load_curves(curves_path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self._conn.execute("COMMIT")

    def _q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(args)).fetchall()

    def _q1(self, sql: str, args: Iterable[Any] = ()) -> Any:
        rows = self._q(sql, args)
        return rows[0][0] if rows else None

    def _now(self) -> str:
        return iso(self.clock.now())

    def _curve(self, segment: str) -> Curve:
        return self._curves[normalize_segment(segment)]

    # ------------------------------------------------------------------ periods

    def _is_locked(self, period: str) -> bool:
        return bool(self._q("SELECT 1 FROM books_period_events WHERE period = ? AND kind = 'lock' LIMIT 1", [period]))

    def locked_periods(self) -> list[str]:
        return [r[0] for r in self._q("SELECT period FROM books_period_status ORDER BY period")]

    def _target(self, event_date: date, known_at: datetime) -> tuple[date, dict[str, str]]:
        """Cut-off follows event_date; an event in a locked period is booked in the current open period, flagged."""
        p = period_of(event_date)
        if not self._is_locked(p):
            return event_date, {}
        kd = utc_date(known_at)
        open_p = max(next_period(p), period_of(kd))
        while self._is_locked(open_p):
            open_p = next_period(open_p)
        eff = kd if period_of(kd) == open_p else period_start(open_p)
        return eff, {"adjusted_from_period": p, "original_event_date": event_date.isoformat()}

    @staticmethod
    def _flag_memo(memo: str, flags: dict[str, str], eff: date) -> str:
        if not flags:
            return memo
        return (f"{memo} · out-of-period: event {flags['original_event_date']} falls in locked period "
                f"{flags['adjusted_from_period']}; booked in open period {period_of(eff)}")

    # ------------------------------------------------------------------ journal writes

    def _insert_je(self, *, kind: str, event_date: date, memo: str, lines: list[dict], known_at: datetime,
                   preparer: str = PREPARER, ias8_class: str = "none", reverses: str | None = None,
                   estimate_ref: str | None = None, source_decision_id: str | None = None, built_from: int = 0,
                   ties_to: Iterable[str] = (), gated: bool = False, run_id: str | None = None,
                   cohort: str | None = None, flight_id: str | None = None, flags: dict[str, str] | None = None,
                   period: str | None = None) -> str:
        if kind not in JE_KINDS:
            raise BooksError(f"unknown JE kind {kind!r}")
        if ias8_class not in IAS8_CLASSES:
            raise BooksError(f"unknown ias8_class {ias8_class!r}")
        p = period or period_of(event_date)
        if p != period_of(event_date):
            raise BooksError(f"cut-off: JE.period {p} must follow event_date {event_date}")
        if self._is_locked(p):
            raise PeriodLocked(f"period {p} is locked; locked periods are never written", period=p)
        clean: list[tuple[str, int, int, dict[str, str]]] = []
        tdr = tcr = 0
        for raw in lines:
            acct = str(raw["account"])
            if acct not in ACCOUNTS:
                raise BooksError(f"account {acct} is not in the chart of accounts")
            d, c = int(raw.get("dr", 0)), int(raw.get("cr", 0))
            if d < 0 or c < 0 or (d > 0) == (c > 0):
                raise BooksError("each journal line has exactly one positive side")
            dims = {k: str(v) for k, v in (raw.get("dims") or {}).items() if v is not None}
            dims.update(flags or {})
            clean.append((acct, d, c, dims))
            tdr, tcr = tdr + d, tcr + c
        if tdr != tcr or tdr <= 0:
            raise BooksError(f"journal entry does not balance: Σdr {tdr} ≠ Σcr {tcr}")
        conn = self._conn
        n = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM books_je").fetchone()[0]
        je_id = f"JE-{n:06d}"
        now = self._now()
        conn.execute(
            "INSERT INTO books_je(je_id, event_date, period, kind, memo, ias8_class, reverses, estimate_ref, "
            "source_decision_id, preparer, built_from, ties_to, gated, run_id, cohort, flight_id, flags, known_at, "
            "recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (je_id, event_date.isoformat(), p, kind, memo, ias8_class, reverses, estimate_ref, source_decision_id,
             preparer, int(built_from), json.dumps(list(ties_to)), int(bool(gated)), run_id, cohort, flight_id,
             json.dumps(flags or {}, sort_keys=True), iso(known_at), now))
        conn.executemany(
            "INSERT INTO books_je_lines(je_id, line_no, account, dr_cents, cr_cents, cohort, segment, flight_id, dims) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(je_id, i, a, d, c, dims.get("cohort"), dims.get("segment"), dims.get("flight"),
              json.dumps(dims, sort_keys=True)) for i, (a, d, c, dims) in enumerate(clean, start=1)])
        conn.execute("INSERT INTO books_je_events(je_id, kind, principal, role, reason, at) VALUES (?,?,?,?,?,?)",
                     (je_id, "drafted", preparer, preparer if preparer.startswith("agent.") else "human", None, now))
        return je_id

    def post_entry(self, *, kind: str, event_date: date, lines: list[JournalLine | dict], memo: str,
                   known_at: datetime, preparer: str = PREPARER, period: str | None = None,
                   ias8_class: str = "none", estimate_ref: str | None = None, reverses: str | None = None,
                   gated: bool = False) -> JournalEntry:
        """Direct (manual) posting. Posting into a locked period raises PeriodLocked; nothing is redirected."""
        raw = []
        for l in lines:
            if isinstance(l, JournalLine):
                raw.append({"account": l.account, "dr": l.dr_cents, "cr": l.cr_cents, "dims": l.dims})
            else:
                raw.append({"account": l["account"], "dr": l.get("dr_cents", l.get("dr", 0)),
                            "cr": l.get("cr_cents", l.get("cr", 0)), "dims": l.get("dims")})
        cohorts = {d["dims"].get("cohort") for d in raw if d.get("dims")} - {None}
        with self._tx():
            je_id = self._insert_je(kind=kind, event_date=event_date, memo=memo, lines=raw, known_at=to_utc(known_at),
                                    preparer=preparer, period=period, ias8_class=ias8_class,
                                    estimate_ref=estimate_ref, reverses=reverses, gated=gated,
                                    cohort=cohorts.pop() if len(cohorts) == 1 else None)
        return self._je(je_id)

    # ------------------------------------------------------------------ journal reads

    def _je_many(self, ids: list[str]) -> list[JournalEntry]:
        if not ids:
            return []
        out: list[JournalEntry] = []
        for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
            marks = ",".join("?" * len(chunk))
            heads = {r["je_id"]: r for r in self._q(
                f"SELECT j.*, s.status, s.approver FROM books_je j JOIN books_je_status s ON s.je_id = j.je_id "
                f"WHERE j.je_id IN ({marks})", chunk)}
            lines: dict[str, list[JournalLine]] = defaultdict(list)
            for r in self._q(f"SELECT * FROM books_je_lines WHERE je_id IN ({marks}) ORDER BY je_id, line_no", chunk):
                lines[r["je_id"]].append(JournalLine(account=r["account"], account_name=ACCOUNTS[r["account"]],
                                                     dr_cents=r["dr_cents"], cr_cents=r["cr_cents"],
                                                     dims=json.loads(r["dims"])))
            for je_id in chunk:
                h = heads.get(je_id)
                if h is None:
                    raise NotFound(f"journal entry {je_id} not found", je_id=je_id)
                out.append(JournalEntry(
                    id=je_id, event_date=date.fromisoformat(h["event_date"]), period=h["period"], memo=h["memo"],
                    lines=lines[je_id], kind=h["kind"], ias8_class=h["ias8_class"], reverses=h["reverses"],
                    estimate_ref=h["estimate_ref"], source_decision_id=h["source_decision_id"],
                    status="approved" if h["status"] == "approved" else "draft", preparer=h["preparer"],
                    approver=h["approver"], built_from=h["built_from"], ties_to=json.loads(h["ties_to"])))
        return out

    def _je(self, je_id: str) -> JournalEntry:
        return self._je_many([je_id])[0]

    def _head(self, je_id: str) -> sqlite3.Row:
        rows = self._q("SELECT j.*, s.status, s.approver FROM books_je j JOIN books_je_status s "
                       "ON s.je_id = j.je_id WHERE j.je_id = ?", [je_id])
        if not rows:
            raise NotFound(f"journal entry {je_id} not found", je_id=je_id)
        return rows[0]

    def journal(self, period: str | None = None, status: str | None = None) -> list[JournalEntry]:
        sql = ("SELECT j.je_id FROM books_je j JOIN books_je_status s ON s.je_id = j.je_id "
               "WHERE s.status != 'rejected'")
        args: list[Any] = []
        if period:
            parse_period(period)
            sql += " AND j.period = ?"
            args.append(period)
        if status:
            if status == "posted":                 # StormCheck never posts beyond approved (parked)
                return []
            if status not in ("draft", "approved"):
                raise ValueError(f"status must be draft|approved|posted, got {status!r}")
            sql += " AND s.status = ?"
            args.append(status)
        return self._je_many([r[0] for r in self._q(sql + " ORDER BY j.seq", args)])

    # ------------------------------------------------------------------ GL balances

    def _liab(self, account: str = "2140", *, through: str | None = None, in_period: str | None = None,
              before: str | None = None, cohort: str | None = None, segment: str | None = None) -> int:
        """cr − dr over GL-counted lines (+ opening balances unless restricted to one period)."""
        sql = "SELECT COALESCE(SUM(cr_cents - dr_cents), 0) FROM books_gl_lines WHERE account = ?"
        osql = "SELECT COALESCE(SUM(balance_cents), 0) FROM books_opening_balances WHERE account = ?"
        args: list[Any] = [account]
        oargs: list[Any] = [account]
        for col, op, val in (("period", "<=", through), ("period", "=", in_period), ("period", "<", before),
                             ("cohort", "=", cohort), ("segment", "=", segment)):
            if val is not None:
                sql += f" AND {col} {op} ?"
                args.append(val)
                if not (col == "period" and op == "="):
                    osql += f" AND {col} {op} ?"
                    oargs.append(val)
        total = self._q1(sql, args)
        if in_period is None:
            total += self._q1(osql, oargs)
        return int(total)

    def gl_balance(self, account: str, period: str | None = None, cohort: str | None = None) -> int:
        """Natural-sign balance through `period` (all periods when None)."""
        if account not in ACCOUNTS:
            raise NotFound(f"account {account} not in chart of accounts")
        if period:
            parse_period(period)
        bal = self._liab(account, through=period, cohort=cohort)
        return -bal if account in DEBIT_NORMAL else bal

    def segment_balances(self, cohort: str, period: str | None = None) -> dict[str, int]:
        sql = "SELECT segment, COALESCE(SUM(cr_cents - dr_cents), 0) FROM books_gl_lines WHERE account = '2140' " \
              "AND cohort = ?"
        args: list[Any] = [cohort]
        if period:
            sql += " AND period <= ?"
            args.append(period)
        out = {r[0]: int(r[1]) for r in self._q(sql + " GROUP BY segment", args)}
        for r in self._q("SELECT segment, balance_cents FROM books_opening_balances WHERE account = '2140' "
                         "AND cohort = ?" + (" AND period <= ?" if period else ""), args):
            out[r[0]] = out.get(r[0], 0) + int(r[1])
        return out

    # ------------------------------------------------------------------ register

    def _reg_decode(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in _REG_JSON:
            d[k] = json.loads(d[k])
        d["recoded"] = bool(d["recoded"])
        return d

    def _register_rows(self, *, flight_ids: Iterable[str] | None = None, cohort: str | None = None,
                       as_of: str | None = None) -> list[dict[str, Any]]:
        if as_of is None:
            sql, args = "SELECT * FROM books_register WHERE 1=1", []
        else:
            sql = ("SELECT r.* FROM books_register_events r JOIN (SELECT coupon_id, MAX(seq) AS seq "
                   "FROM books_register_events WHERE known_at <= ? GROUP BY coupon_id) m ON m.seq = r.seq WHERE 1=1")
            args = [as_of]
        if cohort is not None:
            sql += " AND cohort = ?"
            args.append(cohort)
        if flight_ids is not None:
            fl = sorted(set(flight_ids))
            if not fl:
                return []
            sql += f" AND flight_id IN ({','.join('?' * len(fl))})"
            args += fl
        return [self._reg_decode(r) for r in self._q(sql + " ORDER BY coupon_id", args)]

    def _register_one(self, coupon_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM books_register_events WHERE coupon_id = ? ORDER BY seq DESC LIMIT 1",
                       [coupon_id])
        return self._reg_decode(rows[0]) if rows else None

    def register(self, flight_id: str | None = None, coupon_id: str | None = None,
                 cohort: str | None = None) -> list[dict[str, Any]]:
        """Obligation register, current row per coupon (a view over append-only register events)."""
        if coupon_id:
            row = self._register_one(coupon_id)
            return [row] if row else []
        return self._register_rows(flight_ids=[flight_id] if flight_id else None, cohort=cohort)

    def _reg_insert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        now = self._now()
        vals = []
        for r in rows:
            r = dict(r, recorded_at=now)
            vals.append(tuple(json.dumps(r[c]) if c in _REG_JSON else
                              int(r[c]) if c == "recoded" else r[c] for c in _REG_COLS))
        self._conn.executemany(
            f"INSERT INTO books_register_events({','.join(_REG_COLS)}) VALUES ({','.join('?' * len(_REG_COLS))})",
            vals)

    @staticmethod
    def _reg_from_ent(ent: Entitlement, *, cohort: str, event_date: date, known_at: datetime, reason: str,
                      je_ids: list[str], prev: dict[str, Any] | None = None,
                      decision: FlightDecision | None = None, election: str | None = None,
                      signed: str | None = None) -> dict[str, Any]:
        base: dict[str, Any] = dict(prev) if prev else {
            "claim_ids": [], "settlement": None, "je_ids": [], "decision_commit": None, "cause": None,
            "recoded": False, "confidence": None, "election": None, "voucher_signed_sha256": None,
            "event_date": event_date.isoformat(), "limitation_expiry": limitation_expiry(event_date).isoformat(),
        }
        base.update({
            "coupon_id": ent.coupon_id, "flight_id": ent.flight_id, "cohort": base.get("cohort") or cohort,
            "segment": segment_of_band(ent.band_eur), "band_eur": int(ent.band_eur),
            "distance_km": float(ent.distance_km), "status": ent.status,
            "compensation_cents": int(ent.compensation_cents), "reduction": ent.reduction,
            "voucher_offset_cents": int(ent.voucher_offset_cents), "article": ent.article,
            "rules_applied": list(ent.rules_applied), "reason": reason, "known_at": iso(known_at),
            "je_ids": list(base.get("je_ids", [])) + [j for j in je_ids if j not in base.get("je_ids", [])],
        })
        if decision is not None:
            base.update({"decision_commit": decision.commit, "cause": decision.cause.value,
                         "recoded": bool(decision.recoded), "confidence": decision.confidence.score})
        if election is not None:
            base["election"] = election
        if signed is not None:
            base["voucher_signed_sha256"] = signed
        return base

    # ------------------------------------------------------------------ cohorts

    def _ensure_cohort(self, cohort: str, event_date: date, source: str) -> None:
        self._conn.execute("INSERT OR IGNORE INTO books_cohorts(cohort, event_date, source, recorded_at) "
                           "VALUES (?,?,?,?)", (cohort, event_date.isoformat(), source, self._now()))

    def _cohorts(self) -> list[tuple[str, date]]:
        return [(r[0], date.fromisoformat(r[1]))
                for r in self._q("SELECT cohort, event_date FROM books_cohorts ORDER BY cohort")]

    def _cohort_date(self, cohort: str) -> date | None:
        v = self._q1("SELECT event_date FROM books_cohorts WHERE cohort = ?", [cohort])
        return date.fromisoformat(v) if v else None

    def _cohort_of_flight(self, flight_id: str) -> str | None:
        return self._q1("SELECT run_id FROM books_storm_flights WHERE flight_id = ?", [flight_id])

    def _cohort_segments(self, cohort: str, period: str, known_at_iso: str) -> dict[str, _Seg]:
        pend = period_end(period).isoformat()
        segs: dict[str, _Seg] = defaultdict(_Seg)
        for r in self._q(
                "SELECT r.segment, SUM(r.compensation_cents), COUNT(*) FROM books_register_events r JOIN "
                "(SELECT coupon_id, MAX(seq) AS seq FROM books_register_events WHERE known_at <= ? GROUP BY coupon_id)"
                f" m ON m.seq = r.seq WHERE r.cohort = ? AND r.status IN {_ACCR_SQL} AND r.compensation_cents > 0 "
                "GROUP BY r.segment", [known_at_iso, cohort]):
            segs[r[0]].entitlement += int(r[1])
            segs[r[0]].pax += int(r[2])
        for r in self._q("SELECT segment, entitlement_cents, claimed_cents, balance_cents FROM books_opening_balances "
                         "WHERE cohort = ? AND account = '2140' AND period <= ?", [cohort, period]):
            s = segs[r[0]]
            s.entitlement += int(r[1])
            s.actual += int(r[2])
            s.book += int(r[3])
        for r in self._q(
                "SELECT c.segment, SUM(c.amount_cents) FROM books_claim_events c JOIN books_je_status s "
                "ON s.je_id = c.approval_je_id WHERE c.cohort = ? AND c.kind = 'approved' AND s.status != 'rejected' "
                "AND c.event_date <= ? AND c.known_at <= ? GROUP BY c.segment", [cohort, pend, known_at_iso]):
            segs[r[0]].actual += int(r[1])
        for r in self._q("SELECT segment, SUM(cr_cents - dr_cents) FROM books_gl_lines WHERE account = '2140' "
                         "AND cohort = ? AND period <= ? GROUP BY segment", [cohort, period]):
            segs[r[0]].book += int(r[1])
        return dict(segs)

    def _months_since_last_claim(self, cohort: str, event: date, period: str, known_at_iso: str) -> int:
        pend = period_end(period).isoformat()
        last = self._q1("SELECT MAX(event_date) FROM books_claim_events WHERE cohort = ? AND kind = 'approved' "
                        "AND event_date <= ? AND known_at <= ?", [cohort, pend, known_at_iso])
        refs = [date.fromisoformat(last)] if last else []
        for r in self._q("SELECT as_of FROM books_opening_balances WHERE cohort = ? AND claimed_cents > 0 "
                         "AND period <= ?", [cohort, period]):
            refs.append(date.fromisoformat(r[0][:10]))
        ref = max(refs) if refs else event
        return months_between(period_of(ref), period)

    def _keeps_tail(self, cohort: str, known_at_iso: str) -> bool:
        return bool(self._q("SELECT 1 FROM books_policy_events WHERE kind = 'keep_tail' AND (cohort = ? OR "
                            "cohort = '*') AND known_at <= ? LIMIT 1", [cohort, known_at_iso]))

    def _bf_target(self, s: _Seg, curve: Curve, age: int, keep_tail: bool) -> int:
        """BF remaining = (ultimate − expected rate at age) × entitlement, bounded to [0, unclaimed]."""
        rem = apply_rate(s.entitlement, curve.remaining_rate(age))
        if keep_tail and age >= RELEASE_MIN_AGE:
            rem = max(rem, apply_rate(s.entitlement, curve.remaining_rate(RELEASE_MIN_AGE)))
        return min(max(rem, 0), max(s.entitlement - s.actual, 0))

    # ------------------------------------------------------------------ BooksAPI: day 1

    def post_opening_balances(self, balances: Iterable[OpeningBalance], known_at: datetime) -> None:
        """Migrated cohort balances (e.g. Storm Isha). Idempotent per (cohort, account)."""
        with self._tx():
            for ob in balances:
                if self._q("SELECT 1 FROM books_opening_balances WHERE cohort = ? AND account = ?",
                           [ob.cohort, ob.account]):
                    continue
                if ob.account not in ACCOUNTS:
                    raise BooksError(f"opening balance account {ob.account} not in chart of accounts")
                seg = normalize_segment(ob.curve_segment)
                self._ensure_cohort(ob.cohort, date_in_id(ob.cohort) or utc_date(ob.as_of), "opening_balance")
                self._conn.execute(
                    "INSERT INTO books_opening_balances(cohort, account, segment, entitlement_cents, claimed_cents, "
                    "balance_cents, as_of, period, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ob.cohort, ob.account, seg, ob.entitlement_cents, ob.claimed_cents, ob.balance_cents,
                     iso(ob.as_of), period_of(utc_date(ob.as_of)), self._now()))

    def post_storm(self, run_id: str, world: World, decisions: list[FlightDecision], ents: list[Entitlement],
                   known_at: datetime) -> list[JournalEntry]:
        """Day-1 EU261 compensation estimate per flight: Dr 4090 / Cr 2140 = Σ accruing entitlement × ultimate."""
        known_at = to_utc(known_at)
        flights = {f.id: f for f in world.flights}
        dec = {d.flight_id: d for d in decisions}
        elections = {e.coupon_id: e.kind for e in world.elections}
        signed = {c.coupon_id: c.signed_acceptance_sha256 for c in world.crm
                  if c.kind == "voucher_in_lieu_of_compensation" and c.signed_acceptance_sha256}
        by_flight: dict[str, list[Entitlement]] = defaultdict(list)
        for e in sorted(ents, key=lambda e: e.coupon_id):
            by_flight[e.flight_id].append(e)

        def flight_date(fid: str) -> date | None:
            return flights[fid].date if fid in flights else date_in_id(fid)

        dates = [d for d in (flight_date(f) for f in by_flight) if d]
        cohort_date = date_in_id(run_id) or (min(dates) if dates else utc_date(known_at))
        out_ids: list[str] = []
        with self._tx():
            if world.opening_balances:
                self.post_opening_balances(world.opening_balances, known_at)
            self._ensure_cohort(run_id, cohort_date, "storm")
            for fid in sorted(by_flight):
                done = self._q("SELECT je_id FROM books_storm_flights WHERE flight_id = ?", [fid])
                if done:                                              # idempotent: re-runs go through post_recode
                    if done[0][0]:
                        out_ids.append(done[0][0])
                    continue
                fents = by_flight[fid]
                ev = flight_date(fid) or cohort_date
                acc: dict[str, int] = defaultdict(int)
                held = 0
                for e in fents:
                    a = _accrues(e.status, e.compensation_cents)
                    if a:
                        acc[segment_of_band(e.band_eur)] += a
                        held += a if e.status in HELD else 0
                lines, parts = [], []
                for seg in sorted(acc):
                    curve = self._curves[seg]
                    amt = apply_rate(acc[seg], curve.ultimate)
                    if amt <= 0:
                        continue
                    dims = {"storm": run_id, "cohort": run_id, "flight": fid, "segment": seg}
                    lines += [{"account": "4090", "dr": amt, "dims": dims}, {"account": "2140", "cr": amt, "dims": dims}]
                    parts.append(f"full Art. 7 entitlement {eur(acc[seg])} × {pct(curve.ultimate)} expected ultimate "
                                 f"claim rate ({curve.version}, history to M18 + tail judgment) = {eur(amt)}")
                je_id = None
                if lines:
                    eff, flags = self._target(ev, known_at)
                    memo = (f"EU261 compensation liability (estimated) · {fid} · " + "; ".join(parts)
                            + " · reduction of passenger revenue (IFRS 15 variable consideration)")
                    if held:
                        memo += (f" · {eur(held)} of entitlement held pending ruling, accrued under the IFRS 15.56 "
                                 f"constraint at the segment rate")
                    d = dec.get(fid)
                    je_id = self._insert_je(
                        kind="compensation_estimate", event_date=eff, memo=self._flag_memo(memo, flags, eff),
                        lines=lines, known_at=known_at, source_decision_id=d.commit if d else None,
                        built_from=len({ev_.source_id for ev_ in d.evidence}) if d else 0,
                        ties_to=["2140", f"register:{fid}"], run_id=run_id, cohort=run_id, flight_id=fid,
                        flags=flags, estimate_ref=f"day1:{fid}")
                    out_ids.append(je_id)
                self._conn.execute("INSERT INTO books_storm_flights(flight_id, run_id, je_id, known_at, recorded_at) "
                                   "VALUES (?,?,?,?,?)", (fid, run_id, je_id, iso(known_at), self._now()))
                self._reg_insert([self._reg_from_ent(
                    e, cohort=run_id, event_date=ev, known_at=known_at, reason="post_storm",
                    je_ids=[je_id] if je_id and _accrues(e.status, e.compensation_cents) else [],
                    prev=self._register_one(e.coupon_id), decision=dec.get(fid),
                    election=elections.get(e.coupon_id), signed=signed.get(e.coupon_id)) for e in fents])
        return self._je_many(out_ids)

    # ------------------------------------------------------------------ BooksAPI: claims

    def _claim_event(self, claim: Claim, ent: Entitlement, cohort: str, seg: str, kind: str, amount: int,
                     reason: str | None, event_date: date, known_at: datetime, approval: str | None = None,
                     payment: str | None = None, topup: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO books_claim_events(claim_id, coupon_id, flight_id, cohort, segment, kind, amount_cents, "
            "reason, event_date, approval_je_id, payment_je_id, topup_je_id, known_at, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (claim.id, claim.coupon_id, ent.flight_id, cohort, seg, kind, amount, reason, event_date.isoformat(),
             approval, payment, topup, iso(known_at), self._now()))

    def post_claim(self, claim: Claim, ent: Entitlement, known_at: datetime) -> list[JournalEntry]:
        """Approved: Dr 2140 / Cr 2141 at face value, plus a separate payout draft Dr 2141 / Cr 1000.
        Rejected or held: a reason code and no entry."""
        known_at = to_utc(known_at)
        with self._tx():
            prior = self._q("SELECT topup_je_id, approval_je_id, payment_je_id FROM books_claim_events "
                            "WHERE claim_id = ? AND kind = 'approved' ORDER BY seq LIMIT 1", [claim.id])
            if prior:                                               # idempotent per claim id
                return self._je_many([i for i in tuple(prior[0]) if i])
            reg = self._register_one(ent.coupon_id)
            cohort = (reg or {}).get("cohort") or self._cohort_of_flight(ent.flight_id) or UNASSIGNED
            seg = segment_of_band(ent.band_eur)
            today = utc_date(known_at)
            amount = max(0, int(ent.compensation_cents) - int(ent.voucher_offset_cents))
            if ent.status in HELD:
                self._claim_event(claim, ent, cohort, seg, "held", 0, f"pending_ruling:{ent.status}", today, known_at)
                return []
            if ent.status != "owed" or amount <= 0:
                self._claim_event(claim, ent, cohort, seg, "rejected", 0, ent.status if ent.status != "owed"
                                  else "nil_compensation", today, known_at)
                return []
            if self._q("SELECT 1 FROM books_claim_events WHERE coupon_id = ? AND kind = 'approved' LIMIT 1",
                       [ent.coupon_id]):
                self._claim_event(claim, ent, cohort, seg, "rejected", 0, "duplicate_payment_coupon", today, known_at)
                return []
            eff, flags = self._target(today, known_at)
            period = period_of(eff)
            dims = {"cohort": cohort, "segment": seg, "flight": ent.flight_id, "coupon": ent.coupon_id,
                    "claim": claim.id}
            ids: list[str] = []
            book = self._liab("2140", through=period, cohort=cohort, segment=seg)
            if amount > book:                                        # claims beyond the estimate: top up first
                top = amount - max(book, 0)
                ids.append(self._insert_je(
                    kind="change_in_estimate", event_date=eff, known_at=known_at, ias8_class="change_in_estimate",
                    memo=self._flag_memo(
                        f"Change in estimate (IAS 8.36) · cohort {cohort} · {seg}: approved claims exceed the EU261 "
                        f"compensation liability; top-up {eur(top)} before utilising claim {claim.id} · Controller "
                        f"approval required", flags, eff),
                    lines=[{"account": "4090", "dr": top, "dims": dims}, {"account": "2140", "cr": top, "dims": dims}],
                    estimate_ref=f"topup:{claim.id}", cohort=cohort, flight_id=ent.flight_id, flags=flags,
                    ties_to=["2140"]))
            approval = self._insert_je(
                kind="claim_approved", event_date=eff, known_at=known_at,
                memo=self._flag_memo(
                    f"EU261 claim {claim.id} approved at face value {eur(amount)} ({ent.article}) · coupon "
                    f"{ent.coupon_id} · utilises the EU261 compensation liability · drafted, pending Claims Lead "
                    f"approval", flags, eff),
                lines=[{"account": "2140", "dr": amount, "dims": dims}, {"account": "2141", "cr": amount, "dims": dims}],
                cohort=cohort, flight_id=ent.flight_id, flags=flags, ties_to=["2140", "2141", f"claim:{claim.id}"],
                built_from=1)
            payment = self._insert_je(
                kind="claim_paid", event_date=eff, known_at=known_at, reverses=None, gated=True,
                memo=self._flag_memo(
                    f"EU261 payout {eur(amount)} for claim {claim.id} · coupon {ent.coupon_id} · drafted, pending "
                    f"Claims Lead approval (StormCheck never releases a payment run)", flags, eff),
                lines=[{"account": "2141", "dr": amount, "dims": dims}, {"account": "1000", "cr": amount, "dims": dims}],
                cohort=cohort, flight_id=ent.flight_id, flags=flags, ties_to=["2141", f"claim:{claim.id}"],
                built_from=1)
            self._claim_event(claim, ent, cohort, seg, "approved", amount, "face_value", eff, known_at,
                              approval, payment, ids[0] if ids else None)
            ids += [approval, payment]
            prev = reg or self._reg_from_ent(ent, cohort=cohort, event_date=date_in_id(ent.flight_id) or eff,
                                             known_at=known_at, reason="claim_approved", je_ids=[])
            row = dict(prev)
            row.update({"claim_ids": prev["claim_ids"] + [claim.id], "settlement": "claim_approved",
                        "je_ids": prev["je_ids"] + ids, "reason": "claim_approved", "known_at": iso(known_at)})
            self._reg_insert([row])
        return self._je_many(ids)

    # ------------------------------------------------------------------ BooksAPI: recode / preview

    @staticmethod
    def _state(e: Entitlement | dict[str, Any]) -> tuple[str, str, str, int]:
        if isinstance(e, Entitlement):
            return e.flight_id, segment_of_band(e.band_eur), e.status, int(e.compensation_cents)
        return e["flight_id"], e["segment"], e["status"], int(e["compensation_cents"])

    def _plan(self, before: dict[str, tuple], after: dict[str, tuple], known_at: datetime) -> list[_FlightDelta]:
        """Per flight/segment liability before vs after, at BF remaining rate for the cohort's current age."""
        changed = {c for c in set(before) | set(after) if before.get(c) != after.get(c, before.get(c))}
        touched = {s[0] for c in changed for s in (before.get(c), after.get(c)) if s}
        period = period_of(utc_date(known_at))
        sums: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for c in sorted(set(before) | set(after)):
            b = before.get(c)
            a = after.get(c, b)
            if b and b[0] in touched:
                sums[(b[0], b[1])][0] += _accrues(b[2], b[3])
            if a and a[0] in touched:
                sums[(a[0], a[1])][1] += _accrues(a[2], a[3])
        out: dict[str, _FlightDelta] = {}
        for (fid, seg), (bsum, asum) in sorted(sums.items()):
            fd = out.get(fid)
            if fd is None:
                reg_cohort = self._q1("SELECT cohort FROM books_register_events WHERE flight_id = ? LIMIT 1", [fid])
                fd = out[fid] = _FlightDelta(fid, self._cohort_of_flight(fid) or reg_cohort or UNASSIGNED)
            ev = self._cohort_date(fd.cohort)
            rr = self._curves[seg].remaining_rate(age_months(ev, period) if ev else 0)
            fd.by_segment[seg] = (apply_rate(bsum, rr), apply_rate(asum, rr))
        for c in sorted(changed):
            s = after.get(c) or before.get(c)
            out[s[0]].coupons.append(c)
        return [out[f] for f in sorted(out)]

    def preview(self, before: list[Entitlement], after: list[Entitlement]) -> ReplayDiff:
        """Dry run: € liability delta between two entitlement sets. Writes nothing."""
        bmap = {e.coupon_id: self._state(e) for e in before}
        amap = dict(bmap)
        amap.update({e.coupon_id: self._state(e) for e in after})
        plan = [p for p in self._plan(bmap, amap, self.clock.now()) if p.delta != 0]
        flips = [ReplayFlip(entity_id=p.flight_id, field="eu261_liability_cents", before=p.before, after=p.after,
                            delta_cents=p.delta) for p in plan]
        return ReplayDiff(rule_ref="preview", known_at=to_utc(self.clock.now()), flips=flips,
                          total_delta_cents=sum(f.delta_cents for f in flips),
                          locked_periods_untouched=self.locked_periods())

    def post_recode(self, before: list[Entitlement], after: list[Entitlement], known_at: datetime, *,
                    evidence_received_at: datetime | None = None, rule_ref: str | None = None) -> list[JournalEntry]:
        """Recode JE per flight for the liability delta, in the current open period (IAS 8.36 change in estimate).
        Idempotent: the 'before' state is the obligation register where it knows the coupon."""
        known_at = to_utc(known_at)
        flights = {e.flight_id for e in before} | {e.flight_id for e in after}
        with self._tx():
            reg = {r["coupon_id"]: r for r in self._register_rows(flight_ids=flights)}
            bmap = {c: self._state(r) for c, r in reg.items()}
            for e in before:
                bmap.setdefault(e.coupon_id, self._state(e))
            amap = dict(bmap)
            amap.update({e.coupon_id: self._state(e) for e in after})
            plan = self._plan(bmap, amap, known_at)
            after_by_coupon = {e.coupon_id: e for e in after}
            eff, flags = self._target(utc_date(known_at), known_at)
            period = period_of(eff)
            out: list[str] = []
            reg_rows: list[dict[str, Any]] = []
            for fd in plan:
                lines, parts = [], []
                for seg, (b, a) in sorted(fd.by_segment.items()):
                    d = a - b
                    if d < 0:
                        d = -min(-d, max(self._liab("2140", through=period, cohort=fd.cohort, segment=seg), 0))
                    if d == 0:
                        continue
                    dims = {"cohort": fd.cohort, "segment": seg, "flight": fd.flight_id}
                    if d > 0:
                        lines += [{"account": "4090", "dr": d, "dims": dims}, {"account": "2140", "cr": d, "dims": dims}]
                    else:
                        lines += [{"account": "2140", "dr": -d, "dims": dims}, {"account": "4090", "cr": -d, "dims": dims}]
                    parts.append(f"{seg} {eur(b)} → {eur(a)} (Δ {eur(d)})")
                je_id = None
                if lines:
                    kind, ias8, label = "recode", "change_in_estimate", "change in estimate (IAS 8.36), prospective"
                    ev_period = period_of(self._cohort_date(fd.cohort) or eff)
                    if evidence_received_at is not None and self._is_locked(ev_period):
                        locked_at = self._q1("SELECT locked_at FROM books_period_status WHERE period = ?", [ev_period])
                        if iso(evidence_received_at) <= locked_at:          # IAS 8.5: evidence was available
                            kind, ias8 = "out_of_period_adjustment", "prior_period_error"
                            label = "prior-period error, corrected in current period (immaterial)"
                    rules = sorted({r for c in fd.coupons if c in after_by_coupon
                                    for r in after_by_coupon[c].rules_applied} | ({rule_ref} if rule_ref else set()))
                    memo = (f"EU261 compensation liability recode · {fd.flight_id} · " + "; ".join(parts)
                            + f" · {label}" + (f" · rules {', '.join(rules)}" if rules else ""))
                    je_id = self._insert_je(kind=kind, event_date=eff, memo=self._flag_memo(memo, flags, eff),
                                            lines=lines, known_at=known_at, ias8_class=ias8, cohort=fd.cohort,
                                            flight_id=fd.flight_id, flags=flags, estimate_ref=f"recode:{fd.flight_id}",
                                            ties_to=["2140", f"register:{fd.flight_id}"],
                                            built_from=len(fd.coupons))
                    out.append(je_id)
                for c in fd.coupons:
                    ent = after_by_coupon.get(c)
                    if ent is None:
                        continue
                    prev = reg.get(c)
                    ev = (date.fromisoformat(prev["event_date"]) if prev else
                          date_in_id(ent.flight_id) or self._cohort_date(fd.cohort) or eff)
                    reg_rows.append(self._reg_from_ent(ent, cohort=fd.cohort, event_date=ev, known_at=known_at,
                                                       reason="recode", je_ids=[je_id] if je_id else [], prev=prev))
            self._reg_insert(reg_rows)
        return self._je_many(out)

    # ------------------------------------------------------------------ BooksAPI: month end

    def _month_end_jes(self, period: str) -> list[JournalEntry]:
        ids = [r[0] for r in self._q(
            "SELECT j.je_id FROM books_je j JOIN books_je_status s ON s.je_id = j.je_id WHERE j.period = ? "
            "AND s.status != 'rejected' AND (j.estimate_ref LIKE 'BF:%' OR j.estimate_ref LIKE 'release:%') "
            "ORDER BY j.seq", [period])]
        return self._je_many(ids)

    def month_end(self, period: str, known_at: datetime) -> list[JournalEntry]:
        """BF true-up per cohort/segment (draft change_in_estimate) + release proposals (drafts, not posted)."""
        parse_period(period)
        if self._is_locked(period):
            raise PeriodLocked(f"period {period} is locked; month-end cannot write into it", period=period)
        known_at = to_utc(known_at)
        k_iso = iso(known_at)
        pend = period_end(period)
        with self._tx():
            for cohort, event in self._cohorts():
                if event > pend:
                    continue
                age = age_months(event, period)
                if age < 1:                                         # before M1 the day-1 estimate stands
                    continue
                keep = self._keeps_tail(cohort, k_iso)
                closing: dict[str, int] = {}
                for seg, s in sorted(self._cohort_segments(cohort, period, k_iso).items()):
                    curve = self._curves[seg]
                    target = self._bf_target(s, curve, age, keep)
                    closing[seg] = target
                    change = target - s.book
                    if change == 0:
                        continue
                    expected = apply_rate(s.entitlement, curve.rate_at(age))
                    ae = f"{s.actual / expected:.3f}" if expected else "n/a"
                    dims = {"cohort": cohort, "segment": seg}
                    up = change > 0
                    lines = ([{"account": "4090", "dr": change, "dims": dims},
                              {"account": "2140", "cr": change, "dims": dims}] if up else
                             [{"account": "2140", "dr": -change, "dims": dims},
                              {"account": "4090", "cr": -change, "dims": dims}])
                    memo = (f"Change in estimate (IAS 8.36, prospective) · cohort {cohort} · {seg} · M{age}: "
                            f"A/E {ae} (€ basis: actual {eur(s.actual)} vs expected {pct(curve.rate_at(age))} × "
                            f"{eur(s.entitlement)} = {eur(expected)}) · Bornhuetter-Ferguson remaining "
                            f"({pct(curve.ultimate)} − {pct(curve.rate_at(age))}) × {eur(s.entitlement)} = "
                            f"{eur(target)} vs book {eur(s.book)} · {'Dr 4090 / Cr 2140' if up else 'Dr 2140 / Cr 4090'}"
                            f" {eur(abs(change))} · Controller approval required"
                            + (" · tail kept (keep_tail)" if keep and age >= RELEASE_MIN_AGE else ""))
                    self._insert_je(kind="change_in_estimate", event_date=pend, memo=memo, lines=lines,
                                    known_at=known_at, ias8_class="change_in_estimate", cohort=cohort,
                                    estimate_ref=f"BF:{cohort}:{seg}@{period}", ties_to=["2140", f"cohort:{cohort}"],
                                    built_from=s.pax)
                # release proposal: ≥M12, quiet ≥3 months, once per cohort, never under a keep-tail rule
                total = sum(closing.values())
                if age < RELEASE_MIN_AGE or keep or total <= 0:
                    continue
                if self._q("SELECT 1 FROM books_je WHERE estimate_ref = ? LIMIT 1", [f"release:{cohort}"]):
                    continue
                quiet = self._months_since_last_claim(cohort, event, period, k_iso)
                if quiet < RELEASE_MIN_QUIET_MONTHS:
                    continue
                lines = []
                for seg, amt in sorted(closing.items()):
                    if amt > 0:
                        dims = {"cohort": cohort, "segment": seg}
                        lines += [{"account": "2140", "dr": amt, "dims": dims},
                                  {"account": "4090", "cr": amt, "dims": dims}]
                memo = (f"Release proposal (not posted) · cohort {cohort} · M{age}, no new claims in {quiet} months: "
                        f"proposes reducing the EU261 compensation liability {eur(total)} to nil (Dr 2140 / Cr 4090) "
                        f"· Controller decision required · limitation (6 years) expires "
                        f"{limitation_expiry(event).isoformat()}")
                self._insert_je(kind="change_in_estimate", event_date=pend, memo=memo, lines=lines, known_at=known_at,
                                ias8_class="change_in_estimate", cohort=cohort, gated=True,
                                estimate_ref=f"release:{cohort}", ties_to=["2140", f"cohort:{cohort}"])
        return self._month_end_jes(period)

    def keep_tail(self, rule_ref: str, cohorts: list[str] | None, known_at: datetime) -> None:
        """Controller policy (e.g. R-CTL-1): from M12 keep (ultimate − M12 rate) × entitlement until limitation.
        `cohorts=None` applies to all cohorts ('All storm cohorts?')."""
        with self._tx():
            for c in (cohorts if cohorts is not None else ["*"]):
                self._conn.execute("INSERT INTO books_policy_events(kind, cohort, rule_ref, known_at, recorded_at) "
                                   "VALUES ('keep_tail', ?, ?, ?, ?)", (c, rule_ref, iso(known_at), self._now()))

    # ------------------------------------------------------------------ BooksAPI: approvals & locks

    @staticmethod
    def _required_role(kind: str) -> Role:
        return Role.CLAIMS_LEAD if kind in PAYOUT_KINDS else Role.CONTROLLER

    def _authorize(self, head: sqlite3.Row, session: Session, action: str) -> None:
        role = Role(session.role)
        if session.principal == head["preparer"]:
            raise SoDViolation(f"{session.principal} prepared {head['je_id']} and cannot {action} it "
                               f"(preparer ≠ approver)", je_id=head["je_id"], principal=session.principal)
        required = self._required_role(head["kind"])
        if role != required:
            raise SoDViolation(f"{head['kind']} {head['je_id']} needs the {required.value} to {action}; "
                               f"{role.value} cannot", je_id=head["je_id"], principal=session.principal,
                               required_role=required.value)

    def _je_event(self, je_id: str, kind: str, session: Session, reason: str | None = None) -> None:
        self._conn.execute("INSERT INTO books_je_events(je_id, kind, principal, role, reason, at) VALUES (?,?,?,?,?,?)",
                           (je_id, kind, session.principal, Role(session.role).value, reason, self._now()))

    def _decide(self, je_id: str, session: Session, kind: str, reason: str | None = None) -> JournalEntry:
        with self._lock:
            head = self._head(je_id)
            try:
                self._authorize(head, session, "approve" if kind == "approved" else "reject")
            except SoDViolation as exc:
                with self._tx():
                    self._je_event(je_id, "denied", session, exc.message)
                raise
            if head["status"] == kind:
                return self._je(je_id)
            if head["status"] != "draft":
                raise BooksError(f"{je_id} is {head['status']}; cannot mark it {kind}", je_id=je_id)
            if self._is_locked(head["period"]):
                raise PeriodLocked(f"{je_id} is in locked period {head['period']}", period=head["period"])
            with self._tx():
                self._je_event(je_id, kind, session, reason)
            return self._je(je_id)

    def approve(self, je_id: str, session: Session) -> JournalEntry:
        """Raises SoDViolation if the session prepared the JE, or holds the wrong role (JEs: Controller;
        claim approvals and payouts: Claims Lead)."""
        return self._decide(je_id, session, "approved")

    def reject(self, je_id: str, session: Session, reason: str) -> JournalEntry:
        """Reject a draft (e.g. the Controller rejecting a release proposal). Same authority as approve."""
        return self._decide(je_id, session, "rejected", reason)

    def lock_period(self, period: str, session: Session) -> None:
        parse_period(period)
        if Role(session.role) != Role.CONTROLLER:
            raise Forbidden(f"only the controller can lock a period; {Role(session.role).value} cannot",
                            period=period)
        with self._tx():
            if self._is_locked(period):
                return
            self._conn.execute("INSERT INTO books_period_events(period, kind, principal, at) VALUES (?,?,?,?)",
                               (period, "lock", session.principal, self._now()))

    # ------------------------------------------------------------------ BooksAPI: reporting

    def rollforward(self, period: str) -> Rollforward:
        """2140 by cohort. closing = opening + new − claims − settled in kind − derecognised + change in estimate
        + recode + out-of-period. `ties_to_gl` compares Σ closing with an independent sum of GL 2140 lines."""
        parse_period(period)
        rows: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in self._q("SELECT COALESCE(cohort, ?) c, SUM(cr_cents - dr_cents) FROM books_gl_lines "
                         "WHERE account = '2140' AND period < ? GROUP BY c", [UNASSIGNED, period]):
            rows[r[0]]["opening"] += int(r[1])
        for r in self._q("SELECT cohort, SUM(balance_cents) FROM books_opening_balances WHERE account = '2140' "
                         "AND period <= ? GROUP BY cohort", [period]):
            rows[r[0]]["opening"] += int(r[1])
        for r in self._q("SELECT COALESCE(cohort, ?) c, kind, flags, SUM(cr_cents), SUM(dr_cents) FROM books_gl_lines "
                         "WHERE account = '2140' AND period = ? GROUP BY c, kind, flags", [UNASSIGNED, period]):
            row = rows[r[0]]
            kind, adjusted, crs, drs = r[1], "adjusted_from_period" in (r[2] or ""), int(r[3]), int(r[4])
            net = crs - drs
            if kind == "claim_approved":
                row["claims"] += drs - crs
            elif kind == "voucher_in_lieu":
                row["settled"] += drs - crs
            elif kind == "derecognition":
                row["derecognised"] += drs - crs
            elif adjusted or kind == "out_of_period_adjustment":
                row["oop"] += net
            elif kind == "compensation_estimate":
                row["new"] += net
            elif kind == "change_in_estimate":
                row["cie"] += net
            elif kind == "recode":
                row["recode"] += net
            else:
                row["unclassified"] += net                          # will not tie: surfaces a mapping gap
        pend = period_end(period)
        end_iso = end_of_day_iso(pend)
        out: list[RollforwardRow] = []
        for cohort in sorted(rows):
            v = rows[cohort]
            closing = (v["opening"] + v["new"] - v["claims"] - v["settled"] - v["derecognised"] + v["cie"]
                       + v["recode"] + v["oop"])
            segs = self._cohort_segments(cohort, period, end_iso) if cohort != UNASSIGNED else {}
            unclaimed = sum(max(s.entitlement - s.actual, 0) for s in segs.values())
            out.append(RollforwardRow(
                cohort=cohort, opening_cents=v["opening"], new_cents=v["new"], claims_approved_cents=v["claims"],
                settled_in_kind_cents=v["settled"], change_in_estimate_cents=v["cie"], recode_cents=v["recode"],
                out_of_period_cents=v["oop"], derecognised_cents=v["derecognised"], closing_cents=closing,
                unclaimed_entitlement_cents=unclaimed))
        closing_total = sum(r.closing_cents for r in out)
        gl = self._liab("2140", through=period)
        return Rollforward(period=period, rows=out, closing_total_cents=closing_total, gl_balance_cents=gl,
                           ties_to_gl=closing_total == gl)

    def _card_numbers(self, cohort: str, known_at: datetime) -> dict[str, Any]:
        event = self._cohort_date(cohort)
        if event is None:
            raise NotFound(f"cohort {cohort} not found", cohort=cohort)
        period = period_of(utc_date(known_at))
        age = age_months(event, period)
        k_iso = iso(known_at)
        keep = self._keeps_tail(cohort, k_iso)
        segs = self._cohort_segments(cohort, period, k_iso)
        n = defaultdict(int)
        exp_num = Fraction(0)
        ult_num = Fraction(0)
        used = []
        for seg, s in sorted(segs.items()):
            if s.entitlement <= 0:
                continue
            used.append(seg)
            c = self._curves[seg]
            r_age = c.rate_at(age)
            unclaimed = max(s.entitlement - s.actual, 0)
            n["E"] += s.entitlement
            n["pax"] += s.pax
            n["actual"] += s.actual
            n["expected_loss"] += min(max(apply_rate(s.entitlement, c.ultimate) - s.actual, 0), unclaimed)
            n["bf"] += self._bf_target(s, c, age, keep)
            if r_age > 0:
                cl = round_half_up(Fraction(s.actual) * c.ultimate / r_age) - s.actual
            else:                                                   # no development yet: CL undefined
                cl = apply_rate(s.entitlement, c.ultimate) - s.actual
            n["chain_ladder"] += min(max(cl, 0), unclaimed)
            n["sens"] += apply_rate(s.entitlement, SENSITIVITY)
            exp_num += Fraction(s.entitlement) * r_age
            ult_num += Fraction(s.entitlement) * c.ultimate
        return {"event": event, "age": age, "used": used, "n": n, "expected": exp_num, "ultimate": ult_num,
                "segs": segs}

    def estimate_card(self, cohort: str, known_at: datetime) -> EstimateCard:
        """Expected-loss / Bornhuetter-Ferguson / chain-ladder at the close of known_at's period; BF selected."""
        known_at = to_utc(known_at)
        x = self._card_numbers(cohort, known_at)
        n, used, age = x["n"], x["used"], x["age"]
        if len(used) == 1:
            segment = used[0]
        elif used:
            segment = "mixed"
        else:
            segment = min(x["segs"], default="long_haul_gt3500")
        version = "+".join(self._curves[s].version for s in used) or self._curve(segment).version
        ae = round(float(Fraction(n["actual"]) / x["expected"]), 3) if x["expected"] > 0 else None
        z = round(float(x["expected"] / x["ultimate"]), 3) if x["ultimate"] > 0 else None
        approver = self._q1(
            "SELECT s.approver FROM books_je j JOIN books_je_status s ON s.je_id = j.je_id WHERE j.cohort = ? "
            "AND j.estimate_ref LIKE 'BF:%' AND s.status = 'approved' ORDER BY j.seq DESC LIMIT 1", [cohort])
        return EstimateCard(
            cohort=cohort, segment=segment, pax=n["pax"], entitlement_cents=n["E"], curve_version=version,
            months_developed=age, expected_loss_cents=n["expected_loss"], bf_cents=n["bf"],
            chain_ladder_cents=n["chain_ladder"], selected="bf", actual_vs_expected=ae, credibility_z=z,
            sensitivity_5pp_cents=n["sens"], constraint_note=CONSTRAINT_NOTE, ias8_class="change_in_estimate",
            preparer=PREPARER, approver=approver)

    def curve(self, segment: str) -> ClaimCurve:
        return self._curve(segment).to_model()

    def journal_entry(self, je_id: str) -> JournalEntry:
        return self._je(je_id)

    def audit(self, je_id: str) -> dict:
        je = self._je(je_id)
        events = [dict(r) for r in self._q("SELECT kind, principal, role, reason, at FROM books_je_events "
                                           "WHERE je_id = ? ORDER BY seq", [je_id])]
        reg = [self._reg_decode(r) for r in self._q("SELECT * FROM books_register WHERE je_ids LIKE ? "
                                                    "ORDER BY coupon_id", [f'%"{je_id}"%'])]
        claims = [dict(r) for r in self._q("SELECT claim_id, coupon_id, kind, amount_cents, event_date FROM "
                                           "books_claim_events WHERE approval_je_id = ? OR payment_je_id = ? "
                                           "ORDER BY seq", [je_id, je_id])]
        commits = sorted({c for c in [je.source_decision_id, *(r["decision_commit"] for r in reg)] if c})
        return {"je": je.model_dump(mode="json"), "events": events, "register": reg[:50],
                "register_count": len(reg), "claims": claims, "decision_commits": commits}

    def invariants(self) -> list[InvariantResult]:
        res: list[InvariantResult] = []
        bad = [r[0] for r in self._q("SELECT je_id FROM books_je_lines GROUP BY je_id "
                                     "HAVING SUM(dr_cents) != SUM(cr_cents) OR SUM(dr_cents) <= 0")]
        res.append(InvariantResult(id="INV-2", description="Every JE balances", ok=not bad,
                                   detail=", ".join(bad[:10])))
        periods = sorted({r[0] for r in self._q("SELECT DISTINCT period FROM books_je")}
                         | {period_of(utc_date(self.clock.now()))})
        untied = [p for p in periods if not self.rollforward(p).ties_to_gl]
        res.append(InvariantResult(id="INV-1", description="2140 rollforward foots and equals GL 2140",
                                   ok=not untied, detail=", ".join(untied)))
        sub = self._q1("SELECT COALESCE(SUM(c.amount_cents), 0) FROM books_claim_events c "
                       "JOIN books_je_status a ON a.je_id = c.approval_je_id JOIN books_je_status p "
                       "ON p.je_id = c.payment_je_id WHERE c.kind = 'approved' AND a.status != 'rejected' "
                       "AND p.status != 'approved'")
        gl2141 = self._liab("2141")
        res.append(InvariantResult(id="INV-1b", description="2141 equals the approved-unpaid subledger",
                                   ok=sub == gl2141, detail=f"subledger {sub} vs GL {gl2141}"))
        latest = periods[-1]
        bounds = [r.cohort for r in self.rollforward(latest).rows
                  if not 0 <= r.closing_cents <= max(r.unclaimed_entitlement_cents, 0)
                  and r.cohort != UNASSIGNED]
        res.append(InvariantResult(id="INV-6", description="0 ≤ cohort liability ≤ unclaimed, unexpired entitlement",
                                   ok=not bounds, detail=", ".join(bounds)))
        sod = [r[0] for r in self._q("SELECT e.je_id FROM books_je_events e JOIN books_je j ON j.je_id = e.je_id "
                                     "WHERE e.kind = 'approved' AND e.principal = j.preparer")]
        res.append(InvariantResult(id="INV-9a", description="Preparer ≠ approver", ok=not sod,
                                   detail=", ".join(sod)))
        late = [r[0] for r in self._q(
            "SELECT j.je_id FROM books_je j JOIN books_period_status p ON p.period = j.period "
            "WHERE j.recorded_at > p.locked_at UNION SELECT e.je_id FROM books_je_events e JOIN books_je j "
            "ON j.je_id = e.je_id JOIN books_period_status p ON p.period = j.period WHERE e.kind IN "
            "('approved', 'rejected') AND e.at > p.locked_at")]
        res.append(InvariantResult(id="INV-9b", description="Nothing written into a locked period", ok=not late,
                                   detail=", ".join(late)))
        cut = [r[0] for r in self._q("SELECT je_id FROM books_je WHERE period != substr(event_date, 1, 7)")]
        res.append(InvariantResult(id="INV-11", description="Cut-off: JE.period follows event_date", ok=not cut,
                                   detail=", ".join(cut)))
        return res

    def cfo_metrics(self, known_at: datetime) -> CfoMetrics:
        known_at = to_utc(known_at)
        period = period_of(utc_date(known_at))
        rf = self.rollforward(period)
        k_iso = iso(known_at)
        cohorts = [c for c, ev in self._cohorts() if ev <= utc_date(known_at)]
        full = sens = held = 0
        methods = [0, 0, 0]
        for c in cohorts:
            x = self._card_numbers(c, known_at)
            full += x["n"]["E"]
            sens += x["n"]["sens"]
            methods[0] += x["n"]["expected_loss"]
            methods[1] += x["n"]["bf"]
            methods[2] += x["n"]["chain_ladder"]
        held_by_seg: dict[str, int] = defaultdict(int)
        for r in self._register_rows(as_of=k_iso):
            if r["status"] in HELD and r["compensation_cents"] > 0:
                held_by_seg[r["segment"]] += r["compensation_cents"]
        held = sum(apply_rate(v, self._curves[s].ultimate) for s, v in held_by_seg.items())
        cash = int(self._q1("SELECT COALESCE(SUM(cr_cents - dr_cents), 0) FROM books_gl_lines WHERE account = '1000' "
                            "AND kind = 'claim_paid'"))
        recoded = self._q("SELECT DISTINCT r.flight_id, f.je_id FROM books_register r JOIN books_storm_flights f "
                          "ON f.flight_id = r.flight_id WHERE r.recoded = 1")
        rec_cents = 0
        for r in recoded:
            if r[1]:
                rec_cents += int(self._q1("SELECT COALESCE(SUM(cr_cents), 0) FROM books_je_lines WHERE je_id = ? "
                                          "AND account = '2140'", [r[1]]))
        return CfoMetrics(
            as_of=known_at, cash_basis_cents=cash, full_entitlement_cents=full,
            drafted_liability_cents=rf.gl_balance_cents, sensitivity_5pp_cents=sens,
            method_range_cents=(min(methods), max(methods)), held_for_legal_cents=held,
            liability_bridge=rf.rows, recodes_count=len(recoded), recodes_cents=rec_cents,
            refunds_within_7d_pct=0.0, vouchers_outstanding_cents=max(self._liab("2132"), 0),
            care_accrued_cents=0, care_invoiced_cents=0)
