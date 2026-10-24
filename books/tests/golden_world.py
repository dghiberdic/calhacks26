"""The real golden fixture (contracts/fixtures/golden/world.json + expected/), read-only.

Decisions come from expected/decisions.json (the compared 5-tuple), NS31's entitlements from
expected/entitlements_NS31.json, and the other Éowyn flights' entitlements are built here from the world's coupons
and distances (weather → no compensation; knock-on returns → held at their band). No engine import.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from contracts.models import Confidence, Entitlement, FlightDecision, World

GOLDEN = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "golden"
EXPECTED = GOLDEN / "expected"
EOWYN = "EIDW@2025-01-24"
NS31 = "NS31@2025-01-24"


def expected(name: str) -> dict:
    return json.loads((EXPECTED / name).read_text())


@lru_cache(maxsize=1)
def golden_world() -> World:
    return World.model_validate_json((GOLDEN / "world.json").read_text())


def golden_decisions(known_at: datetime) -> list[FlightDecision]:
    world = golden_world()
    flights = {f.id: f for f in world.flights}
    out = []
    for fid, x in sorted(expected("decisions.json")["storms"][EOWYN].items()):
        out.append(FlightDecision(
            flight_id=fid, cause=x["cause"], extraordinary=x["extraordinary"],
            ops_cause_code=flights[fid].ops_cause_code, recoded=x["recoded"], recode_label=x["recode_label"],
            in_window_dep="out", in_window_arr="out",
            confidence=Confidence(score=0.91 if x["outcome"] == "auto" else 0.47, kind="cause",
                                  label="cause-finding confidence", features={}, calibration_version="cal-v1"),
            reason="golden", evidence=[], rules_applied=[], legal_basis=[], outcome=x["outcome"],
            routed_to=x["routed_to"], known_at=known_at, commit=f"commit-{fid}"))
    return out


def _band(km: float) -> int:
    return 250 if km <= 1500 else 400 if km <= 3500 else 600


def golden_ents() -> list[Entitlement]:
    world = golden_world()
    dist = world.meta["distances_km"]
    flights = {f.id: f for f in world.flights}
    e31 = expected("entitlements_NS31.json")
    out = [Entitlement(coupon_id=r["coupon_id"], flight_id=NS31, distance_km=e31["distance_km"],
                       band_eur=e31["band_eur"], band_margin_km=e31["band_margin_km"],
                       compensation_cents=r["compensation_cents"], reduction=r["reduction"],
                       refund_due_cents=r["refund_due_cents"], refund_already_initiated=r["refund_already_initiated"],
                       care_due=r["care_due"], voucher_offset_cents=r["voucher_offset_cents"], status=r["status"],
                       article="EU261 Art.7(1)(c)", reason="golden", rules_applied=["R-MINED-REDUCE@1"]
                       if r["reduction"] != "none" else [])
           for r in e31["coupons"]]
    for fid, x in sorted(expected("decisions.json")["storms"][EOWYN].items()):
        if fid == NS31:
            continue
        f = flights[fid]
        km = float(dist["-".join(sorted([f.origin, f.dest], key=lambda a: a != "DUB"))])
        band = _band(km)
        held = x["extraordinary"] == "needs_legal"
        for c in (c for c in world.coupons if c.flight_id == fid):
            out.append(Entitlement(
                coupon_id=c.id, flight_id=fid, distance_km=km, band_eur=band, band_margin_km=0.0,
                compensation_cents=band * 100 if held else 0, status="held" if held else "no_compensation",
                article="EU261 Art.5(3), Art.7(1)" if held else "EU261 Art.5(3)", reason="golden"))
    return out
