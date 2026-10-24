"""F3b · Passengers, elections, CRM, BSP, claims and care for every cancelled Northstar flight.

Formats follow the golden world (`contracts/fixtures/golden/world.json`): coupon ids `<flight id>:<seat>`, a
`SRC-PSS-<flight>` CSV and a `SRC-MANIFEST-<flight>` line per cancelled flight, CRM/BSP/claim records with a raw
`SRC-<record id>` document each, care accrual rows (invoiced=false) and their vendor invoices (invoiced=true).

Ground truth per coupon (`coupon_truth`) is computed from the flight's *latent* truth and the coupon's own facts,
never from the engine. Claims are drawn from €-based segment curves with a quota per cohort × segment, so the
generated history reproduces `curves.json` to within half a coupon per point.
"""
from __future__ import annotations

import hashlib
import json
import random
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from contracts.models import CareCost, Claim, Coupon, CrmEvent, Election, Flight, Source, SourceKind
from world import network as N
from world import texts as T
from world.airports import airport, band_eur, distance_km

ROOT = Path(__file__).resolve().parent.parent
CURVES_PATH = ROOT / "contracts" / "fixtures" / "golden" / "curves.json"
SEGMENT = {600: "long_haul_gt3500", 400: "medium_1500_3500", 250: "short_le1500"}
REDUCTION_LIMIT_MIN = {250: 120, 400: 180, 600: 240}      # Art. 7(2)(a)-(c)
CLAIMS_HORIZON = datetime(2026, 7, 1, tzinfo=UTC)        # the claims extract is cut here
ELECTION_MIX = (("reaccommodated_own", 0.64), ("refund", 0.19), ("reroute_partner", 0.09), ("voucher", 0.08))
CHANNEL_MIX = (("direct", 0.70), ("ota", 0.20), ("agency_gds", 0.10))
P_STAFF = 0.01
P_IN_LIEU = 0.03            # service-desk vouchers in lieu of compensation, per coupon on a cancelled flight
P_IN_LIEU_SIGNED = 0.6
P_WEATHER_CLAIM = 0.04      # passengers who claim anyway on extraordinary cancellations (rejected)
P_AGENCY = 0.30
P_OVERNIGHT_OF_M1 = 0.35
UK_ROUTES = frozenset({"LHR", "LGW", "MAN", "EDI", "BHX", "GLA"})
FARE_RANGE = {250: (45, 260, 18, 40), 400: (90, 380, 25, 55), 600: (280, 950, 60, 130)}   # € fare lo/hi, tax lo/hi
PNR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def rng_for(seed: int, *key: object) -> random.Random:
    return random.Random(":".join([str(seed), *map(str, key)]))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H%MZ")


def pick(r: random.Random, mix: tuple[tuple[str, float], ...]) -> str:
    u, acc = r.random(), 0.0
    for k, p in mix:
        acc += p
        if u < acc:
            return k
    return mix[-1][0]


def eur(cents: int) -> str:
    return f"EUR {cents / 100:,.2f}"


# ---------------------------------------------------------------- curves

