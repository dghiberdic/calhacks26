"""The Fact field registry (CONTRACTS §2 shared helpers). Every `Fact.field` must be registered here.

Each field says its value type, unit, which subject kind it describes, which DSL features (CONTRACTS §4) it feeds,
and which `contracts.parse` kind re-parses its value from a span. The Reader drops facts whose field is unknown.

`DSL_FEATURES` is the CONTRACTS §4 allowlist (the only names a Rule condition may use). `ENGINE_DERIVED` lists the
features the engine computes from facts rather than reading one fact directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------- CONTRACTS §4 feature allowlist
DSL_FEATURES: tuple[str, ...] = (
    "flight.in_window_dep", "flight.in_window_arr", "flight.window_margin_min", "flight.distance_km",
    "flight.band_eur", "flight.departs_eu", "flight.arrives_eu", "flight.operating_carrier_eu",
    "flight.route_region", "flight.ops_cause_code", "flight.is_return_sector",
    "aog.before_window", "aog.inside_window", "aog.ata_chapter", "aog.root_cause_internal", "aog.mel_relief",
    "rotation.prev_cancelled", "rotation.prev_cause", "spare.available_within_h",
    "pax.notice_days", "pax.arrival_delay_min", "pax.election", "pax.reroute_earliest_offered", "pax.fare_type",
    "voucher.in_lieu", "voucher.signed", "voucher.amount_cents",
    "claim.channel", "claim.authority", "claim.duplicate", "claim.age_months", "claim.after_limitation",
    "claim.regime",
    "cohort.age_months", "cohort.months_since_last_claim", "cohort.limitation_expired",
    "sources.disagree", "precedent.count",
)
# additive (blackout v1): external-event features (grid outage). in_event_window_* take "in" | "out" | "unknown".
# Kept OUT of DSL_FEATURES on purpose: llm/drafter.py builds its structured-output schema from DSL_FEATURES and the
# recorded demo LLM cache keys include that schema, so growing it would break offline replay of rule drafting. The
# event rule is templated from the Legal ruling (no LLM). The engine's allowlist is ALL_DSL_FEATURES.
EVENT_DSL_FEATURES: tuple[str, ...] = ("flight.in_event_window_dep", "flight.in_event_window_arr", "event.kind")
ALL_DSL_FEATURES: tuple[str, ...] = DSL_FEATURES + EVENT_DSL_FEATURES
DSL_OPS: tuple[str, ...] = ("eq", "ne", "lt", "le", "gt", "ge", "in", "nin", "exists")
# DSL context keys usable in Rule.scope besides the features (engine/dsl.py)
SCOPE_CONTEXT_KEYS: tuple[str, ...] = ("storm", "cohort", "flight", "station", "segment", "coupon")

# features the engine derives (windows, distances, ATA table, rotations, ages, evidence comparison)
ENGINE_DERIVED: frozenset[str] = frozenset({
    "flight.in_window_dep", "flight.in_window_arr", "flight.window_margin_min", "flight.distance_km",
    "flight.band_eur", "flight.departs_eu", "flight.arrives_eu", "flight.route_region", "flight.is_return_sector",
    "aog.before_window", "aog.inside_window", "aog.root_cause_internal",
    "rotation.prev_cancelled", "rotation.prev_cause", "pax.notice_days",
    "claim.duplicate", "claim.age_months", "claim.after_limitation",
    "cohort.age_months", "cohort.months_since_last_claim", "cohort.limitation_expired",
    "sources.disagree", "precedent.count",
    "flight.in_event_window_dep", "flight.in_event_window_arr",     # additive (blackout v1)
})
# values of the event-window features (as for the storm windows: ±60 min around an edge is "unknown")
EVENT_WINDOW_VALUES: tuple[str, ...] = ("in", "out", "unknown")

TYPES = ("str", "int", "float", "bool", "cents", "datetime", "date", "enum", "json")
SUBJECTS = ("flight", "aircraft", "coupon", "claim", "station", "storm", "care", "cohort", "source",
            "event")                        # additive (blackout v1): "event:<ExternalEvent.id>"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str                               # one of TYPES; "cents" = integer euro cents
    subject: str                            # subject kind: Fact.subject is "<subject>:<id>"
    description: str
    unit: str | None = None                 # "kt", "sm", "deg", "min", "h", "km", "eur_cents", "pct"
    feeds: tuple[str, ...] = ()             # DSL features this fact feeds (directly or via the engine)
    parse: str | None = None                # contracts.parse kind that re-parses the value from a span
    enum: tuple[str, ...] | None = None


class UnknownField(KeyError):
    pass


_SPECS: list[FieldSpec] = []


def _f(name: str, type_: str, subject: str, description: str, *, unit: str | None = None,
       feeds: tuple[str, ...] = (), parse: str | None = None, enum: tuple[str, ...] | None = None) -> None:
    _SPECS.append(FieldSpec(name, type_, subject, description, unit, feeds, parse, enum))


# ---------------------------------------------------------------- flight (schedule, manifest, OCC)
_f("flight.number", "str", "flight", "Marketing flight number", parse="flight_number")
_f("flight.date", "date", "flight", "Local departure date", parse="date")
_f("flight.origin", "str", "flight", "Origin IATA", parse="iata", feeds=("flight.departs_eu", "flight.distance_km",
                                                                       "flight.route_region"))
_f("flight.dest", "str", "flight", "Destination IATA", parse="iata", feeds=("flight.arrives_eu", "flight.distance_km",
                                                                         "flight.route_region"))
_f("flight.sched_dep", "datetime", "flight", "STD (UTC)", parse="time", feeds=("flight.in_window_dep",
                                                                              "flight.window_margin_min",
                                                                              "pax.notice_days"))
_f("flight.sched_arr", "datetime", "flight", "STA (UTC)", parse="time", feeds=("flight.in_window_arr",
                                                                              "pax.arrival_delay_min"))
_f("flight.actual_dep", "datetime", "flight", "ATD (UTC)", parse="time")
_f("flight.actual_arr", "datetime", "flight", "ATA (UTC)", parse="time")
_f("flight.aircraft", "str", "flight", "Tail registration", parse="tail")
_f("flight.status", "enum", "flight", "Movement status", enum=("operated", "cancelled", "delayed"))
_f("flight.pax", "int", "flight", "Passengers on the manifest (manifest wins over ops)", parse="int")
_f("flight.ops_cause_code", "str", "flight", "IATA delay code as typed by OCC (never trusted alone)",
   parse="delay_code", feeds=("flight.ops_cause_code", "sources.disagree"))
_f("flight.inbound_flight_id", "str", "flight", "Previous rotation of the same tail", feeds=("rotation.prev_cancelled",
                                                                                            "rotation.prev_cause"))
_f("flight.outbound_pair_id", "str", "flight", "Outbound that positions the aircraft for this return sector",
   feeds=("flight.is_return_sector", "rotation.prev_cancelled", "rotation.prev_cause"))
_f("flight.notified_at", "datetime", "flight", "When passengers were told of the cancellation", parse="time",
   feeds=("pax.notice_days",))
_f("flight.operating_carrier_eu", "bool", "flight", "Operating carrier is an EU carrier",
   feeds=("flight.operating_carrier_eu",))
_f("flight.cancelled_by_occ", "bool", "flight", "Listed on an OCC cancel list", parse="bool")

# ---------------------------------------------------------------- tech log (AMOS) — subject aircraft:<tail>
_f("aog.logged_at", "datetime", "aircraft", "Defect raised (UTC)", parse="time",
   feeds=("aog.before_window", "aog.inside_window"))
_f("aog.ata_chapter", "str", "aircraft", "ATA 100 chapter/section, e.g. 2913", parse="ata",
   feeds=("aog.ata_chapter", "aog.root_cause_internal"))
_f("aog.mel_relief", "bool", "aircraft", "MEL relief exists (False = no-go)", parse="mel_relief",
   feeds=("aog.mel_relief",))
_f("aog.aog", "bool", "aircraft", "Aircraft on ground", parse="aog", feeds=("aog.before_window", "aog.inside_window"))
_f("aog.station", "str", "aircraft", "Station where the defect was raised", parse="iata")
_f("aog.rts_est", "datetime", "aircraft", "Estimated return to service (UTC)", parse="time")
_f("aog.defect_text", "str", "aircraft", "Verbatim defect text (engine/ata_table.py classifies it)",
   feeds=("aog.root_cause_internal",))
_f("aog.tail", "str", "aircraft", "Tail registration named in the entry", parse="tail")

# ---------------------------------------------------------------- MCC / spares / rotation — subject flight or aircraft
_f("mcc.part_eta", "datetime", "flight", "Part ETA quoted by MCC (UTC)", parse="time")
_f("mcc.text", "str", "flight", "Verbatim MCC line")
_f("mcc.rts_est", "datetime", "flight", "Return to service estimated by MCC (UTC)", parse="time")
_f("ops.not_weather", "bool", "flight", "An ops/maintenance note says the cancellation was not weather (tier 3)",
   parse="not_weather", feeds=("sources.disagree",))
_f("spare.available_within_h", "float", "flight", "Hours after STD until a spare tail could operate", unit="h",
   parse="duration_h", feeds=("spare.available_within_h",))
_f("spare.text", "str", "flight", "Verbatim spares-log line (context only for technical causes)")
_f("rotation.prev_cancelled", "bool", "flight", "The positioning outbound was cancelled", parse="bool",
   feeds=("rotation.prev_cancelled",))
_f("rotation.prev_cause", "str", "flight", "Cause of the positioning outbound's cancellation",
   feeds=("rotation.prev_cause",))

# ---------------------------------------------------------------- METAR — subject station:<ICAO>
_f("metar.sknt", "int", "station", "Sustained wind", unit="kt", parse="int",
   feeds=("flight.in_window_dep", "flight.in_window_arr"))
_f("metar.gust_kt", "int", "station", "Gust", unit="kt", parse="int",
   feeds=("flight.in_window_dep", "flight.in_window_arr"))
_f("metar.drct", "int", "station", "Wind direction", unit="deg", parse="int")
_f("metar.vsby_sm", "float", "station", "Visibility", unit="sm", parse="float",
   feeds=("flight.in_window_dep", "flight.in_window_arr"))
_f("metar.wxcodes", "str", "station", "Present weather codes", feeds=("flight.in_window_dep", "flight.in_window_arr"))
_f("metar.raw", "str", "station", "Verbatim METAR")

# ---------------------------------------------------------------- storm context — subject storm:<id>
_f("storm.window", "json", "storm", "Computed storm window {start,end,peak_gust_kt} (engine output as a fact)")
_f("storm.name", "str", "storm", "Storm name")
_f("storm.eurocontrol_departures", "int", "storm", "Real departures that day (Eurocontrol)", parse="int")
_f("storm.normal_departures", "str", "storm", "Normal departure range")
_f("storm.reported_cancellations_dep", "int", "storm", "Reported departure cancellations", parse="int")
_f("storm.reported_cancellations_arr", "int", "storm", "Reported arrival cancellations", parse="int")
_f("storm.red_warning", "str", "storm", "Met Éireann red warning hours")
_f("storm.orange_warning", "str", "storm", "Met Éireann orange warning hours")
_f("storm.peak_gust_kt", "int", "storm", "Peak gust", unit="kt", parse="int")

# ---------------------------------------------------------------- external events — subject event:<id> (blackout v1)
# One event.kind fact per event; one window_start/window_end pair per airport window (the fact's record names the
# ICAO: normalize.event_fact_id(event_id, field, icao)). Values are UTC times from a tier-1 operator notice.
_f("event.kind", "str", "event", "Kind of external event, e.g. grid_outage", feeds=("event.kind",))
_f("event.window_start", "datetime", "event", "Outage window start at one airport (UTC)", parse="time",
   feeds=("flight.in_event_window_dep", "flight.in_event_window_arr"))
_f("event.window_end", "datetime", "event", "Normal operations resumed at that airport (UTC)", parse="time",
   feeds=("flight.in_event_window_dep", "flight.in_event_window_arr"))

# ---------------------------------------------------------------- PSS — subject coupon:<id>
_f("coupon.flight_id", "str", "coupon", "Flight the coupon is for")
_f("coupon.pnr", "str", "coupon", "Booking reference")
_f("coupon.pax_ref", "str", "coupon", "Pseudonymous passenger reference")
_f("coupon.fare_cents", "cents", "coupon", "Fare incl. carrier surcharges", unit="eur_cents", parse="eur")
_f("coupon.taxes_cents", "cents", "coupon", "Taxes", unit="eur_cents", parse="eur")
_f("coupon.channel", "enum", "coupon", "Sales channel", enum=("direct", "ota", "agency_gds"))
_f("coupon.fare_type", "enum", "coupon", "Revenue or staff ticket", enum=("revenue", "staff_id90"),
   feeds=("pax.fare_type",))
_f("coupon.lead_booker", "bool", "coupon", "Lead booker of a multi-passenger PNR", parse="bool")
_f("pax.election", "enum", "coupon", "What the passenger chose",
   enum=("refund", "voucher", "reaccommodated_own", "reroute_partner", "none"), feeds=("pax.election",))
_f("pax.new_arrival", "datetime", "coupon", "Arrival of the reaccommodation/reroute (UTC)", parse="time",
   feeds=("pax.arrival_delay_min",))
_f("pax.arrival_delay_min", "int", "coupon", "Arrival delay vs. the original STA", unit="min", parse="minutes",
   feeds=("pax.arrival_delay_min",))
_f("pax.election_recorded_by", "enum", "coupon", "Channel that recorded the election",
   enum=("crm-bot", "service-desk", "web", "call-centre", "occ"))
_f("pax.reroute_earliest_offered", "bool", "flight", "Passengers were offered the earliest reroute on any carrier",
   parse="bool", feeds=("pax.reroute_earliest_offered",))

# ---------------------------------------------------------------- CRM / BSP — subject coupon:<id>
_f("crm.refund_initiated", "cents", "coupon", "Refund initiated (amount)", unit="eur_cents", parse="eur",
   feeds=("claim.duplicate",))
_f("crm.bsp_refund", "cents", "coupon", "Refund settled through BSP (amount)", unit="eur_cents", parse="eur",
   feeds=("claim.duplicate",))
_f("crm.chargeback", "cents", "coupon", "Card chargeback (amount)", unit="eur_cents", parse="eur",
   feeds=("claim.duplicate",))
_f("crm.voucher_issued", "cents", "coupon", "Refund voucher issued (amount)", unit="eur_cents", parse="eur")
_f("crm.care_issued", "cents", "coupon", "Care issued at the airport (amount)", unit="eur_cents", parse="eur")
_f("crm.rights_email_sent", "str", "coupon", "Verbatim rights email the passenger received (Art. 14(2))")
_f("voucher.in_lieu", "bool", "coupon", "A voucher was issued in lieu of compensation", parse="bool",
   feeds=("voucher.in_lieu",))
_f("voucher.amount_cents", "cents", "coupon", "In-lieu voucher amount", unit="eur_cents", parse="eur",
   feeds=("voucher.amount_cents",))
_f("voucher.signed", "bool", "coupon", "Signed acceptance on file (Art. 7(3))", parse="signed",
   feeds=("voucher.signed",))
_f("voucher.signed_acceptance_sha256", "str", "coupon", "Hash of the signed acceptance")
_f("voucher.accepted", "bool", "coupon", "CRM records the passenger as accepting", parse="bool",
   feeds=("sources.disagree",))
_f("voucher.issued_by", "str", "coupon", "Desk or channel that issued the voucher")

# ---------------------------------------------------------------- claims — subject claim:<id>
_f("claim.coupon_id", "str", "claim", "Coupon claimed for")
_f("claim.received_at", "datetime", "claim", "When the claim arrived (UTC)", parse="time",
   feeds=("claim.age_months", "claim.after_limitation"))
_f("claim.channel", "enum", "claim", "Direct or via an agency", enum=("direct", "agency"), feeds=("claim.channel",))
_f("claim.agency", "str", "claim", "Claims agency name")
_f("claim.authority", "enum", "claim", "Agency authority", enum=("poa", "assignment", "none"),
   feeds=("claim.authority",))
_f("claim.pnr_scope", "enum", "claim", "Claim scope (lead booker for the PNR)", enum=("coupon", "pnr"),
   feeds=("claim.duplicate",))
_f("claim.amount_claimed_cents", "cents", "claim", "Amount claimed in EUR cents (GBP claims are re-based)",
   unit="eur_cents", parse="eur")
_f("claim.regime", "enum", "claim", "Regime the claim cites", enum=("EU261", "UK261"), feeds=("claim.regime",))
_f("claim.voucher_disputed", "bool", "claim", "The passenger says she never agreed to a voucher", parse="disputed",
   feeds=("sources.disagree",))
_f("claim.flight_number", "str", "claim", "Flight number named in the claim", parse="flight_number")
_f("claim.flight_date", "date", "claim", "Flight date named in the claim", parse="date")
_f("claim.seat", "str", "claim", "Seat named in the claim", parse="seat")
_f("claim.amount_claimed_gbp_pence", "int", "claim", "Amount claimed in GBP pence (UK261 claims)", parse="gbp")

# ---------------------------------------------------------------- care — subject care:<id>
_f("care.flight_id", "str", "care", "Flight the care was for")
_f("care.kind", "enum", "care", "Hotel, meal or transport", enum=("hotel", "meal", "transport"))
_f("care.amount_cents", "cents", "care", "Amount", unit="eur_cents", parse="eur")
_f("care.vendor", "str", "care", "Vendor")
_f("care.invoiced", "bool", "care", "False = accrual estimate, True = vendor invoice", parse="bool")

# ---------------------------------------------------------------- cohorts (opening balances) — subject cohort:<id>
_f("cohort.account", "str", "cohort", "GL account")
_f("cohort.entitlement_cents", "cents", "cohort", "Full Art. 7 entitlement of the cohort", unit="eur_cents",
   parse="eur")
_f("cohort.claimed_cents", "cents", "cohort", "Claimed to date", unit="eur_cents", parse="eur")
_f("cohort.claimed_pct", "float", "cohort", "Claimed to date / entitlement", unit="pct", parse="pct")
_f("cohort.balance_cents", "cents", "cohort", "2140 balance", unit="eur_cents", parse="eur")
_f("cohort.curve_segment", "enum", "cohort", "Claim-curve segment",
   enum=("long_haul_gt3500", "medium_1500_3500", "short_le1500"))
_f("cohort.as_of", "datetime", "cohort", "Balance date", parse="time", feeds=("cohort.months_since_last_claim",))
_f("cohort.last_claim_at", "date", "cohort", "Date of the latest claim", parse="date",
   feeds=("cohort.months_since_last_claim",))
_f("cohort.months_since_last_claim", "int", "cohort", "Months since the latest claim", unit="months", parse="int",
   feeds=("cohort.months_since_last_claim",))

# ---------------------------------------------------------------- Reader-only fields (messy documents, injections)
_f("manufacturer.hidden_defect", "bool", "aircraft", "Manufacturer says a hidden manufacturing defect affects it",
   parse="bool")
_f("manufacturer.part_number", "str", "aircraft", "Part number named by the manufacturer")
_f("email.asserts_approval", "bool", "source", "An external message claims an internal approval (never satisfies one)",
   parse="bool")
_f("challenge.classification", "enum", "flight", "How a challenge was classified",
   enum=("assertion", "new_fact", "new_legal_pattern"))
_f("challenge.text", "str", "flight", "Verbatim challenge text (tier 4)")

REGISTRY: dict[str, FieldSpec] = {s.name: s for s in _SPECS}
assert len(REGISTRY) == len(_SPECS), "duplicate field registration"


def get(name: str) -> FieldSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise UnknownField(name) from None


def is_registered(name: str) -> bool:
    return name in REGISTRY


def feeding(feature: str) -> list[str]:
    """Fields that feed a DSL feature."""
    return sorted(s.name for s in _SPECS if feature in s.feeds)


def check_value(name: str, value: Any) -> bool:
    """True if `value` has the registered type (JSON-mode values: datetimes may be ISO strings)."""
    s = get(name)
    if value is None:
        return True
    t = s.type
    if t == "str":
        return isinstance(value, str)
    if t in ("int", "cents"):
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "float":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if t == "bool":
        return isinstance(value, bool)
    if t == "datetime":
        if isinstance(value, datetime):
            return value.tzinfo is not None
        return isinstance(value, str) and value.endswith("Z") and "T" in value
    if t == "date":
        return (isinstance(value, date) and not isinstance(value, datetime)) or (
            isinstance(value, str) and len(value) == 10)
    if t == "enum":
        return isinstance(value, str) and (s.enum is None or value in s.enum)
    return True  # json
