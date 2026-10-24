"""``EngineAPI.run_storm``: every Northstar flight touching ``station`` on its local day, decided and summed.

Counts come from here (never hand-typed): passengers, cancelled, operated, drafted, held, questions, people,
repeat_questions, rules_cited. ``liability_drafted_cents`` is the engine's preview of Books' day-1 estimate (the same
segment rates and rounding); Books' booked number is authoritative.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from contracts.models import (
    Entitlement,
    Extraordinary,
    FlightDecision,
    FlightRow,
    Question,
    Rule,
    StormRun,
    TraceEvent,
    World,
)
from engine import questions as qs
from engine.case import station_obs, stations_for
from engine.engine import expected_liability, local_day_span, station_airport
from engine.geo import UnknownAirport, airport
from engine.timeline import storm_windows

if TYPE_CHECKING:
    from engine.engine import Engine

METAR_PAD = timedelta(hours=6)


def storm_flights(world: World, station: str, local_day: date):
    """Flights with STD at ``station`` or STA at ``station`` inside its local day (overnight inbounds included)."""
    ap = station_airport(world, station)
    start, end = local_day_span(ap, local_day)
    codes = {station} | ({ap.iata, ap.icao} if ap else set())
    out = []
    for f in world.flights:
        dep_here = f.origin in codes and start <= f.sched_dep < end
        arr_here = f.dest in codes and start <= f.sched_arr < end
        if dep_here or arr_here:
            out.append(f)
    return sorted(out, key=lambda f: (f.sched_dep, f.id))


def _chip_summary(d: FlightDecision, ents: Sequence[Entitlement], number: str) -> tuple[str, str]:
    owed = sum(1 for e in ents if e.status == "owed")
    if d.outcome == "escalated":
        who = d.routed_to.value.replace("_", " ") if d.routed_to else "a person"
        return "HELD", f"{number} held for {who} · {d.cause.value}"
    if d.extraordinary == Extraordinary.NO:
        rec = f" recoded {d.recode_label} ·" if d.recode_label else ""
        return "DRAFTED", f"{number}{rec} {d.cause.value} · {owed} payouts drafted, pending Claims Lead approval"
    return "APPLIED", f"{number} {d.cause.value} · no compensation; refunds and care still due"


def run_storm(engine: Engine, world: World, station: str, local_day: date, rules: Sequence[Rule],
              known_at: datetime) -> StormRun:
    ap = station_airport(world, station)
    icao = ap.icao if ap else station
    storm_id = f"{icao}@{local_day.isoformat()}"
    start, end = local_day_span(ap, local_day)
    obs = [o for o in station_obs(world, icao, known_at) if start - METAR_PAD <= o.valid < end + METAR_PAD]
    windows = storm_windows(obs)

    stations = stations_for(world, known_at)
    flights = storm_flights(world, station, local_day)
    rows: list[FlightRow] = []
    decisions: list[FlightDecision] = []
    ents_all: list[Entitlement] = []
    liability: dict[str, int] = {}
    feed: list[TraceEvent] = []
    for f in flights:
        if f.status != "cancelled":
            rows.append(FlightRow(flight=f, decision=None))
            continue
        d = engine.decide_in(world, f.id, rules, known_at, stations=stations, storm_id=storm_id)
        ents = engine.entitlements(d, world, list(rules))
        decisions.append(d)
        ents_all += ents
        liability[f.id] = expected_liability(ents, engine.claim_rates)
        rows.append(FlightRow(flight=f, decision=d))
        chip, summary = _chip_summary(d, ents, f.number)
        feed.append(TraceEvent(seq=len(feed) + 1, at=known_at, kind="decision", actor="agent.engine",
                               summary=summary, ref=f.id, chip=chip, amount_cents=liability[f.id] or None))

    questions: list[Question] = qs.flight_questions(decisions, ents_all, known_at, liability)
    questions += qs.voucher_questions(world, ents_all, storm_id, known_at, engine.calibration, known_at)
    questions += qs.release_questions(world, rules, known_at, engine.calibration)
    for q in questions:
        feed.append(TraceEvent(
            seq=len(feed) + 1, at=known_at, kind="question", actor="agent.engine",
            summary=(f"Asked {q.routed_to.value.replace('_', ' ')}: {q.title} · "
                     + (f"confidence {q.confidence.score:.0%}" if q.confidence.score is not None else "uncalibrated")
                     + f" · {q.reason_tag.replace('-', ' ')}"),
            ref=q.id, chip="ASKED", amount_cents=q.holds_cents or None))

    cancelled = [r.flight for r in rows if r.flight.status == "cancelled"]
    dec_rules = {d.flight_id: set(d.rules_applied) for d in decisions}
    cited = sum(len(d.rules_applied) for d in decisions) + sum(
        1 for e in ents_all for r in e.rules_applied if r not in dec_rules.get(e.flight_id, set()))
    counters = {
        "passengers": sum(f.pax for f in cancelled),
        "cancelled": len(cancelled),
        "operated": sum(1 for r in rows if r.flight.status == "operated"),
        "drafted": sum(1 for e in ents_all if e.status == "owed"),
        "held": sum(1 for e in ents_all if e.status in {"held", "needs_ruling"}),
        "questions": len(questions),
        "people": len({q.routed_to for q in questions}),
        "repeat_questions": 0,
        "rules_cited": cited,
        "recoded": sum(1 for d in decisions if d.recoded),
        "weather": sum(1 for d in decisions if d.cause.value == "weather"),
        "auto": sum(1 for d in decisions if d.outcome == "auto"),
    }
    entitlement = sum(e.compensation_cents for e in ents_all if e.status in {"owed", "needs_ruling"})
    codes = sorted({c for f in flights for c in (f.origin, f.dest)})
    airports = []
    for c in codes:
        try:
            airports.append(airport(world, c))
        except UnknownAirport:
            pass
    message = None
    if not windows:
        peak = max((o.gust if o.gust is not None else (o.sknt or 0) for o in obs), default=None)
        message = f"max gust {peak} kt · no storm window" if peak is not None else "no METAR · no storm window"
    return StormRun(
        id=storm_id, station=icao, date=local_day, windows=windows, metar=obs, flights=rows, counters=counters,
        entitlement_cents=entitlement, liability_drafted_cents=sum(liability.values()),
        learned=[], questions=questions, feed=feed, real_context=world.real_context.get(storm_id, {}),
        message=message, airports=airports)
