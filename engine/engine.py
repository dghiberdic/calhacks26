"""The deterministic engine (``EngineAPI``): decide each cancellation's cause, work out entitlements, group what
it cannot settle into questions for the right person, and assemble the ``StormRun``.

``decide(flight_id, facts, rules, known_at, calibration_version)`` is bitemporal: it sees facts recorded by
``known_at`` and rules in force at ``known_at`` for the flight's date. The engine holds the base ``World``
(schedule, logs, METAR); ``facts`` are overlaid on it (``engine.case.overlay_facts``).

Pure: no LLM, no wall clock, no randomness. Same inputs, same outputs, same hashes.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from contracts.models import (
    Airport,
    Cause,
    Confidence,
    Entitlement,
    Extraordinary,
    Fact,
    FlightDecision,
    FlightRow,
    Role,
    Rule,
    RuleAction,
    RuleProposal,
    Source,
    StormRun,
    TraceEvent,
    World,
)
from engine import confidence as conf
from engine import dsl, eu261, routing
from engine import rules as rulebook
from engine.case import FlightCase, build_case, overlay_facts, station_obs, stations_for
from engine.cause import Finding, deciding_margin, find_cause, recode_label
from engine.geo import UnknownAirport, airport, distance_km, route_region
from engine.timeline import storm_windows

CAUSE_ACTIONS = (RuleAction.SET_EXTRAORDINARY, RuleAction.SET_NOT_EXTRAORDINARY)
CAUSE_RULE_TIERS = frozenset({"hard_control", "regulation", "legal_ruling"})   # who may settle extraordinary
RULING_TIERS = frozenset({"hard_control", "regulation", "legal_ruling", "controller_ruling", "claims_lead_ruling"})
RULE_PRECEDENT_WEIGHT = 10        # a binding ruling counts as a full set of precedents (capped at 10)
# patterns with a grounded aircraft in play: a ruling that says nothing about the AOG cannot settle them
AOG_PATTERNS = frozenset({"concurrent_causes", "external_event", "technical_internal"})


def may_settle(rule: Rule, pattern: str) -> bool:
    """A cause ruling settles only the pattern it was ruled on (``scope.pattern``, checked by the DSL) and never an
    AOG pattern unless its condition is about the AOG (``aog.*``)."""
    if pattern in AOG_PATTERNS:
        return any(str(c.get("f", "")).startswith("aog.") for c in dsl.clauses(rule.condition))
    return True


def notice_exemption(flight: Any) -> str | None:
    """Art. 5(1)(c)(i) when the passengers were told ≥ 14 days before STD (``eu261.flight_notice_exemption``)."""
    helper = getattr(eu261, "flight_notice_exemption", None)
    if helper is not None:
        return helper(flight)
    got = eu261.notice_exemption(flight, None)          # with no election only sub-paragraph (i) can apply
    return got if got == "Art.5(1)(c)(i)" else None

# Expected ultimate claim rate by band (Books' curves: LH .35, MH .27, SH .20); the engine uses it only for the
# materiality gate and the run's "drafted" preview. Books owns the booked number.
DEFAULT_CLAIM_RATES: dict[int, Fraction] = {600: Fraction(35, 100), 400: Fraction(27, 100), 250: Fraction(20, 100)}
SEGMENT = {600: "long_haul_gt3500", 400: "medium_1500_3500", 250: "short_le1500"}
ACCRUING = frozenset({"owed", "held", "needs_ruling"})


def round_half_away(x: Fraction) -> int:
    n = abs(x)
    q = int(n)
    if n - q >= Fraction(1, 2):
        q += 1
    return q if x >= 0 else -q


def expected_liability(ents: Sequence[Entitlement], rates: dict[int, Fraction] = DEFAULT_CLAIM_RATES) -> int:
    """Σ accruing compensation × segment rate, rounded once per (flight, segment), half away from zero."""
    buckets: dict[tuple[str, int], int] = {}
    for e in ents:
        if e.status in ACCRUING:
            k = (e.flight_id, e.band_eur)
            buckets[k] = buckets.get(k, 0) + e.compensation_cents
    return sum(round_half_away(v * rates[band]) for (_, band), v in sorted(buckets.items()))


@dataclass
class Evaluated:
    case: FlightCase
    finding: Finding
    features: dict[str, Any]
    rules_applied: list[str] = field(default_factory=list)
    settled_by: Rule | None = None


class Engine:
    """``EngineAPI`` implementation. ``world`` is the base the ``decide`` facts are overlaid on."""

    def __init__(self, world: World | None = None, *, calibration: dict[str, Any] | None = None,
                 claim_rates: dict[int, Fraction] | None = None, engine_version: str = "engine@dev"):
        self.world = world
        self.calibration = calibration if calibration is not None else conf.load_calibration()
        self.claim_rates = claim_rates or DEFAULT_CLAIM_RATES
        self.engine_version = engine_version

    @property
    def calibration_version(self) -> str:
        return str(self.calibration.get("version", "uncalibrated"))

    # ---------- EngineAPI ----------

    def decide(self, flight_id: str, facts: list[Fact], rules: list[Rule], known_at: datetime,
               calibration_version: str | None = None, *, sources: Sequence[Source] = ()) -> FlightDecision:
        """``sources``: documents the facts come from that the base world doesn't hold (an injected tech-log line).
        Their kind caps their tier; a fact whose source is found nowhere is tier 4."""
        if self.world is None:
            raise ValueError("Engine.decide needs the base world (Engine(world=...))")
        world = overlay_facts(self.world, facts, known_at, sources)
        return self.decide_in(world, flight_id, rules, known_at)

    def entitlements(self, decision: FlightDecision, world: World, rules: list[Rule]) -> list[Entitlement]:
        return eu261.entitlements(decision, world, rules, decision.known_at)

    def mine_rules(self, world: World) -> list[RuleProposal]:
        from engine import miner  # D7

        return miner.mine_rules(world)

    def run_storm(self, world: World, station: str, local_day: date, rules: list[Rule],
                  known_at: datetime) -> StormRun:
        from engine.storm import run_storm

        return run_storm(self, world, station, local_day, rules, known_at)

    # ---------- deciding ----------

    def evaluate(self, world: World, flight_id: str, rules: Sequence[Rule], known_at: datetime,
                 stations=None, _depth: int = 0) -> Evaluated:
        stations = stations or stations_for(world, known_at)
        case = build_case(world, flight_id, known_at, stations)
        prev_eval: Evaluated | None = None
        if case.prev is not None and case.prev.status == "cancelled" and _depth < 3:
            prev_eval = self.evaluate(world, case.prev.id, rules, known_at, stations, _depth + 1)
        finding = find_cause(case, prev_eval.finding if prev_eval else None)
        feats = flight_features(world, case, finding, prev_eval.finding if prev_eval else None)
        ev = Evaluated(case, finding, feats)
        self._apply_cause_rules(ev, rules, known_at)
        return ev

    def _apply_cause_rules(self, ev: Evaluated, rules: Sequence[Rule], known_at: datetime) -> None:
        """Only a Legal ruling settles or overrides ``extraordinary``; regulation cards and agreeing rules are cited.

        A generic regulation card (e.g. "in window at either end → extraordinary") never flips a case the engine
        sent to Legal (a concurrent AOG sits in the window too). Two equal Legal rulings that disagree → Legal.
        """
        f = ev.finding
        when = dict(known_at=known_at, flight_date=ev.case.flight.date)

        def want(r: Rule) -> Extraordinary:
            return Extraordinary.YES if r.action == RuleAction.SET_EXTRAORDINARY else Extraordinary.NO

        settling = [r for r in rules if r.action not in CAUSE_ACTIONS or may_settle(r, f.pattern)]
        legal = rulebook.resolve(settling, ev.features, actions=CAUSE_ACTIONS, tiers={"legal_ruling"}, **when)
        if legal.conflicted:
            f.extraordinary, f.route, f.pattern = Extraordinary.NEEDS_LEGAL, Role.LEGAL, "rule_conflict"
            f.reason_tag = "new-legal-pattern"
            f.caps.append("capped:rule-conflict")
            f.reason = (f"{f.reason.rstrip('.')}. Conflicting rulings "
                        f"{', '.join(dsl.ref(r) for r in legal.conflict)}: Legal to resolve.")
        elif legal.rule is not None and want(legal.rule) != f.extraordinary:
            r = legal.rule
            ev.rules_applied.append(dsl.ref(r))
            f.extraordinary = want(r)
            ev.settled_by = r
            f.route = None
            f.reason = f"{f.reason.rstrip('.')}. Settled by {dsl.ref(r)}" + (f" ({r.title})." if r.title else ".")
        else:
            cited = rulebook.resolve(settling, ev.features, actions=CAUSE_ACTIONS, tiers=CAUSE_RULE_TIERS, **when)
            agree = next((r for r in cited.hits if want(r) == f.extraordinary), None)
            if agree is not None:
                ev.rules_applied.append(dsl.ref(agree))
        if f.extraordinary == Extraordinary.NEEDS_LEGAL:
            routes = rulebook.resolve(rules, ev.features, actions=[RuleAction.ROUTE_TO],
                                      tiers=RULING_TIERS - {"hard_control", "regulation"}, **when)
            if routes.rule is not None and routes.rule.action_arg:
                try:
                    target = Role(routes.rule.action_arg)
                except ValueError:
                    target = None
                # a Legal pattern stays with Legal whatever a routing rule says (only Legal settles law)
                if target is not None and not (routing.role_for(f.pattern) == Role.LEGAL and target != Role.LEGAL):
                    f.route = target
                    ev.rules_applied.append(dsl.ref(routes.rule))

    def cause_confidence(self, world: World, ev: Evaluated) -> Confidence:
        f, case = ev.finding, ev.case
        n_hist = sum(1 for h in world.history_cases if h.kind == f.pattern)
        n_rules = sum(1 for r in ev.rules_applied if not r.startswith("R-HC"))
        precedent = conf.precedents(n_hist + RULE_PRECEDENT_WEIGHT * n_rules)
        aog = case.aog if case.aog is not None and case.aog.decisive else None
        feats = {
            "in_window_dep": conf.pos(case.dep.position),
            "in_window_arr": conf.pos(case.arr.position),
            "window_margin_h": conf.margin_h(deciding_margin(case)),
            "aog_before_window": 1.0 if aog is not None and aog.before_window else 0.0,
            "aog_inside_window": 1.0 if aog is not None and aog.inside_window else 0.0,
            "root_cause_internal": 1.0 if aog is not None and aog.cls.internal else 0.0,
            "sources_disagree": 1.0 if f.sources_disagree else 0.0,
            "precedent_count": precedent,
            "knock_on": 1.0 if f.cause == Cause.KNOCK_ON else 0.0,
            "concurrent_causes": 1.0 if f.cause == Cause.CONCURRENT else 0.0,
            "in_event_window": 1.0 if case.event_in else 0.0,
            "internal_cause_logged": 1.0 if f.pattern == "internal_cause_logged" else 0.0,
        }
        caps = list(f.caps)
        if precedent == 0 and f.extraordinary == Extraordinary.NEEDS_LEGAL and f.reason_tag == "no-precedent":
            caps.append("capped:no-precedent")
        return conf.score("cause", feats, self.calibration, caps)

    def decide_in(self, world: World, flight_id: str, rules: Sequence[Rule], known_at: datetime, *,
                  stations=None, storm_id: str | None = None) -> FlightDecision:
        ev = self.evaluate(world, flight_id, rules, known_at, stations)
        return self.to_decision(world, ev, rules, known_at, storm_id)

    def to_decision(self, world: World, ev: Evaluated, rules: Sequence[Rule], known_at: datetime,
                    storm_id: str | None = None) -> FlightDecision:
        f, case = ev.finding, ev.case
        c = self.cause_confidence(world, ev)
        dec = FlightDecision(
            flight_id=case.flight.id, cause=f.cause, extraordinary=f.extraordinary,
            ops_cause_code=case.ops_code, recoded=f.recoded, recode_label=recode_label(case.ops_code, f.new_code)
            if f.recoded else None,
            in_window_dep=case.any_position("dep"), in_window_arr=case.any_position("arr"),
            window_margin_min=deciding_margin(case), confidence=c, reason=f.reason, evidence=f.evidence,
            rules_applied=list(dict.fromkeys(ev.rules_applied)), legal_basis=f.legal_basis, outcome="auto",
            routed_to=None, question_id=None, known_at=known_at)
        exempt = notice_exemption(case.flight)
        if exempt is not None:
            # Art. 5(1)(c)(i): no compensation whatever the cause, so the cause question is moot; refunds and care
            # still apply (eu261 returns exempt_notice per coupon). The cause found is kept as recorded.
            days = (case.flight.sched_dep - case.flight.notified_at).days if case.flight.notified_at else None
            return dec.model_copy(update={
                "extraordinary": Extraordinary.NO if f.extraordinary == Extraordinary.NEEDS_LEGAL else f.extraordinary,
                "reason": f"{f.reason.rstrip('.')}. Notice ≥14 days ({days} days), Art. 5(1)(c)(i): no compensation "
                          "whatever the cause; refunds and care still due.",
                "legal_basis": list(dict.fromkeys([f"EU261 {exempt}", *f.legal_basis])),
                "outcome": "auto", "routed_to": None, "question_id": None})
        liability = 0
        if f.extraordinary == Extraordinary.NO:
            liability = expected_liability(eu261.entitlements(dec, world, list(rules), known_at), self.claim_rates)
        r = routing.route(extraordinary=f.extraordinary, confidence=c, pattern=f.pattern, liability_cents=liability,
                          role=f.route, settled_by_rule=ev.settled_by is not None)
        qid = None
        if r.outcome == "escalated":
            # one question per external event, whichever station's run asks it
            sid = (case.event.event.id if f.pattern == "external_event_window" and case.event is not None
                   else storm_id or default_storm_id(world, case))
            qid = question_id(world, sid, f.pattern)
        return dec.model_copy(update={"outcome": r.outcome, "routed_to": r.routed_to, "question_id": qid})


# ---------- features ----------

def flight_features(world: World, case: FlightCase, finding: Finding, prev: Finding | None) -> dict[str, Any]:
    """DSL features (CONTRACTS §4) for flight-level rules, plus the ``pattern`` context key (the question a cause
    ruling answers). Spares are blanked whenever an AOG grounds the tail (technical or concurrent causes)."""
    fl = case.flight
    dist = distance_km(world, fl.origin, fl.dest)
    band = eu261.band_for(dist, case.origin.eu and case.dest.eu)
    aog = case.aog
    technical = finding.cause in (Cause.TECHNICAL, Cause.CONCURRENT)
    return {
        "flight.in_window_dep": case.dep.position,
        "flight.in_window_arr": case.arr.position,
        "flight.window_margin_min": deciding_margin(case),
        "flight.distance_km": dist,
        "flight.band_eur": band.eur,
        "flight.departs_eu": case.origin.eu,
        "flight.arrives_eu": case.dest.eu,
        "flight.operating_carrier_eu": fl.operating_carrier_eu,
        "flight.route_region": route_region(case.origin, case.dest),
        "flight.ops_cause_code": case.ops_code,
        "flight.is_return_sector": fl.outbound_pair_id is not None,
        "aog.before_window": aog.before_window if aog else None,
        "aog.inside_window": aog.inside_window if aog else None,
        "aog.ata_chapter": aog.cls.chapter if aog else None,
        "aog.root_cause_internal": aog.cls.internal if aog else None,
        "aog.mel_relief": aog.entry.mel_relief if aog else None,
        "flight.in_event_window_dep": case.dep_event.position if case.dep_event else None,
        "flight.in_event_window_arr": case.arr_event.position if case.arr_event else None,
        "event.kind": case.event.event.kind if case.event else None,
        "rotation.prev_cancelled": (case.prev.status == "cancelled") if case.prev else None,
        "rotation.prev_cause": prev.cause.value if prev else None,
        "spare.available_within_h": None if technical else case.spare_within_h,
        "pax.notice_days": eu261.notice_days(fl),
        "pax.reroute_earliest_offered": case.reroute_earliest_offered,
        "sources.disagree": finding.sources_disagree,
        "precedent.count": sum(1 for h in world.history_cases if h.kind == finding.pattern),
        "flight": fl.id,
        "station": case.origin.icao,
        "pattern": finding.pattern,
    }


# ---------- ids ----------

# Short ids for the world's primary storm match the stub and the demo script (Q-1 voucher, Q-2 knock-on, Q-3 the
# cohort release); every other storm gets ids qualified by storm, so runs never collide in a store.
PATTERN_NO = {
    "voucher_in_lieu_unsigned": 1, "knock_on_return": 2, "cohort_release": 3, "concurrent_causes": 4,
    "external_event": 5, "weather_code_contradicted": 6, "window_unknown": 7, "cause_unknown": 8,
    "technical_unverified": 9, "crew": 10, "atc": 11, "new_legal_pattern": 12, "rule_conflict": 13,
    "occ_code_in_window": 14, "airport_restriction": 15, "aog_unverified": 16,
}


def primary_storm(world: World) -> str | None:
    """``meta.primary_storm``, else the earliest of ``meta.storms``; ``None`` if the world lists no storms."""
    storms = world.meta.get("storms") if isinstance(world.meta, dict) else None
    if not isinstance(storms, dict) or not storms:
        return None
    if world.meta.get("primary_storm") in storms:
        return str(world.meta["primary_storm"])

    def key(k: str) -> tuple[str, str]:
        v = storms[k]
        d = v.get("local_date") if isinstance(v, dict) else None
        return (str(d or k.split("@")[-1]), k)
    return min(storms, key=key)


def question_id(world: World, storm_id: str, pattern: str) -> str:
    if pattern in PATTERN_NO and storm_id == primary_storm(world):
        return f"Q-{PATTERN_NO[pattern]}"
    return f"Q-{storm_id}:{pattern}"


def cohort_question_id(world: World, cohort: str) -> str:
    if primary_storm(world) is not None and len({o.cohort for o in world.opening_balances}) == 1:
        return f"Q-{PATTERN_NO['cohort_release']}"
    return f"Q-{cohort}:cohort_release"


def default_storm_id(world: World, case: FlightCase) -> str:
    from engine.cause import main_window

    w = main_window(case)
    if w is not None:
        return f"{w.station}@{w.start.date().isoformat()}"
    return f"{case.origin.icao}@{case.flight.date.isoformat()}"


def local_day_span(ap: Airport | None, day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of a local calendar day at the airport."""
    tz = ZoneInfo(ap.tz) if ap is not None and ap.tz else ZoneInfo("UTC")
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    utc = ZoneInfo("UTC")
    return start.astimezone(utc), end.astimezone(utc)


def station_airport(world: World, station: str) -> Airport | None:
    try:
        return airport(world, station)
    except UnknownAirport:
        return None

