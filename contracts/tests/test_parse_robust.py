"""parse.py never crashes on bad input: every parser either returns a value or raises ParseError (the module's
"unparseable" result), and verify() turns that into (False, "unparseable_span"). An impossible time like
`24JAN 25:99Z` once escaped as a bare ValueError and became a 500 behind /api/inject (F9 fuzz)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from contracts import fields, parse

REF = datetime(2025, 1, 24, 6, 0, tzinfo=timezone.utc)
TECH = "24JAN 25:99Z EI-NSB DUB N/S. NO MEL RELIEF. A/C AOG."

BAD = {
    "time": ["24JAN 25:99Z", "24JAN 24:00Z", "23JAN 21:60Z", "2025-13-45T25:61:00Z", "2025-02-30T10:00:00Z",
             "2025-01-24T24:30Z", "32JAN 10:00Z", "00JAN 10:00Z", "30FEB 10:00Z", "29FEB 2025 10:00Z", "991630Z",
             "242530Z", "241699Z", "99:99Z", "25:00Z", "", "Z", "::Z", "2025-00-10T10:00Z"],
    "date": ["2025-13-01", "2025-02-30", "2025-00-10", "32/01/2025", "31/13/2025", "00/01/2025", "31 FEB 2025",
             "30 Feb 2025", "29FEB25", "0 Jan 2025", "Jan 32, 2025", "Feb 30, 2025", "", "99/99/99"],
    "ata": ["", "ATA", "ATA x", "-"],
    "tail": ["", "E-", "A/C", "-NSB"],
    "flight_number": ["", "31", "N"],
    "iata": ["", "12", "D"],
    "seat": ["", "seat", "99Z"],
    "delay_code": ["", "RSN", "RSN 7", "CODE x"],
    "int": ["", "abc", "-", ","],
    "float": ["", "abc", "."],
    "pct": ["", "%", "abc%"],
    "eur": ["", "€", "EUR", "600", "€.", "£520", "EUR ,", "€,,,", "EUR 1.2.3,4"],
    "gbp": ["", "£", "€600", "GBP"],
    "minutes": ["", "h", "STD+", "min"],
    "duration_h": ["", "STD+h", "x h"],
    "bool": ["", "   "],
    "mel_relief": ["", "MEL", "relief"],
    "aog": ["", "A/C", "ground"],
    "signed": ["", "signature", "sig"],
    "disputed": ["", "voucher"],
    "not_weather": ["", "AOG", "cancelled"],
}


def test_every_parser_has_bad_cases():
    assert set(BAD) == set(parse.PARSERS)


@pytest.mark.parametrize("kind,span", [(k, s) for k, spans in BAD.items() for s in spans])
def test_bad_spans_raise_parse_error_only(kind, span):
    fn = parse.PARSERS[kind]
    try:
        fn(span, REF)
    except parse.ParseError:
        return
    if kind in ("int", "float", "bool"):
        return                         # lenient parsers may return a value; they just must not crash
    if kind == "time" and span in ("2025-13-45T25:61:00Z",):
        pytest.fail("impossible ISO time accepted")


@pytest.mark.parametrize("kind", sorted(parse.PARSERS))
@pytest.mark.parametrize("span", [None, 42, b"24JAN", ["x"]])
def test_non_string_spans_are_unparseable(kind, span):
    with pytest.raises(parse.ParseError):
        parse.PARSERS[kind](span, REF)


def test_impossible_times_and_dates_are_unparseable():
    for s in ("24JAN 25:99Z", "2025-13-45T25:61:00Z", "30FEB 10:00Z", "241699Z"):
        with pytest.raises(parse.ParseError):
            parse.parse_time(s, REF)
    for s in ("2025-02-30", "31/13/2025", "31 FEB 2025"):
        with pytest.raises(parse.ParseError):
            parse.parse_date(s, REF)
    assert parse.parse_time("24JAN 21:40Z", REF).hour == 21     # valid neighbours still parse


def test_verify_rejects_an_impossible_time_instead_of_raising():
    assert parse.verify("aog.logged_at", "2025-01-24T21:40:00Z", "24JAN 25:99Z", TECH, REF) == (
        False, "unparseable_span")
    assert parse.verify("aog.mel_relief", False, "NO MEL RELIEF", TECH, REF) == (True, "reparsed")


@settings(max_examples=300, deadline=None)
@given(kind=st.sampled_from(sorted(parse.PARSERS)), span=st.text(max_size=40))
def test_fuzz_parsers_return_or_raise_parse_error(kind, span):
    try:
        parse.PARSERS[kind](span, REF)
    except parse.ParseError:
        pass


@settings(max_examples=300, deadline=None)
@given(day=st.integers(-5, 99), month=st.sampled_from(["JAN", "FEB", "DEC", "jan"]), hh=st.integers(0, 99),
       mm=st.integers(0, 99), year=st.integers(0, 99999))
def test_fuzz_out_of_range_time_and_date_tokens(day, month, hh, mm, year):
    for span in (f"{day:02d}{month} {hh:02d}:{mm:02d}Z", f"{year:04d}-{month[:2]}-{day:02d}T{hh:02d}:{mm:02d}Z",
                 f"{day:02d}{hh:02d}{mm:02d}Z", f"{day}/{hh}/{year}", f"{day} {month} {year}",
                 f"{year:04d}-{hh:02d}-{day:02d}"):
        for fn in (parse.parse_time, parse.parse_date):
            try:
                fn(span, REF)
            except parse.ParseError:
                pass


@settings(max_examples=300, deadline=None)
@given(field=st.sampled_from(sorted(fields.REGISTRY)), span=st.text(max_size=30),
       value=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=10)))
def test_fuzz_verify_never_raises(field, span, value):
    ok, reason = parse.verify(field, value, span, TECH + span, REF)
    assert isinstance(ok, bool) and isinstance(reason, str)


# ---------------------------------------------------------------- Reader requests (llm/DECISIONS.md)
@pytest.mark.parametrize("span", ["EI-NSB", "ei-nsb", "23JAN 21:40Z EI-NSB DUB N/S.", "G-EUPT", "D-AIBL", "F-HPJA",
                                  "OE-LBA", "C-FKAU", "4X-EKA", "tail N123AB at BOS", "N12345"])
def test_parse_tail_accepts_registrations(span):
    assert parse.parse_tail(span) == parse.parse_tail(span.upper())
    assert "-" in parse.parse_tail(span) or parse.parse_tail(span).startswith("N")


@pytest.mark.parametrize("span", ["EX-TLS", "POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z", "UNIT EX-HAM", "XX-ABC",
                                  "EI-NSBXY", "EI-", "-NSB", "A/C AOG", "RTS-EST", "ENG 1 N1 HIGH", "EDP PRESS LINE B-NUT",
                                  "NS-31", "ZZ-1234"])
def test_parse_tail_rejects_look_alikes(span):
    with pytest.raises(parse.ParseError):
        parse.parse_tail(span)


def test_parse_tail_skips_ex_station_and_finds_the_real_tail():
    assert parse.parse_tail("FW: EI-NSB AOG · POOL UNIT EX-TLS VIA CDG") == "EI-NSB"
    assert parse.parse_tail("POOL UNIT EX-TLS VIA CDG FOR EI-NSB") == "EI-NSB"


def test_verify_collapses_whitespace_but_keeps_case():
    text = "From: mcc.dub\n\nocc - pls note NS31 is NOT a wx cancel,\n  ac was u/s since last nite."
    assert parse.verify("ops.not_weather", True, "NS31 is NOT a wx cancel, ac was u/s", text, REF) == (
        True, "reparsed")
    assert parse.verify("ops.not_weather", True, "NS31  is\nNOT a wx cancel", text, REF)[0]
    assert parse.verify("ops.not_weather", True, "ns31 is not a wx cancel", text, REF) == (False, "span_not_in_source")
    assert parse.verify("ops.not_weather", True, "   ", text, REF) == (False, "span_not_in_source")


def test_new_fields_ops_not_weather_and_mcc_rts_est():
    assert fields.get("ops.not_weather").type == "bool" and fields.get("mcc.rts_est").type == "datetime"
    assert parse.parse_not_weather("NS31 is NOT a wx cancel") is True
    assert parse.parse_not_weather("it was AOG anyway") is True
    assert parse.parse_not_weather("storm weather cancel") is False
    assert parse.verify("mcc.rts_est", "2025-01-25T20:00:00Z", "RTS EST 20:00Z",
                        "ETA 14:00Z, RTS EST 20:00Z.", datetime(2025, 1, 25, 14, 0, tzinfo=timezone.utc))[0]


# ---------------------------------------------------------------- integrity review #3 / #4 (exact cases)
@pytest.mark.parametrize("fn,span", [
    (parse.parse_time, "23JAN 25:99Z"), (parse.parse_time, "31FEB 21:40Z"), (parse.parse_time, "2025-02-30T10:00Z"),
    (parse.parse_time, "321640Z"), (parse.parse_time, "242599Z"),
    (parse.parse_date, "31/02/2025"), (parse.parse_date, "1/13/2025"), (parse.parse_date, "Feb 30, 2025"),
    (parse.parse_date, "29FEB"), (parse.parse_date, "00JAN"),
    (parse.parse_eur, "€1\t234"), (parse.parse_eur, "EUR 1\n234"), (parse.parse_eur, "€" + "9" * 400),
    (parse.parse_eur, "1e309 €"), (parse.parse_int, "NS" + "9" * 5000),
    (parse.parse_time, "21:40 CET"), (parse.parse_time, "16:30 local"), (parse.parse_time, "2025-01-24 16:30 BST"),
])
def test_review_cases_are_unparseable(fn, span):
    with pytest.raises(parse.ParseError):
        fn(span, REF)


@pytest.mark.parametrize("span,expected", [
    ("2025-01-23T21:40+05:00", "2025-01-23T16:40:00+00:00"),
    ("2025-01-23T16:40:00-08:00", "2025-01-24T00:40:00+00:00"),
    ("2025-01-23T21:40:00Z", "2025-01-23T21:40:00+00:00"),
    ("2025-01-23 21:40 UTC", "2025-01-23T21:40:00+00:00"),
    ("21:40+01:00", "2025-01-24T20:40:00+00:00"),
    ("23JAN 21:40+0100", "2025-01-23T20:40:00+00:00"),
    ("2025-01-24 16:30", "2025-01-24T16:30:00+00:00"),            # IEM CSV: UTC by definition
])
def test_numeric_offsets_are_converted_to_utc(span, expected):
    assert parse.parse_time(span, REF).isoformat() == expected


def test_money_with_spaces_still_parses():
    assert parse.parse_eur("€1 234") == 123400 and parse.parse_eur("€1 234,50") == 123450
    assert parse.parse_eur("EUR 510.00") == 51000


def test_reparse_and_verify_absorb_value_errors():
    assert parse.verify("coupon.fare_cents", 1, "€" + "9" * 400, "x €" + "9" * 400, REF) == (False, "unparseable_span")
    with pytest.raises(parse.ParseError):
        parse.reparse("flight.pax", "NS" + "9" * 5000)
