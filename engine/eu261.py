"""D3 · EU261 entitlements per coupon: scope (Art. 3), notice (Art. 5(1)(c)), bands (Art. 7(1)), the Art. 7(2)
reduction (only under an active mined policy), vouchers (Art. 7(3)), refunds (Art. 8) and care (Art. 9).

A coupon is final (``owed`` / ``no_compensation``) only when its flight's decision is ``auto``; an escalated or
batch-review decision holds every in-scope coupon at its band (Books accrues it under IFRS 15.56). Bands use the
unrounded distance (``engine.geo.distance_km``); ``Entitlement.distance_km`` is rounded for display.

The engine computes every amount; the LLM never does. Money is integer euro cents. Pure: no wall clock, no
randomness. ``known_at`` filters CRM events (an event recorded later is not known yet).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from contracts.models import (
    Airport,
    Coupon,
    CrmEvent,
    Election,
    Entitlement,
    Extraordinary,
    Flight,
    FlightDecision,
    Rule,
    RuleAction,
    World,
)
from engine import dsl
from engine import rules as rulebook
from engine.geo import airport, display_km, distance_km, route_region

SHORT_KM = 1500.0
LONG_KM = 3500.0
BAND_LETTER = {250: "a", 400: "b", 600: "c"}
REDUCTION_LIMIT_MIN = {250: 120, 400: 180, 600: 240}   # Art. 7(2)(a)/(b)/(c), by the same distance classes
REROUTE_KINDS = frozenset({"reroute_partner", "reaccommodated_own"})
REFUND_EVENT_KINDS = frozenset({"refund_initiated", "bsp_refund"})
OFFSET_TIERS = frozenset({"legal_ruling"})     # statutory floor: only Legal may lower EU261 compensation (plan §2.4)
SELF_SERVICE = frozenset({"web"})              # the passenger chose it themselves: their own (electronic) agreement


# ---------- bands ----------

@dataclass(frozen=True)
class Band:
    eur: Literal[250, 400, 600]
    margin_km: float          # distance to the threshold that would change the band (always >= 0)
    threshold_km: float
    intra_eu: bool

    @property
    def cents(self) -> int:
        return self.eur * 100

    @property
    def letter(self) -> str:
        return BAND_LETTER[self.eur]

    def note(self, distance: float) -> str:
        """e.g. "1,486 km · 14 km under the €400 band"."""
        if self.eur == 250:
            return f"{distance:,.0f} km · {self.margin_km:,.0f} km under the €400 band"
        if self.eur == 600:
            return f"{distance:,.0f} km · {self.margin_km:,.0f} km over the €600 threshold"
        if self.threshold_km == SHORT_KM:
            return f"{distance:,.0f} km · {self.margin_km:,.0f} km over the €400 threshold"
        return f"{distance:,.0f} km · {self.margin_km:,.0f} km under the €600 band"


def band_for(distance: float, intra_eu: bool) -> Band:
    """Art. 7(1): (a) <=1,500 km €250; (b) intra-EU >1,500 km, or other 1,500-3,500 km, €400; (c) else €600."""
    if distance <= SHORT_KM:
        return Band(250, round(SHORT_KM - distance, 1), SHORT_KM, intra_eu)
    if intra_eu:
        return Band(400, round(distance - SHORT_KM, 1), SHORT_KM, intra_eu)
    if distance <= LONG_KM:
        lo, hi = distance - SHORT_KM, LONG_KM - distance
        return Band(400, round(min(lo, hi), 1), SHORT_KM if lo <= hi else LONG_KM, intra_eu)
    return Band(600, round(distance - LONG_KM, 1), LONG_KM, intra_eu)


# ---------- scope ----------

def scope_article(origin: Airport, dest: Airport, operating_carrier_eu: bool) -> str | None:
    """Art. 3(1): (a) departs EU261 territory; (b) arrives there on an EU carrier. ``None`` = out of scope."""
    if origin.eu:
        return "Art.3(1)(a)"
    if dest.eu and operating_carrier_eu:
        return "Art.3(1)(b)"
    return None


# ---------- notice ----------

def notice_days(flight: Flight) -> float | None:
    if flight.notified_at is None:
        return None
    return (flight.sched_dep - flight.notified_at) / timedelta(days=1)


def flight_notice_exemption(flight: Flight) -> str | None:
    """``"Art.5(1)(c)(i)"`` when passengers were told >= 14 days before STD (``Flight.notified_at``), else ``None``.

    It covers every passenger on the flight, so the cause is moot for compensation: the cause stage can call this
    before routing a cause question. Refunds or re-routing (Art. 8) and care (Art. 9) are still owed. (ii)/(iii) are
    per passenger (``notice_exemption``) and need the offered reroute's departure time.
    """
    days = notice_days(flight)
    return "Art.5(1)(c)(i)" if days is not None and days >= 14 else None


def notice_exemption(flight: Flight, election: Election | None,
                     departure_advance_min: int | None = None) -> str | None:
    """Art. 5(1)(c) sub-paragraph if exempt, else ``None``.

    (i) >= 14 days. (ii) 7-14 days with a reroute leaving <= 2 h early and arriving < 4 h late. (iii) < 7 days with
    a reroute leaving <= 1 h early and arriving < 2 h late. ``Election`` carries no rerouted departure time, so
    (ii)/(iii) need ``departure_advance_min`` from the caller; without it the carrier has not shown the condition
    and the passenger is not exempt (see engine/DECISIONS.md D3).

    The Regulation keys (ii)/(iii) on the reroute being *offered*, not on the passenger taking it. No world model
    carries an offered reroute's departure time, so ``entitlements`` never passes ``departure_advance_min`` and
    (ii)/(iii) never fire: a conservative overpay (the passenger is paid), never an underpay.
    """
    days = notice_days(flight)
    if days is None:
        return None
    if flight_notice_exemption(flight):
        return "Art.5(1)(c)(i)"
    if election is None or election.kind not in REROUTE_KINDS or departure_advance_min is None:
        return None
    delay = arrival_delay_min(flight, election)
    if delay is None:
        return None
    if 7 <= days < 14 and departure_advance_min <= 120 and delay < 240:
        return "Art.5(1)(c)(ii)"
    if days < 7 and departure_advance_min <= 60 and delay < 120:
        return "Art.5(1)(c)(iii)"
    return None


def arrival_delay_min(flight: Flight, election: Election | None) -> int | None:
    if election is None:
        return None
    if election.arrival_delay_min is not None:
        return election.arrival_delay_min
    if election.new_arrival is not None:
        return round((election.new_arrival - flight.sched_arr) / timedelta(minutes=1))
    return None


# ---------- per-coupon world view ----------

@dataclass(frozen=True)
class CouponView:
    coupon: Coupon
    election: Election | None
    crm: tuple[CrmEvent, ...]          # known by known_at, sorted by time

    def events(self, *kinds: str) -> list[CrmEvent]:
        return [e for e in self.crm if e.kind in kinds]

    @property
    def in_lieu(self) -> CrmEvent | None:
        ev = self.events("voucher_in_lieu_of_compensation")
        return ev[-1] if ev else None


def coupon_views(world: World, flight_id: str, known_at: datetime | None) -> list[CouponView]:
    elections: dict[str, Election] = {}
    for e in world.elections:
        elections[e.coupon_id] = e            # last one wins
    crm: dict[str, list[CrmEvent]] = {}
    for ev in world.crm:
        if known_at is None or ev.at <= known_at:
            crm.setdefault(ev.coupon_id, []).append(ev)
    out = []
    for c in world.coupons:
        if c.flight_id != flight_id:
            continue
        evs = tuple(sorted(crm.get(c.id, []), key=lambda e: (e.at, e.id)))
        out.append(CouponView(c, elections.get(c.id), evs))
    return out


def coupon_features(flight: Flight, view: CouponView, band: Band, dist: float, origin: Airport, dest: Airport,
                    decision: FlightDecision | None = None) -> dict[str, Any]:
    """DSL features (CONTRACTS §4) for entitlement-level rules."""
    v = view.in_lieu
    feats: dict[str, Any] = {
        "flight.distance_km": dist,
        "flight.band_eur": band.eur,
        "flight.departs_eu": origin.eu,
        "flight.arrives_eu": dest.eu,
        "flight.operating_carrier_eu": flight.operating_carrier_eu,
        "flight.route_region": route_region(origin, dest),
        "flight.ops_cause_code": flight.ops_cause_code,
        "flight.is_return_sector": flight.outbound_pair_id is not None,
        "pax.notice_days": notice_days(flight),
        "pax.arrival_delay_min": arrival_delay_min(flight, view.election),
        "pax.election": view.election.kind if view.election else "none",
        "pax.fare_type": view.coupon.fare_type,
        "voucher.in_lieu": v is not None,
        "voucher.signed": bool(v.signed_acceptance_sha256) if v is not None else None,
        "voucher.amount_cents": v.amount_cents if v is not None else None,
        "flight": flight.id,
        "coupon": view.coupon.id,
    }
    if decision is not None:
        feats["flight.in_window_dep"] = decision.in_window_dep
        feats["flight.in_window_arr"] = decision.in_window_arr
        feats["flight.window_margin_min"] = decision.window_margin_min
    return feats


# ---------- entitlement ----------

def _flight(world: World, flight_id: str) -> Flight:
    for f in world.flights:
        if f.id == flight_id:
            return f
    raise KeyError(flight_id)


def signed_refund_voucher(view: CouponView) -> CrmEvent | None:
    """The latest known ``voucher_issued`` event with the passenger's signed agreement (Art. 7(3)), if any."""
    ev = [e for e in view.events("voucher_issued") if e.signed_acceptance_sha256]
    return ev[-1] if ev else None


