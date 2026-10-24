"""Inline mini-world from IMPLEMENTATION_PLAN §1.2-1.4 (used until golden world.json lands, and alongside it).

Flights: NS31 (technical, the hero), NS108 DUB-BCN and NS101 LHR-DUB (weather), NS116 DUB-MUC (weather, positions
EI-NSL) and NS117 MUC-DUB (knock-on return), plus two operated departures after the window. METAR: the REAL pinned
EIDW CSV, and a synthetic calm MUC day (outstation METAR is not pinned in the repo).
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from contracts.models import (
    Airport,
    Coupon,
    CrmEvent,
    Election,
    Flight,
    MetarObs,
    OpsLogEntry,
    Source,
    SourceKind,
    TechLogEntry,
    World,
)
from engine.geo import airport as lookup_airport
from engine.timeline import load_iem_csv

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
EOWYN_CSV = GOLDEN / "eidw_2025-01-23_25.csv"
DAY = date(2025, 1, 24)
DISTANCES = {"DUB-BOS": 4804, "DUB-BCN": 1486, "DUB-LHR": 449, "DUB-MUC": 1381, "DUB-CDG": 786, "DUB-LIS": 1643,
             "DUB-FCO": 1886, "DUB-JFK": 5103, "DUB-ATH": 2876, "DUB-AMS": 750}
TECH_LOG_TEXT = ("23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. GND RUN: ECAM HYD Y ENG 2 PUMP LO PR. "
                 "EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.")
MCC_TEXT = "22:15Z: NO EDP IN DUB STORES; POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z, RTS EST 20:00Z."
OCC_TEXT = ("05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71. NS100/101 NS102/103 NS104/105 NS106/107 "
            "NS108/109 NS110/111 NS112/113 NS114/115 NS116/117 NS118 NS21 NS41 NS51 NS31. INBD NS20 NS30 NS40 NS50 "
            "RSN 72. ASM SENT. IROPS SMS 05:20Z.")
SPARES_NS31 = ("No long-range tail at DUB. XLR EI-NSN at BOS (NS30 CNL 72); A330s at JFK/ORD/YYZ (NS20/40/50 CNL); "
               "A320/A321neo lack range.")
SPARES_NS117 = "No tail at MUC. Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20."


def z(hhmm: str, day: int = 24, month: int = 1) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2025, month, day, int(h), int(m), tzinfo=UTC)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def seats(n: int) -> list[str]:
    out: list[str] = []
    row = 1
    while len(out) < n:
        out += [f"{row}{c}" for c in "ABCDEF"]
        row += 1
    return out[:n]


def fid(number: str, day: date = DAY) -> str:
    return f"{number}@{day.isoformat()}"


def flight(number: str, o: str, d: str, std: datetime, sta: datetime, pax: int, tail: str, *,
           status: str = "cancelled", code: str | None = "71", day: date = DAY, **kw) -> Flight:
    return Flight(id=fid(number, day), number=number, date=day, origin=o, dest=d, sched_dep=std, sched_arr=sta,
                  aircraft=tail, status=status, pax=pax, ops_cause_code=code if status == "cancelled" else None,
                  notified_at=kw.pop("notified_at", z("05:20") if status == "cancelled" else None), **kw)


def calm_obs(station: str, start: datetime, hours: int, sknt: int = 8) -> list[MetarObs]:
    out = []
    for i in range(hours * 2 + 1):
        t = start + timedelta(minutes=30 * i)
        raw = f"{station} {t:%d%H%M}Z 24{sknt:03d}KT 9999 FEW030 05/01 Q1012"
        out.append(MetarObs(station=station, valid=t, sknt=sknt, gust=None, drct=240, vsby_sm=6.21, raw=raw))
    return out


class Builder:
    def __init__(self) -> None:
        self.flights: list[Flight] = []
        self.coupons: list[Coupon] = []
        self.elections: list[Election] = []
        self.crm: list[CrmEvent] = []
        self.tech_log: list[TechLogEntry] = []
        self.ops_log: list[OpsLogEntry] = []
        self.sources: list[Source] = []
        self.metar: dict[str, list[MetarObs]] = {}
        self.airports: dict[str, Airport] = {}
        self.history = []
        self.meta = {"carrier": "Northstar Air", "distances_km": dict(DISTANCES)}

    def add_flight(self, f: Flight) -> Flight:
        self.flights.append(f)
        for code in (f.origin, f.dest):
            self.airports.setdefault(code, lookup_airport(None, code))
        return f

    def add_coupons(self, f: Flight, spec: list[tuple[int, str, dict]], fare: int = 45_000, tax: int = 6_000,
                    **coupon_kw) -> list[Coupon]:
        labels = iter(seats(sum(n for n, _, _ in spec)))
        made = []
        for n, kind, ekw in spec:
            for _ in range(n):
                seat = next(labels)
                c = Coupon(id=f"{f.id}:{seat}", pnr="P" + sha(f.id + seat)[:6].upper(),
                           pax_ref=f"pax:{f.number}:{seat}", flight_id=f.id, fare_cents=fare, taxes_cents=tax,
                           **coupon_kw)
                self.coupons.append(c)
                made.append(c)
                if kind != "none":
                    self.elections.append(Election(coupon_id=c.id, kind=kind,
                                                   recorded_by=ekw.get("recorded_by", "web"),
                                                   arrival_delay_min=ekw.get("delay"),
                                                   new_arrival=ekw.get("new_arrival")))
        return made

    def source(self, sid: str, kind: SourceKind, title: str, text: str, at: datetime, tier: int,
               tags: list[str] | None = None) -> Source:
        s = Source(id=sid, kind=kind, title=title, text=text, sha256=sha(text), received_at=at, trust_tier=tier,
                   acl_tags=tags or [])
        self.sources.append(s)
        return s

    def world(self) -> World:
        return World(meta=self.meta, airports=sorted(self.airports.values(), key=lambda a: a.iata),
                     flights=self.flights, tech_log=self.tech_log, ops_log=self.ops_log, coupons=self.coupons,
                     elections=self.elections, crm=self.crm, claims=[], care=[], metar=self.metar,
                     sources=self.sources, history_cases=self.history)


def build(*, with_muc_metar: bool = True, ns31_extra: dict | None = None) -> World:
    b = Builder()
    eowyn = load_iem_csv(EOWYN_CSV)
    b.metar["EIDW@2025-01-24"] = eowyn
    if with_muc_metar:
        b.metar["EDDM@2025-01-24"] = calm_obs("EDDM", z("10:00"), 10)
    b.source("SRC-METAR-EIDW-2025-01-23_25", SourceKind.METAR, "IEM METAR EIDW",
             "\n".join(o.raw for o in eowyn), z("00:00", 25), 1, ["ops"])

    # --- NS31, the airtight technical case
    ns31 = b.add_flight(flight("NS31", "DUB", "BOS", z("16:30"), z("23:10"), 172, "EI-NSB", **(ns31_extra or {})))
    coupons = b.add_coupons(ns31, [
        (32, "refund", {"recorded_by": "crm-bot"}),
        (14, "voucher", {"recorded_by": "web"}),
        (112, "reaccommodated_own", {"delay": 1500, "recorded_by": "occ"}),
        (14, "reroute_partner", {"delay": 220, "recorded_by": "service-desk"}),
    ])
    for i, c in enumerate(coupons[:32]):
        at = z("06:02") + timedelta(minutes=7 * i)  # 06:02 .. 09:39
        b.crm.append(CrmEvent(id=f"CRM-REF-{i:03d}", coupon_id=c.id, at=at, kind="refund_initiated",
                              amount_cents=c.fare_cents + c.taxes_cents, actor="agent.crm_bot",
                              text="Refund initiated: weather, no compensation."))
    b.crm.append(CrmEvent(id="CRM-BSP-DUP", coupon_id=coupons[0].id, at=z("11:00"), kind="bsp_refund",
                          amount_cents=51_000, actor="bsp", text="BSP refund RFND 51000"))
    b.crm.append(CrmEvent(id="CRM-14C-VIL", coupon_id=f"{ns31.id}:14C", at=z("10:15"),
                          kind="voucher_in_lieu_of_compensation", amount_cents=30_000, actor="service-desk:T2",
                          text="€300 voucher issued in lieu of compensation. Pax accepted."))
    tl = b.source("SRC-TECHLOG-EI-NSB-2025-01-23T2140Z", SourceKind.TECH_LOG, "AMOS tech log EI-NSB", TECH_LOG_TEXT,
                  z("21:40", 23), 1, ["maintenance"])
    b.tech_log.append(TechLogEntry(id="TL-EI-NSB-1", aircraft="EI-NSB", logged_at=z("21:40", 23), station="DUB",
                                   ata="2913", text=tl.text, mel_relief=False, aog=True, rts_est=z("20:00", 25)))
    b.source("SRC-MCC-2025-01-23T2215Z", SourceKind.MCC_LOG, "MCC log", MCC_TEXT, z("22:15", 23), 1, ["maintenance"])
    b.ops_log.append(OpsLogEntry(id="MCC-1", at=z("22:15", 23), kind="mcc", flight_ids=[ns31.id], text=MCC_TEXT,
                                 author="MCC"))
    b.source("SRC-OCC-2025-01-24T0512Z", SourceKind.OCC_LOG, "OCC cancel list", OCC_TEXT, z("05:12"), 3, ["ops"])

    # --- weather: NS108 DUB-BCN (STD in window), NS101 LHR-DUB (STA in window at DUB)
    ns108 = b.add_flight(flight("NS108", "DUB", "BCN", z("08:15"), z("10:50"), 192, "EI-NSD"))
    b.add_coupons(ns108, [(40, "refund", {}), (152, "reaccommodated_own", {"delay": 1440})])
    ns101 = b.add_flight(flight("NS101", "LHR", "DUB", z("08:00"), z("09:15"), 182, "EI-NSA"))
    b.add_coupons(ns101, [(182, "reaccommodated_own", {"delay": 600})])

    # --- knock-on: NS116 DUB-MUC cancelled by the storm, so EI-NSL never reached Munich for NS117
    ns116 = b.add_flight(flight("NS116", "DUB", "MUC", z("11:00"), z("13:15"), 170, "EI-NSL"))
    b.add_coupons(ns116, [(170, "reaccommodated_own", {"delay": 900})])
    ns117 = b.add_flight(flight("NS117", "MUC", "DUB", z("14:05"), z("16:20"), 168, "EI-NSL",
                                inbound_flight_id=ns116.id, outbound_pair_id=ns116.id))
    b.add_coupons(ns117, [(150, "reroute_partner", {"delay": 300}), (18, "refund", {})])
    b.source("SRC-SPARES-2025-01-24", SourceKind.SPARES, "Spares log",
             f"NS31: {SPARES_NS31}\nNS117: {SPARES_NS117}", z("06:30"), 2, ["ops"])
    b.ops_log.append(OpsLogEntry(id="SPARES-NS31", at=z("06:30"), kind="spares", flight_ids=[ns31.id],
                                 text=SPARES_NS31, author="OCC"))
    b.ops_log.append(OpsLogEntry(id="SPARES-NS117", at=z("06:30"), kind="spares", flight_ids=[ns117.id],
                                 text=SPARES_NS117, author="OCC"))
    b.ops_log.append(OpsLogEntry(id="OCC-0512", at=z("05:12"), kind="occ", code="71",
                                 flight_ids=[f.id for f in (ns31, ns108, ns101, ns116, ns117)], text=OCC_TEXT,
                                 author="OCC DM"))

    # --- operated after the window ("everyone else flew")
    b.add_flight(flight("NS120", "DUB", "CDG", z("15:40"), z("17:05"), 160, "EI-NSE", status="operated",
                        actual_dep=z("15:52"), actual_arr=z("17:14")))
    b.add_flight(flight("NS122", "DUB", "AMS", z("16:10"), z("17:40"), 150, "EI-NSF", status="operated",
                        actual_dep=z("16:15"), actual_arr=z("17:44")))
    return b.world()
