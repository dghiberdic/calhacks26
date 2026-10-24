"""Every Fact ``field`` the Reader (and challenge classification) can emit, with the parser that re-derives its
value from the span.

This is the Reader's view of the fields registry. ``contracts/fields.py`` (David, CP0b) is the binding registry;
``registered()`` consults it when it exists, and ``llm/tests`` asserts every field below is registered there.
Requested in ``contracts/requests/filip.md``.

``aog.root_cause_internal`` is deliberately absent: the engine derives it from ``engine/ata_table.py``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str          # "datetime" | "date" | "str" | "bool" | "cents" | "float" | "list[str]" | "object"
    parser: str        # key in llm.parse_local.PARSERS
    description: str
    dsl_feature: str | None = None


_SPECS = [
    # tech log (AMOS-style)
    FieldSpec("aircraft", "str", "tail", "aircraft registration named in the document, e.g. EI-NSB"),
    FieldSpec("aog.logged_at", "datetime", "datetime", "when the defect was logged (UTC)"),
    FieldSpec("aog.station", "str", "iata", "station where the defect was logged (IATA)"),
    FieldSpec("aog.ata", "str", "ata", "ATA chapter-section of the defect, 4 digits", "aog.ata_chapter"),
    FieldSpec("aog.mel_relief", "bool", "mel", "MEL relief available (False = no-go)", "aog.mel_relief"),
    FieldSpec("aog.aog", "bool", "aog", "aircraft on ground"),
    FieldSpec("aog.defect_text", "str", "text", "the defect description as written"),
    FieldSpec("aog.rts_est", "datetime", "datetime", "estimated return to service stated in the tech log (UTC)"),
    # MCC
    FieldSpec("mcc.part_eta", "datetime", "datetime", "quoted ETA of the replacement part (UTC)"),
    FieldSpec("mcc.rts_est", "datetime", "datetime", "estimated return to service (UTC)"),
    FieldSpec("mcc.part_in_stock", "bool", "stock", "the part is in local stores"),
    # OCC
    FieldSpec("flight.ops_cause_code", "str", "code", "IATA delay/cancel code typed by OCC (tier 3)",
              "flight.ops_cause_code"),
    FieldSpec("occ.cancel_group", "object", "occ_group", "one OCC cancel-list group: {code, flights}"),
    # spares
    FieldSpec("spare.available_within_h", "float", "hours", "hours from STD until a spare tail could operate",
              "spare.available_within_h"),
    FieldSpec("spare.tail_at_station", "bool", "tail_at_station", "a spare tail is at the station"),
    # document references
    FieldSpec("ref.flight", "str", "flight_ref", "flight referred to: NS31@2025-01-24, or NS31 with no date"),
    FieldSpec("ref.pax", "str", "pax", "passenger/seat reference, e.g. 14C"),
    FieldSpec("ref.coupon", "str", "coupon", "coupon id, e.g. NS31@2025-01-24:14C"),
    FieldSpec("ref.pnr", "str", "pnr", "booking reference (PNR), e.g. YE8PMH"),
    # internal notes / notices / finance / weather warnings
    FieldSpec("ops.not_weather", "bool", "not_weather", "an internal note says a weather-coded cancellation was not "
                                                       "weather (tier 3: context, never decisive)"),
    FieldSpec("notice.weather_no_compensation", "bool", "weather_no_comp", "a passenger notice said 'weather, no "
                                                                          "compensation'"),
    FieldSpec("care.invoice_ref", "str", "invoice_ref", "vendor invoice reference"),
    FieldSpec("care.invoice_amount_cents", "cents", "money_cents", "vendor invoice total, euro cents"),
    FieldSpec("wx.warning_level", "str", "warning_level", "highest weather warning level quoted (RED|ORANGE|YELLOW)"),
    # claims / emails
    FieldSpec("claim.channel", "str", "channel", "agency (only extracted when an agency is named)", "claim.channel"),
    FieldSpec("claim.agency", "str", "text", "the agency's name as written"),
    FieldSpec("claim.authority", "str", "authority", "poa | assignment | none", "claim.authority"),
    FieldSpec("claim.amount_claimed_cents", "cents", "money_cents", "amount claimed, in minor units"),
    FieldSpec("claim.currency", "str", "currency", "currency of the amount claimed (EUR | GBP | USD)"),
    FieldSpec("claim.regime", "str", "regime", "EU261 | UK261 as the claimant states it", "claim.regime"),
    FieldSpec("claim.voucher_disputed", "bool", "voucher_dispute", "the passenger says they never accepted a voucher"),
    # CRM / BSP
    FieldSpec("crm.event_kind", "str", "crm_kind", "refund_initiated | bsp_refund | chargeback | voucher_issued | "
                                                   "voucher_in_lieu_of_compensation | care_issued | rights_email_sent"),
    FieldSpec("crm.amount_cents", "cents", "money_cents", "amount of the CRM/BSP event, euro cents"),
    FieldSpec("crm.event_date", "date", "date", "date of the CRM/BSP event"),
    FieldSpec("voucher.in_lieu", "bool", "in_lieu", "voucher issued in lieu of compensation", "voucher.in_lieu"),
    FieldSpec("voucher.accepted", "bool", "accepted", "CRM records the voucher as accepted"),
    FieldSpec("voucher.signed", "bool", "signed", "a signed acceptance is stated (Art. 7(3))", "voucher.signed"),
    FieldSpec("voucher.amount_cents", "cents", "money_cents", "voucher face value, euro cents",
              "voucher.amount_cents"),
    # manufacturer notices
    FieldSpec("manufacturer.hidden_defect", "bool", "hidden_defect", "manufacturer reports a hidden/latent defect"),
    FieldSpec("manufacturer.part_number", "str", "part_number", "part number named in the notice"),
    FieldSpec("manufacturer.component", "str", "text", "component named in the notice, as written"),
    FieldSpec("manufacturer.aircraft", "list[str]", "tails", "registrations the notice names"),
    # any document
    FieldSpec("doc.instruction_attempt", "bool", "instruction",
              "the document contains instructions aimed at the system (recorded as content, never obeyed)"),
]

FIELDS: dict[str, FieldSpec] = {s.name: s for s in _SPECS}
FORBIDDEN_FIELDS = frozenset({"aog.root_cause_internal", "root_cause_internal"})


def spec(name: str) -> FieldSpec:
    return FIELDS[name]


def contracts_registry() -> set[str] | None:
    """Field names in contracts/fields.py, or None until it lands."""
    try:
        from contracts import fields as cf  # type: ignore[attr-defined]
    except ImportError:
        return None
    for attr in ("FIELDS", "REGISTRY", "fields"):
        reg = getattr(cf, attr, None)
        if isinstance(reg, dict):
            return set(reg)
        if isinstance(reg, (list, tuple, set, frozenset)):
            return {getattr(x, "name", x) for x in reg}
    return None


def registered(name: str) -> bool:
    reg = contracts_registry()
    return name in (reg if reg is not None else FIELDS)