def voucher_agreed(view: CouponView) -> bool:
    """Art. 8(1)(a) via Art. 7(3): the passenger agreed to be reimbursed in a travel voucher.

    Either a known signed ``voucher_issued`` event, or a voucher the passenger elected themselves through
    self-service (``Election.recorded_by == "web"``: an authenticated acceptance, a simple electronic signature).
    A voucher recorded *for* the passenger (service desk, call centre, OCC, CRM bot) needs the signed event.
    """
    if signed_refund_voucher(view) is not None:
        return True
    return view.election is not None and view.election.recorded_by in SELF_SERVICE


def _refund(view: CouponView) -> tuple[int, bool, list[str]]:
    """Art. 8(1)(a): (refund_due_cents, reimbursement already made, reason notes).

    - A carrier refund (CRM bot or BSP) is the reimbursement: nothing more is due; a second refund or a later
      chargeback is flagged as a duplicate.
    - A chargeback with no carrier refund is the reimbursement too (the card scheme returned the money): nothing
      more is due, and it is flagged as a possible duplicate (e.g. the passenger also took re-routing).
    - A refund voucher reimburses only with the passenger's signed agreement (Art. 8(1)(a) via Art. 7(3),
      ``voucher_agreed``): without it the refund is still due in money, flagged.
    - A refund election with nothing paid yet: due.
    """
    refunds = view.events(*REFUND_EVENT_KINDS)
    chargebacks = view.events("chargeback")
    due = view.coupon.fare_cents + view.coupon.taxes_cents
    if refunds:
        notes = ["refund already initiated, not repeated"]
        if len(refunds) > 1:
            notes.append(f"duplicate refund ({' + '.join(sorted({e.kind for e in refunds}))}) flagged, not repeated")
        elif chargebacks:
            notes.append("chargeback after a refund flagged as a duplicate, not repeated")
        return 0, True, notes
    kind = view.election.kind if view.election is not None else None
    if chargebacks:
        note = ("chargeback: the card scheme already reimbursed the ticket; flagged as a possible duplicate, "
                "not repeated")
        if kind in REROUTE_KINDS:
            note += " (the passenger also took re-routing, Art. 8(1)(b): contest the chargeback)"
        return 0, True, [note]
    if kind == "refund":
        return due, False, []
    if kind == "voucher":
        if voucher_agreed(view):
            return 0, False, []
        return due, False, [f"refund voucher recorded by {view.election.recorded_by} with no signed agreement on file "
                            f"(Art. 8(1)(a), Art. 7(3)): refund of €{due / 100:,.2f} due in money, flagged"]
    return 0, False, []


