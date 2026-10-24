"""Inline PSS-side scenario for F8b/F8c (IMPLEMENTATION_PLAN §1.3): coupons, elections, CRM, care, OCC, airports.

NS31 (172 coupons, fare €450 incl. YQ/YR + taxes €60):
  seats 1A–6B   32 refunds, all initiated by the CRM bot 06:02–09:40Z (direct-sold); BSP duplicate on 1A at 11:00Z
  seats 6C–8D   14 refund vouchers
  seats 8E–27D 112 reaccommodated on our own flights (14C among them: the €300 service-desk voucher in lieu)
  seats 27E–29F 14 partner reroutes via LHR (the 14 Art. 7(2) 50% coupons in helpers.make_ents)
NS100 (186 coupons, weather, fare €90 + taxes €30): 20 refunds elected with no payment yet, 166 reaccommodated.
Care: €227,000 accrued across NS31 and NS100; vendor invoices €221,300 in February.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from contracts.models import (
    Airport,
    CareCost,
    Coupon,
    CrmEvent,
    Election,
    Entitlement,
    Flight,
    FlightDecision,
    OpsLogEntry,
    World,
)

from .helpers import EOWYN, KNOCK_ONS, flight_id, make_decision, make_ents, make_flight, seats, ts

FARE, TAX = 45_000, 6_000
FARE100, TAX100 = 9_000, 3_000
NS31 = flight_id("NS31")
NS100 = flight_id("NS100")
SEATS31 = seats(172)
REFUND_SEATS = SEATS31[:32]
VOUCHER_SEATS = SEATS31[32:46]
REACC_SEATS = SEATS31[46:158]
REROUTE_SEATS = SEATS31[158:]
SEATS100 = seats(186)
C14 = f"{NS31}:14C"
SIG = "9f2c" + "0" * 60

AIRPORTS = [
    Airport(icao="EIDW", iata="DUB", name="Dublin", lat=53.4213, lon=-6.2701, country="IE", eu=True,
            tz="Europe/Dublin"),
    Airport(icao="KBOS", iata="BOS", name="Boston Logan", lat=42.3643, lon=-71.0052, country="US", eu=False,
            tz="America/New_York"),
    Airport(icao="EGLL", iata="LHR", name="London Heathrow", lat=51.4706, lon=-0.4619, country="GB", eu=False,
            tz="Europe/London"),
]

CARE = [  # (id, flight, kind, accrued, invoiced)
    ("CARE-NS31-HOTEL", NS31, "hotel", 12_000_000, 11_800_000),
    ("CARE-NS31-MEAL", NS31, "meal", 1_700_000, 1_650_000),
    ("CARE-NS31-TAXI", NS31, "transport", 2_000_000, 1_900_000),
    ("CARE-NS100-HOTEL", NS100, "hotel", 5_000_000, 4_900_000),
    ("CARE-NS100-MEAL", NS100, "meal", 2_000_000, 1_880_000),
]
assert sum(c[3] for c in CARE) == 22_700_000 and sum(c[4] for c in CARE) == 22_130_000


def operated(number: str, origin: str, dest: str, std: str) -> Flight:
    dep = ts(std)
    return Flight(id=flight_id(number), number=number, date=dep.date(), origin=origin, dest=dest, sched_dep=dep,
                  sched_arr=dep + timedelta(hours=1, minutes=20), aircraft="EI-NSX", status="operated", pax=180,
                  actual_dep=dep, actual_arr=dep + timedelta(hours=1, minutes=20))


def coupons_31() -> list[Coupon]:
    return [Coupon(id=f"{NS31}:{s}", pnr=f"P31{i:03d}", pax_ref=f"pax:NS31:{s}", flight_id=NS31, fare_cents=FARE,
                   taxes_cents=TAX, channel="agency_gds" if s in REROUTE_SEATS else "direct")
            for i, s in enumerate(SEATS31)]


def coupons_100() -> list[Coupon]:
    return [Coupon(id=f"{NS100}:{s}", pnr=f"P100{i:03d}", pax_ref=f"pax:NS100:{s}", flight_id=NS100,
                   fare_cents=FARE100, taxes_cents=TAX100) for i, s in enumerate(SEATS100)]


def elections_31() -> list[Election]:
    out = [Election(coupon_id=f"{NS31}:{s}", kind="refund", recorded_by="crm-bot") for s in REFUND_SEATS]
    out += [Election(coupon_id=f"{NS31}:{s}", kind="voucher", recorded_by="web") for s in VOUCHER_SEATS]
    out += [Election(coupon_id=f"{NS31}:{s}", kind="reaccommodated_own", arrival_delay_min=1500, recorded_by="occ")
            for s in REACC_SEATS]
    out += [Election(coupon_id=f"{NS31}:{s}", kind="reroute_partner", arrival_delay_min=220, recorded_by="occ")
            for s in REROUTE_SEATS]
    return out


def elections_100() -> list[Election]:
    return ([Election(coupon_id=f"{NS100}:{s}", kind="refund", recorded_by="web") for s in SEATS100[:20]]
            + [Election(coupon_id=f"{NS100}:{s}", kind="reaccommodated_own", arrival_delay_min=600,
                        recorded_by="occ") for s in SEATS100[20:]])


def bot_refunds_31() -> list[CrmEvent]:
    start = ts("2025-01-24T06:02:00Z")
    return [CrmEvent(id=f"CRM-REF-{i:03d}", coupon_id=f"{NS31}:{s}", at=start + timedelta(minutes=7 * i),
                     kind="refund_initiated", amount_cents=FARE + TAX, actor="agent.crm_bot",
                     text="Refund initiated: weather, no compensation.") for i, s in enumerate(REFUND_SEATS)]


def crm_event(eid: str, coupon: str, at: str, kind: str, amount: int = 0, signed: str | None = None,
              actor: str = "test") -> CrmEvent:
    return CrmEvent(id=eid, coupon_id=coupon, at=ts(at), kind=kind, amount_cents=amount,
                    signed_acceptance_sha256=signed, actor=actor, text=kind)


def in_lieu_14c(signed: str | None = None) -> CrmEvent:
    return crm_event("CRM-14C-VIL", C14, "2025-01-24T14:20:00Z", "voucher_in_lieu_of_compensation", 30_000,
                     signed=signed, actor="service-desk:T2")


def care_rows(invoices: bool = False) -> list[CareCost]:
    rows = [CareCost(id=cid, flight_id=fid, kind=kind, amount_cents=acc, vendor=f"vendor-{kind}",
                     at=ts("2025-01-24T21:00:00Z")) for cid, fid, kind, acc, _inv in CARE]
    if invoices:
        rows += invoice_rows()
    return rows


def invoice_rows(at: str = "2025-02-12T10:00:00Z") -> list[CareCost]:
    return [CareCost(id=cid.replace("CARE-", "INV-"), flight_id=fid, kind=kind, amount_cents=inv,
                     vendor=f"vendor-{kind}", at=ts(at), invoiced=True) for cid, fid, kind, _acc, inv in CARE]


def eowyn_world(*, ns100: bool = True, bsp_duplicate: bool = True, in_lieu_signed: str | None = None,
                in_lieu: bool = True, care: bool = True, invoices: bool = False, knock_ons: bool = False,
                extra_crm: list[CrmEvent] | None = None, extra_flights: list[Flight] | None = None,
                eurocontrol: int | None = 179, occ: bool = True) -> World:
    numbers = ["NS31"] + (["NS100"] if ns100 else []) + (KNOCK_ONS if knock_ons else [])
    flights = [make_flight(n) for n in numbers] + [operated("NS33", "DUB", "LHR", "2025-01-24T16:00:00Z"),
                                                   operated("NS35", "DUB", "LHR", "2025-01-24T17:10:00Z")]
    flights += extra_flights or []
    coupons = coupons_31() + (coupons_100() if ns100 else [])
    elections = elections_31() + (elections_100() if ns100 else [])
    crm = bot_refunds_31()
    if bsp_duplicate:
        crm.append(crm_event("CRM-BSP-DUP", f"{NS31}:1A", "2025-01-24T11:00:00Z", "bsp_refund", FARE + TAX,
                             actor="bsp"))
    if in_lieu:
        crm.append(in_lieu_14c(in_lieu_signed))
    crm += extra_crm or []
    cancelled = [f.id for f in flights if f.status == "cancelled"]
    ops_log = [OpsLogEntry(id="OCC-0512", at=ts("2025-01-24T05:12:00Z"), kind="occ", flight_ids=cancelled,
                           code="71", text="05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71.",
                           author="occ")] if occ else []
    return World(meta={"carrier": "Northstar Air"}, airports=AIRPORTS, flights=flights, tech_log=[], ops_log=ops_log,
                 coupons=coupons, elections=elections, crm=crm, claims=[],
                 care=care_rows(invoices) if care else [], metar={}, sources=[],
                 real_context={EOWYN: {"eurocontrol_departures": eurocontrol}} if eurocontrol is not None else {})


def eowyn(known_at: datetime, **kw) -> tuple[World, list[FlightDecision], list[Entitlement]]:
    world = eowyn_world(**kw)
    numbers = [f.number for f in world.flights if f.status == "cancelled" and f.number in
               {"NS31", "NS100", *KNOCK_ONS}]
    decisions = [make_decision(n, known_at) for n in numbers]
    ents = [e for n in numbers for e in make_ents(n)]
    return world, decisions, ents


def ent(coupon_id: str, ents: list[Entitlement]) -> Entitlement:
    return next(e for e in ents if e.coupon_id == coupon_id)
