"""Compose a StormRun and FlightFiles from a World, using whichever engine pieces exist on main.

Used when no full `run_storm` (real Engine or FakeEngine) is importable yet. Decisions come from, in order:
the engine's own `decide`, the stub fixture decision for the same flight id (CONTRACTS-exact golden values), or a
provisional window-only decision (weather if in a storm window at either end, else unknown → Ops). Windows and
entitlements always come from the real `engine.timeline` / `engine.eu261` when they exist. The server never
computes an amount itself: every cent is engine (entitlements) or books (journals).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable, Sequence

from contracts.models import (
    Airport, Cause, Confidence, Draft, Entitlement, Evidence, Extraordinary, Flight, FlightDecision, FlightFile,
    FlightRow, JournalEntry, LearnedItem, MetarObs, Question, Role, Rule, StormRun, StormWindow, World,
)

from .impls import _module

ROLE_LABEL = {Role.CLAIMS_LEAD: "Claims Lead", Role.LEGAL: "Legal", Role.CONTROLLER: "Controller", Role.OPS: "Ops",
              Role.CFO: "CFO", Role.JUDGE: "Judge"}
CAL_VERSION = "cal-v1"
PROVISIONAL = "provisional:window-only"


def label(role: Role | str | None) -> str:
    if role is None:
        return "nobody"
    try:
        return ROLE_LABEL.get(Role(role), Role(role).value)
    except ValueError:
        return str(role)


def eur(cents: int) -> str:
    v = cents / 100
    return f"€{v:,.0f}" if cents % 100 == 0 else f"€{v:,.2f}"


def hhmm(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%H:%MZ")


# ---------------------------------------------------------------- airports
def _airport_from_table(code: str) -> Airport | None:
    geo = _module("engine.geo")
    if geo is not None:
        try:
            return geo.airport(None, code)
        except Exception:
            return None
    return None


def airport_by(world: World | None, code: str) -> Airport | None:
    code = code.upper()
    for a in (world.airports if world else []):
        if code in (a.iata, a.icao):
            return a
    return _airport_from_table(code)


def iata_of(world: World | None, station: str) -> str:
    a = airport_by(world, station)
    return a.iata if a else station


# ---------------------------------------------------------------- which storm days, which flights
def storm_days(world: World, hub_icao: str) -> list[tuple[str, date]]:
    """Storm runs in a world: `meta["storms"]` when given, else every METAR key of a station that has cancellations."""
    listed = world.meta.get("storms") or world.meta.get("storm_runs")
    out: list[tuple[str, date]] = []
    if isinstance(listed, list) and listed:
        for item in listed:
            sid = item.get("id") if isinstance(item, dict) else str(item)
            if sid and "@" in sid:
                st, d = sid.split("@", 1)
                try:
                    out.append((st, date.fromisoformat(d[:10])))
                except ValueError:
                    continue
        return sorted(set(out), key=lambda x: (x[1], x[0]))
    cancelled_days = {f.date for f in world.flights if f.status == "cancelled"}
    for key in world.metar:
        if "@" not in key:
            continue
        st, d = key.split("@", 1)
        try:
            day = date.fromisoformat(d[:10])
        except ValueError:
            continue
        if day in cancelled_days and (st == hub_icao or not any(k.startswith(hub_icao + "@") for k in world.metar)):
            out.append((st, day))
    return sorted(set(out), key=lambda x: (x[1], x[0]))


def run_flights(world: World, station_iata: str, day: date) -> list[Flight]:
    """Flights touching the station whose local date, STD or STA falls on the day (overnight inbounds included)."""
    out = []
    for f in world.flights:
        if station_iata not in (f.origin, f.dest):
            continue
        if f.date == day or f.sched_dep.astimezone(UTC).date() == day or f.sched_arr.astimezone(UTC).date() == day:
            out.append(f)
    # a flight dated the day before that also arrived the day before belongs to the previous run
    out = [f for f in out if not (f.date < day and f.sched_arr.astimezone(UTC).date() < day)]
    return sorted(out, key=lambda f: (f.status != "cancelled", f.sched_dep, f.id))


def station_obs(world: World, station: str, day: date) -> list[MetarObs]:
    """Obs for station-day: the exact `ICAO@day` key, else every key for the station within ±1 day."""
    exact = world.metar.get(f"{station}@{day.isoformat()}")
    if exact:
        return sorted(exact, key=lambda o: o.valid)
    lo = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=12)
    hi = lo + timedelta(hours=48)
    seen: dict[datetime, MetarObs] = {}
    for key, obs in world.metar.items():
        if key.split("@", 1)[0] != station:
            continue
        for o in obs:
            if lo <= o.valid <= hi:
                seen.setdefault(o.valid, o)
    return [seen[k] for k in sorted(seen)]


def storm_windows(obs: Sequence[MetarObs]) -> list[StormWindow]:
    tl = _module("engine.timeline")
    if tl is None or not obs:
        return []
    return list(tl.storm_windows(obs))


def main_window(windows: Sequence[StormWindow]) -> StormWindow | None:
    if not windows:
        return None
    return max(windows, key=lambda w: ((w.end - w.start), w.peak_gust_kt))


def position(t: datetime, obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> tuple[str, int | None]:
    tl = _module("engine.timeline")
    if tl is None:
        return "unknown", None
    pos = tl.position(t, obs, windows)
    return pos, (None if pos == "unknown" else tl.margin_min(t, windows))


# ---------------------------------------------------------------- decisions
def rebase_decision(d: FlightDecision, known_at: datetime) -> FlightDecision:
    return d.model_copy(update={"known_at": known_at, "commit": None})


def provisional_decision(f: Flight, world: World, known_at: datetime) -> FlightDecision:
    """Window-only decision while `engine.cause` has not landed: weather if in a window at either end, else
    `unknown` routed to Ops. Uncalibrated; never recodes; never owes compensation on its own."""
    ends = []
    for code, t in ((f.origin, f.sched_dep), (f.dest, f.sched_arr)):
        a = airport_by(world, code)
        icao = a.icao if a else code
        obs = station_obs(world, icao, t.astimezone(UTC).date())
        wins = storm_windows(obs)
        ends.append((code, t, obs, wins, *position(t, obs, wins)))
    (o_code, std, o_obs, o_w, dep, dep_m), (d_code, sta, d_obs, d_w, arr, arr_m) = ends
    margins = [m for m in (dep_m, arr_m) if m is not None]
    margin = min((abs(m) for m in margins), default=None)
    evidence = []
    for code, t, obs, wins, pos, _ in ends:
        near = min(obs, key=lambda o: abs((o.valid - t).total_seconds()), default=None)
        if near is not None and pos != "unknown":
            evidence.append(Evidence(fact_id=f"F-METAR-{near.station}-{near.valid:%Y%m%dT%H%MZ}",
                                     source_id=f"SRC-METAR-{near.station}", field="metar.gust_kt",
                                     value=near.gust if near.gust is not None else near.sknt, quote=near.raw,
                                     role="supports" if pos == "in" else "context", trust_tier=1))
    conf_feats = {"in_window_dep": 1.0 if dep == "in" else 0.0, "in_window_arr": 1.0 if arr == "in" else 0.0}
    if "in" in (dep, arr):
        end = o_code if dep == "in" else d_code
        return FlightDecision(
            flight_id=f.id, cause=Cause.WEATHER, extraordinary=Extraordinary.YES, ops_cause_code=f.ops_cause_code,
            recoded=False, in_window_dep=dep, in_window_arr=arr, window_margin_min=margin,
            confidence=Confidence(score=None, kind="cause", label="cause-finding confidence", features=conf_feats,
                                  caps=["uncalibrated"], calibration_version=CAL_VERSION),
            reason=f"Weather: {'STD' if dep == 'in' else 'STA'} inside the {end} storm window; no compensation; "
                   "refunds and care still due.",
            evidence=evidence, rules_applied=["R-REG-ART5-3@1"], legal_basis=["EU261 Art.5(3)"], outcome="auto",
            known_at=known_at)
    return FlightDecision(
        flight_id=f.id, cause=Cause.UNKNOWN, extraordinary=Extraordinary.NEEDS_LEGAL, ops_cause_code=f.ops_cause_code,
        recoded=False, in_window_dep=dep, in_window_arr=arr, window_margin_min=margin,
        confidence=Confidence(score=0.4, kind="cause", label="cause-finding confidence", features=conf_feats,
                              caps=["capped:no-tier1-evidence"], calibration_version=CAL_VERSION),
        reason="Cause not established from the evidence: outside any storm window and no tier-1 log; asked Ops.",
        evidence=evidence, rules_applied=[], legal_basis=["EU261 Art.5(3)"], outcome="escalated",
        routed_to=Role.OPS, known_at=known_at)


# ---------------------------------------------------------------- entitlements
def entitlements_for(decision: FlightDecision, world: World, rules: Sequence[Rule], known_at: datetime,
                     engine: Any = None) -> list[Entitlement]:
    if engine is not None and hasattr(engine, "entitlements"):
        try:
            from .impls import call
            return list(call(engine.entitlements, decision, world, list(rules), known_at=known_at))
        except Exception:
            pass
    eu = _module("engine.eu261")
    if eu is None:
        return []
    return list(eu.entitlements(decision, world, list(rules), known_at=known_at))


def summarize(ents: Sequence[Entitlement], world: World | None = None, flight: Flight | None = None) -> dict[str, Any]:
    eu = _module("engine.eu261")
    out: dict[str, Any] = dict(eu.summarize(ents)) if eu is not None else {"coupons": len(ents)}
    if ents:
        e = ents[0]
        out.update({"distance_km": e.distance_km, "band_eur": e.band_eur, "band_margin_km": e.band_margin_km})
        if eu is not None and flight is not None:
            try:
                o, d = airport_by(world, flight.origin), airport_by(world, flight.dest)
                if o and d:
                    out["band_note"] = eu.band_for(e.distance_km, o.eu and d.eu).note(e.distance_km)
            except Exception:
                pass
        out["owed"] = sum(1 for x in ents if x.status == "owed")
        out["held"] = sum(1 for x in ents if x.status == "held")
        out["needs_ruling"] = sum(1 for x in ents if x.status == "needs_ruling")
    return out


def sample(ents: Sequence[Entitlement], n: int = 6) -> list[Entitlement]:
    """One entitlement per distinct (status, reduction, refund, voucher) shape, rulings first."""
    seen: dict[tuple, Entitlement] = {}
    for e in sorted(ents, key=lambda e: (e.status != "needs_ruling", e.coupon_id)):
        key = (e.status, e.reduction, e.refund_already_initiated, e.voucher_offset_cents > 0)
        seen.setdefault(key, e)
    return list(seen.values())[:n]


# ---------------------------------------------------------------- questions (fallback grouping)
def group_questions(run_id: str, decisions: Sequence[FlightDecision], ents: dict[str, list[Entitlement]],
                    known_at: datetime, curated: Sequence[Question] = (),
                    extra_case_refs: Iterable[str] = ()) -> list[Question]:
    """One question per (pattern, storm). Curated (stub fixture) questions win when they cover the same cases."""
    held_refs = {d.flight_id for d in decisions if d.outcome == "escalated"}
    ruling_refs = {e.coupon_id for es in ents.values() for e in es if e.status == "needs_ruling"}
    known = held_refs | ruling_refs | set(extra_case_refs)
    out: list[Question] = []
    covered: set[str] = set()
    for q in curated:
        if set(q.case_refs) & known:
            out.append(q.model_copy(update={"asked_at": known_at, "remind_at": known_at + timedelta(hours=3),
                                            "status": "open"}))
            covered |= set(q.case_refs)
    groups: dict[tuple[str, Role], list[FlightDecision]] = defaultdict(list)
    for d in decisions:
        if d.outcome != "escalated" or d.flight_id in covered:
            continue
        pattern = {Cause.KNOCK_ON: "knock_on_return", Cause.CONCURRENT: "concurrent_causes",
                   Cause.UNKNOWN: "data_gap"}.get(d.cause, "new_legal_pattern")
        groups[(pattern, d.routed_to or Role.LEGAL)].append(d)
    n = 0
    for (pattern, role), ds in sorted(groups.items(), key=lambda kv: kv[0][0]):
        n += 1
        refs = [d.flight_id for d in ds]
        holds = sum(e.compensation_cents for fid in refs for e in ents.get(fid, []))
        nums = " / ".join(r.split("@")[0] for r in refs)
        tag = {"knock_on_return": "no-precedent", "concurrent_causes": "concurrent-causes",
               "data_gap": "no-precedent"}.get(pattern, "new-legal-pattern")
        title = {"data_gap": f"What caused {nums}?", "knock_on_return": f"Are the {nums} knock-on returns "
                 "extraordinary?", "concurrent_causes": f"Concurrent causes on {nums}: weather or technical?"}.get(
            pattern, f"New legal pattern on {nums}")
        scores = [d.confidence.score for d in ds if d.confidence.score is not None]
        out.append(Question(
            id=f"Q-{run_id}-{n}", case_refs=refs, pattern=pattern, routed_to=role, asked_at=known_at, title=title,
            found=f"{len(refs)} cancellation(s) at {run_id}: " + "; ".join(d.reason for d in ds[:3]),
            why_flagged="The evidence does not settle the cause; the engine asks instead of guessing.",
            recommends="Hold compensation until ruled; refunds and care still due.",
            recommended_option="Hold until ruled", options=["Hold until ruled", "Extraordinary", "Not extraordinary"],
            evidence=[ev for d in ds[:3] for ev in d.evidence[:2]],
            confidence=ds[0].confidence.model_copy(update={"score": min(scores) if scores else None}),
            reason_tag=tag, holds=refs, holds_cents=holds, status="open", remind_at=known_at + timedelta(hours=3)))
    unsettled = sorted(ruling_refs - covered)
    if unsettled:
        n += 1
        holds = sum(e.compensation_cents for es in ents.values() for e in es if e.coupon_id in unsettled)
        out.append(Question(
            id=f"Q-{run_id}-{n}", case_refs=unsettled, pattern="voucher_in_lieu_unsigned", routed_to=Role.CLAIMS_LEAD,
            asked_at=known_at, title=f"{len(unsettled)} service-desk voucher(s) in lieu without a signed acceptance",
            found="Vouchers 'in lieu of compensation' with no signed acceptance (Art. 7(3)).",
            why_flagged="Sources disagree: CRM says accepted, there is no signature hash.",
            recommends="No signed acceptance, no offset: pay cash; the voucher stays as goodwill.",
            recommended_option="Pay cash; voucher stays as goodwill",
            options=["Pay cash; voucher stays as goodwill", "Offset the voucher"], evidence=[],
            confidence=Confidence(score=0.39, kind="voucher", label="voucher confidence",
                                  features={"in_lieu": 1.0, "signed": 0.0, "sources_disagree": 1.0},
                                  caps=["capped:sources-disagree"], calibration_version=CAL_VERSION),
            reason_tag="sources-disagree", holds=unsettled, holds_cents=holds, status="open",
            remind_at=known_at + timedelta(hours=3)))
    return out


# ---------------------------------------------------------------- run assembly
def counters(flights: Sequence[Flight], decisions: Sequence[FlightDecision], ents: dict[str, list[Entitlement]],
             questions: Sequence[Question]) -> dict[str, int]:
    cancelled = [f for f in flights if f.status == "cancelled"]
    all_ents = [e for es in ents.values() for e in es]
    held_flights = {d.flight_id for d in decisions if d.outcome == "escalated"}
    return {
        "passengers": sum(f.pax for f in cancelled),
        "cancelled": len(cancelled),
        "operated": sum(1 for f in flights if f.status == "operated"),
        "drafted": sum(1 for e in all_ents if e.status in ("owed", "needs_ruling") and e.compensation_cents > 0
                       and e.flight_id not in held_flights),
        "held": sum(1 for e in all_ents if e.status == "held"),
        "questions": len(questions),
        "people": len({q.routed_to for q in questions}),
        "repeat_questions": 0,
        "rules_cited": sum(len(d.rules_applied) for d in decisions) + sum(1 for e in all_ents if e.reduction != "none"),
        "recoded": sum(1 for d in decisions if d.recoded),
        "weather": sum(1 for d in decisions if d.cause == Cause.WEATHER),
    }


def no_storm_message(obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> str | None:
    if windows:
        return None
    if not obs:
        return "no METAR observations for this day · no storm window"
    gusts = [o.gust if o.gust is not None else (o.sknt or 0) for o in obs]
    return f"max gust {max(gusts)} kt · no storm window"


def airports_for(world: World, flights: Sequence[Flight]) -> list[Airport]:
    codes = sorted({c for f in flights for c in (f.origin, f.dest)})
    return [a for a in (airport_by(world, c) for c in codes) if a is not None]


def default_learned(rules: Sequence[Rule]) -> list[LearnedItem]:
    items = []
    for r in rules:
        if r.tier == "mined" and r.status == "active":
            items.append(LearnedItem(text=r.title or f"Mined policy {r.id}", support=r.support,
                                     rule_ref=f"{r.id}@{r.version}"))
    return items


def compose_run(*, world: World, station: str, day: date, flights: Sequence[Flight],
                decisions: Sequence[FlightDecision], ents: dict[str, list[Entitlement]],
                questions: Sequence[Question], learned: Sequence[LearnedItem], liability_drafted_cents: int,
                obs: Sequence[MetarObs], windows: Sequence[StormWindow]) -> StormRun:
    run_id = f"{station}@{day.isoformat()}"
    dec = {d.flight_id: d for d in decisions}
    owed = sum(e.compensation_cents for es in ents.values() for e in es if e.status in ("owed", "needs_ruling"))
    return StormRun(
        id=run_id, station=station, date=day, windows=list(windows), metar=list(obs),
        flights=[FlightRow(flight=f, decision=dec.get(f.id)) for f in flights],
        counters=counters(flights, decisions, ents, questions), entitlement_cents=owed,
        liability_drafted_cents=liability_drafted_cents, learned=list(learned), questions=list(questions), feed=[],
        real_context=dict(world.real_context.get(run_id, {})), message=no_storm_message(obs, windows),
        airports=airports_for(world, flights))


# ---------------------------------------------------------------- flight file
def flight_timeline(world: World, f: Flight, obs: Sequence[MetarObs], windows: Sequence[StormWindow],
                    ents: Sequence[Entitlement]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    lo, hi = f.sched_dep - timedelta(hours=48), f.sched_arr + timedelta(hours=24)
    for t in world.tech_log:
        if t.aircraft == f.aircraft and lo <= t.logged_at <= hi:
            items.append({"at": t.logged_at, "kind": "tech_log", "id": t.id, "text": t.text, "trust_tier": 1,
                          "ata": t.ata, "aog": t.aog, "mel_relief": t.mel_relief})
    for e in world.ops_log:
        if f.id in e.flight_ids or (e.kind in ("mcc", "spares") and (f.aircraft in e.text or
                                                                      f" {f.number}" in f" {e.text}")):
            items.append({"at": e.at, "kind": e.kind, "id": e.id, "text": e.text, "code": e.code,
                          "trust_tier": 1 if e.kind == "mcc" else 3 if e.kind == "occ" else 2})
    mw = main_window(windows)
    if mw is not None:
        items.append({"at": mw.start, "kind": "metar_window_start", "text": f"Storm window opens · peak gust "
                      f"{mw.peak_gust_kt} kt", "station": mw.station})
        items.append({"at": mw.end, "kind": "metar_window_end", "text": "Storm window closes", "station": mw.station})
    for label_, t in (("STD", f.sched_dep), ("STA", f.sched_arr)):
        near = min(obs, key=lambda o: abs((o.valid - t).total_seconds()), default=None)
        if near is not None and abs((near.valid - t).total_seconds()) <= 3600:
            items.append({"at": near.valid, "kind": "metar", "text": near.raw, "station": near.station,
                          "mark": label_, "gust_kt": near.gust, "sknt": near.sknt})
    coupons = {e.coupon_id for e in ents}
    crm = [c for c in world.crm if c.coupon_id in coupons]
    by_kind: dict[str, list] = defaultdict(list)
    for c in crm:
        by_kind[c.kind].append(c)
    for kind, evs in sorted(by_kind.items()):
        evs.sort(key=lambda c: c.at)
        span = hhmm(evs[0].at) if len(evs) == 1 else f"{hhmm(evs[0].at)}–{hhmm(evs[-1].at)}"
        items.append({"at": evs[0].at, "kind": "crm", "text": f"{len(evs)} × {kind.replace('_', ' ')} · {span}",
                      "count": len(evs), "crm_kind": kind})
    items.sort(key=lambda x: (x["at"], x["kind"]))
    return [{**x, "at": x["at"].astimezone(UTC).isoformat().replace("+00:00", "Z")} for x in items]


def handoff(ents: Sequence[Entitlement]) -> dict[str, Any] | None:
    n = sum(1 for e in ents if e.refund_already_initiated)
    if not n:
        return None
    owed = any(e.status in ("owed", "needs_ruling") for e in ents)
    return {"refunds_already_initiated": n, "not_repeated": True, "rights_notices_drafted": n if owed else 0,
            "drafter_pii_seen": 0}


def template_explanation(d: FlightDecision) -> Draft:
    return Draft(id=f"DRAFT-EXPL-{d.flight_id}", kind="explanation", text=d.reason, numbers_verified=True,
                 template_fallback=True)


def flight_file(world: World, f: Flight, d: FlightDecision, ents: Sequence[Entitlement],
                journal: Sequence[JournalEntry], obs: Sequence[MetarObs], windows: Sequence[StormWindow],
                explanation: Draft | None) -> FlightFile:
    jes = [je for je in journal if any(line.dims.get("flight") == f.id for line in je.lines)]
    return FlightFile(flight=f, decision=d, entitlements_summary=summarize(ents, world, f),
                      sample_entitlements=sample(ents), journal_preview=jes,
                      timeline=flight_timeline(world, f, obs, windows, ents), handoff=handoff(ents),
                      explanation=explanation)


def status_counts(ents: Iterable[Entitlement]) -> Counter:
    return Counter(e.status for e in ents)
