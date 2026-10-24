"""Append-only SQLite storage for books. Every `books_*` table aborts UPDATE/DELETE; statuses are views over events."""
from __future__ import annotations

import sqlite3

from .coa import ACCOUNTS, GROUP

TABLES: dict[str, str] = {
    "books_accounts": """
        code TEXT PRIMARY KEY, name TEXT NOT NULL, grp TEXT NOT NULL""",
    # JE header: immutable once written
    "books_je": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        je_id TEXT NOT NULL UNIQUE, event_date TEXT NOT NULL, period TEXT NOT NULL, kind TEXT NOT NULL,
        memo TEXT NOT NULL, ias8_class TEXT NOT NULL, reverses TEXT, estimate_ref TEXT, source_decision_id TEXT,
        preparer TEXT NOT NULL, built_from INTEGER NOT NULL, ties_to TEXT NOT NULL,
        gated INTEGER NOT NULL,            -- 1: counts in the GL only once approved (payouts, release proposals)
        run_id TEXT, cohort TEXT, flight_id TEXT, flags TEXT NOT NULL,
        known_at TEXT NOT NULL, recorded_at TEXT NOT NULL""",
    "books_je_lines": """
        je_id TEXT NOT NULL, line_no INTEGER NOT NULL, account TEXT NOT NULL,
        dr_cents INTEGER NOT NULL CHECK (dr_cents >= 0), cr_cents INTEGER NOT NULL CHECK (cr_cents >= 0),
        cohort TEXT, segment TEXT, flight_id TEXT, dims TEXT NOT NULL,
        PRIMARY KEY (je_id, line_no)""",
    # drafted | approved | rejected | denied
    "books_je_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, je_id TEXT NOT NULL, kind TEXT NOT NULL,
        principal TEXT NOT NULL, role TEXT NOT NULL, reason TEXT, at TEXT NOT NULL""",
    "books_period_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, kind TEXT NOT NULL,
        principal TEXT NOT NULL, at TEXT NOT NULL""",
    "books_cohorts": """
        cohort TEXT PRIMARY KEY, event_date TEXT NOT NULL, source TEXT NOT NULL, recorded_at TEXT NOT NULL""",
    "books_storm_flights": """
        flight_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, je_id TEXT, known_at TEXT NOT NULL,
        recorded_at TEXT NOT NULL""",
    "books_opening_balances": """
        cohort TEXT NOT NULL, account TEXT NOT NULL, segment TEXT NOT NULL,
        entitlement_cents INTEGER NOT NULL, claimed_cents INTEGER NOT NULL, balance_cents INTEGER NOT NULL,
        as_of TEXT NOT NULL, period TEXT NOT NULL, recorded_at TEXT NOT NULL,
        PRIMARY KEY (cohort, account)""",
    # obligation register: one full-state snapshot per event; current row per coupon is the books_register view
    "books_register_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        coupon_id TEXT NOT NULL, flight_id TEXT NOT NULL, cohort TEXT NOT NULL, segment TEXT NOT NULL,
        band_eur INTEGER NOT NULL, distance_km REAL NOT NULL, status TEXT NOT NULL,
        compensation_cents INTEGER NOT NULL, reduction TEXT NOT NULL, voucher_offset_cents INTEGER NOT NULL,
        voucher_signed_sha256 TEXT, election TEXT, article TEXT NOT NULL, rules_applied TEXT NOT NULL,
        decision_commit TEXT, cause TEXT, recoded INTEGER NOT NULL, confidence REAL,
        claim_ids TEXT NOT NULL, settlement TEXT, je_ids TEXT NOT NULL,
        event_date TEXT NOT NULL, limitation_expiry TEXT NOT NULL,
        reason TEXT NOT NULL, known_at TEXT NOT NULL, recorded_at TEXT NOT NULL""",
    # approved | rejected | held
    "books_claim_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL, coupon_id TEXT NOT NULL,
        flight_id TEXT, cohort TEXT NOT NULL, segment TEXT NOT NULL, kind TEXT NOT NULL,
        amount_cents INTEGER NOT NULL, reason TEXT, event_date TEXT NOT NULL,
        approval_je_id TEXT, payment_je_id TEXT, topup_je_id TEXT,
        known_at TEXT NOT NULL, recorded_at TEXT NOT NULL""",
    # keep_tail (R-CTL-1): cohort '*' = all cohorts
    "books_policy_events": """
        seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, cohort TEXT NOT NULL, rule_ref TEXT NOT NULL,
        known_at TEXT NOT NULL, recorded_at TEXT NOT NULL""",
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS books_je_lines_acct ON books_je_lines(account, cohort, segment)",
    "CREATE INDEX IF NOT EXISTS books_je_events_je ON books_je_events(je_id, kind)",
    "CREATE INDEX IF NOT EXISTS books_je_ref ON books_je(estimate_ref)",
    "CREATE INDEX IF NOT EXISTS books_je_period ON books_je(period)",
    "CREATE INDEX IF NOT EXISTS books_register_coupon ON books_register_events(coupon_id, seq)",
    "CREATE INDEX IF NOT EXISTS books_register_flight ON books_register_events(flight_id)",
    "CREATE INDEX IF NOT EXISTS books_claim_events_claim ON books_claim_events(claim_id)",
    "CREATE INDEX IF NOT EXISTS books_claim_events_coupon ON books_claim_events(coupon_id)",
]

VIEWS = {
    "books_je_status": """
        SELECT j.je_id,
          CASE WHEN EXISTS (SELECT 1 FROM books_je_events e WHERE e.je_id = j.je_id AND e.kind = 'approved')
                 THEN 'approved'
               WHEN EXISTS (SELECT 1 FROM books_je_events e WHERE e.je_id = j.je_id AND e.kind = 'rejected')
                 THEN 'rejected'
               ELSE 'draft' END AS status,
          (SELECT e.principal FROM books_je_events e WHERE e.je_id = j.je_id AND e.kind = 'approved'
             ORDER BY e.seq LIMIT 1) AS approver,
          (SELECT e.at FROM books_je_events e WHERE e.je_id = j.je_id AND e.kind = 'approved'
             ORDER BY e.seq LIMIT 1) AS approved_at
        FROM books_je j""",
    # Parked-journal ledger: drafts and approvals count; rejected never; gated entries only once approved.
    "books_gl_lines": """
        SELECT l.je_id, l.line_no, l.account, l.dr_cents, l.cr_cents, l.cohort, l.segment, l.flight_id, l.dims,
               j.period, j.kind, j.flags, j.event_date, s.status
        FROM books_je_lines l
        JOIN books_je j ON j.je_id = l.je_id
        JOIN books_je_status s ON s.je_id = l.je_id
        WHERE s.status != 'rejected' AND (j.gated = 0 OR s.status = 'approved')""",
    "books_period_status": """
        SELECT period, 'locked' AS status, MIN(at) AS locked_at, MIN(seq) AS seq
        FROM books_period_events WHERE kind = 'lock' GROUP BY period""",
    "books_register": """
        SELECT r.* FROM books_register_events r
        JOIN (SELECT coupon_id, MAX(seq) AS seq FROM books_register_events GROUP BY coupon_id) m ON m.seq = r.seq""",
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
    conn.executemany("INSERT OR IGNORE INTO books_accounts(code, name, grp) VALUES (?, ?, ?)",
                     [(c, n, GROUP[c]) for c, n in ACCOUNTS.items()])
