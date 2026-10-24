"""Planted judge cases for `generate_day` (F3d), planted as latent events and re-simulated through `DaySim`.

Nothing is edited after a simulation. A planted fault is a `DayPlan` entry (an AOG with its AMOS line), the day is
simulated again, and the tech log, MCC, OCC and spares logs, flight status, coupons and truth all come from that one
run, so they agree. Weather observations are never modified.

1. **One OCC weather code the METAR contradicts** (when the day allows it). A Dublin departure on the judge's route,
   observed calm at both ends (reports within ±1 h, no storm conditions), whose aircraft is at DUB, gets an AOG
   logged at DUB before departure. OCC types it RSN 71 (inside the storm-day batch on a storm day: the NS31
   pattern). Later sectors of that aircraft follow from the simulation (rotation knock-ons, or the same AOG at DUB).
   If a DUB standby spare of the aircraft's class would cover it, that class is unavailable for the whole day, so
   every spares-log line tells the same story. This is applied only when it is needed.
2. **A non-EU departure with compensation owed.** At a non-EU airport this is the faulted aircraft's return. At the
   hub, the fault prefers a non-EU route for the same reason. Between DUB and an EU airport every sector departs the
   EU, so the day's BOS→DUB inbound joins as context, as in golden's Herminia mini-day, with an honest AOG at BOS
   typed RSN 41, unless it is already cancelled with compensation owed.
3. **Only when the day gives nothing else:** an honest AOG (RSN 41) at the origin of the first eligible EU or non-EU
   departure, so the voucher cases below have a cancelled flight to sit on.
4. **Unsigned service-desk vouchers in lieu:** 3 on EU departures and 1 on a non-EU departure. They go on revenue
   coupons with compensation owed where there are any (the planted fault's passengers first), through the passenger
   generator's own voucher path (`pax.FlightPax.in_lieu`).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

from contracts.models import Coupon
from world import causes as C
from world import metar as M
from world import network as N
from world import pax as P
from world.airports import airport
from world.generator import DayOutput, DayPlan, rng_for

CALM_WINDOW = timedelta(hours=1)
UNSIGNED = "voucher_in_lieu_unsigned"
Sim = Callable[[DayPlan, frozenset[str]], DayOutput]


# ---------------------------------------------------------------- helpers

def observed_calm(o: DayOutput, code: str, t: datetime) -> bool:
    """Reports exist within ±1 h of `t` at `code`, none shows storm conditions, and the latent severity is 0."""
    idx = o.idx.get(code)
    near = idx.near(t, CALM_WINDOW) if idx else []
    return bool(near) and not any(M.storm_conditions(x) for x in near) and C.severity(idx, t) == 0


def spares_of_class(tail: str) -> frozenset[str]:
    """The DUB standby spares that could cover `tail` (long-range for XLR/A330, narrowbody otherwise)."""
    long_range = N.FLEET[tail].code in ("A21X", "A333")
    return frozenset(sp for sp in N.SPARES if (N.FLEET[sp].code == "A333") == long_range)


def owed_cancellation(o: DayOutput, fid: str) -> bool:
    """Cancelled, and compensation is owed (not extraordinary, not a planned ≥14-day-notice change)."""
    t = o.truth.get(fid)
    return t is not None and t.status == "cancelled" and t.extraordinary != "extraordinary" and t.latent != "notice"


@lru_cache(maxsize=64)
def _network_day(d: date) -> tuple[N.Sector, ...]:
    return tuple(N.day_sectors(d))


def _prev_network_arrival(s: N.Sector) -> datetime | None:
    """When the aircraft last arrived at the sector's origin in the full network rotation. That sector may not be in
    the desk world (e.g. the overnight inbound before NS31, or NS31 before the next NS30)."""
    arrivals = [x.sta for k in (-1, 0, 1) for x in _network_day(s.local_date + timedelta(days=k))
                if x.tail == s.tail and x.dest == s.origin and x.sta <= s.std]
    return max(arrivals) if arrivals else None


def _at_origin(o: DayOutput, s: N.Sector, rot: dict[str, list[N.Sector]]) -> tuple[bool, datetime | None]:
    """(is the scheduled aircraft at the sector's origin, when it got there). First sector of the tail in this
    world: in position since its last network arrival. Otherwise its previous sector must have flown in, on it."""
    flights = {f.id: f for f in o.flights}
    secs = rot[s.tail]
    k = [x.id for x in secs].index(s.id)
    if flights[s.id].aircraft != s.tail:          # a spare already took this rotation over
        return False, None
    if k == 0:
        return True, _prev_network_arrival(s)
    prev = secs[k - 1]
    pf = flights[prev.id]
    ok = prev.dest == s.origin and pf.status != "cancelled" and pf.aircraft == s.tail
    return ok, pf.actual_arr or prev.sta


def _logged(r: Any, s: N.Sector, since: datetime | None) -> datetime | None:
    """An AOG write-up time before `s`, after the aircraft got there. At DUB: 5 h to 90 min before STD, from 30 min
    after arrival. At an outstation (found during the turn): from 15 min after arrival to 20 min before STD."""
    hub = s.origin == N.HUB
    lo = s.std - timedelta(hours=5)
    if since is not None:
        lo = max(lo, since + timedelta(minutes=30 if hub else 15))
    hi = s.std - timedelta(minutes=90 if hub else 20)
    if lo > hi:
        # an outstation turn with no time in it (the US/EU daylight-saving gap: NS31 lands as NS30 is due out):
        # the defect is written up on arrival
        if not hub and since is not None and since <= s.std:
            return since.replace(second=0, microsecond=0)
        return None
    span = int((hi - lo).total_seconds() // 60)
    return (lo + timedelta(minutes=r.randrange(0, span + 1, 5))).replace(second=0, microsecond=0)


# ---------------------------------------------------------------- 1. the contradicted weather code

def contradiction_root(o: DayOutput, sectors: Sequence[N.Sector], context: Sequence[str], r: Any, *,
                       prefer_non_eu: bool) -> tuple[N.Sector, datetime] | None:
    """The Dublin departure to plant the miscoded AOG on, and its write-up time (None: the day doesn't allow it)."""
    rot = N.tail_rotation(list(sectors))
    cands = []
    for s in sectors:
        if s.origin != N.HUB or s.id in context or o.truth[s.id].status == "cancelled":
            continue
        here, since = _at_origin(o, s, rot)
        if not here or not (observed_calm(o, s.origin, s.std) and observed_calm(o, s.dest, s.sta)):
            continue
        logged = _logged(r, s, since)
        if logged is None:
            continue
        secs = rot[s.tail]
        ret = next((x for x in secs if x.pair is s.pair and x.is_return and x.std > s.std), None)
        ret_ok = (ret is not None and o.truth[ret.id].status != "cancelled"
                  and observed_calm(o, ret.origin, ret.std) and observed_calm(o, ret.dest, ret.sta))
        cands.append((s, logged, ret_ok, not airport(s.dest).eu))
    if not cands:
        return None
    r.shuffle(cands)
    cands.sort(key=lambda c: (not c[2], prefer_non_eu and not c[3]))
    return cands[0][0], cands[0][1]


# ---------------------------------------------------------------- the plan

def _side_ok(o: DayOutput, eu: bool) -> bool:
    return any(owed_cancellation(o, f.id) and airport(f.origin).eu == eu for f in o.flights)


def _fallback(o: DayOutput, sectors: Sequence[N.Sector], context: Sequence[str], eu: bool, r: Any,
              taken: set[str]) -> tuple[N.Sector, datetime] | None:
    """First departure on that side whose aircraft is at its origin, has no planted fault yet, and which isn't
    already an owed cancellation."""
    rot = N.tail_rotation(list(sectors))
    for s in sectors:
        if s.id in context or s.tail in taken or airport(s.origin).eu != eu or owed_cancellation(o, s.id):
            continue
        here, since = _at_origin(o, s, rot)
        logged = _logged(r, s, since) if here else None
        if logged is not None:
            return s, logged
    return None


def plan_day(sim: Sim, sectors: Sequence[N.Sector], context: Sequence[str], *, seed: int, key: str,
             storm: bool, prefer_non_eu: bool) -> tuple[DayOutput, dict[str, Any]]:
    """Dry-run the day, plan the judge cases as latent events, re-simulate. Returns (final output, planted meta)."""
    r = rng_for(seed, "desk", key)
    by_id = {s.id: s for s in sectors}
    plan = DayPlan()
    blocked: frozenset[str] = frozenset()
    dry = sim(plan, blocked)
    planted: dict[str, Any] = {"contradicted_weather_code": None, "faults": [], "context_flights": list(context),
                               "spares_unavailable": [], "notes": []}

    def fault(s: N.Sector, logged: datetime, code: str, kind: str) -> None:
        plan.aog[s.tail] = (logged, True) if s.origin == N.HUB else (logged, True, s.origin)
        plan.code[s.id] = code
        planted["faults"].append({"flight_id": s.id, "kind": kind, "aircraft": s.tail, "station": s.origin,
                                  "logged_at": logged.isoformat().replace("+00:00", "Z"), "ops_code": code})

    root = contradiction_root(dry, sectors, context, r, prefer_non_eu=prefer_non_eu)
    if root is not None:
        s, logged = root
        fault(s, logged, "71", "aog_miscoded_weather")
        if storm:
            plan.batch.add(s.id)
    else:
        planted["notes"].append("no Dublin departure on this route was observed calm at both ends with its aircraft "
                                "at DUB, so no weather code can be contradicted by the METAR today")
    rot = N.tail_rotation(list(sectors))
    for cid in context:
        if not owed_cancellation(dry, cid):
            s = by_id[cid]
            here, since = _at_origin(dry, s, rot)
            logged = _logged(r, s, since) if here else None
            if logged is not None:
                fault(s, logged, "41", "aog_context")
    out = sim(plan, blocked)

    if root is not None:
        s = root[0]
        ret = next((x for x in sectors if x.pair is s.pair and x.is_return and x.std > s.std), None)
        need_ret = ret is not None and not airport(ret.origin).eu and not _side_ok(out, False)
        if out.truth[s.id].status != "cancelled" or (need_ret and out.truth[ret.id].status != "cancelled"):
            blocked = spares_of_class(s.tail)
            out = sim(plan, blocked)

    fallbacks: list[N.Sector] = []
    for eu in (True, False):
        if _side_ok(out, eu):
            continue
        pick = _fallback(out, sectors, context, eu, r, set(plan.aog))
        if pick is None:
            planted["notes"].append(f"no {'EU' if eu else 'non-EU'} departure can carry an owed cancellation today")
            continue
        fault(pick[0], pick[1], "41", "aog_fallback")
        fallbacks.append(pick[0])
    if fallbacks:
        out = sim(plan, blocked)
        covered = [s for s in fallbacks if s.origin == N.HUB and not owed_cancellation(out, s.id)]
        if covered:                  # a DUB spare stood in: that class is unavailable today, as for the root
            blocked = blocked.union(*(spares_of_class(s.tail) for s in covered))
            out = sim(plan, blocked)

    if root is not None:
        s = root[0]
        t = out.truth[s.id]
        f = next(x for x in out.flights if x.id == s.id)
        if t.status == "cancelled" and t.latent == "internal_aog" and f.ops_cause_code in ("71", "72"):
            planted["contradicted_weather_code"] = s.id
        else:
            planted["notes"].append(f"{s.id}: the planted AOG did not end as a weather-coded cancellation")
    planted["spares_unavailable"] = sorted(blocked)
    return out, planted


# ---------------------------------------------------------------- 4. the vouchers

def plant_vouchers(out: DayOutput, seed: int, planted: dict[str, Any]) -> None:
    """Unsigned vouchers in lieu: 3 on EU departures, 1 on a non-EU departure (owed coupons first)."""
    po = out.pax
    flights = {f.id: f for f in out.flights}
    elections = {e.coupon_id: e for e in po.elections}
    ids = {c.id for c in po.claims} | {e.id for e in po.crm}
    r = rng_for(seed, "desk-vouchers", out.meta["date"])
    first = [x for x in [planted["contradicted_weather_code"], *(f["flight_id"] for f in planted["faults"])] if x]
    by_flight: dict[str, list[Coupon]] = {}
    for c in po.coupons:
        by_flight.setdefault(c.flight_id, []).append(c)

    def pool(eu: bool) -> list[Coupon]:
        fids = sorted((f.id for f in out.flights if f.status == "cancelled" and airport(f.origin).eu == eu),
                      key=lambda fid: (first.index(fid) if fid in first else len(first), flights[fid].sched_dep, fid))
        cs: list[Coupon] = []
        for fid in fids:
            mine = [c for c in by_flight.get(fid, []) if c.fare_type == "revenue" and c.id not in po.in_lieu]
            r.shuffle(mine)
            cs += mine
        owed = [c for c in cs if po.coupon_truth[c.id]["status"] == "owed"]
        owed_ids = {c.id for c in owed}
        return owed + [c for c in cs if c.id not in owed_ids]

    picked: dict[str, list[str]] = {}
    for eu, n, name in ((True, 3, "in_lieu_unsigned_eu_departures"), (False, 1, "in_lieu_unsigned_non_eu")):
        chosen = pool(eu)[:n]
        makers: dict[str, P.FlightPax] = {}
        for c in chosen:
            f = flights[c.flight_id]
            fp = makers.setdefault(f.id, P.FlightPax(seed, f, out.truth[f.id].__dict__, po, ids))
            ev = fp.in_lieu(c, signed=False)
            po.coupon_truth[c.id] = P.coupon_truth(f, out.truth[f.id].__dict__, c, elections.get(c.id), ev)
        picked[name] = [c.id for c in chosen]
        if len(chosen) < n:
            planted["notes"].append(f"only {len(chosen)} of {n} {name.replace('_', ' ')}: too few cancelled coupons")
    for e in po.crm:          # natural and planted alike: the answer key tags every unsigned voucher in lieu
        if e.kind == "voucher_in_lieu_of_compensation" and not e.signed_acceptance_sha256:
            tags = po.coupon_truth[e.coupon_id].setdefault("planted", [])
            if UNSIGNED not in tags:
                tags.append(UNSIGNED)
    planted.update(picked)
    out.meta["judge_unsigned_vouchers"] = picked["in_lieu_unsigned_eu_departures"] + picked["in_lieu_unsigned_non_eu"]
