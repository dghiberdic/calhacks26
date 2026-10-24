"""D0b: contracts/fields.py (registry), parse.py (typed re-parse from spans), normalize.py (World → Facts)."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from contracts import fields, parse
from contracts.models import Fact, World
from contracts.normalize import STRUCTURED_SOURCE, by_subject, resolve, world_to_facts

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
ID_RE = re.compile(r"^[A-Za-z0-9@.:_-]+$")


def t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def world() -> World:
    return World.model_validate_json((ROOT / "contracts" / "fixtures" / "golden" / "world.json").read_text())


@pytest.fixture(scope="module")
def facts(world: World) -> list[Fact]:
    return world_to_facts(world)


# ---------------------------------------------------------------- fields
def test_every_dsl_feature_is_fed_or_engine_derived():
    fed = {feat for s in fields.REGISTRY.values() for feat in s.feeds}
    assert fed <= set(fields.DSL_FEATURES), fed - set(fields.DSL_FEATURES)
    missing = [f for f in fields.DSL_FEATURES if f not in fed and f not in fields.ENGINE_DERIVED]
    assert not missing, missing
    assert fields.ENGINE_DERIVED <= set(fields.DSL_FEATURES)
    assert len(fields.DSL_FEATURES) == len(set(fields.DSL_FEATURES)) == 38


def test_registry_specs_are_well_formed():
    for name, s in fields.REGISTRY.items():
        assert s.name == name and s.type in fields.TYPES and s.subject in fields.SUBJECTS
        assert s.parse is None or s.parse in parse.PARSERS, name
        assert (s.enum is not None) == (s.type == "enum") or s.type != "enum", name
        assert ID_RE.match(name)
    assert fields.feeding("voucher.signed") == ["voucher.signed"]
    with pytest.raises(fields.UnknownField):
        fields.get("flight.vibes")


def test_check_value():
    assert fields.check_value("flight.pax", 172) and not fields.check_value("flight.pax", "172")
    assert fields.check_value("coupon.fare_cents", 45000) and not fields.check_value("coupon.fare_cents", True)
    assert fields.check_value("pax.election", "refund") and not fields.check_value("pax.election", "cash")
    assert fields.check_value("aog.logged_at", "2025-01-23T21:40:00Z")
    assert not fields.check_value("aog.logged_at", datetime(2025, 1, 23, 21, 40))      # naive
    assert fields.check_value("voucher.signed", False) and not fields.check_value("voucher.signed", 0)


# ---------------------------------------------------------------- parse
REF = datetime(2025, 1, 24, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize("span,ref,expected", [
    ("2025-01-23T21:40:00Z", None, "2025-01-23T21:40:00Z"),
    ("2025-01-23 21:40Z", None, "2025-01-23T21:40:00Z"),
    ("23JAN 21:40Z EI-NSB DUB N/S.", REF, "2025-01-23T21:40:00Z"),
    ("24 Jan 2025 16:30Z", None, "2025-01-24T16:30:00Z"),
    ("POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z", REF, "2025-01-25T14:00:00Z"),
    ("05:12Z OCC DM", REF, "2025-01-24T05:12:00Z"),
    ("STD 1630Z", REF, "2025-01-24T16:30:00Z"),
    ("EIDW 241500Z 25021G34KT", REF, "2025-01-24T15:00:00Z"),
    ("28DEC 10:00Z", datetime(2025, 1, 5, tzinfo=UTC), "2024-12-28T10:00:00Z"),
])
def test_parse_time(span, ref, expected):
    assert parse.parse_time(span, ref) == t(expected)


def test_parse_time_rolls_forward_and_needs_a_date():
    assert parse.parse_time("RTS EST 20:00Z", REF, not_before=t("2025-01-24T22:15:00Z")) == t("2025-01-25T20:00:00Z")
    with pytest.raises(parse.ParseError):
        parse.parse_time("21:40Z")
    with pytest.raises(parse.ParseError):
        parse.parse_time("no time here", REF)


@pytest.mark.parametrize("span,expected", [
    ("2025-01-24", date(2025, 1, 24)), ("24/01/2025", date(2025, 1, 24)), ("24 Jan 2025", date(2025, 1, 24)),
    ("on 24 January 2025, seat 14C", date(2025, 1, 24)), ("24JAN25", date(2025, 1, 24)),
    ("Jan 24, 2025", date(2025, 1, 24)), ("12 March 2018", date(2018, 3, 12)), ("24JAN", date(2025, 1, 24)),
])
def test_parse_date(span, expected):
    assert parse.parse_date(span, REF) == expected


@pytest.mark.parametrize("fn,span,expected", [
    (parse.parse_ata, "ATA 2913", "2913"), (parse.parse_ata, "ATA 29-13", "2913"), (parse.parse_ata, "29-13", "2913"),
    (parse.parse_ata, "2913", "2913"), (parse.parse_ata, "MEL 33-20-01 CAT C", "3320"),
    (parse.parse_tail, "23JAN 21:40Z EI-NSB DUB", "EI-NSB"), (parse.parse_tail, "ei-nsb", "EI-NSB"),
    (parse.parse_tail, "G-EUPT", "G-EUPT"), (parse.parse_tail, "tail N123AB at BOS", "N123AB"),
    (parse.parse_flight_number, "NS 31", "NS31"), (parse.parse_flight_number, "flight ns0031", "NS31"),
    (parse.parse_delay_code, "RSN 71", "71"), (parse.parse_delay_code, "72", "72"),
    (parse.parse_int, "BOOKED 172", 172), (parse.parse_int, "5,292 passengers", 5292),
    (parse.parse_seat, "seat 14C", "14C"),
    (parse.parse_minutes, "STD+4h20", 260), (parse.parse_minutes, "+3h40", 220),
    (parse.parse_minutes, "220 min", 220), (parse.parse_duration_h, "STD+4h20", 4.33),
    (parse.parse_pct, "29%", 0.29),
])
def test_parse_codes_and_numbers(fn, span, expected):
    assert fn(span) == expected


@pytest.mark.parametrize("span,cents,cur", [
    ("€300", 30000, "EUR"), ("EUR300 VOUCHER", 30000, "EUR"), ("EUR 510.00", 51000, "EUR"),
    ("600,00 €", 60000, "EUR"), ("EUR 600,00", 60000, "EUR"), ("€1,234.56", 123456, "EUR"),
    ("€1.234,56", 123456, "EUR"), ("claiming £520.", 52000, "GBP"), ("3,600.00 EUR", 360000, "EUR"),
])
def test_parse_money(span, cents, cur):
    assert parse.parse_money(span) == (cents, cur)


def test_parse_eur_rejects_other_currencies_and_bare_numbers():
    with pytest.raises(parse.ParseError):
        parse.parse_eur("£520")
    with pytest.raises(parse.ParseError):
        parse.parse_eur("600")
    assert parse.parse_gbp("£520") == 52000


def test_parse_domain_booleans():
    assert parse.parse_mel_relief("NO MEL RELIEF. A/C AOG.") is False
    assert parse.parse_mel_relief("MEL 33-20-01 CAT C DEFERRED") is True
    assert parse.parse_aog("A/C AOG") is True
    assert parse.parse_signed("SIGNATURE: NOT CAPTURED") is False and parse.parse_signed("I did not sign anything") is False
    assert parse.parse_signed("SIGNED ACCEPTANCE ON FILE") is True
    assert parse.parse_disputed("I never agreed to take a voucher instead of my compensation") is True
    assert parse.parse_bool("PAX ACCEPTED") is True and parse.parse_bool("NOT CAPTURED") is False
    with pytest.raises(parse.ParseError):
        parse.parse_mel_relief("HYD FLUID ENG 2")


def test_verify_is_the_readers_acceptance_test():
    text = "23JAN 21:40Z EI-NSB DUB N/S. EXT LEAK EDP CASE DRAIN PORT. NO MEL RELIEF. A/C AOG."
    ref = t("2025-01-23T21:42:00Z")
    assert parse.verify("aog.mel_relief", False, "NO MEL RELIEF", text, ref) == (True, "reparsed")
    assert parse.verify("aog.logged_at", "2025-01-23T21:40:00Z", "23JAN 21:40Z", text, ref)[0]
    assert parse.verify("aog.logged_at", "2025-01-23T22:40:00Z", "23JAN 21:40Z", text, ref) == (False, "value_mismatch")
    assert parse.verify("aog.mel_relief", False, "NO MEL RELIEF!", text, ref) == (False, "span_not_in_source")
    assert parse.verify("aog.vibes", True, "A/C AOG", text, ref) == (False, "unregistered_field")
    assert parse.verify("aog.mel_relief", False, "EI-NSB", text, ref) == (False, "unparseable_span")
    assert parse.verify("claim.amount_claimed_cents", 60000, "€600", "I claim €600 under EU261.", ref)[0]
    assert not parse.verify("claim.amount_claimed_cents", 60000, "£520", "I claim £520.", ref)[0]


# ---------------------------------------------------------------- normalize
def test_normalize_fields_registered_values_typed_ids_unique(facts: list[Fact]):
    assert len(facts) > 50_000
    bad = [(f.field, f.value) for f in facts if not fields.check_value(f.field, f.value)]
    assert not bad, bad[:5]
    ids = [f.id for f in facts]
    assert len(ids) == len(set(ids)) and all(ID_RE.match(i) for i in ids)
    assert {f.extractor for f in facts} == {"normalize@1"}


def test_normalize_sources_and_spans_are_real(world: World, facts: list[Fact]):
    src = {s.id: s for s in world.sources}
    assert not [f for f in facts if f.source_id == STRUCTURED_SOURCE], "golden world: every fact has a document"
    for f in facts:
        s = src[f.source_id]
        assert f.span is None or f.span in s.text, (f.id, f.span)
        assert f.recorded_at.tzinfo is not None
        assert f.acl_tags == s.acl_tags


ATOMIC = {"aog.logged_at", "aog.ata_chapter", "aog.mel_relief", "aog.aog", "aog.rts_est", "aog.tail",
          "flight.ops_cause_code", "flight.pax", "flight.notified_at", "mcc.part_eta", "mcc.rts_est",
          "spare.available_within_h",
          "crm.refund_initiated", "crm.bsp_refund", "crm.chargeback", "crm.voucher_issued", "voucher.amount_cents",
          "voucher.signed", "voucher.in_lieu", "voucher.accepted", "claim.amount_claimed_cents",
          "claim.voucher_disputed", "pax.reroute_earliest_offered", "cohort.last_claim_at"}


def test_atomic_spans_reparse_to_their_values(world: World, facts: list[Fact]):
    src = {s.id: s for s in world.sources}
    checked = 0
    for f in facts:
        if f.field in ATOMIC and f.span:
            ok, why = parse.verify(f.field, f.value, f.span, src[f.source_id].text, f.valid_at or f.recorded_at)
            assert ok, (f.id, f.span, f.value, why)
            checked += 1
    assert checked > 150


def test_golden_hero_facts(facts: list[Fact]):
    idx = {(f.subject, f.field): f for f in facts}
    nsb = "aircraft:EI-NSB"
    assert idx[(nsb, "aog.mel_relief")].value is False and idx[(nsb, "aog.mel_relief")].span == "NO MEL RELIEF"
    assert idx[(nsb, "aog.ata_chapter")].value == "2913"
    assert idx[(nsb, "aog.logged_at")].value == "2025-01-23T21:40:00Z"
    ns31 = "flight:NS31@2025-01-24"
    assert idx[(ns31, "flight.ops_cause_code")].value == "71" and idx[(ns31, "flight.ops_cause_code")].span == "RSN 71"
    assert idx[(ns31, "mcc.part_eta")].value == "2025-01-25T14:00:00Z"
    assert idx[(ns31, "mcc.rts_est")].value == "2025-01-25T20:00:00Z" and idx[(ns31, "mcc.rts_est")].span == "RTS EST 20:00Z"
    assert idx[("flight:NS117@2025-01-24", "spare.available_within_h")].value == 4.33
    assert idx[("flight:NS117@2025-01-24", "pax.reroute_earliest_offered")].value is True
    assert idx[("flight:NS20@2025-01-23", "flight.ops_cause_code")].span == "RSN 72"
    c14 = "coupon:NS31@2025-01-24:14C"
    assert idx[(c14, "voucher.in_lieu")].value is True and idx[(c14, "voucher.signed")].value is False
    assert idx[(c14, "voucher.amount_cents")].value == 30000
    assert idx[("cohort:EIDW@2024-01-21", "cohort.balance_cents")].value == 360000
    assert idx[("storm:EIDW@2025-01-24", "storm.eurocontrol_departures")].value == 179
    disputed = [f for f in facts if f.field == "claim.voucher_disputed"]
    assert len(disputed) == 1 and disputed[0].value is True


def test_normalize_is_deterministic_and_filterable(world: World, facts: list[Fact]):
    again = world_to_facts(world)
    assert [f.model_dump() for f in again[:2000]] == [f.model_dump() for f in facts[:2000]] and len(again) == len(facts)
    sub = world_to_facts(world, flight_ids=["NS31@2025-01-24"])
    ids = {f.id for f in facts}
    assert sub and all(f.id in ids for f in sub)
    subjects = set(by_subject(sub))
    assert "flight:NS31@2025-01-24" in subjects and "aircraft:EI-NSB" in subjects and "station:KBOS" in subjects
    assert not any(s.startswith("coupon:NS100@") for s in subjects)


def test_resolve_bitemporal_tier_then_latest(world: World, facts: list[Fact]):
    known = t("2025-01-25T06:00:00Z")
    r = resolve(facts, world.sources, known)
    assert not any(k[0].startswith("claim:") and r[k].recorded_at > known for k in r)
    assert len({k[0] for k in r if k[0].startswith("claim:")}) == 6        # only the overnight claims by day 1
    occ = r[("flight:NS31@2025-01-24", "flight.ops_cause_code")]
    tier1 = occ.model_copy(update={"id": "F:test:recode", "source_id": "SRC-TECHLOG-EI-NSB-2025-01-23T2140Z",
                                   "value": "41", "recorded_at": t("2025-01-24T00:00:00Z")})
    r2 = resolve([occ, tier1], world.sources, known)
    assert r2[("flight:NS31@2025-01-24", "flight.ops_cause_code")].value == "41", "better tier beats a later fact"
    later = occ.model_copy(update={"id": "F:test:later", "value": "93", "recorded_at": t("2025-01-25T05:00:00Z")})
    assert resolve([occ, later], world.sources, known)[("flight:NS31@2025-01-24", "flight.ops_cause_code")].value == "93"
    assert resolve([later], world.sources, t("2025-01-25T04:00:00Z")) == {}