def entitlements(decision: FlightDecision, world: World, rules: Sequence[Rule] = (),
                 known_at: datetime | None = None) -> list[Entitlement]:
    """One ``Entitlement`` per coupon on a cancelled flight (operated/delayed flights: none)."""
    flight = _flight(world, decision.flight_id)
    if flight.status != "cancelled":
        return []
    known_at = known_at or decision.known_at
    origin, dest = airport(world, flight.origin), airport(world, flight.dest)
    dist = distance_km(world, flight.origin, flight.dest)
    band = band_for(dist, origin.eu and dest.eu)
    scope = scope_article(origin, dest, flight.operating_carrier_eu)
    return [_one(flight, v, band, dist, origin, dest, scope, decision, rules, known_at)
            for v in coupon_views(world, flight.id, known_at)]


def _one(flight: Flight, view: CouponView, band: Band, dist: float, origin: Airport, dest: Airport,
         scope: str | None, decision: FlightDecision, rules: Sequence[Rule], known_at: datetime) -> Entitlement:
    c = view.coupon
    refund_due, refund_init, refund_notes = _refund(view)
    base = dict(coupon_id=c.id, flight_id=flight.id, distance_km=display_km(dist), band_eur=band.eur,
                band_margin_km=band.margin_km)

    def ent(status: str, article: str, reason: list[str], *, comp: int = 0, care: bool = True,
            reduction: str = "none", offset: int = 0, applied: Iterable[str] = ()) -> Entitlement:
        return Entitlement(**base, compensation_cents=comp, reduction=reduction, refund_due_cents=refund_due,
                           refund_already_initiated=refund_init, care_due=care, voucher_offset_cents=offset,
                           status=status, article=article, reason="; ".join(reason + refund_notes) + ".",
                           rules_applied=list(dict.fromkeys(applied)))

    if scope is None:
        return ent("out_of_scope", "EU261 Art.3(1)", [
            f"Out of scope: departs {origin.iata} outside the EU on a non-EU carrier"], care=False)
    if c.fare_type == "staff_id90":
        return ent("staff_ticket", "EU261 Art.3(3)", [
            "Staff ID90 ticket at a fare not available to the public: no compensation"], care=False)

    election = view.election
    exempt = notice_exemption(flight, election)
    if exempt is not None:
        return ent("exempt_notice", f"EU261 {exempt}", [
            f"Cancellation notified {notice_days(flight):.0f} days before departure: no compensation; "
            "refunds and care still due"])

    art7 = f"Art.7(1)({band.letter})"
    feats = coupon_features(flight, view, band, dist, origin, dest, decision)
    flight_rules = list(decision.rules_applied)

    if decision.extraordinary == Extraordinary.NEEDS_LEGAL or decision.outcome != "auto":
        # not final: escalated (a person is asked) or batch review. Held at the band, never no_compensation/owed.
        who = decision.question_id or (f"{decision.routed_to.value.replace('_', ' ')} review"
                                       if decision.routed_to else "review")
        return ent("held", f"EU261 Art.5(3), {art7}", [
            f"Held pending {who}: €{band.eur} owed unless the cancellation is extraordinary"],
            comp=band.cents, applied=flight_rules)
    if decision.extraordinary == Extraordinary.YES:
        return ent("no_compensation", "EU261 Art.5(3)", [
            "Extraordinary circumstances: no compensation; refunds and care still due"], applied=flight_rules)

    # not extraordinary -> compensation owed
    comp, reduction, applied = band.cents, "none", list(flight_rules)
    articles = [art7]
    reason = [f"Compensation owed: €{band.eur} ({band.note(dist)})"]
    delay = feats["pax.arrival_delay_min"]
    if election is not None and election.kind in REROUTE_KINDS and delay is not None \
            and delay <= REDUCTION_LIMIT_MIN[band.eur]:
        hits = dsl.matching(rules, feats, actions=[RuleAction.APPLY_7_2_REDUCTION], known_at=known_at,
                            flight_date=flight.date)
        if hits:
            comp = band.cents // 2
            reduction = "art7_2_50pct"
            applied.append(dsl.ref(hits[0]))
            articles.append(f"Art.7(2)({band.letter})")
            reason = [f"Compensation owed: €{band.eur} less 50% (rerouted, arrived {delay} min late, within "
                      f"{REDUCTION_LIMIT_MIN[band.eur] // 60} h)"]
    if refund_due or refund_init:
        articles.append("Art.8(1)(a)")

    voucher = view.in_lieu
    if voucher is not None:
        articles.append("Art.7(3)")
        if voucher.signed_acceptance_sha256:
            offset = min(voucher.amount_cents, comp)
            return ent("owed", "EU261 " + ", ".join(articles), reason + [
                f"signed acceptance of the €{voucher.amount_cents // 100} voucher in lieu: offset €{offset // 100}"],
                comp=comp, reduction=reduction, offset=offset, applied=applied)
        # statutory floor: an ALLOW_OFFSET lowers EU261 compensation, so only a Legal ruling can apply it
        floor = [r for r in dsl.matching(rules, feats, actions=[RuleAction.ALLOW_OFFSET], known_at=known_at,
                                         flight_date=flight.date) if r.tier not in OFFSET_TIERS]
        allowed = [r for r in rules if r.action != RuleAction.ALLOW_OFFSET or r.tier in OFFSET_TIERS]
        res = rulebook.resolve(allowed, feats, actions=[RuleAction.DENY_OFFSET, RuleAction.ALLOW_OFFSET],
                               known_at=known_at, flight_date=flight.date)
        ignored = ([f"{', '.join(dsl.ref(r) for r in floor)} ignored: only a Legal ruling may offset an unsigned "
                    "voucher (statutory floor)"] if floor else [])
        if res.rule is None:
            why = (f"conflicting rules {', '.join(dsl.ref(r) for r in res.conflict)}: offset needs a ruling"
                   if res.conflicted else "offset needs a ruling")
            return ent("needs_ruling", "EU261 " + ", ".join(articles), reason + [
                f"€{voucher.amount_cents // 100} voucher 'in lieu of compensation' has no signed acceptance "
                f"(Art. 7(3)): {why}"] + ignored, comp=comp, reduction=reduction, applied=applied)
        rule = res.rule
        applied.append(dsl.ref(rule))
        if rule.action == RuleAction.ALLOW_OFFSET:
            offset = min(voucher.amount_cents, comp)
            return ent("owed", "EU261 " + ", ".join(articles), reason + [
                f"unsigned voucher offset €{offset // 100} under {dsl.ref(rule)}"],
                comp=comp, reduction=reduction, offset=offset, applied=applied)
        return ent("owed", "EU261 " + ", ".join(articles), reason + [
            f"no signed acceptance, no offset ({dsl.ref(rule)}): pay cash; the voucher stays as goodwill"] + ignored,
            comp=comp, reduction=reduction, applied=applied)

    return ent("owed", "EU261 " + ", ".join(articles), reason, comp=comp, reduction=reduction, applied=applied)


def summarize(ents: Sequence[Entitlement], world: World | None = None) -> dict[str, Any]:
    """Every documented Flight File summary key (contracts.models.EntitlementsSummary) from the entitlements: counts,
    sums and plan §9 labels of numbers the engine computed. `world` adds the election counts."""
    from contracts.summary import entitlements_summary
    elections = None
    if world is not None:
        ids = {e.coupon_id for e in ents}
        elections = {el.coupon_id: el.kind for el in world.elections if el.coupon_id in ids}
    return entitlements_summary(ents, elections=elections)
