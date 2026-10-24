"""Explicit simulated judge cases. Weather observations are never modified."""
from __future__ import annotations

from datetime import timedelta

from contracts.models import CrmEvent, OpsLogEntry, Source, SourceKind, TechLogEntry
from world import metar, texts
from world.airports import airport
from world.generator import Cancel, DayOutput, FlightTruth, rng_for, sha


def _source(out: DayOutput, sid: str, kind: SourceKind, text: str, at, tier: int, tags: list[str]) -> None:
    out.sources.append(Source(id=sid, kind=kind, title=f"Simulated judge case · {sid}", text=text,
                              sha256=sha(text), received_at=at, trust_tier=tier, acl_tags=tags))


def _calm_at(out: DayOutput, flight) -> bool:
    for code, at in ((flight.origin, flight.sched_dep), (flight.dest, flight.sched_arr)):
        station = airport(code).icao
        near = [o for rows in out.metar.values() for o in rows if o.station == station
                and abs((o.valid - at).total_seconds()) <= 3600]
        if not near or any(metar.storm_conditions(o) for o in near):
            return False
    return True


def _ground_rotation(out: DayOutput, root, seed: int) -> None:
    """An explicit latent no-go fault also cancels the tail's later sectors, preserving its position."""
    at = root.sched_dep - timedelta(hours=2)
    defect = texts.AOG_DEFECTS[0]
    line = texts.tech_log_line(at, root.aircraft, root.origin,
                               texts.fill(defect, rng_for(seed, "judge-defect", root.id), root.origin), defect)
    tid = f"JUDGE-AOG-{root.id}"
    out.tech_log.append(TechLogEntry(id=tid, aircraft=root.aircraft, logged_at=at, station=root.origin,
                                    ata=defect.ata, text=line, mel_relief=False, aog=True,
                                    rts_est=at + timedelta(days=2)))
    _source(out, f"SRC-{tid}", SourceKind.TECH_LOG, line, at, 1, ["maintenance", "ops"])
    changed = []
    for flight in out.flights:
        if flight.aircraft != root.aircraft or flight.sched_dep < root.sched_dep:
            changed.append(flight)
            continue
        is_root = flight.id == root.id
        latent = "internal_aog" if is_root else "rotation"
        cause = "technical" if is_root else "knock_on"
        concurrent = is_root and not _calm_at(out, root)
        if concurrent:
            latent, cause = "concurrent", "concurrent"
        code = "71" if is_root else "93"
        notified = at + timedelta(minutes=10)
        changed.append(flight.model_copy(update={"status": "cancelled", "actual_dep": None, "actual_arr": None,
                                                   "ops_cause_code": code, "notified_at": notified}))
        out.cancels[flight.id] = Cancel(latent, at, root=None if is_root else root.id, defect_entry=tid)
        out.truth[flight.id] = FlightTruth(
            flight.id, out.meta["date"], out.meta["split"], "cancelled", latent, cause, "not_extraordinary",
            root_flight_id=None if is_root else root.id, root_latent=None if is_root else "internal_aog",
            planted=["miscoded_technical"] if is_root and not concurrent else [],
            expected_route="legal" if concurrent else None, ops_code=code,
            note="Explicit simulated judge fault; subsequent sectors cannot use the grounded aircraft.",
        )
        oid = f"JUDGE-OCC-{flight.id}"
        text = f"{texts.ddmon(at)} {texts.hhmmz(at)} {flight.number} CNL RSN {code}. IROPS SMS {texts.hhmmz(notified)}."
        out.ops_log.append(OpsLogEntry(id=oid, at=at, kind="occ", flight_ids=[flight.id], code=code,
                                       text=text, author="OCC demo desk"))
        _source(out, f"SRC-{oid}", SourceKind.OCC_LOG, text, at, 3, ["ops"])
    out.flights = changed
    out.meta["cancelled"] = sorted(out.cancels)


def prepare_flights(out: DayOutput, seed: int) -> None:
    calm = next((f for f in out.flights if _calm_at(out, f)), None)
    if calm is not None:
        _ground_rotation(out, calm, seed)
    for eu in (True, False):
        if not any(f.status == "cancelled" and airport(f.origin).eu == eu for f in out.flights):
            root = next((f for f in out.flights if airport(f.origin).eu == eu), None)
            if root is not None:
                _ground_rotation(out, root, seed)


def plant_vouchers(out: DayOutput) -> None:
    from world.pax import coupon_truth

    po = out.pax
    flights = {f.id: f for f in out.flights}
    elections = {e.coupon_id: e for e in po.elections}
    selected = []
    for eu, count in ((True, 3), (False, 1)):
        coupons = [c for c in po.coupons if c.fare_type == "revenue" and c.id not in po.in_lieu
                   and airport(flights[c.flight_id].origin).eu == eu]
        for coupon in coupons[:count]:
            flight = flights[coupon.flight_id]
            at = flight.sched_dep - timedelta(minutes=30)
            eid = f"JUDGE-VOUCHER-{coupon.id}"
            text = f"EUR100 VOUCHER IN LIEU OF COMPENSATION - PAX ACCEPTED · {coupon.id}"
            event = CrmEvent(id=eid, coupon_id=coupon.id, at=at, kind="voucher_in_lieu_of_compensation",
                             amount_cents=10000, signed_acceptance_sha256=None, actor="service-desk:demo", text=text)
            po.crm.append(event)
            po.in_lieu[coupon.id] = event
            po.coupon_truth[coupon.id] = coupon_truth(flight, out.truth[flight.id].__dict__, coupon,
                                                       elections.get(coupon.id), event)
            _source(out, f"SRC-{eid}", SourceKind.CRM, text, at, 3, ["pii"])
            selected.append(coupon.id)
    out.meta["judge_unsigned_vouchers"] = selected