@lru_cache(maxsize=1)
def curve_points() -> dict[str, list[tuple[int, float]]]:
    """Cumulative € claim rate by development month, per segment (golden curves.json; plan defaults if absent)."""
    lh = [(1, 0.09), (3, 0.17), (6, 0.24), (12, 0.29), (18, 0.32)]
    out = {"long_haul_gt3500": lh,
           "medium_1500_3500": [(m, round(r * 27 / 35, 4)) for m, r in lh],
           "short_le1500": [(m, round(r * 20 / 35, 4)) for m, r in lh]}
    try:
        data = json.loads(CURVES_PATH.read_text())
        for c in data.get("curves", []):
            out[c["segment"]] = [(int(m), float(r)) for m, r in c["points"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return out


def month_end(y: int, m: int) -> datetime:
    return datetime(y, m, monthrange(y, m)[1], 23, 59, 59, tzinfo=UTC)


def dev_month_end(event: date, k: int) -> datetime:
    """Month-end of development month k: M1 = the first month-end at least 28 days after the event."""
    first = event + timedelta(days=28)
    y, m = first.year, first.month + (k - 1)
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return month_end(y, m)


def dev_month(event: date, t: datetime) -> int:
    """Smallest k with t <= month-end of M_k (0 never: claims before M1's month-end are M1)."""
    k = 1
    while t > dev_month_end(event, k):
        k += 1
    return k


# ---------------------------------------------------------------- truth

def coupon_truth(flight: Flight, ftruth: dict[str, Any], coupon: Coupon, election: Election | None,
                 in_lieu: CrmEvent | None, distances: dict[str, float] | None = None) -> dict[str, Any]:
    """True entitlement and correct handling for one coupon (EU261 as Northstar's rulings apply it)."""
    other = flight.dest if flight.origin == N.HUB else flight.origin
    km = (distances or {}).get(f"{N.HUB}-{other}") or distance_km(flight.origin, flight.dest)
    band = _band(flight.origin, flight.dest, km)
    t: dict[str, Any] = {"flight_id": flight.id, "band_eur": band, "segment": SEGMENT[band],
                         "compensation_cents": 0, "voucher_offset_cents": 0, "reduction": "none",
                         "refund_due": bool(election and election.kind == "refund"), "care_due": True}
    if coupon.fare_type == "staff_id90":
        t.update(status="staff_ticket", handling="no_compensation_staff_ticket", care_due=False,
                 article="Art.3(3)")
        return t
    if flight.notified_at is not None and (flight.sched_dep - flight.notified_at) >= timedelta(days=14):
        t.update(status="exempt_notice", handling="no_compensation_notice_14d", article="Art.5(1)(c)(i)")
        return t
    if ftruth.get("extraordinary") == "extraordinary":
        t.update(status="no_compensation", handling="refund_and_care_only", article="Art.5(3)")
        return t
    comp = band * 100
    if election is not None and election.kind in ("reroute_partner", "reaccommodated_own") \
            and election.arrival_delay_min is not None and election.arrival_delay_min <= REDUCTION_LIMIT_MIN[band]:
        comp //= 2
        t["reduction"] = "art7_2_50pct"
    offset, handling = 0, "pay_cash"
    if in_lieu is not None:
        if in_lieu.signed_acceptance_sha256:
            offset = min(in_lieu.amount_cents, comp)
            handling = "pay_net_of_signed_voucher" if offset < comp else "settled_in_kind"
        else:
            handling = "pay_cash_voucher_stays_goodwill"     # Art. 7(3): no signed acceptance, no offset (R-CL-1)
    t.update(status="owed", compensation_cents=comp, voucher_offset_cents=offset, handling=handling,
             article="Art.7(1)", pay_cents=comp - offset)
    return t


def _band(a: str, b: str, km: float) -> int:
    if km <= 1500:
        return 250
    if (airport(a).eu and airport(b).eu) or km <= 3500:
        return 400
    return 600


# ---------------------------------------------------------------- per flight

@dataclass
class PaxOutput:
    coupons: list[Coupon] = field(default_factory=list)
    elections: list[Election] = field(default_factory=list)
    crm: list[CrmEvent] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    care: list[CareCost] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    coupon_truth: dict[str, dict[str, Any]] = field(default_factory=dict)
    claim_truth: dict[str, dict[str, Any]] = field(default_factory=dict)
    in_lieu: dict[str, CrmEvent] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)      # coupon id -> passenger name (PII, sources only)


def seats(n: int) -> list[str]:
    out: list[str] = []
    row = 1
    while len(out) < n:
        out += [f"{row}{c}" for c in "ABCDEF"]
        row += 1
    return out[:n]


def _src(out: PaxOutput, sid: str, kind: SourceKind, title: str, text: str, at: datetime, tier: int,
         tags: list[str]) -> None:
    out.sources.append(Source(id=sid, kind=kind, title=title, text=text, sha256=sha(text), received_at=at,
                              trust_tier=tier, acl_tags=tags))


def _uniq(existing: set[str], base: str) -> str:
    i, cid = 1, base
    while cid in existing:
        i += 1
        cid = f"{base}-{i}"
    existing.add(cid)
    return cid


class FlightPax:
    """Coupons, elections, CRM and care for one cancelled flight."""

    def __init__(self, seed: int, flight: Flight, ftruth: dict[str, Any], out: PaxOutput, ids: set[str],
                 distances: dict[str, float] | None = None) -> None:
        self.seed, self.f, self.ft, self.out, self.ids = seed, flight, ftruth, out, ids
        self.r = rng_for(seed, "pax", flight.id)
        self.distances = distances
        other = flight.dest if flight.origin == N.HUB else flight.origin
        km = (distances or {}).get(f"{N.HUB}-{other}") or distance_km(flight.origin, flight.dest)
        self.band = _band(flight.origin, flight.dest, km)
        self.weather_coded = flight.ops_cause_code in ("71", "72")
        self.template_sent = False
        self.cancel_known = flight.notified_at or flight.sched_dep - timedelta(hours=2)

    def run(self) -> None:
        f, r = self.f, self.r
        labels = seats(f.pax)
        flo, fhi, tlo, thi = FARE_RANGE[self.band]
        i = 0
        staff = 0
        while i < len(labels):
            size = min(len(labels) - i, 1 + (r.random() < 0.5) + (r.random() < 0.25) + (r.random() < 0.1))
            pnr = "".join(r.choice(PNR_ALPHABET) for _ in range(6))
            channel = pick(r, CHANNEL_MIX)
            fare_type = "staff_id90" if r.random() < P_STAFF else "revenue"
            fare = r.randint(flo, fhi) * 100 if fare_type == "revenue" else r.randint(2, 6) * 1000
            tax = r.randint(tlo, thi) * 100
            elect = pick(r, ELECTION_MIX)
            for j in range(size):
                seat = labels[i + j]
                cid = f"{f.id}:{seat}"
                c = Coupon(id=cid, pnr=pnr, pax_ref="PAX-" + sha(f"{self.seed}:{cid}")[:10].upper(),
                           flight_id=f.id, fare_cents=fare, taxes_cents=tax, channel=channel, fare_type=fare_type,
                           lead_booker=(j == 0 and size > 1))
                staff += fare_type == "staff_id90"
                self.out.coupons.append(c)
                self.out.names[cid] = T.name(r)
                e = self._election(c, elect if r.random() < 0.85 else pick(r, ELECTION_MIX))
                self.out.elections.append(e)
                self._crm(c, e)
            i += size
        num, day = f.number, f.date.strftime("%d%b").upper()
        _src(self.out, f"SRC-MANIFEST-{f.id}", SourceKind.MANIFEST, f"Manifest {num}/{f.date}",
             f"MANIFEST {num}/{day} {f.origin}-{f.dest} {f.aircraft} BOOKED {f.pax} · INF 0 · STAFF {staff} · "
             f"STATUS CNL\n", f.sched_dep - timedelta(hours=3), 2, ["ops"])
        self._care()

    def _election(self, c: Coupon, kind: str) -> Election:
        f, r = self.f, self.r
        if kind in ("refund", "voucher"):
            by = "crm-bot" if (kind == "refund" and c.channel == "direct") else ("web" if r.random() < 0.7
                                                                                else "call-centre")
            return Election(coupon_id=c.id, kind=kind, recorded_by=by)  # type: ignore[arg-type]
        limit = REDUCTION_LIMIT_MIN[self.band]
        if kind == "reroute_partner":
            delay = r.randint(60, limit) if r.random() < 0.55 else r.randint(limit + 1, limit + 300)
            by = "service-desk"
        else:
            u = r.random()
            if u < 0.08:
                delay = r.randint(45, limit)
            elif u < 0.3:
                delay = r.randint(limit + 1, 600)
            else:
                delay = r.randint(1000, 3000 if self.band == 600 else 1800)
            by = "occ"
        delay = int(round(delay / 5) * 5)
        return Election(coupon_id=c.id, kind=kind, new_arrival=f.sched_arr + timedelta(minutes=delay),  # type: ignore[arg-type]
                        arrival_delay_min=delay, recorded_by=by)  # type: ignore[arg-type]

    def _crm(self, c: Coupon, e: Election) -> None:
        f, r = self.f, self.r
        seat = c.id.rsplit(":", 1)[1]
        day = f.date.strftime("%d%b").upper()
        amount = c.fare_cents + c.taxes_cents
        if e.kind == "refund" and c.channel == "direct":
            at = (self.cancel_known + timedelta(minutes=r.randint(5, 240))).replace(second=0, microsecond=0)
            rid = _uniq(self.ids, f"CRM-BOT-{f.number}-{seat}-{stamp(at)}")
            rsn = "WX CNL" if self.weather_coded else "CNL"
            self._event(rid, c, at, "refund_initiated", amount, "agent.crm_bot",
                        f"REFUND INITIATED {f.number}/{day} {seat} PNR {c.pnr} {eur(amount)} TO ORIGINAL FOP · RSN {rsn}",
                        "crm", 3, ["finance"], source=False)
            mid = _uniq(self.ids, f"CRM-BOT-MAIL-{f.number}-{seat}-{stamp(at)}")
            if self.weather_coded:
                txt = (f"Your flight {f.number} on {f.date.strftime('%d %b').lstrip('0')} was cancelled due to "
                       f"weather (extraordinary circumstances). No compensation is payable under EU261. Your "
                       f"refund of {eur(amount)} has been initiated.")
            else:
                txt = (f"Your flight {f.number} on {f.date.strftime('%d %b').lstrip('0')} was cancelled. Your "
                       f"refund of {eur(amount)} has been initiated. You may be entitled to compensation under "
                       "EU261 Art. 7.")
            self._event(mid, c, at, "rights_email_sent", 0, "agent.crm_bot", txt, "crm", 3, ["pii"], source=False)
            if not self.template_sent:
                self.template_sent = True
                tpl = "IROPS_WX_REFUND_v3" if self.weather_coded else "IROPS_REFUND_v3"
                body = txt.replace(eur(amount), "EUR {{amount}}")
                _src(self.out, f"SRC-EMAIL-CRM-BOT-TEMPLATE-{f.number}-{stamp(at)}", SourceKind.EMAIL,
                     f"CRM bot email template used {T.hhmmz(at)} ({f.number})",
                     f"TEMPLATE {tpl} · sent by agent.crm_bot · {at:%d %b %Y} {T.hhmmz(at)}\n\n"
                     f"Dear {{{{first_name}}}},\n\n{body}\n\nNorthstar Air\n", at, 3, ["ops"])
        elif e.kind == "refund":
            at = (self.cancel_known + timedelta(days=r.randint(1, 9), minutes=r.randint(0, 600))).replace(
                second=0, microsecond=0)
            rid = _uniq(self.ids, f"BSP-{f.number}-{seat}-{stamp(at)}")
            agent = f"{r.randint(10, 99)}-{r.randint(1, 9)} {r.randint(1000, 9999)} {r.randint(1, 9)}"
            self._event(rid, c, at, "bsp_refund", amount, f"bsp:agent-{agent.replace(' ', '-')}",
                        f"BSP RFND TKT 220-{r.randint(10**7, 10**8 - 1)} {f.number}/{day} {seat} {eur(amount)} "
                        f"AGT {agent}", "bsp", 2, ["finance"])
        elif e.kind == "voucher":
            at = (self.cancel_known + timedelta(minutes=r.randint(30, 600))).replace(second=0, microsecond=0)
            rid = _uniq(self.ids, f"CRM-VCH-{f.number}-{seat}-{stamp(at)}")
            self._event(rid, c, at, "voucher_issued", amount, "web",
                        f"REFUND VOUCHER ISSUED {f.number}/{day} {seat} {eur(amount)} VALID 12M", "crm", 3, ["finance"],
                        source=False)
        if c.fare_type == "revenue" and r.random() < P_IN_LIEU:
            self.in_lieu(c, signed=r.random() < P_IN_LIEU_SIGNED)

    def in_lieu(self, c: Coupon, *, signed: bool, amount: int | None = None) -> CrmEvent:
        f, r = self.f, self.r
        seat = c.id.rsplit(":", 1)[1]
        at = (max(self.cancel_known, f.sched_dep - timedelta(hours=2)) + timedelta(minutes=r.randint(10, 300))
              ).replace(second=0, microsecond=0)
        amt = amount if amount is not None else min(self.band, r.choice([100, 150, 200, 250, 300])) * 100
        desk = f"service-desk:{'T2' if f.origin == N.HUB else f.origin}-{r.randint(1, 9):02d}"
        sig = sha(f"signed-acceptance:{c.id}:{at.isoformat()}") if signed else None
        text = f"EUR{amt // 100} VOUCHER IN LIEU OF COMPENSATION - PAX ACCEPTED"
        if signed:
            text += f" · SIGNED FORM ART7(3) REF SF-{sig[:8].upper()}"
        rid = _uniq(self.ids, f"CRM-{f.number}-{seat}-{stamp(at)}")
        ev = self._event(rid, c, at, "voucher_in_lieu_of_compensation", amt, desk, text, "crm", 3, ["pii"],
                         signed=sig)
        self.out.in_lieu[c.id] = ev
        return ev

    def _event(self, rid: str, c: Coupon, at: datetime, kind: str, amount: int, actor: str, text: str,
               src_kind: str, tier: int, tags: list[str], signed: str | None = None, source: bool = True) -> CrmEvent:
        ev = CrmEvent(id=rid, coupon_id=c.id, at=at, kind=kind, amount_cents=amount,  # type: ignore[arg-type]
                      signed_acceptance_sha256=signed, actor=actor, text=text)
        self.out.crm.append(ev)
        if source:
            _src(self.out, f"SRC-{rid}", SourceKind(src_kind), f"{kind} · {c.id}", text + "\n",
                 at + timedelta(minutes=1), tier, tags)
        return ev

    def _care(self) -> None:
        f, r = self.f, self.r
        n = f.pax
        station = f.origin
        hotel_pax = int(n * (0.55 if self.band != 250 or f.sched_dep.hour >= 12 else 0.35))
        rows = {"hotel": hotel_pax * r.randint(85, 140) * 100 // 1,
                "meal": n * r.randint(12, 18) * 100,
                "transport": hotel_pax * r.randint(15, 30) * 100}
        vendors = {"hotel": f"{airport(station).name.replace(' Airport', '')} Airport Hotel (simulated)",
                   "meal": "Terminal meal voucher scheme (simulated)", "transport": "Northstar ground transport pool"}
        acc_at = datetime.combine(f.sched_dep.date(), datetime.min.time(), UTC) + timedelta(hours=22)
        inv_at = acc_at + timedelta(days=r.randint(18, 30), hours=-10)
        for kind, amt in rows.items():
            self.out.care.append(CareCost(id=f"CARE-ACC-{f.id}-{kind}", flight_id=f.id, kind=kind,  # type: ignore[arg-type]
                                          amount_cents=amt, vendor=vendors[kind], at=acc_at, invoiced=False))
            inv = int(amt * (0.94 + 0.08 * r.random()))
            self.out.care.append(CareCost(id=f"CARE-INV-{f.id}-{kind}", flight_id=f.id, kind=kind,  # type: ignore[arg-type]
                                          amount_cents=inv, vendor=vendors[kind], at=inv_at, invoiced=True))


# ---------------------------------------------------------------- claims per cohort

@dataclass
class ClaimSpec:
    coupon: Coupon
    flight: Flight
    at: datetime
    channel: str = "direct"
    agency: str | None = None
    authority: str | None = None
    regime: str = "EU261"
    amount_cents: int | None = None
    pnr_scope: str = "coupon"
    text: str | None = None
    valid: bool = True
    pay_cents: int = 0
    reason: str = "valid"
    planted: list[str] = field(default_factory=list)


def claim_record(out: PaxOutput, spec: ClaimSpec, ids: set[str], r: random.Random) -> Claim:
    f, c = spec.flight, spec.coupon
    seat = c.id.rsplit(":", 1)[1]
    at = spec.at.replace(second=0, microsecond=0)
    cid = _uniq(ids, f"CLM-{f.number}-{seat}-{stamp(at)}")
    other = f.dest if f.origin == N.HUB else f.origin
    band = _band(f.origin, f.dest, distance_km(N.HUB, other))
    amount = spec.amount_cents if spec.amount_cents is not None else (
        22000 if spec.regime == "UK261" else band * 100)
    who = out.names.get(c.id) or T.name(r)
    text = spec.text or T.claim_text(r, who=who, flight_number=f.number, day=f.date.strftime("%d %B %Y"),
                                     coupon_ref=f"{c.pnr} seat {seat}", amount_eur=amount // 100,
                                     channel=spec.channel, agency=spec.agency, authority=spec.authority,
                                     regime=spec.regime, pnr_scope=spec.pnr_scope)
    claim = Claim(id=cid, coupon_id=c.id, received_at=at, channel=spec.channel, agency=spec.agency,  # type: ignore[arg-type]
                  authority=spec.authority, pnr_scope=spec.pnr_scope, amount_claimed_cents=amount,  # type: ignore[arg-type]
                  currency_regime=spec.regime, text=text)  # type: ignore[arg-type]
    out.claims.append(claim)
    _src(out, f"SRC-{cid}", SourceKind.CLAIM, f"EU261 claim · {f.number} {seat}", text + "\n", at, 4, ["pii"])
    out.claim_truth[cid] = {"coupon_id": c.id, "valid": spec.valid, "pay_cents": spec.pay_cents if spec.valid else 0,
                            "covers": [c.id] if spec.valid else [], "reason": spec.reason,
                            "planted": list(spec.planted), "dev_month": dev_month(f.date, at)}
    return claim


def quota_claim_times(event: date, coupons: list[tuple[Coupon, int]], segment: str,
                      r: random.Random) -> list[tuple[Coupon, int, datetime]]:
    """Pick the claimants and their claim times so that cumulative € claimed by each curve point is as close as
    possible to rate(point) × entitlement (to within half a coupon). `coupons` = (coupon, entitlement cents)."""
    pts = curve_points()[segment]
    total = sum(e for _, e in coupons)
    order = coupons[:]
    r.shuffle(order)
    out: list[tuple[Coupon, int, datetime]] = []
    cum = 0
    k_idx = 0
    prev_end = datetime.combine(event, datetime.min.time(), UTC) + timedelta(hours=18)
    for c, e in order:
        mid = cum + e / 2
        while k_idx < len(pts) and mid > pts[k_idx][1] * total:
            k_idx += 1
        if k_idx >= len(pts):
            break
        m = pts[k_idx][0]
        lo = prev_end if k_idx == 0 else dev_month_end(event, pts[k_idx - 1][0])
        hi = dev_month_end(event, m)
        if k_idx == 0 and r.random() < P_OVERNIGHT_OF_M1:
            at = prev_end + timedelta(minutes=r.randint(60, 12 * 60))        # the night after the storm
        else:
            at = lo + timedelta(seconds=r.randint(0, int((hi - lo).total_seconds())))
        cum += e
        if at < CLAIMS_HORIZON:
            out.append((c, e, at))
    return out
