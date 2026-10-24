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
