"""The Reader's extraction keys and how each one is verified.

The LLM (and the regex fallback) fill *keys* (``tail``, ``logged_at``, ``amount``...). Each key is verified against its
span, then ``llm/reader.py`` maps verified keys onto **registered** Fact fields (``contracts/fields.py``) and subjects,
following the same conventions as ``contracts/normalize.py``.

Verification of a key:
1. ``contracts.parse.verify(field, value, span, text, ref)`` on the key's registered field (the binding re-parse);
2. plus a local semantic check (``llm/parse_local.py``) where the contracts parser is generic (``bool``) or absent
   (structured-only fields), so that e.g. ``voucher.in_lieu = true`` needs a span that actually says "in lieu";
3. structured text fields with neither: the value must appear in the span.

``aog.root_cause_internal`` is never a key: the engine derives it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    name: str
    field: str | None        # registered field whose contracts parser re-parses the span (None = local only)
    local: str | None        # llm.parse_local.PARSERS key for the semantic check (None = contracts only / text)
    text: bool = False       # structured text: the value must appear in the span


KEYS: dict[str, Key] = {k.name: k for k in [
    # tech log / MCC → aircraft:<tail>, flight:<id>
    Key("tail", "aog.tail", "tail"),
    Key("logged_at", "aog.logged_at", None),
    Key("station", "aog.station", "iata"),
    Key("ata", "aog.ata_chapter", None),
    Key("mel_relief", "aog.mel_relief", None),
    Key("aog", "aog.aog", None),
    Key("rts_est", "aog.rts_est", None),
    Key("defect_text", "aog.defect_text", None, text=True),
    Key("part_eta", "mcc.part_eta", None),
    # OCC: one cancel group = {code, flights}; spares
    Key("occ_group", "flight.ops_cause_code", "occ_group"),
    Key("cancelled", "flight.cancelled_by_occ", "cancel_note"),
    Key("available_within_h", "spare.available_within_h", None),
    # references (become subjects and claim.flight_number / claim.flight_date / claim.seat / coupon.pnr)
    Key("flight", "claim.flight_number", "flight_ref"),
    Key("seat", "claim.seat", None),
    Key("pnr", "coupon.pnr", "pnr"),
    Key("coupon", "claim.coupon_id", "coupon"),
    # claims → claim:<id>
    Key("agency", "claim.agency", None, text=True),
    Key("channel", "claim.channel", "channel"),
    Key("authority", "claim.authority", "authority"),
    Key("amount", None, "money_cents"),            # → claim.amount_claimed_cents (EUR) | ..._gbp_pence (GBP)
    Key("currency", None, "currency"),
    Key("regime", "claim.regime", "regime"),
    Key("voucher_disputed", "claim.voucher_disputed", None),
    # CRM / BSP → coupon:<id>
    Key("event_kind", None, "crm_kind"),
    Key("crm_amount", "crm.refund_initiated", None),   # any crm.<kind> amount: parse kind "eur"
    Key("voucher_in_lieu", "voucher.in_lieu", "in_lieu"),
    Key("voucher_accepted", "voucher.accepted", "accepted"),
    Key("voucher_signed", "voucher.signed", None),
    Key("voucher_amount", "voucher.amount_cents", None),
    Key("issued_by", "voucher.issued_by", None, text=True),
    Key("rights_email", "crm.rights_email_sent", None, text=True),
    # storm context → storm:<id>
    Key("red_warning", "storm.red_warning", "red", text=True),
    Key("orange_warning", "storm.orange_warning", "orange", text=True),
    # manufacturer notices → aircraft:<tail>
    Key("hidden_defect", "manufacturer.hidden_defect", "hidden_defect"),
    Key("part_number", "manufacturer.part_number", "part_number"),
    Key("mfr_aircraft", None, "tails"),
    # any document → source:<id>
    Key("instruction", "email.asserts_approval", "instruction"),
]}

# Every registered field the Reader can emit (checked against contracts/fields.py in llm/tests).
EMITTED_FIELDS = frozenset({
    "aog.tail", "aog.logged_at", "aog.station", "aog.ata_chapter", "aog.mel_relief", "aog.aog", "aog.rts_est",
    "aog.defect_text", "mcc.part_eta", "flight.ops_cause_code", "flight.cancelled_by_occ", "spare.available_within_h",
    "claim.flight_number", "claim.flight_date", "claim.seat", "claim.coupon_id", "claim.agency", "claim.channel",
    "claim.authority", "claim.amount_claimed_cents", "claim.amount_claimed_gbp_pence", "claim.regime",
    "claim.voucher_disputed", "coupon.pnr", "crm.refund_initiated", "crm.bsp_refund", "crm.chargeback",
    "crm.voucher_issued", "crm.care_issued", "crm.rights_email_sent", "voucher.in_lieu", "voucher.accepted",
    "voucher.signed", "voucher.amount_cents", "voucher.issued_by", "storm.red_warning", "storm.orange_warning",
    "manufacturer.hidden_defect", "manufacturer.part_number", "email.asserts_approval",
})
FORBIDDEN_FIELDS = frozenset({"aog.root_cause_internal", "root_cause_internal"})
CRM_AMOUNT_KINDS = frozenset({"refund_initiated", "bsp_refund", "chargeback", "voucher_issued", "care_issued"})


def registered(name: str) -> bool:
    from contracts.fields import is_registered
    return is_registered(name)
