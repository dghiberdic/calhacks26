"""World → Facts: the one canonical conversion (CONTRACTS §2 shared helpers).

`world_to_facts(world)` turns the structured feeds into `Fact`s with extractor `normalize@1`, each pointing at the raw
document it came from (`source_id`) and, where the document has one, a verbatim `span`. Every field is registered in
`contracts/fields.py`. The same world always gives the same facts, in the same order, with the same ids.

Source conventions (see contracts/DECISIONS.md): tech-log / ops-log / CRM / claim records → `SRC-<record id>`;
coupons and elections → `SRC-PSS-<flight id>`; manifests → `SRC-MANIFEST-<flight id>`; METAR → `SRC-METAR-<key>`;
schedule lines, care rows and cohort balances are found by content. A record whose document is missing gets
`SRC-WORLD` (a structured feed with no raw text) and no span.

`resolve(facts, sources, known_at)` applies plan §2 rule 7: facts recorded by `known_at`, per (subject, field), the
best trust tier wins, then the latest.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .fields import get as _spec
from .models import Fact, MetarObs, Source, World

EXTRACTOR = "normalize@1"
STRUCTURED_SOURCE = "SRC-WORLD"
_ID_BAD = re.compile(r"[^A-Za-z0-9@.:_-]")


def _id(*parts: str) -> str:
    return _ID_BAD.sub("_", ":".join(("F", *parts)))


# ---------------------------------------------------------------- public id builders
# The id world_to_facts gives a (record, field) fact (its first occurrence). The engine uses these so the evidence
# it cites links to the normalize facts (trace: decision → fact → span → source).
def fact_id(record: str, field: str) -> str:
    return _id(record, field)


def metar_record(o: MetarObs) -> str:
    return f"METAR-{o.station}-{o.valid.strftime('%Y%m%dT%H%MZ')}"


def metar_fact_id(o: MetarObs, field: str = "metar.gust_kt") -> str:
    return fact_id(metar_record(o), field)


def flight_fact_id(flight_id: str, field: str) -> str:
    return fact_id(flight_id, field)


def techlog_fact_id(entry_id: str, field: str) -> str:
    return fact_id(entry_id, field)


def ops_record(entry_id: str, flight_id: str) -> str:
    return f"{entry_id}:{flight_id}"


def ops_fact_id(entry_id: str, flight_id: str, field: str) -> str:
    """MCC and spares facts are per (log entry, flight named in it)."""
    return fact_id(ops_record(entry_id, flight_id), field)


def crm_fact_id(event_id: str, field: str) -> str:
    return fact_id(event_id, field)


def claim_fact_id(claim_id: str, field: str) -> str:
    return fact_id(claim_id, field)


def cohort_record(cohort: str, account: str = "2140") -> str:
    return f"OB-{cohort}-{account}"


def cohort_fact_id(cohort: str, field: str, account: str = "2140") -> str:
    return fact_id(cohort_record(cohort, account), field)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return _iso(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


class _Builder:
    def __init__(self, world: World):
        self.world = world
        self.src: dict[str, Source] = {s.id: s for s in world.sources}
        self.out: list[Fact] = []
        self.ids: set[str] = set()
        self._lines: dict[str, list[str]] | None = None
        self._finance_index: dict[str, str] | None = None

    # ---- sources
    def source(self, sid: str) -> Source | None:
        return self.src.get(sid)

    def lines(self) -> dict[str, list[str]]:
        if self._lines is None:
            self._lines = {s.id: (s.text or "").splitlines() for s in self.world.sources
                           if s.kind.value in ("schedule", "finance")}
        return self._lines

    def finance_row(self, key: str) -> tuple[str, str] | None:
        """(source id, line) of a finance/sheet line whose first CSV cell is `key`."""
        if self._finance_index is None:
            self._finance_index = {}
            for sid, ls in self.lines().items():
                for ln in ls:
                    head = ln.split(",", 1)[0]
                    self._finance_index.setdefault(head, sid)
                    self._finance_index.setdefault(head + "\0line", ln)
        sid = self._finance_index.get(key)
        return (sid, self._finance_index[key + "\0line"]) if sid else None

    @staticmethod
    def span_in(src: Source | None, *candidates: str | None) -> str | None:
        text = src.text if src is not None else None
        if not text:
            return None
        for c in candidates:
            if c and c in text:
                return c
        return None

    # ---- emit
    def add(self, record: str, subject: str, field: str, value: Any, src: Source | None, *, span: str | None = None,
            valid_at: datetime | None = None, recorded_at: datetime | None = None) -> None:
        if value is None:
            return
        _spec(field)  # raises UnknownField: every normalize field is registered
        sid = src.id if src is not None else STRUCTURED_SOURCE
        if span is not None and (src is None or not src.text or span not in src.text):
            span = None
        rec = recorded_at or (src.received_at if src is not None else valid_at)
        if rec is None:
            raise ValueError(f"no recorded_at for {subject} {field}")
        fid = _id(record, field)
        n = 1
        while fid in self.ids:
            n += 1
            fid = _id(record, field, str(n))
        self.ids.add(fid)
        self.out.append(Fact(id=fid, source_id=sid, subject=subject, field=field,
                             value=_jsonable(value), span=span, extractor=EXTRACTOR, extract_conf=1.0,
                             valid_at=valid_at, recorded_at=rec, acl_tags=list(src.acl_tags) if src else []))


# ---------------------------------------------------------------- per-feed conversions
def _flights(b: _Builder, flight_ids: set[str] | None) -> None:
    occ = sorted((e for e in b.world.ops_log if e.kind == "occ"), key=lambda e: (e.at, e.id))
    for f in b.world.flights:
        if flight_ids is not None and f.id not in flight_ids:
            continue
        subj = f"flight:{f.id}"
        day = f.date.strftime("%d%b").upper()
        line, sched_src = None, None
        for sid, ls in b.lines().items():
            for ln in ls:
                if ln.startswith(f.number + " ") and day in ln and f"{f.origin}-{f.dest}" in ln:
                    line, sched_src = ln, b.source(sid)
                    break
            if line:
                break
        for field, value in (("flight.number", f.number), ("flight.date", f.date), ("flight.origin", f.origin),
                             ("flight.dest", f.dest), ("flight.sched_dep", f.sched_dep),
                             ("flight.sched_arr", f.sched_arr), ("flight.aircraft", f.aircraft),
                             ("flight.status", f.status), ("flight.actual_dep", f.actual_dep),
                             ("flight.actual_arr", f.actual_arr), ("flight.inbound_flight_id", f.inbound_flight_id),
                             ("flight.outbound_pair_id", f.outbound_pair_id),
                             ("flight.operating_carrier_eu", f.operating_carrier_eu)):
            b.add(f.id, subj, field, value, sched_src, span=line)
        man = b.source(f"SRC-MANIFEST-{f.id}")
        b.add(f.id, subj, "flight.pax", f.pax, man or sched_src,
              span=b.span_in(man, f"BOOKED {f.pax}") if man else b.span_in(sched_src, f"PAX {f.pax}"))
        listed = [e for e in occ if f.id in e.flight_ids]
        if f.ops_cause_code is not None:
            e = listed[0] if listed else None
            s = b.source(f"SRC-{e.id}") if e else None
            b.add(f.id, subj, "flight.ops_cause_code", f.ops_cause_code, s or sched_src,
                  span=b.span_in(s, f"RSN {f.ops_cause_code}"), valid_at=e.at if e else None)
        if listed and f.status == "cancelled":
            e = listed[0]
            s = b.source(f"SRC-{e.id}")
            b.add(f.id, subj, "flight.cancelled_by_occ", f.status == "cancelled", s,
                  span=b.span_in(s, "CNL"), valid_at=e.at)
        if f.notified_at is not None:
            e = next((x for x in listed if "IROPS SMS" in x.text), None)
            s = b.source(f"SRC-{e.id}") if e else None
            sp = None
            if s is not None:
                m = re.search(r"IROPS SMS \d{2}:\d{2}Z", s.text or "")
                sp = m.group(0) if m and m.group(0).endswith(f.notified_at.strftime("%H:%MZ")) else None
            b.add(f.id, subj, "flight.notified_at", f.notified_at, s if sp else sched_src, span=sp)


_AMOS_STAMP = re.compile(r"^\d{2}[A-Z]{3} \d{2}:\d{2}Z")
_MEL_DEFER = re.compile(r"MEL [\d-]+ CAT [A-D]( DEFERRED)?")


def _tech_log(b: _Builder, tails: set[str] | None) -> None:
    for e in sorted(b.world.tech_log, key=lambda e: (e.logged_at, e.id)):
        if tails is not None and e.aircraft not in tails:
            continue
        s = b.source(f"SRC-{e.id}")
        subj = f"aircraft:{e.aircraft}"
        m = _AMOS_STAMP.match(e.text)
        b.add(e.id, subj, "aog.tail", e.aircraft, s, span=b.span_in(s, e.aircraft), valid_at=e.logged_at)
        b.add(e.id, subj, "aog.logged_at", e.logged_at, s, span=m.group(0) if m else None, valid_at=e.logged_at)
        b.add(e.id, subj, "aog.ata_chapter", e.ata, s, span=b.span_in(s, f"ATA {e.ata}"), valid_at=e.logged_at)
        if e.mel_relief is not None:
            mel = _MEL_DEFER.search(e.text)
            b.add(e.id, subj, "aog.mel_relief", e.mel_relief, s,
                  span=b.span_in(s, "NO MEL RELIEF") if e.mel_relief is False else (mel.group(0) if mel else None),
                  valid_at=e.logged_at)
        b.add(e.id, subj, "aog.aog", e.aog, s, span=b.span_in(s, "A/C AOG") if e.aog else None, valid_at=e.logged_at)
        b.add(e.id, subj, "aog.station", e.station, s, valid_at=e.logged_at)
        if e.rts_est is not None:
            stamp = e.rts_est.strftime("%d%b").upper() + " " + e.rts_est.strftime("%H:%MZ")
            b.add(e.id, subj, "aog.rts_est", e.rts_est, s, span=b.span_in(s, f"RTS EST {stamp}"), valid_at=e.logged_at)
        b.add(e.id, subj, "aog.defect_text", e.text, s, span=e.text, valid_at=e.logged_at)


_ETA = re.compile(r"(?:\d{2}[A-Z]{3} )?ETA \d{2}:\d{2}Z")
_RTS = re.compile(r"RTS EST (?:\d{2}[A-Z]{3} )?\d{2}:\d{2}Z")
_STD_PLUS = re.compile(r"STD\+\d+h\d*")


def _ops_log(b: _Builder, flight_ids: set[str] | None) -> None:
    from .parse import ParseError, parse_duration_h, parse_time
    for e in sorted(b.world.ops_log, key=lambda e: (e.at, e.id)):
        if e.kind == "occ":
            continue                      # OCC codes are emitted per flight (flight.ops_cause_code)
        targets = [f for f in e.flight_ids if flight_ids is None or f in flight_ids]
        s = b.source(f"SRC-{e.id}")
        for fid in targets:
            subj = f"flight:{fid}"
            rec = ops_record(e.id, fid)
            if e.kind == "mcc":
                b.add(rec, subj, "mcc.text", e.text, s, span=e.text, valid_at=e.at)
                m = _ETA.search(e.text)
                eta = None
                if m:
                    try:
                        eta = parse_time(m.group(0), e.at, not_before=e.at)
                    except ParseError:
                        eta = None
                    b.add(rec, subj, "mcc.part_eta", eta, s, span=m.group(0), valid_at=e.at)
                r = _RTS.search(e.text)
                if r:
                    day = eta or e.at              # "ETA 14:00Z, RTS EST 20:00Z": the RTS is on the ETA's day
                    try:
                        rts = parse_time(r.group(0), day, not_before=day)
                    except ParseError:
                        rts = None
                    b.add(rec, subj, "mcc.rts_est", rts, s, span=r.group(0), valid_at=day)
            else:
                b.add(rec, subj, "spare.text", e.text, s, span=e.text, valid_at=e.at)
                m = _STD_PLUS.search(e.text)
                if m:
                    try:
                        b.add(rec, subj, "spare.available_within_h", parse_duration_h(m.group(0)), s,
                              span=m.group(0), valid_at=e.at)
                    except ParseError:
                        pass


def _metar(b: _Builder, stations: set[str] | None) -> None:
    seen: set[tuple[str, str]] = set()
    for key in sorted(b.world.metar):
        s = b.source(f"SRC-METAR-{key}")
        for o in b.world.metar[key]:
            if stations is not None and o.station not in stations:
                continue
            k = (o.station, o.raw)
            if k in seen:
                continue
            seen.add(k)
            _metar_obs(b, o, s)


def _metar_obs(b: _Builder, o: MetarObs, s: Source | None) -> None:
    rec = metar_record(o)
    subj = f"station:{o.station}"
    kw = dict(span=o.raw, valid_at=o.valid, recorded_at=o.valid + timedelta(minutes=5))
    for field, value in (("metar.sknt", o.sknt), ("metar.gust_kt", o.gust), ("metar.drct", o.drct),
                         ("metar.vsby_sm", o.vsby_sm), ("metar.wxcodes", o.wxcodes), ("metar.raw", o.raw)):
        b.add(rec, subj, field, value, s, **kw)


def _coupons(b: _Builder, flight_ids: set[str] | None) -> set[str]:
    elections = {e.coupon_id: e for e in b.world.elections}
    rows: dict[str, dict[str, str]] = {}
    kept: set[str] = set()
    for c in b.world.coupons:
        if flight_ids is not None and c.flight_id not in flight_ids:
            continue
        kept.add(c.id)
        sid = f"SRC-PSS-{c.flight_id}"
        s = b.source(sid)
        if sid not in rows:
            rows[sid] = {ln.split(",", 1)[0]: ln for ln in (s.text or "").splitlines()} if s and s.text else {}
        row = rows[sid].get(c.id)
        subj = f"coupon:{c.id}"
        for field, value in (("coupon.flight_id", c.flight_id), ("coupon.pnr", c.pnr), ("coupon.pax_ref", c.pax_ref),
                             ("coupon.fare_cents", c.fare_cents), ("coupon.taxes_cents", c.taxes_cents),
                             ("coupon.channel", c.channel), ("coupon.fare_type", c.fare_type),
                             ("coupon.lead_booker", c.lead_booker)):
            b.add(c.id, subj, field, value, s, span=row)
        e = elections.get(c.id)
        if e is not None:
            for field, value in (("pax.election", e.kind), ("pax.new_arrival", e.new_arrival),
                                 ("pax.arrival_delay_min", e.arrival_delay_min),
                                 ("pax.election_recorded_by", e.recorded_by)):
                b.add(c.id, subj, field, value, s, span=row)
    for sid, s in sorted(b.src.items()):
        if not sid.startswith("SRC-PSS-") or not s.text:
            continue
        fid = sid[len("SRC-PSS-"):]
        if flight_ids is not None and fid not in flight_ids:
            continue
        m = re.search(r"EARLIEST REROUTE OFFERED: [^\n]+", s.text)
        if m:
            b.add(f"{fid}:reroute", f"flight:{fid}", "pax.reroute_earliest_offered", True, s, span=m.group(0))
    return kept


_EUR_SPAN = re.compile(r"EUR\s?\d[\d,.]*|€\s?\d[\d,.]*")


def _crm(b: _Builder, coupons: set[str] | None) -> None:
    from .parse import ParseError, parse_eur
    for e in sorted(b.world.crm, key=lambda e: (e.at, e.id)):
        if coupons is not None and e.coupon_id not in coupons:
            continue
        s = b.source(f"SRC-{e.id}")
        subj = f"coupon:{e.coupon_id}"
        amt_span = None
        for m in _EUR_SPAN.finditer(e.text):
            try:
                if parse_eur(m.group(0)) == e.amount_cents:
                    amt_span = m.group(0)
                    break
            except ParseError:
                continue
        kw = dict(valid_at=e.at)
        if e.kind in ("refund_initiated", "bsp_refund", "chargeback", "voucher_issued", "care_issued"):
            b.add(e.id, subj, f"crm.{e.kind}", e.amount_cents, s, span=amt_span, **kw)
        elif e.kind == "rights_email_sent":
            b.add(e.id, subj, "crm.rights_email_sent", e.text, s, span=e.text, **kw)
        elif e.kind == "voucher_in_lieu_of_compensation":
            b.add(e.id, subj, "voucher.in_lieu", True, s, span=b.span_in(s, "IN LIEU OF COMPENSATION"), **kw)
            b.add(e.id, subj, "voucher.amount_cents", e.amount_cents, s, span=amt_span, **kw)
            signed = e.signed_acceptance_sha256 is not None
            b.add(e.id, subj, "voucher.signed", signed, s,
                  span=b.span_in(s, "SIGNATURE: NOT CAPTURED") if not signed else None, **kw)
            if signed:
                b.add(e.id, subj, "voucher.signed_acceptance_sha256", e.signed_acceptance_sha256, s, **kw)
            if "ACCEPTED" in e.text.upper():
                b.add(e.id, subj, "voucher.accepted", True, s, span=b.span_in(s, "PAX ACCEPTED"), **kw)
            b.add(e.id, subj, "voucher.issued_by", e.actor, s, **kw)


def _claims(b: _Builder, coupons: set[str] | None) -> None:
    from .parse import ParseError, parse_disputed, parse_eur
    for c in sorted(b.world.claims, key=lambda c: (c.received_at, c.id)):
        if coupons is not None and c.coupon_id not in coupons:
            continue
        s = b.source(f"SRC-{c.id}")
        subj = f"claim:{c.id}"
        kw = dict(valid_at=c.received_at)
        amt_span = None
        for m in re.finditer(r"(?:EUR|€)\s?\d[\d,.]*", c.text):
            try:
                if parse_eur(m.group(0)) == c.amount_claimed_cents:
                    amt_span = m.group(0)
                    break
            except ParseError:
                continue
        for field, value in (("claim.coupon_id", c.coupon_id), ("claim.received_at", c.received_at),
                             ("claim.channel", c.channel), ("claim.agency", c.agency), ("claim.authority", c.authority),
                             ("claim.pnr_scope", c.pnr_scope), ("claim.regime", c.currency_regime)):
            b.add(c.id, subj, field, value, s, **kw)
        b.add(c.id, subj, "claim.amount_claimed_cents", c.amount_claimed_cents, s, span=amt_span, **kw)
        m = re.search(r"I never agreed[^.]*", c.text, re.IGNORECASE)
        if m:
            try:
                b.add(c.id, subj, "claim.voucher_disputed", parse_disputed(m.group(0)), s, span=m.group(0), **kw)
            except ParseError:
                pass


def _care(b: _Builder, flight_ids: set[str] | None) -> None:
    for c in b.world.care:
        if flight_ids is not None and c.flight_id not in flight_ids:
            continue
        hit = b.finance_row(c.id)
        s = b.source(hit[0]) if hit else None
        subj = f"care:{c.id}"
        for field, value in (("care.flight_id", c.flight_id), ("care.kind", c.kind), ("care.amount_cents", c.amount_cents),
                             ("care.vendor", c.vendor), ("care.invoiced", c.invoiced)):
            b.add(c.id, subj, field, value, s, span=hit[1] if hit else None, valid_at=c.at)


def _cohorts(b: _Builder) -> None:
    for ob in b.world.opening_balances:
        s = next((x for x in b.world.sources if x.kind.value == "finance" and x.text and ob.cohort in x.text), None)
        line = next((ln for ln in (s.text or "").splitlines() if ob.cohort in ln), None) if s else None
        subj = f"cohort:{ob.cohort}"
        rec = cohort_record(ob.cohort, ob.account)
        claimed_pct = round(ob.claimed_cents / ob.entitlement_cents, 4) if ob.entitlement_cents else None
        for field, value in (("cohort.account", ob.account), ("cohort.entitlement_cents", ob.entitlement_cents),
                             ("cohort.claimed_cents", ob.claimed_cents), ("cohort.claimed_pct", claimed_pct),
                             ("cohort.balance_cents", ob.balance_cents), ("cohort.curve_segment", ob.curve_segment),
                             ("cohort.as_of", ob.as_of)):
            b.add(rec, subj, field, value, s, span=line, valid_at=ob.as_of)
        if line:
            m = re.search(r"LAST CLAIM (\d{4}-\d{2}-\d{2})", line)
            if m:
                b.add(rec, subj, "cohort.last_claim_at", m.group(1), s, span=m.group(0), valid_at=ob.as_of)


_CTX_FIELDS = {"storm_name": "storm.name", "eurocontrol_departures": "storm.eurocontrol_departures",
               "normal_departures": "storm.normal_departures",
               "reported_cancellations_dep": "storm.reported_cancellations_dep",
               "reported_cancellations_arr": "storm.reported_cancellations_arr", "red_warning": "storm.red_warning",
               "orange_warning": "storm.orange_warning", "peak_gust_kt": "storm.peak_gust_kt"}


def _context(b: _Builder) -> None:
    for storm, ctx in sorted(b.world.real_context.items()):
        s = b.source(f"SRC-REALCTX-{storm}")
        for k, field in _CTX_FIELDS.items():
            if k in ctx:
                b.add(f"CTX-{storm}", f"storm:{storm}", field, ctx[k], s, span=b.span_in(s, f"{k}: {ctx[k]}"))


# ---------------------------------------------------------------- public API
def world_to_facts(world: World, *, flight_ids: Iterable[str] | None = None, include_metar: bool = True) -> list[Fact]:
    """Every fact in the world (or only those about `flight_ids`: their flights, coupons, CRM, claims, care, logs,
    tails and the METAR of their airports). Deterministic order and ids."""
    b = _Builder(world)
    fids = set(flight_ids) if flight_ids is not None else None
    _flights(b, fids)
    tails = None
    stations = None
    if fids is not None:
        fl = [f for f in world.flights if f.id in fids]
        tails = {f.aircraft for f in fl}
        icao = {a.iata: a.icao for a in world.airports}
        stations = {icao.get(c, c) for f in fl for c in (f.origin, f.dest)}
    _tech_log(b, tails)
    _ops_log(b, fids)
    if include_metar:
        _metar(b, stations)
    kept = _coupons(b, fids)
    _crm(b, kept if fids is not None else None)
    _claims(b, kept if fids is not None else None)
    _care(b, fids)
    if fids is None:
        _cohorts(b)
        _context(b)
    return b.out


def resolve(facts: Iterable[Fact], sources: Iterable[Source] | dict[str, Source],
            known_at: datetime | None = None) -> dict[tuple[str, str], Fact]:
    """Plan §2 rule 7: keep facts with recorded_at ≤ known_at; per (subject, field) the lowest trust tier number
    wins, then the latest recorded_at (then valid_at, then id, for determinism)."""
    src = sources if isinstance(sources, dict) else {s.id: s for s in sources}
    best: dict[tuple[str, str], tuple[tuple, Fact]] = {}
    for f in facts:
        if known_at is not None and f.recorded_at > known_at:
            continue
        s = src.get(f.source_id)
        tier = s.trust_tier if s is not None else 2
        far_past = datetime.min.replace(tzinfo=f.recorded_at.tzinfo)
        key = (-tier, f.recorded_at, f.valid_at or far_past, f.id)
        k = (f.subject, f.field)
        if k not in best or key > best[k][0]:
            best[k] = (key, f)
    return {k: v[1] for k, v in best.items()}


def by_subject(facts: Iterable[Fact]) -> dict[str, list[Fact]]:
    out: dict[str, list[Fact]] = {}
    for f in facts:
        out.setdefault(f.subject, []).append(f)
    return out
