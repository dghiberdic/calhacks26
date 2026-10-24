"""F8b: the PSS-side postings around the EU261 estimate (IMPLEMENTATION_PLAN §1.3).

- **Sale.** ATL brought forward per flight: Dr 1110 / Cr 2100 fare (incl. carrier surcharges YQ/YR) / Cr 2110 taxes.
- **Refunds.** Relieve ATL + taxes once per coupon. A CRM-bot refund is the bot's own Dr 2125 / Cr 1110, then Books
  posts Dr 2100 / Dr 2110 / Cr 2125, so 2125 nets to 0. A BSP refund goes to 2120 refunds payable, a chargeback to
  1110, and a refund elected with no payment yet is queued in 2120. A second refund on the same coupon is a
  duplicate: it is flagged and never relieves ATL again.
- **Refund voucher.** Ticket value incl. taxes → 2131. **Partner reroute.** FIM net → 2160, excess → 6110.
  **Reaccommodated on our own flights.** Stays in ATL until flown.
- **Voucher in lieu of compensation.** Signed (Art. 7(3)) → settles in kind, Dr 2140 / Cr 2132. Unsigned → goodwill,
  Dr 4090 / Cr 2132; a void while unredeemed reverses it (Dr 2132 / Cr 4090).
- **Care.** Accrual Dr 6100 / Cr 2150; the invoice batch clears the accrual to 2000 and trues up 6100.

Every posting is idempotent per coupon (sale, relief) or per source event (CRM event, care id, invoice id), so
re-running with a newer world posts only what is new. Pure: no LLM, no wall clock, no randomness.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from contracts.models import CareCost, Coupon, CrmEvent, JournalEntry, Role, World

from .errors import BooksError, NotFound
from .money import eur
from .periods import date_in_id, iso, period_of, to_utc, utc_date

CRM_BOT = Role.CRM_BOT.value                      # "agent.crm_bot"
REFUND_EVENTS = ("refund_initiated", "bsp_refund", "chargeback")
EXEC_CHANNEL = {"refund_initiated": "crm_bot", "bsp_refund": "bsp", "chargeback": "chargeback"}
REFUND_CHANNELS = frozenset({"crm_bot", "bsp", "chargeback", "queued"})
OPEN_2120 = frozenset({"bsp", "queued"})          # reliefs that leave a refund payable in 2120
RELIEF_ELECTIONS = {"refund": "queued", "voucher": "voucher", "reroute_partner": "reroute_fim"}
IN_LIEU = "voucher_in_lieu_of_compensation"
ACCRUING = ("owed", "held", "needs_ruling")
OPS_KINDS = ("sale", "refund", "voucher", "reroute_fim", "voucher_in_lieu", "voucher_void", "care_accrual",
             "care_invoice")

# bucket -> (JE kind, credit account of the relief); bucket order fixes the JE order within a flight and date
_BUCKETS = ("sale", "bot", "relief:crm_bot", "settle:crm_bot", "relief:bsp", "relief:chargeback",
            "settle:chargeback", "relief:queued", "relief:voucher", "relief:reroute_fim")
_CREDIT = {"crm_bot": "2125", "bsp": "2120", "chargeback": "1110", "queued": "2120", "voucher": "2131",
           "reroute_fim": "2160"}


def enum_value(x: Any) -> Any:
    """`Cause.WEATHER` → "weather" (and plain strings unchanged, e.g. from an unvalidated model_copy)."""
    return getattr(x, "value", x)


def coupon_flight(coupon_id: str) -> str:
    """`NS31@2025-01-24:14C` → `NS31@2025-01-24`."""
    return coupon_id.rsplit(":", 1)[0] if ":" in coupon_id else coupon_id


@dataclass
class _Post:
    coupon: Coupon
    kind: str                     # coupon-event kind
    channel: str | None
    event_date: date
    bucket: str | None = None     # None: a flag row with no JE
    amount: int = 0
    crm_id: str | None = None
    detail: str | None = None
    fim: int | None = None        # reroute: FIM value (default: ticket value)


class OpsMixin:
    """Mixed into `books.Books`; relies on its `_tx`, `_q`, `_insert_je`, `_target`, register and claim helpers."""

    # ------------------------------------------------------------------ public

    def post_operations(self, run_id: str, world: World, known_at: datetime, *,
                        flight_ids: Iterable[str] | None = None,
                        fim_values: dict[str, int] | None = None) -> list[JournalEntry]:
        """Post whatever is new in the world for the run's flights (later BSP refunds, CRM-bot refunds, in-lieu
        vouchers, care invoices). Idempotent per coupon and per source event. Returns only the new entries."""
        known_at = to_utc(known_at)
        with self._tx():
            if flight_ids is None:
                flights = {r[0] for r in self._q("SELECT flight_id FROM books_storm_flights WHERE run_id = ?",
                                                 [run_id])}
            else:
                flights = set(flight_ids)
            cohort_date = self._cohort_date(run_id) or date_in_id(run_id) or utc_date(known_at)
            ids, by_coupon = self._post_atl(run_id, world, flights, known_at, fim_values, cohort_date)
            self._reg_append(by_coupon, known_at, "pss")
            ids += self._post_in_lieu(run_id, world, flights, known_at)
            ids += self._post_care(run_id, world, flights, known_at)
        return self._je_many(ids)

    def post_care_invoices(self, run_id: str, invoices: Iterable[CareCost], known_at: datetime) -> list[JournalEntry]:
        """Vendor invoices for a run's care: Dr 2150 (the open accrual of every flight invoiced) / Cr 2000 invoiced,
        the difference to 6100 (a reversal of the over-accrual, or extra care cost). Idempotent per invoice id."""
        known_at = to_utc(known_at)
        with self._tx():
            done = self._care_done()
            ids = self._care_invoices(run_id, [i for i in invoices if (i.id, "invoice") not in done], known_at)
        return self._je_many(ids)

    def void_voucher(self, coupon_id: str, known_at: datetime, reason: str = "unredeemed") -> JournalEntry:
        """Void an unredeemed goodwill voucher in lieu of compensation: Dr 2132 / Cr 4090. A signed voucher that
        settled the claim in kind can't be voided to revenue. Idempotent: a second void returns the first."""
        known_at = to_utc(known_at)
        with self._tx():
            rows = self._q("SELECT kind, channel, amount_cents, je_id, cohort, flight_id FROM books_coupon_events "
                           "WHERE coupon_id = ? AND kind IN ('in_lieu', 'void') ORDER BY seq", [coupon_id])
            goodwill = sum(r["amount_cents"] for r in rows if r["kind"] == "in_lieu" and r["channel"] == "goodwill")
            in_kind = sum(r["amount_cents"] for r in rows if r["kind"] == "in_lieu" and r["channel"] == "in_kind")
            voided = [r for r in rows if r["kind"] == "void"]
            outstanding = goodwill - sum(r["amount_cents"] for r in voided)
            if outstanding <= 0:
                if voided:
                    return self._je(voided[-1]["je_id"])
                if in_kind:
                    raise BooksError(f"the voucher on {coupon_id} was signed and settled the EU261 compensation in "
                                     f"kind; it can't be voided to revenue", coupon_id=coupon_id)
                raise NotFound(f"no voucher in lieu of compensation on {coupon_id}", coupon_id=coupon_id)
            first = next(r for r in rows if r["kind"] == "in_lieu")
            cohort, fid = first["cohort"], first["flight_id"]
            eff, flags = self._target(utc_date(known_at), known_at)
            dims = {"cohort": cohort, "flight": fid, "coupon": coupon_id}
            memo = self._flag_memo(
                f"Service-desk voucher void · {coupon_id}: {eur(outstanding)} goodwill voucher in lieu of "
                f"compensation voided ({reason}) · Dr 2132 / Cr 4090 (reverses the goodwill reduction of passenger "
                f"revenue) · drafted, pending approval", flags, eff)
            je_id = self._insert_je(kind="voucher_void", event_date=eff, memo=memo, known_at=known_at,
                                    lines=[{"account": "2132", "dr": outstanding, "dims": dims},
                                           {"account": "4090", "cr": outstanding, "dims": dims}],
                                    cohort=cohort, flight_id=fid, flags=flags, ties_to=["2132"],
                                    reverses=first["je_id"], built_from=1)
            self._coupon_rows([_Post(coupon=_stub_coupon(coupon_id, fid), kind="void", channel="goodwill",
                                     event_date=eff, amount=outstanding, detail=reason)],
                              {None: je_id}, cohort, known_at)
            self._reg_append({coupon_id: [je_id]}, known_at, "voucher_void")
        return self._je(je_id)

    def post_interline_bill(self, flight_id: str, billed_cents: int, known_at: datetime, *,
                            bill_ref: str) -> JournalEntry:
        """The partner's IATA SIS bill for a flight's FIM reroutes: Dr 2160 (open FIM) / Cr 2000 billed; a bill above
        the FIM value is rerouting cost (Dr 6110), a bill below it is retained passenger revenue (Cr 4000)."""
        known_at = to_utc(known_at)
        if billed_cents <= 0:
            raise BooksError("an interline bill must be positive")
        ref = f"sis:{bill_ref}"
        with self._tx():
            prior = self._q1("SELECT je_id FROM books_je WHERE estimate_ref = ?", [ref])
            if prior:
                return self._je(prior)
            open_fim = int(self._q1("SELECT COALESCE(SUM(cr_cents - dr_cents), 0) FROM books_gl_lines "
                                    "WHERE account = '2160' AND flight_id = ?", [flight_id]))
            cohort = self._cohort_of_flight(flight_id) or "unassigned"
            dims = {"cohort": cohort, "flight": flight_id}
            lines: list[dict] = []
            if open_fim > 0:
                lines.append({"account": "2160", "dr": open_fim, "dims": dims})
            diff = int(billed_cents) - max(open_fim, 0)
            if diff > 0:
                lines.append({"account": "6110", "dr": diff, "dims": dims})
            lines.append({"account": "2000", "cr": int(billed_cents), "dims": dims})
            if diff < 0:
                lines.append({"account": "4000", "cr": -diff, "dims": dims})
            eff, flags = self._target(utc_date(known_at), known_at)
            memo = self._flag_memo(
                f"Interline (IATA SIS) bill {bill_ref} · {flight_id}: billed {eur(int(billed_cents))} vs FIM "
                f"{eur(max(open_fim, 0))} in 2160 · "
                + (f"excess {eur(diff)} → 6110 rerouting" if diff > 0 else
                   f"retained {eur(-diff)} → 4000 passenger revenue" if diff < 0 else "no difference")
                + " · drafted, pending approval", flags, eff)
            je_id = self._insert_je(kind="reroute_fim", event_date=eff, memo=memo, lines=lines, known_at=known_at,
                                    cohort=cohort, flight_id=flight_id, flags=flags, estimate_ref=ref,
                                    ties_to=["2160", "2000"])
        return self._je(je_id)

    def coupon_events(self, coupon_id: str | None = None, kind: str | None = None,
                      flight_id: str | None = None) -> list[dict[str, Any]]:
        """The ATL / refund / voucher subledger (append-only), oldest first."""
        sql, args = "SELECT * FROM books_coupon_events WHERE 1=1", []
        for col, val in (("coupon_id", coupon_id), ("kind", kind), ("flight_id", flight_id)):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        return [dict(r) for r in self._q(sql + " ORDER BY seq", args)]

    def care_events(self, flight_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM books_care_events", []
        if flight_id is not None:
            sql += " WHERE flight_id = ?"
            args.append(flight_id)
        return [dict(r) for r in self._q(sql + " ORDER BY seq", args)]

    # ------------------------------------------------------------------ ATL side

    def _coupon_state(self, flights: set[str]) -> tuple[set[str], dict[str, str], set[str], set[str]]:
        sold: set[str] = set()
        relief: dict[str, str] = {}
        settled: set[str] = set()
        processed: set[str] = set()
        fl = sorted(flights)
        for chunk in (fl[i:i + 500] for i in range(0, len(fl), 500)):
            marks = ",".join("?" * len(chunk))
            for r in self._q(f"SELECT coupon_id, kind, channel, crm_event_id FROM books_coupon_events "
                             f"WHERE flight_id IN ({marks}) ORDER BY seq", chunk):
                k = r["kind"]
                if k == "sale":
                    sold.add(r["coupon_id"])
                elif k == "relief":
                    relief.setdefault(r["coupon_id"], r["channel"])
                elif k in ("settle", "executed"):
                    settled.add(r["coupon_id"])
                if r["crm_event_id"]:
                    processed.add(r["crm_event_id"])
        return sold, relief, settled, processed

    def _post_atl(self, run_id: str, world: World, flights: set[str], known_at: datetime,
                  fim_values: dict[str, int] | None, cohort_date: date) -> tuple[list[str], dict[str, list[str]]]:
        coupons = {c.id: c for c in world.coupons if c.flight_id in flights}
        if not coupons:
            return [], {}
        fdates = {f.id: f.date for f in world.flights}

        def fdate(fid: str) -> date:
            return fdates.get(fid) or date_in_id(fid) or cohort_date

        sold, relief, settled, processed = self._coupon_state({c.flight_id for c in coupons.values()})
        posts: list[_Post] = []
        for c in sorted(coupons.values(), key=lambda c: c.id):
            if c.id not in sold:
                posts.append(_Post(coupon=c, kind="sale", channel=c.channel, event_date=fdate(c.flight_id),
                                   bucket="sale"))
                sold.add(c.id)

        events = sorted((e for e in world.crm if e.coupon_id in coupons and e.kind in REFUND_EVENTS
                         and to_utc(e.at) <= known_at and e.id not in processed),
                        key=lambda e: (to_utc(e.at), e.id))
        for e in events:
            posts += self._refund_event(coupons[e.coupon_id], e, relief, settled)

        elections: dict[str, str] = {}
        for el in world.elections:                       # last election per coupon wins (as in the engine)
            if el.coupon_id in coupons:
                elections[el.coupon_id] = el.kind
        for cid in sorted(elections):
            channel = RELIEF_ELECTIONS.get(elections[cid])
            if channel is None or cid in relief:
                continue
            c = coupons[cid]
            fim = None
            if channel == "reroute_fim":
                fim = int((fim_values or {}).get(cid, c.fare_cents + c.taxes_cents))
            posts.append(_Post(coupon=c, kind="relief", channel=channel, event_date=fdate(c.flight_id),
                               bucket=f"relief:{channel}", fim=fim))
            relief[cid] = channel
        return self._emit_atl(run_id, posts, known_at)

    def _refund_event(self, c: Coupon, e: CrmEvent, relief: dict[str, str], settled: set[str]) -> list[_Post]:
        """One refund-type CRM event against the coupon's relief state (mutated)."""
        d = utc_date(e.at)
        channel = EXEC_CHANNEL[e.kind]
        value = c.fare_cents + c.taxes_cents
        amount = int(e.amount_cents) if e.amount_cents else value
        prior = relief.get(c.id)
        out: list[_Post] = []
        if channel == "crm_bot":                         # the bot's own posting happened, whatever Books does next
            out.append(_Post(coupon=c, kind="bot_refund", channel="crm_bot", event_date=d, bucket="bot",
                             amount=amount, crm_id=e.id))
        if prior is None:
            out.append(_Post(coupon=c, kind="relief", channel=channel, event_date=d, bucket=f"relief:{channel}",
                             crm_id=e.id))
            relief[c.id] = channel
            return out
        open_2120 = prior in OPEN_2120 and c.id not in settled
        if channel in ("crm_bot", "chargeback") and open_2120:
            out.append(_Post(coupon=c, kind="settle", channel=channel, event_date=d, bucket=f"settle:{channel}",
                             amount=value, crm_id=e.id,
                             detail=f"pays the {prior} refund payable in 2120"))
            settled.add(c.id)
            if prior == "bsp":
                out.append(_Post(coupon=c, kind="duplicate", channel="bsp", event_date=d, crm_id=e.id,
                                 detail=f"BSP refund duplicates the {channel} refund ({e.id}): recall it before the "
                                        f"BSP remittance (ADM)"))
            return out
        if channel == "bsp" and prior == "queued" and c.id not in settled:
            out.append(_Post(coupon=c, kind="executed", channel="bsp", event_date=d, crm_id=e.id,
                             detail="BSP executes the queued refund; 2120 settles in the BSP remittance"))
            settled.add(c.id)
            return out
        if channel == "crm_bot":
            out.append(_Post(coupon=c, kind="double_refund", channel="crm_bot", event_date=d, amount=amount,
                             crm_id=e.id, detail=f"CRM-bot refund on a coupon already relieved by {prior}: cash out "
                                                 f"twice, 2125 left open for recovery"))
        else:
            out.append(_Post(coupon=c, kind="duplicate", channel=channel, event_date=d, crm_id=e.id,
                             detail=f"{e.kind} after the {prior} relief: flagged, not repeated"
                                    + (" (contest the chargeback with the refund evidence)"
                                       if channel == "chargeback" else " (recall the BSP refund, ADM)")))
        return out

    def _emit_atl(self, run_id: str, posts: list[_Post], known_at: datetime) -> tuple[list[str], dict[str, list[str]]]:
        groups: dict[tuple[str, str, date], list[_Post]] = defaultdict(list)
        flags: list[_Post] = []
        for p in posts:
            if p.bucket is None:
                flags.append(p)
            else:
                groups[(p.coupon.flight_id, p.event_date.isoformat(), p.bucket)].append(p)
        order = {b: i for i, b in enumerate(_BUCKETS)}
        ids: list[str] = []
        by_coupon: dict[str, list[str]] = defaultdict(list)
        cohort_cache: dict[str, str] = {}

        def cohort_of(fid: str) -> str:
            if fid not in cohort_cache:
                cohort_cache[fid] = self._cohort_of_flight(fid) or run_id
            return cohort_cache[fid]

        for key in sorted(groups, key=lambda k: (k[0], k[1], order[k[2]])):
            fid, day, bucket = key
            grp = groups[key]
            cohort = cohort_of(fid)
            je_id = self._atl_je(run_id, cohort, fid, date.fromisoformat(day), bucket, grp, known_at)
            ids.append(je_id)
            self._coupon_rows(grp, {None: je_id}, cohort, known_at)
            for p in grp:
                if je_id not in by_coupon[p.coupon.id]:
                    by_coupon[p.coupon.id].append(je_id)
        for p in flags:
            self._coupon_rows([p], {None: None}, cohort_of(p.coupon.flight_id), known_at)
        return ids, dict(by_coupon)

    def _atl_je(self, run_id: str, cohort: str, fid: str, day: date, bucket: str, grp: list[_Post],
                known_at: datetime) -> str:
        n = len(grp)
        fare = sum(p.coupon.fare_cents for p in grp)
        tax = sum(p.coupon.taxes_cents for p in grp)
        dims = {"storm": run_id, "cohort": cohort, "flight": fid}
        ln = lambda acct, dr=0, cr=0: {"account": acct, "dr": dr, "cr": cr, "dims": dims}
        preparer = None
        kind = "refund"
        ties: list[str] = ["2100", "2110"]
        if bucket == "sale":
            kind = "sale"
            lines = [ln("1110", dr=fare + tax), ln("2100", cr=fare), ln("2110", cr=tax)]
            memo = (f"ATL brought forward · {fid}: {n} coupons · fares incl. carrier surcharges YQ/YR {eur(fare)} → "
                    f"2100 ATL · taxes {eur(tax)} → 2110 taxes payable (the PSS extract carries no sale dates; dated "
                    f"at departure)")
        elif bucket == "bot":
            amt = sum(p.amount for p in grp)
            preparer = CRM_BOT
            lines = [ln("2125", dr=amt), ln("1110", cr=amt)]
            ties = ["2125"]
            memo = (f"CRM bot · {fid}: {n} refunds initiated to the card acquirer {eur(amt)} (posted by the CRM bot "
                    f"to 2125 refund clearing) · Dr 2125 / Cr 1110")
        elif bucket.startswith("settle:"):
            channel = bucket.split(":", 1)[1]
            amt = sum(p.amount for p in grp)
            credit = "2125" if channel == "crm_bot" else "1110"
            lines = [ln("2120", dr=amt), ln(credit, cr=amt)]
            ties = ["2120", credit]
            who = "the CRM bot" if channel == "crm_bot" else "card chargebacks"
            memo = (f"Refunds · {fid}: {who} paid {n} refunds already payable in 2120 {eur(amt)} · Dr 2120 / Cr "
                    f"{credit}" + (" (2125 nets to 0: no double refund)" if credit == "2125" else ""))
        else:
            channel = bucket.split(":", 1)[1]
            credit = _CREDIT[channel]
            ties.append(credit)
            lines = [ln("2100", dr=fare), ln("2110", dr=tax)]
            value = fare + tax
            if channel == "voucher":
                kind = "voucher"
                lines.append(ln("2131", cr=value))
                memo = (f"Refund vouchers · {fid}: {n} vouchers at ticket value incl. taxes {eur(value)} → 2131 "
                        f"refund vouchers (ATL {eur(fare)} + taxes {eur(tax)})")
            elif channel == "reroute_fim":
                kind = "reroute_fim"
                fim = sum(p.fim if p.fim is not None else p.coupon.fare_cents + p.coupon.taxes_cents for p in grp)
                excess = fim - value
                if excess > 0:
                    lines.append(ln("6110", dr=excess))
                lines.append(ln("2160", cr=fim))
                if excess < 0:
                    lines.append(ln("4000", cr=-excess))
                memo = (f"Partner reroutes · {fid}: {n} reroutes on a partner (FIM, net): ATL {eur(fare)} + taxes "
                        f"{eur(tax)} → 2160 interline payable {eur(fim)}"
                        + (f" · excess {eur(excess)} → 6110 rerouting" if excess > 0 else "")
                        + (f" · retained {eur(-excess)} → 4000 passenger revenue" if excess < 0 else "")
                        + " · the partner bills through IATA SIS")
            else:
                lines.append(ln(credit, cr=value))
                memo = {
                    "crm_bot": f"Refunds · {fid}: {n} refunds already initiated by the CRM bot, not repeated · ATL "
                               f"{eur(fare)} + taxes {eur(tax)} clear 2125 refund clearing (2125 nets to 0: no double "
                               f"refund) · EU261 Art. 8(1)(a)",
                    "bsp": f"Refunds · {fid}: {n} BSP (agency) refunds · ATL {eur(fare)} + taxes {eur(tax)} → 2120 "
                           f"refunds payable (settled in the BSP remittance) · EU261 Art. 8(1)(a)",
                    "chargeback": f"Refunds · {fid}: {n} card chargebacks · ATL {eur(fare)} + taxes {eur(tax)} → 1110 "
                                  f"card acquirer · EU261 Art. 8(1)(a)",
                    "queued": f"Refunds · {fid}: {n} refunds elected · ATL {eur(fare)} + taxes {eur(tax)} → 2120 "
                              f"refunds payable · refund draft queued for the payment provider (EU261 Art. 8(1)(a), "
                              f"within 7 days) · drafted, pending approval",
                }[channel]
        eff, flags = self._target(day, known_at)
        kw: dict[str, Any] = {} if preparer is None else {"preparer": preparer}
        return self._insert_je(kind=kind, event_date=eff, memo=self._flag_memo(memo, flags, eff), lines=lines,
                               known_at=known_at, run_id=run_id, cohort=cohort, flight_id=fid, flags=flags,
                               ties_to=ties, built_from=n, **kw)

    def _coupon_rows(self, posts: list[_Post], je: dict[None, str | None], cohort: str, known_at: datetime) -> None:
        now = self._now()
        self._conn.executemany(
            "INSERT INTO books_coupon_events(coupon_id, flight_id, cohort, kind, channel, crm_event_id, fare_cents, "
            "taxes_cents, amount_cents, je_id, event_date, detail, known_at, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(p.coupon.id, p.coupon.flight_id, cohort, p.kind, p.channel, p.crm_id, p.coupon.fare_cents,
              p.coupon.taxes_cents, _row_amount(p), je[None], p.event_date.isoformat(), p.detail, iso(known_at), now)
             for p in posts])

    def _reg_append(self, by_coupon: dict[str, list[str]], known_at: datetime, reason: str,
                    updates: dict[str, dict[str, Any]] | None = None) -> None:
        rows = []
        for cid in sorted(set(by_coupon) | set(updates or {})):
            prev = self._register_one(cid)
            if prev is None:
                continue
            row = dict(prev)
            row["je_ids"] = list(prev["je_ids"]) + [j for j in by_coupon.get(cid, []) if j not in prev["je_ids"]]
            row.update((updates or {}).get(cid, {}))
            row.update({"reason": reason, "known_at": iso(known_at)})
            rows.append(row)
        self._reg_insert(rows)

    # ------------------------------------------------------------------ vouchers in lieu

    def _post_in_lieu(self, run_id: str, world: World, flights: set[str], known_at: datetime) -> list[str]:
        coupons = {c.id: c for c in world.coupons}
        done = {r[0] for r in self._q("SELECT DISTINCT crm_event_id FROM books_coupon_events WHERE kind = 'in_lieu' "
                                      "AND crm_event_id IS NOT NULL")}
        evs = sorted((e for e in world.crm if e.kind == IN_LIEU and to_utc(e.at) <= known_at and e.id not in done
                      and (coupons[e.coupon_id].flight_id if e.coupon_id in coupons
                           else coupon_flight(e.coupon_id)) in flights),
                     key=lambda e: (to_utc(e.at), e.id))
        ids: list[str] = []
        for e in evs:
            ids += self._in_lieu_one(run_id, e, coupons.get(e.coupon_id), known_at)
        return ids

    def _in_lieu_one(self, run_id: str, e: CrmEvent, coupon: Coupon | None, known_at: datetime) -> list[str]:
        fid = coupon.flight_id if coupon else coupon_flight(e.coupon_id)
        c = coupon or _stub_coupon(e.coupon_id, fid)
        reg = self._register_one(e.coupon_id)
        cohort = (reg or {}).get("cohort") or self._cohort_of_flight(fid) or run_id
        amount = int(e.amount_cents)
        d = utc_date(e.at)
        if amount <= 0:
            self._coupon_rows([_Post(coupon=c, kind="in_lieu", channel="goodwill", event_date=d, crm_id=e.id,
                                     detail="no amount on the CRM event: nothing posted")], {None: None}, cohort,
                              known_at)
            return []
        settle = 0
        if e.signed_acceptance_sha256 and reg and reg["status"] in ACCRUING and reg["compensation_cents"] > 0:
            used = int(self._q1("SELECT COALESCE(SUM(amount_cents), 0) FROM books_claim_events WHERE coupon_id = ? "
                                "AND kind IN ('approved', 'in_kind')", [e.coupon_id]))
            settle = max(0, min(amount, int(reg["compensation_cents"]) - used))
        goodwill = amount - settle
        eff, flags = self._target(d, known_at)
        seg = reg["segment"] if reg else None
        dims = {"cohort": cohort, "segment": seg, "flight": fid, "coupon": e.coupon_id}
        ids: list[str] = []
        topup = None
        lines: list[dict] = []
        if settle:
            book = self._liab("2140", through=period_of(eff), cohort=cohort, segment=seg)
            if settle > book:
                top = settle - max(book, 0)
                topup = self._insert_je(
                    kind="change_in_estimate", event_date=eff, known_at=known_at, ias8_class="change_in_estimate",
                    memo=self._flag_memo(
                        f"Change in estimate (IAS 8.36) · cohort {cohort} · {seg}: a signed voucher in lieu settles "
                        f"more than the EU261 compensation liability holds; top-up {eur(top)} · Controller approval "
                        f"required", flags, eff),
                    lines=[{"account": "4090", "dr": top, "dims": dims}, {"account": "2140", "cr": top, "dims": dims}],
                    estimate_ref=f"topup:in-lieu:{e.id}", cohort=cohort, flight_id=fid, flags=flags, ties_to=["2140"])
                ids.append(topup)
            lines.append({"account": "2140", "dr": settle, "dims": dims})
        if goodwill:
            lines.append({"account": "4090", "dr": goodwill, "dims": dims})
        lines.append({"account": "2132", "cr": amount, "dims": dims})
        if settle:
            memo = (f"Service-desk voucher in lieu of compensation · {e.coupon_id}: {eur(amount)}, signed acceptance "
                    f"sha256:{e.signed_acceptance_sha256[:12]}… (Art. 7(3)) · settles the EU261 compensation in kind "
                    f"{eur(settle)}: Dr 2140 / Cr 2132"
                    + (f" · {eur(goodwill)} above the compensation is goodwill (Dr 4090)" if goodwill else "")
                    + " · any residual stays claimable under Art. 15(2) if the passenger was not informed")
        else:
            why = ("no signed acceptance (Art. 7(3)): goodwill, not an offset; the compensation stays claimable in "
                   "cash" if not e.signed_acceptance_sha256 else "nothing owed to settle: goodwill")
            memo = (f"Service-desk voucher in lieu of compensation · {e.coupon_id}: {eur(amount)}, {why} · "
                    f"Dr 4090 / Cr 2132 (reduction of passenger revenue)")
        je_id = self._insert_je(kind="voucher_in_lieu", event_date=eff, memo=self._flag_memo(memo + " · drafted, "
                                "pending approval", flags, eff), lines=lines, known_at=known_at, run_id=run_id,
                                cohort=cohort, flight_id=fid, flags=flags, built_from=1,
                                ties_to=["2132"] + (["2140"] if settle else []))
        ids.append(je_id)
        posts = []
        if settle:
            posts.append(_Post(coupon=c, kind="in_lieu", channel="in_kind", event_date=eff, amount=settle,
                               crm_id=e.id, detail=f"signed {e.signed_acceptance_sha256}"))
        if goodwill:
            posts.append(_Post(coupon=c, kind="in_lieu", channel="goodwill", event_date=eff, amount=goodwill,
                               crm_id=e.id, detail="signed" if e.signed_acceptance_sha256 else "unsigned"))
        self._coupon_rows(posts, {None: je_id}, cohort, known_at)
        if settle:
            self._conn.execute(
                "INSERT INTO books_claim_events(claim_id, coupon_id, flight_id, cohort, segment, kind, amount_cents, "
                "reason, event_date, approval_je_id, payment_je_id, topup_je_id, known_at, recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"in-lieu:{e.id}", e.coupon_id, fid, cohort, seg, "in_kind", settle, "signed_in_lieu",
                 eff.isoformat(), je_id, None, topup, iso(known_at), self._now()))
        upd: dict[str, Any] = {}
        if e.signed_acceptance_sha256:
            upd["voucher_signed_sha256"] = e.signed_acceptance_sha256
        if settle:
            upd["settlement"] = "in_kind"
        self._reg_append({e.coupon_id: ids}, known_at, "voucher_in_lieu", {e.coupon_id: upd} if upd else None)
        return ids

    # ------------------------------------------------------------------ care

    def _care_done(self) -> set[tuple[str, str]]:
        return {(r[0], r[1]) for r in self._q("SELECT care_id, kind FROM books_care_events")}

    def _post_care(self, run_id: str, world: World, flights: set[str], known_at: datetime) -> list[str]:
        rows = [c for c in world.care if c.flight_id in flights]
        if not rows:
            return []
        done = self._care_done()
        accr = [c for c in rows if not c.invoiced and (c.id, "accrual") not in done]
        invs = [c for c in rows if c.invoiced and to_utc(c.at) <= known_at and (c.id, "invoice") not in done]
        ids: list[str] = []
        by_period: dict[str, list[CareCost]] = defaultdict(list)
        for c in accr:
            by_period[period_of(utc_date(c.at))].append(c)
        for p in sorted(by_period):
            grp = sorted(by_period[p], key=lambda c: c.id)
            day = max(utc_date(c.at) for c in grp)
            eff, flags = self._target(day, known_at)
            total = sum(c.amount_cents for c in grp)
            if total <= 0:
                continue
            nflights = len({c.flight_id for c in grp})
            kinds = ", ".join(sorted({c.kind for c in grp}))
            cohort = self._cohort_of_flight(grp[0].flight_id) or run_id
            dims = {"storm": run_id, "cohort": cohort}
            memo = (f"Care accrued · {run_id}: {nflights} cancelled flights ({kinds}) {eur(total)} · Dr 6100 / Cr 2150 "
                    f"· care is owed even when the circumstances are extraordinary (EU261 Art. 9, CJEU C-12/11 "
                    f"McDonagh) · drafted, pending approval")
            je_id = self._insert_je(kind="care_accrual", event_date=eff, memo=self._flag_memo(memo, flags, eff),
                                    lines=[{"account": "6100", "dr": total, "dims": dims},
                                           {"account": "2150", "cr": total, "dims": dims}],
                                    known_at=known_at, run_id=run_id, cohort=cohort, flags=flags,
                                    ties_to=["2150"], built_from=len(grp))
            ids.append(je_id)
            self._care_rows([(c.id, c.flight_id, "accrual", c.amount_cents, c.vendor) for c in grp], cohort, je_id,
                            eff, known_at)
        if invs:
            ids += self._care_invoices(run_id, invs, known_at)
        return ids

    def _care_rows(self, rows: list[tuple[str, str, str, int, str | None]], cohort: str, je_id: str | None,
                   eff: date, known_at: datetime) -> None:
        now = self._now()
        self._conn.executemany(
            "INSERT INTO books_care_events(care_id, flight_id, cohort, kind, amount_cents, vendor, je_id, event_date, "
            "known_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(cid, fid, cohort, kind, int(amt), vendor, je_id, eff.isoformat(), iso(known_at), now)
             for cid, fid, kind, amt, vendor in rows])

    def _care_invoices(self, run_id: str, invoices: list[CareCost], known_at: datetime) -> list[str]:
        ids: list[str] = []
        by_period: dict[str, list[CareCost]] = defaultdict(list)
        for c in invoices:
            by_period[period_of(utc_date(c.at))].append(c)
        for p in sorted(by_period):
            grp = sorted(by_period[p], key=lambda c: c.id)
            day = max(utc_date(c.at) for c in grp)
            eff, flags = self._target(day, known_at)
            billed = sum(int(c.amount_cents) for c in grp)
            flights = sorted({c.flight_id for c in grp})
            open_by_flight: dict[str, int] = {}
            for fid in flights:
                v = int(self._q1("SELECT COALESCE(SUM(CASE WHEN kind = 'accrual' THEN amount_cents WHEN kind = "
                                 "'cleared' THEN -amount_cents ELSE 0 END), 0) FROM books_care_events "
                                 "WHERE flight_id = ?", [fid]))
                if v > 0:
                    open_by_flight[fid] = v
            clear = sum(open_by_flight.values())
            diff = clear - billed
            cohort = self._cohort_of_flight(flights[0]) or run_id
            dims = {"storm": run_id, "cohort": cohort}
            lines: list[dict] = []
            if clear:
                lines.append({"account": "2150", "dr": clear, "dims": dims})
            if diff < 0:
                lines.append({"account": "6100", "dr": -diff, "dims": dims})
            lines.append({"account": "2000", "cr": billed, "dims": dims})
            if diff > 0:
                lines.append({"account": "6100", "cr": diff, "dims": dims})
            memo = (f"Care invoices · {run_id}: {len(grp)} vendor invoices for {len(flights)} flights {eur(billed)} → "
                    f"2000 trade payables · clears accrued care {eur(clear)} (2150)"
                    + (f" · reversal of the over-accrual {eur(diff)} → 6100 care" if diff > 0 else
                       f" · care above the accrual {eur(-diff)} → 6100 care" if diff < 0 else "")
                    + " · drafted, pending approval")
            je_id = self._insert_je(kind="care_invoice", event_date=eff, memo=self._flag_memo(memo, flags, eff),
                                    lines=lines, known_at=known_at, run_id=run_id, cohort=cohort, flags=flags,
                                    ties_to=["2150", "2000"], built_from=len(grp))
            ids.append(je_id)
            self._care_rows([(c.id, c.flight_id, "invoice", c.amount_cents, c.vendor) for c in grp], cohort, je_id,
                            eff, known_at)
            self._care_rows([(f"cleared:{je_id}:{fid}", fid, "cleared", amt, None)
                             for fid, amt in sorted(open_by_flight.items())], cohort, je_id, eff, known_at)
        return ids

    # ------------------------------------------------------------------ provenance and completeness snapshots

    def _record_decisions(self, run_id: str | None, decisions: Iterable[Any], known_at: datetime) -> None:
        now = self._now()
        for d in sorted(decisions, key=lambda d: d.flight_id):
            prev = self._q("SELECT cause, extraordinary, recoded, decision_commit FROM books_decisions "
                           "WHERE flight_id = ?", [d.flight_id])
            key = (enum_value(d.cause), enum_value(d.extraordinary), int(bool(d.recoded)), d.commit)
            if prev and tuple(prev[0]) == key:
                continue
            sources = sorted({ev.source_id for ev in d.evidence})
            self._conn.execute(
                "INSERT INTO books_decision_events(flight_id, run_id, cause, extraordinary, recoded, recode_label, "
                "ops_cause_code, decision_commit, sources, rules, legal_basis, confidence, known_at, recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d.flight_id, run_id, enum_value(d.cause), enum_value(d.extraordinary), int(bool(d.recoded)),
                 d.recode_label,
                 d.ops_cause_code, d.commit, json.dumps(sources), json.dumps(list(d.rules_applied)),
                 json.dumps(list(d.legal_basis)), d.confidence.score, iso(known_at), now))

    def _record_run(self, run_id: str, world: World, run_flights: set[str], cohort_date: date,
                    known_at: datetime) -> None:
        station = run_id.split("@", 1)[0]
        iata = next((a.iata for a in world.airports if a.icao == station), None) or (
            station if len(station) == 3 else None)
        day = [f for f in world.flights if f.id in run_flights or (
            f.date == cohort_date and (iata is None or iata in (f.origin, f.dest)))]
        if not day:
            return                                       # no schedule supplied: completeness can't be assessed
        ids = {f.id for f in day}
        occ_entries = [e for e in world.ops_log if e.kind == "occ"]
        occ = None
        if occ_entries:
            occ = sorted({fid for e in occ_entries if _is_cancel_message(e.text) for fid in e.flight_ids
                          if fid in ids})
        care_flights = sorted({c.flight_id for c in world.care if c.flight_id in ids and not c.invoiced})
        ctx = world.real_context.get(run_id) or {}
        euro = ctx.get("eurocontrol_departures")
        ops_dep = (sum(1 for f in day if f.status != "cancelled" and f.origin == iata) if iata else None)
        self._conn.execute(
            "INSERT INTO books_run_events(run_id, station, station_iata, cohort_date, scheduled, operated, cancelled, "
            "occ, care_flights, eurocontrol_departures, operated_station_departures, known_at, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, station, iata, cohort_date.isoformat(), json.dumps(sorted(ids)),
             json.dumps(sorted(f.id for f in day if f.status != "cancelled")),
             json.dumps(sorted(f.id for f in day if f.status == "cancelled")),
             None if occ is None else json.dumps(occ), json.dumps(care_flights),
             int(euro) if isinstance(euro, (int, float)) else None, ops_dep, iso(known_at), self._now()))


def _row_amount(p: _Post) -> int:
    """Subledger amount: the ticket value for a sale or relief (the FIM value for a reroute), else the event amount."""
    if p.kind == "relief" and p.channel == "reroute_fim" and p.fim is not None:
        return int(p.fim)
    if p.kind in ("sale", "relief"):
        return p.coupon.fare_cents + p.coupon.taxes_cents
    return int(p.amount)


def _is_cancel_message(text: str) -> bool:
    t = (text or "").upper()
    return "CNL" in t or "CANCEL" in t


def _stub_coupon(coupon_id: str, flight_id: str) -> Coupon:
    """A coupon the world did not list (e.g. an in-lieu voucher on a coupon outside the extract): no fare data."""
    return Coupon(id=coupon_id, pnr="unknown", pax_ref="unknown", flight_id=flight_id, fare_cents=0, taxes_cents=0)
