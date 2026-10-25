"""F8c: invariants, the CFO view, the estimate card and `audit(je_id)`.

Mixed into `books.Books`. Read-only: nothing here writes. Pure: no LLM, no wall clock (the injected clock gives
"now" for the 7-day refund test and the current period), no randomness.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Any

from contracts.models import CfoMetrics, EstimateCard, InvariantResult

from .curves import normalize_segment
from .errors import NotFound
from .money import apply_rate, eur, round_half_up
from .ops import REFUND_CHANNELS
from .periods import age_months, iso, limitation_expiry, period_of, to_utc, utc_date

SENSITIVITY = Fraction(5, 100)
HELD = ("held", "needs_ruling")
ACCRUING = ("owed", "held", "needs_ruling")
ESTIMATE_KINDS = ("compensation_estimate", "change_in_estimate", "recode", "out_of_period_adjustment",
                  "derecognition")
REFUND_DAYS = 7                                    # EU261 Art. 8(1)(a) via Reg 1107/2006 Art. 8: within 7 days
CONSTRAINT_NOTE = (
    "IFRS 15.50–58 variable consideration (IFRIC Sept 2019): EU261 compensation is a reduction of passenger "
    "revenue, estimated on € claim curves (expected ultimate claim rate, history to M18 + tail judgment) and "
    "constrained under IFRS 15.56; held / needs-Legal items accrue at their segment rate until resolved."
)
DISCLOSURE = ("Presented in full within passenger revenue (IAG approach); IFRIC left open whether the reduction is "
              "capped at nil; refunded passengers have a nil transaction price.")


def eur0(cents: int) -> str:
    """€99,000 (cents only when there are any)."""
    s = eur(cents)
    return s.removesuffix(".00")


def cfo_bridge(m: CfoMetrics) -> str:
    """The CFO line: "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)"."""
    return (f"Cash basis {eur0(m.cash_basis_cents)} · full entitlement {eur0(m.full_entitlement_cents)} · drafted "
            f"{eur0(m.drafted_liability_cents)} (±5pp ±{eur0(m.sensitivity_5pp_cents)})")


class _S:
    __slots__ = ("actual", "entitlement", "pax")

    def __init__(self) -> None:
        self.entitlement = 0
        self.pax = 0
        self.actual = 0


class ReportingMixin:
    """Relies on `books.Books` helpers (`_q`, `_curves`, `_cohort_segments`, `_bf_target`, `rollforward`, …)."""

    # ------------------------------------------------------------------ estimate methods

    def _methods(self, segs: dict[str, Any], age: int, keep: bool) -> dict[str, Any]:
        """Expected-loss / BF / chain-ladder per segment, then summed (each bounded to [0, unclaimed])."""
        n: dict[str, int] = defaultdict(int)
        exp_num = Fraction(0)
        ult_num = Fraction(0)
        used: list[str] = []
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
        return {"n": n, "used": used, "expected": exp_num, "ultimate": ult_num}

    def _legal_flights(self, k_iso: str) -> set[str]:
        """Flights whose latest decision (as of k_iso) waits on Legal (extraordinary = needs_legal)."""
        last: dict[str, str] = {}
        for r in self._q("SELECT flight_id, extraordinary FROM books_decision_events WHERE known_at <= ? "
                         "ORDER BY seq", [k_iso]):
            last[r[0]] = r[1]
        return {f for f, x in last.items() if x == "needs_legal"}

    def _split_segments(self, cohort: str, period: str, k_iso: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """(owed, held-for-Legal) entitlement by segment, as of k_iso; claims and opening balances sit in owed."""
        legal = self._legal_flights(k_iso)
        owed: dict[str, _S] = defaultdict(_S)
        held: dict[str, _S] = defaultdict(_S)
        for r in self._register_rows(cohort=cohort, as_of=k_iso,
                                     columns=("coupon_id", "status", "compensation_cents", "flight_id", "segment")):
            if r["status"] not in ACCRUING or r["compensation_cents"] <= 0:
                continue
            is_legal = r["status"] == "held" or (r["status"] in HELD and r["flight_id"] in legal)
            s = (held if is_legal else owed)[r["segment"]]
            s.entitlement += int(r["compensation_cents"])
            s.pax += 1
        for seg, s in self._cohort_segments(cohort, period, k_iso).items():
            o = owed[seg]                               # + opening balances; claims settle owed entitlement only
            o.actual = s.actual
            o.entitlement = s.entitlement - (held[seg].entitlement if seg in held else 0)
        return dict(owed), {k: v for k, v in held.items() if v.entitlement > 0}

    def _held_cents(self, cohort: str, held: dict[str, Any], age: int, period: str) -> int:
        """The part of the book on held-for-Legal entitlement: BF remaining rate × entitlement, ≤ segment book."""
        if not held:
            return 0
        book = self.segment_balances(cohort, period)
        total = 0
        for seg, s in held.items():
            amt = apply_rate(s.entitlement, self._curves[seg].remaining_rate(age))
            total += min(amt, max(book.get(seg, 0), 0))
        return total

    def _card_numbers(self, cohort: str, known_at: datetime, segment: str | None = None) -> dict[str, Any]:
        event = self._cohort_date(cohort)
        if event is None:
            raise NotFound(f"cohort {cohort} not found", cohort=cohort)
        period = period_of(utc_date(known_at))
        age = age_months(event, period)
        k_iso = iso(known_at)
        keep = self._keeps_tail(cohort, k_iso)
        segs = self._cohort_segments(cohort, period, k_iso)
        if segment is not None:
            segs = {k: v for k, v in segs.items() if k == segment}
        x = self._methods(segs, age, keep)
        x.update({"event": event, "age": age, "segs": segs, "period": period, "keep": keep})
        return x

    def estimate_card(self, cohort: str, known_at: datetime, *, segment: str | None = None) -> EstimateCard:
        """Expected-loss / Bornhuetter-Ferguson / chain-ladder at the close of known_at's period; BF selected.
        Preparer / approver and the IAS 8 class are those of the cohort's latest estimate entry."""
        known_at = to_utc(known_at)
        if segment is not None:
            segment = normalize_segment(segment)
        x = self._card_numbers(cohort, known_at, segment)
        n, used, age, period = x["n"], x["used"], x["age"], x["period"]
        if segment is not None:
            seg_label = segment
        elif len(used) == 1:
            seg_label = used[0]
        elif used:
            seg_label = "mixed"
        else:
            seg_label = min(x["segs"], default="long_haul_gt3500")
        version = "+".join(self._curves[s].version for s in used) or self._curve(seg_label if seg_label != "mixed"
                                                                                 else "long_haul_gt3500").version
        ae = round(float(Fraction(n["actual"]) / x["expected"]), 3) if x["expected"] > 0 else None
        z = round(float(x["expected"] / x["ultimate"]), 3) if x["ultimate"] > 0 else None
        latest = self._q(
            "SELECT j.preparer, j.ias8_class, s.status, s.approver FROM books_je j JOIN books_je_status s "
            f"ON s.je_id = j.je_id WHERE j.cohort = ? AND j.period <= ? AND j.kind IN {ESTIMATE_KINDS!r} "
            "AND s.status != 'rejected' AND COALESCE(j.estimate_ref, '') NOT LIKE 'release:%' "
            "ORDER BY j.seq DESC LIMIT 1", [cohort, period])
        if latest:
            preparer, ias8, approver = latest[0]["preparer"], latest[0]["ias8_class"], latest[0]["approver"]
        else:
            preparer, ias8, approver = "agent.engine", "change_in_estimate" if age >= 1 else "none", None
        _owed, held = self._split_segments(cohort, period, iso(known_at))
        if segment is not None:
            held = {k: v for k, v in held.items() if k == segment}
        held_c = self._held_cents(cohort, held, age, period)
        note = CONSTRAINT_NOTE
        if held_c:
            note += (f" {eur0(held_c)} of the estimate is on entitlement held pending Legal, accrued at segment rates "
                     f"under the IFRS 15.56 constraint.")
        if x["keep"] and age >= 12:
            note += " Tail kept under the Controller's keep-tail rule (reduce to the expected tail; derecognise at " \
                    "limitation)."
        note += " " + DISCLOSURE
        return EstimateCard(
            cohort=cohort, segment=seg_label, pax=n["pax"], entitlement_cents=n["E"], curve_version=version,
            months_developed=age, expected_loss_cents=n["expected_loss"], bf_cents=n["bf"],
            chain_ladder_cents=n["chain_ladder"], selected="bf", actual_vs_expected=ae, credibility_z=z,
            sensitivity_5pp_cents=n["sens"], constraint_note=note, ias8_class=ias8, preparer=preparer,
            approver=approver)

    # ------------------------------------------------------------------ CFO view

    def cfo_metrics(self, known_at: datetime, *, cohort: str | None = None) -> CfoMetrics:
        """The CFO bridge, by default over every storm cohort that has happened by known_at (migrated opening
        balances, e.g. Isha, appear in the 2140 bridge rows only). `cohort=` narrows it to one storm.

        cash basis = compensation actually paid (approved payouts) · full entitlement = owed Art. 7 compensation if
        every passenger claims · drafted = GL 2140 for those cohorts less what is held pending Legal ·
        sensitivity = ±5 pp on the ultimate · method range = min/max of expected-loss, BF and chain-ladder."""
        known_at = to_utc(known_at)
        kd = utc_date(known_at)
        period = period_of(kd)
        k_iso = iso(known_at)
        rf = self.rollforward(period)
        if cohort is not None:
            if self._cohort_date(cohort) is None:
                raise NotFound(f"cohort {cohort} not found", cohort=cohort)
            scope = [cohort]
        else:
            scope = [r[0] for r in self._q("SELECT cohort FROM books_cohorts WHERE source = 'storm' AND event_date <= ? "
                                           "ORDER BY cohort", [kd.isoformat()])]
        full = sens = held = drafted = lo = hi = 0
        for c in scope:
            event = self._cohort_date(c)
            age = age_months(event, period)
            owed, held_segs = self._split_segments(c, period, k_iso)
            m = self._methods(owed, age, self._keeps_tail(c, k_iso))
            full += m["n"]["E"]
            sens += m["n"]["sens"]
            h = self._held_cents(c, held_segs, age, period)
            held += h
            drafted += self._liab("2140", through=period, cohort=c) - h
            vals = (m["n"]["expected_loss"], m["n"]["bf"], m["n"]["chain_ladder"])
            lo += min(vals)
            hi += max(vals)
        marks = ",".join("?" * len(scope))

        def gl(account: str, kind: str | None = None, credits_only: bool = False) -> int:
            if not scope:
                return 0
            amount = "cr_cents" if credits_only else "cr_cents - dr_cents"
            sql = (f"SELECT COALESCE(SUM({amount}), 0) FROM books_gl_lines WHERE account = ? AND period <= ? "
                   f"AND cohort IN ({marks})")
            args: list[Any] = [account, period, *scope]
            if kind:
                sql += " AND kind = ?"
                args.append(kind)
            return int(self._q1(sql, args))

        recoded = self._recoded_flights(scope, k_iso)
        rec_cents = 0
        for fid in recoded:
            rec_cents += int(self._q1("SELECT COALESCE(SUM(cr_cents - dr_cents), 0) FROM books_gl_lines "
                                      "WHERE account = '2140' AND flight_id = ? AND period <= ?", [fid, period]))
        return CfoMetrics(
            as_of=known_at, cash_basis_cents=gl("1000", "claim_paid", True), full_entitlement_cents=full,
            drafted_liability_cents=drafted, sensitivity_5pp_cents=sens,
            method_range_cents=(lo, hi), held_for_legal_cents=held, liability_bridge=rf.rows,
            recodes_count=len(recoded), recodes_cents=rec_cents,
            refunds_within_7d_pct=self._refunds_within_7d(scope, kd),
            vouchers_outstanding_cents=max(gl("2131") + gl("2132"), 0),
            care_accrued_cents=gl("2150", "care_accrual", True), care_invoiced_cents=gl("2000", "care_invoice", True))

    def _recoded_flights(self, scope: list[str], k_iso: str) -> list[str]:
        if not scope:
            return []
        marks = ",".join("?" * len(scope))
        flights = {r[0] for r in self._q(f"SELECT DISTINCT flight_id FROM books_register WHERE recoded = 1 AND "
                                         f"cohort IN ({marks})", scope)}
        last: dict[str, int] = {}
        for r in self._q("SELECT flight_id, recoded FROM books_decision_events WHERE known_at <= ? ORDER BY seq",
                         [k_iso]):
            last[r[0]] = int(r[1])
        in_scope = {r[0] for r in self._q(f"SELECT flight_id FROM books_storm_flights WHERE run_id IN ({marks})",
                                          scope)}
        flights |= {f for f, v in last.items() if v and f in in_scope}
        flights -= {f for f, v in last.items() if not v}
        return sorted(flights)

    def _refund_cases(self, scope: list[str] | None = None) -> list[tuple[str, date, str | None, date | None]]:
        """(coupon, cancellation date, refund channel or None, refund date) for every refund elected or made."""
        sql = "SELECT coupon_id, channel, event_date FROM books_coupon_events WHERE kind = 'relief'"
        args: list[Any] = []
        if scope is not None:
            if not scope:
                return []
            sql += f" AND cohort IN ({','.join('?' * len(scope))})"
            args += scope
        relief: dict[str, tuple[str, date]] = {}
        for r in self._q(sql + " ORDER BY seq", args):
            relief.setdefault(r["coupon_id"], (r["channel"], date.fromisoformat(r["event_date"])))
        rsql = "SELECT coupon_id, event_date, election FROM books_register WHERE 1=1"
        rargs: list[Any] = []
        if scope is not None:
            rsql += f" AND cohort IN ({','.join('?' * len(scope))})"
            rargs += scope
        reg = {r[0]: (date.fromisoformat(r[1]), r[2]) for r in self._q(rsql, rargs)}
        out = []
        for cid in sorted(set(relief) | {c for c, (_d, el) in reg.items() if el == "refund"}):
            ch, d = relief.get(cid, (None, None))
            if ch is not None and ch not in REFUND_CHANNELS:
                continue                                    # relieved by a voucher / FIM: not a refund
            cancel = reg[cid][0] if cid in reg else d
            out.append((cid, cancel, ch, d))
        return out

    def _refunds_within_7d(self, scope: list[str], today: date) -> float:
        cases = self._refund_cases(scope)
        if not cases:
            return 100.0
        ok = sum(1 for _c, cancel, ch, d in cases if ch is not None and d <= cancel + timedelta(days=REFUND_DAYS))
        return round(100.0 * ok / len(cases), 1)

    # ------------------------------------------------------------------ audit

    def audit(self, je_id: str) -> dict:
        """Everything behind one JE: lines (blame ids `JE-…:n`), approval events, register rows, ATL / care
        subledger rows, claims, decision commits, evidence sources, rules, period lock, GL tie-outs."""
        je = self._je(je_id)
        head = self._head(je_id)
        events = [dict(r) for r in self._q("SELECT kind, principal, role, reason, at FROM books_je_events "
                                           "WHERE je_id = ? ORDER BY seq", [je_id])]
        reg = [self._reg_decode(r) for r in self._q("SELECT * FROM books_register WHERE je_ids LIKE ? "
                                                    "ORDER BY coupon_id", [f'%"{je_id}"%'])]
        if not reg and head["cohort"] and je.kind in ESTIMATE_KINDS and head["flight_id"] is None:
            reg = [r for r in self._register_rows(cohort=head["cohort"])
                   if r["status"] in ACCRUING and r["compensation_cents"] > 0]
        claims = [dict(r) for r in self._q("SELECT claim_id, coupon_id, kind, amount_cents, reason, event_date FROM "
                                           "books_claim_events WHERE approval_je_id = ? OR payment_je_id = ? OR "
                                           "topup_je_id = ? ORDER BY seq", [je_id, je_id, je_id])]
        coupon_rows = [dict(r) for r in self._q("SELECT coupon_id, kind, channel, crm_event_id, amount_cents, "
                                                "event_date, detail FROM books_coupon_events WHERE je_id = ? "
                                                "ORDER BY seq", [je_id])]
        care = [dict(r) for r in self._q("SELECT care_id, flight_id, kind, amount_cents, vendor, event_date FROM "
                                         "books_care_events WHERE je_id = ? ORDER BY seq", [je_id])]
        flights = sorted({l.dims["flight"] for l in je.lines if l.dims.get("flight")}
                         | {r["flight_id"] for r in reg})
        dec_rows = []
        if flights:
            dec_rows = [dict(r) for r in self._q(
                f"SELECT flight_id, cause, extraordinary, recoded, recode_label, decision_commit, sources, rules, "
                f"legal_basis FROM books_decisions WHERE flight_id IN ({','.join('?' * len(flights))}) "
                f"ORDER BY flight_id", flights)]
        commits = sorted({c for c in [je.source_decision_id, *(r["decision_commit"] for r in reg),
                                      *(d["decision_commit"] for d in dec_rows)] if c})
        sources = sorted({s for d in dec_rows for s in json.loads(d["sources"])})
        rules = sorted({x for r in reg for x in r["rules_applied"]}
                       | {x for d in dec_rows for x in json.loads(d["rules"])})
        locked_at = self._q1("SELECT locked_at FROM books_period_status WHERE period = ?", [je.period])
        ties = {a: self.gl_balance(a, period=je.period) for a in sorted({l.account for l in je.lines})}
        liab = next((i for i, l in enumerate(je.lines, start=1) if l.account == "2140"), 1)
        return {
            "je": je.model_dump(mode="json"),
            "lines": [{"line_id": f"{je_id}:{i}", "account": l.account, "account_name": l.account_name,
                       "dr_cents": l.dr_cents, "cr_cents": l.cr_cents, "dims": l.dims}
                      for i, l in enumerate(je.lines, start=1)],
            "events": events,
            "period": {"period": je.period, "locked": locked_at is not None, "locked_at": locked_at},
            "register": reg[:50], "register_count": len(reg),
            "coupon_events": coupon_rows[:50], "coupon_events_count": len(coupon_rows),
            "care": care, "claims": claims,
            "decisions": [dict(d, sources=json.loads(d["sources"]), rules=json.loads(d["rules"]),
                               legal_basis=json.loads(d["legal_basis"]), recoded=bool(d["recoded"]))
                          for d in dec_rows],
            "decision_commits": commits, "sources": sources, "rules": rules,
            "ties": ties, "blame_target": f"{je_id}:{liab}",
        }

    # ------------------------------------------------------------------ invariants

    def invariants(self) -> list[InvariantResult]:
        """The 11 books invariants (THREAD_FILIP F8c), some split into parts. INV-2, INV-9b and INV-11 are also
        hard guards on every insert; the rest are evaluated here, on demand."""
        now = to_utc(self.clock.now())
        out: list[InvariantResult] = []

        def add(iid: str, desc: str, bad: list[str], good: str, sep: str = ", ") -> None:
            bad = list(bad)
            out.append(InvariantResult(id=iid, description=desc, ok=not bad,
                                       detail=good if not bad else sep.join(bad[:10])
                                       + (f" (+{len(bad) - 10} more)" if len(bad) > 10 else "")))

        periods = sorted({r[0] for r in self._q("SELECT DISTINCT period FROM books_je")}
                         | {r[0] for r in self._q("SELECT DISTINCT period FROM books_opening_balances")}
                         | {period_of(utc_date(now))})
        rfs = {p: self.rollforward(p) for p in periods}
        latest = periods[-1]

        # 1 · rollforward ties; 2141 = approved-unpaid subledger
        add("INV-1", "2140 rollforward foots and equals GL 2140",
            [f"{p}: rollforward {eur0(rf.closing_total_cents)} ≠ GL {eur0(rf.gl_balance_cents)}"
             for p, rf in rfs.items() if not rf.ties_to_gl],
            f"{len(periods)} periods tie to GL 2140 · {latest} {eur0(rfs[latest].gl_balance_cents)}")
        sub = int(self._q1("SELECT COALESCE(SUM(c.amount_cents), 0) FROM books_claim_events c "
                           "JOIN books_je_status a ON a.je_id = c.approval_je_id JOIN books_je_status p "
                           "ON p.je_id = c.payment_je_id WHERE c.kind = 'approved' AND a.status != 'rejected' "
                           "AND p.status != 'approved'"))
        gl2141 = self._liab("2141")
        add("INV-1b", "2141 equals the approved-unpaid subledger",
            [] if sub == gl2141 else [f"subledger {eur0(sub)} ≠ GL 2141 {eur0(gl2141)}"],
            f"subledger {eur0(sub)} = GL 2141 {eur0(gl2141)}")

        # 2 · every JE balances
        bad = [r[0] for r in self._q("SELECT je_id FROM books_je_lines GROUP BY je_id "
                                     "HAVING SUM(dr_cents) != SUM(cr_cents) OR SUM(dr_cents) <= 0")]
        bad += [r[0] for r in self._q("SELECT je_id FROM books_je WHERE je_id NOT IN (SELECT je_id FROM "
                                      "books_je_lines)")]
        n_je = int(self._q1("SELECT COUNT(*) FROM books_je"))
        add("INV-2", "Every journal entry balances (Σ Dr = Σ Cr)", sorted(set(bad)), f"{n_je} entries balance")

        # 3 · completeness
        add("INV-3", "Completeness: scheduled − operated = register = ops-log cancellations; operated departures ≤ "
                     "Eurocontrol", *self._completeness())

        # 4 · ATL relieved once; open rebooks stay; 2125 nets to 0
        multi = [f"{r[0]} relieved {r[1]}×" for r in self._q(
            "SELECT coupon_id, COUNT(*) FROM books_coupon_events WHERE kind = 'relief' GROUP BY coupon_id "
            "HAVING COUNT(*) > 1")]
        rebook = [f"{r[0]} (reaccommodated) relieved by {r[1]}" for r in self._q(
            "SELECT e.coupon_id, e.channel FROM books_coupon_events e JOIN books_register r ON r.coupon_id = "
            "e.coupon_id WHERE e.kind = 'relief' AND r.election = 'reaccommodated_own' AND e.channel IN "
            "('queued', 'voucher', 'reroute_fim')")]
        sub_atl = self._q("SELECT COALESCE(SUM(CASE WHEN e.kind = 'sale' THEN e.fare_cents ELSE -e.fare_cents END), 0), "
                          "COALESCE(SUM(CASE WHEN e.kind = 'sale' THEN e.taxes_cents ELSE -e.taxes_cents END), 0) "
                          "FROM books_coupon_events e JOIN books_je_status s ON s.je_id = e.je_id "
                          "WHERE e.kind IN ('sale', 'relief') AND s.status != 'rejected'")[0]
        ties = []
        for acct, subv in (("2100", int(sub_atl[0])), ("2110", int(sub_atl[1]))):
            g = self._liab(acct)
            if g != subv:
                ties.append(f"GL {acct} {eur0(g)} ≠ coupon subledger {eur0(subv)}")
        open_n = int(self._q1("SELECT COUNT(*) FROM books_coupon_events s WHERE s.kind = 'sale' AND NOT EXISTS "
                              "(SELECT 1 FROM books_coupon_events r WHERE r.coupon_id = s.coupon_id AND "
                              "r.kind = 'relief')"))
        add("INV-4", "Each coupon is relieved from ATL once (refund, voucher, FIM); open rebooks stay in 2100",
            multi + rebook + ties, f"ATL {eur0(int(sub_atl[0]))} ties to the coupon subledger · {open_n} open coupons "
                                   f"stay in 2100")
        g2125 = self._liab("2125")
        doubles = [r[0] for r in self._q("SELECT DISTINCT coupon_id FROM books_coupon_events WHERE kind = "
                                         "'double_refund' ORDER BY coupon_id")]
        bot = int(self._q1("SELECT COALESCE(SUM(dr_cents), 0) FROM books_gl_lines WHERE account = '2125'"))
        add("INV-4b", "Refund clearing 2125 nets to 0 after Books (no double refund)",
            [] if g2125 == 0 else [f"2125 {eur0(g2125)}" + (f" · double refunds: {', '.join(doubles[:5])}"
                                                            if doubles else "")],
            f"Dr {eur0(bot)} (CRM bot) = Cr {eur0(bot)} (Books)")

        # 5 · one payment per coupon; paid ≤ entitlement; assignment
        add("INV-5", "At most one compensation payment per coupon across channels; paid ≤ entitlement; a direct "
                     "payment after an assignment notice does not discharge", *self._payments())

        # 6 · 0 ≤ cohort liability ≤ unclaimed, unexpired entitlement
        add("INV-6", "0 ≤ cohort liability ≤ unclaimed, unexpired entitlement",
            [f"{r.cohort}: {eur0(r.closing_cents)} vs unclaimed {eur0(r.unclaimed_entitlement_cents)}"
             for r in rfs[latest].rows if r.cohort != "unassigned"
             and not 0 <= r.closing_cents <= max(r.unclaimed_entitlement_cents, 0)],
            f"{len(rfs[latest].rows)} cohorts within bounds at {latest}")

        # 7 · extraordinary → no compensation, refunds and care remain; evidence + rule links
        add("INV-7", "Extraordinary → no compensation; refunds and care still due", *self._extraordinary())
        unlinked = [r[0] for r in self._q(
            f"SELECT coupon_id FROM books_register WHERE compensation_cents > 0 AND status IN {ACCRUING!r} AND "
            f"(decision_commit IS NULL OR decision_commit = '' OR article IS NULL OR article = '') ORDER BY coupon_id")]
        n_owed = int(self._q1(f"SELECT COUNT(*) FROM books_register WHERE compensation_cents > 0 AND status IN "
                              f"{ACCRUING!r}"))
        add("INV-7b", "Every non-zero entitlement links its decision evidence and rule", unlinked,
            f"{n_owed} of {n_owed} non-zero entitlements trace to a decision commit and an article")

        # 8 · no voucher offset without a signed hash
        add("INV-8", "No voucher offset without a signed acceptance hash (Art. 7(3))", *self._offsets())

        # 9 · SoD, locks, derecognition
        sod = [r[0] for r in self._q("SELECT e.je_id FROM books_je_events e JOIN books_je j ON j.je_id = e.je_id "
                                     "WHERE e.kind = 'approved' AND e.principal = j.preparer")]
        n_app = int(self._q1("SELECT COUNT(*) FROM books_je_events WHERE kind = 'approved'"))
        add("INV-9a", "Preparer ≠ approver", sod, f"{n_app} approvals, none by their preparer")
        late = [r[0] for r in self._q(
            "SELECT j.je_id FROM books_je j JOIN books_period_status p ON p.period = j.period "
            "WHERE j.recorded_at > p.locked_at UNION SELECT e.je_id FROM books_je_events e JOIN books_je j "
            "ON j.je_id = e.je_id JOIN books_period_status p ON p.period = j.period WHERE e.kind IN "
            "('approved', 'rejected') AND e.at > p.locked_at")]
        locked = self.locked_periods()
        add("INV-9b", "Nothing written into a locked period", late,
            f"locked {', '.join(locked)}, untouched" if locked else "no locked periods yet")
        add("INV-9c", "No derecognition before limitation without a Controller rule", *self._derecognitions())

        # 10 · refunds within 7 days or a refund draft queued
        add("INV-10", "Refunds within 7 days, or a refund draft is queued (EU261 Art. 8)", *self._refunds(now))

        # 11 · cut-off
        cut = [r[0] for r in self._q("SELECT je_id FROM books_je WHERE period != substr(event_date, 1, 7)")]
        add("INV-11", "Cut-off: JE.period follows event_date", cut, f"{n_je} entries in their event period")
        return out

    def _completeness(self) -> tuple[list[str], str]:
        bad: list[str] = []
        good: list[str] = []
        runs: dict[str, list[Any]] = defaultdict(list)
        for r in self._q("SELECT * FROM books_run_events ORDER BY seq"):
            runs[r["run_id"]].append(r)
        for run, rows in sorted(runs.items()):
            sched: set[str] = set()
            ops: set[str] = set()
            canc: set[str] = set()
            occ: set[str] | None = None
            euro = dep = None
            for r in rows:
                sched |= set(json.loads(r["scheduled"]))
                ops |= set(json.loads(r["operated"]))
                canc |= set(json.loads(r["cancelled"]))
                if r["occ"] is not None:
                    occ = (occ or set()) | set(json.loads(r["occ"]))
                euro = r["eurocontrol_departures"] if r["eurocontrol_departures"] is not None else euro
                if r["operated_station_departures"] is not None:
                    dep = max(dep or 0, int(r["operated_station_departures"]))
            canc -= ops
            reg = {x[0] for x in self._q("SELECT DISTINCT flight_id FROM books_register WHERE cohort = ?", [run])}
            n = len(sched) - len(ops)
            msgs = []
            if n != len(reg) or canc != reg:
                missing, extra = sorted(canc - reg), sorted(reg - canc)
                msgs.append(f"{run}: {n} cancelled vs register {len(reg)}"
                            + (f" · not in register: {', '.join(missing[:5])}" if missing else "")
                            + (f" · not cancelled: {', '.join(extra[:5])}" if extra else ""))
            if occ is not None and occ != canc:
                msgs.append(f"{run}: OCC log lists {len(occ)} cancellations vs {len(canc)} cancelled"
                            + (f" · missing from the OCC log: {', '.join(sorted(canc - occ)[:5])}" if canc - occ else "")
                            + (f" · OCC-listed but not cancelled: {', '.join(sorted(occ - canc)[:5])}"
                               if occ - canc else ""))
            if euro is not None and dep is not None and dep > euro:
                msgs.append(f"{run}: {dep} operated departures > Eurocontrol {euro}")
            bad += msgs
            if not msgs:
                good.append(f"{run}: {len(sched)} scheduled − {len(ops)} operated = {n} = register {len(reg)}"
                            + (f" = OCC {len(occ)}" if occ is not None else "")
                            + (f" · {dep} operated departures ≤ Eurocontrol {euro}" if euro is not None
                               and dep is not None else ""))
        return bad, " · ".join(good) or "no schedule supplied"

    def _payments(self) -> tuple[list[str], str]:
        bad = [f"{r[0]}: {r[1]} approved claims" for r in self._q(
            "SELECT c.coupon_id, COUNT(*) FROM books_claim_events c JOIN books_je_status s ON s.je_id = "
            "c.approval_je_id WHERE c.kind = 'approved' AND s.status != 'rejected' GROUP BY c.coupon_id "
            "HAVING COUNT(*) > 1")]
        bad += [f"{r[0]}: {r[1]} payout entries" for r in self._q(
            "SELECT json_extract(l.dims, '$.coupon') cp, COUNT(DISTINCT l.je_id) FROM books_je_lines l JOIN books_je j "
            "ON j.je_id = l.je_id JOIN books_je_status s ON s.je_id = l.je_id WHERE j.kind = 'claim_paid' AND "
            "l.account = '1000' AND s.status != 'rejected' GROUP BY cp HAVING COUNT(DISTINCT l.je_id) > 1")]
        bad += [f"{r[0]}: paid {eur0(int(r[1]))} > entitlement {eur0(int(r[2]))}" for r in self._q(
            "SELECT c.coupon_id, SUM(c.amount_cents), r.compensation_cents FROM books_claim_events c JOIN "
            "books_je_status s ON s.je_id = c.approval_je_id JOIN books_register r ON r.coupon_id = c.coupon_id "
            "WHERE c.kind IN ('approved', 'in_kind') AND s.status != 'rejected' GROUP BY c.coupon_id "
            "HAVING SUM(c.amount_cents) > r.compensation_cents")]
        bad += [f"{r[0]}: paid directly after the assignment notice of {r[1][:10]} (does not discharge)"
                for r in self._q(
                    "SELECT DISTINCT m.coupon_id, m.received_at FROM books_claims m JOIN books_claim_events c ON "
                    "c.coupon_id = m.coupon_id AND c.kind = 'approved' JOIN books_claims d ON d.claim_id = c.claim_id "
                    "AND d.channel = 'direct' WHERE m.authority = 'assignment' AND c.known_at >= m.received_at")]
        n = int(self._q1("SELECT COUNT(DISTINCT coupon_id) FROM books_claim_events WHERE kind IN ('approved', "
                         "'in_kind')"))
        return bad, f"{n} coupons settled once, each ≤ its entitlement"

    def _extraordinary(self) -> tuple[list[str], str]:
        ext = [r[0] for r in self._q("SELECT flight_id FROM books_decisions WHERE extraordinary = 'extraordinary'")]
        bad: list[str] = []
        if ext:
            marks = ",".join("?" * len(ext))
            bad += [f"{r[0]}: {r[1]} coupons with compensation" for r in self._q(
                f"SELECT flight_id, COUNT(*) FROM books_register WHERE flight_id IN ({marks}) AND "
                f"compensation_cents > 0 GROUP BY flight_id ORDER BY flight_id", ext)]
        care_due: set[str] = set()
        for r in self._q("SELECT care_flights FROM books_run_events"):
            care_due |= set(json.loads(r[0]))
        accrued = {r[0] for r in self._q("SELECT DISTINCT flight_id FROM books_care_events WHERE kind = 'accrual'")}
        bad += [f"{f}: care issued but not accrued" for f in sorted(care_due - accrued)]
        return bad, (f"{len(ext)} extraordinary flights: no compensation; refunds and care still due · care accrued "
                     f"for {len(accrued)} flights")

    def _offsets(self) -> tuple[list[str], str]:
        bad = [f"{r[0]}: offset {eur0(int(r[1]))} with no signed acceptance" for r in self._q(
            "SELECT coupon_id, voucher_offset_cents FROM books_register WHERE voucher_offset_cents > 0 AND "
            "(voucher_signed_sha256 IS NULL OR voucher_signed_sha256 = '') ORDER BY coupon_id")]
        bad += [f"{r[0]}: voucher settled in kind with no signed acceptance" for r in self._q(
            "SELECT DISTINCT e.coupon_id FROM books_coupon_events e LEFT JOIN books_register r ON r.coupon_id = "
            "e.coupon_id WHERE e.kind = 'in_lieu' AND e.channel = 'in_kind' AND (r.voucher_signed_sha256 IS NULL "
            "OR r.voucher_signed_sha256 = '')")]
        bad += [f"{r[0]}: claim approved at {eur0(int(r[1]))} < {eur0(int(r[2]))} with no signed acceptance"
                for r in self._q(
                    "SELECT c.coupon_id, c.amount_cents, r.compensation_cents FROM books_claim_events c JOIN "
                    "books_register r ON r.coupon_id = c.coupon_id JOIN books_je_status s ON s.je_id = "
                    "c.approval_je_id WHERE c.kind = 'approved' AND s.status != 'rejected' AND c.amount_cents < "
                    "r.compensation_cents AND (r.voucher_signed_sha256 IS NULL OR r.voucher_signed_sha256 = '')")]
        n = int(self._q1("SELECT COUNT(*) FROM books_register WHERE voucher_offset_cents > 0"))
        return bad, f"{n} offsets, each with a signed acceptance hash"

    def _derecognitions(self) -> tuple[list[str], str]:
        bad: list[str] = []
        rows = self._q("SELECT j.je_id, j.cohort, j.event_date, j.known_at FROM books_je j JOIN books_je_status s "
                       "ON s.je_id = j.je_id WHERE j.kind = 'derecognition' AND s.status != 'rejected' ORDER BY j.seq")
        for r in rows:
            event = self._cohort_date(r["cohort"]) if r["cohort"] else None
            if event is not None and limitation_expiry(event) <= date.fromisoformat(r["event_date"]):
                continue
            ok = self._q("SELECT 1 FROM books_policy_events WHERE kind = 'derecognise' AND cohort = ? AND known_at <= ? "
                         "LIMIT 1", [r["cohort"] or "", r["known_at"]])
            if not ok:
                bad.append(f"{r['je_id']} ({r['cohort']}) before limitation, no Controller rule")
        return bad, f"{len(rows)} derecognitions, each at limitation or under a Controller rule"

    def _refunds(self, now: datetime) -> tuple[list[str], str]:
        today = utc_date(now)
        bad: list[str] = []
        cases = self._refund_cases()
        queued = cash = 0
        for cid, cancel, ch, d in cases:
            due = cancel + timedelta(days=REFUND_DAYS)
            if ch is None:
                if today > due:
                    bad.append(f"{cid}: refund elected, none drafted by {due.isoformat()}")
            elif ch == "queued":
                queued += 1
            elif d > due:
                bad.append(f"{cid}: refunded {d.isoformat()}, after {due.isoformat()}")
            else:
                cash += 1
        return bad, f"{cash} refunded within 7 days · {queued} refund drafts queued"

