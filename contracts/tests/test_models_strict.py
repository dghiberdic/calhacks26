"""D0b-6 contract tightening: UTC-only datetimes, ID charset, strict integer cents (integrity review #11)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import orjson
import pytest
from pydantic import ValidationError

from contracts.models import Coupon, Fact, Flight, Question

UTC = timezone.utc
T = datetime(2025, 1, 24, 16, 30, tzinfo=UTC)


def fact(t: datetime, fid: str = "F-1") -> Fact:
    return Fact(id=fid, source_id="SRC-1", subject="flight:NS31@2025-01-24", field="flight.sched_dep", value="x",
                extractor="e", recorded_at=t)


def h(m) -> str:
    return hashlib.sha256(orjson.dumps(m.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)).hexdigest()


def test_offset_datetimes_are_stored_in_utc_and_hash_the_same():
    cet = T.astimezone(timezone(timedelta(hours=1)))
    a, b = fact(T), fact(cet)
    assert b.recorded_at.utcoffset() == timedelta(0) and h(a) == h(b)
    assert b.model_dump(mode="json")["recorded_at"] == "2025-01-24T16:30:00Z"
    assert Fact.model_validate_json(orjson.dumps(dict(a.model_dump(mode="json"), recorded_at="2025-01-24T17:30:00+01:00")
                                                 )).recorded_at == T


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValidationError, match="naive datetime"):
        fact(datetime(2025, 1, 24, 16, 30))
    with pytest.raises(ValidationError):
        Fact.model_validate_json(orjson.dumps(dict(fact(T).model_dump(mode="json"), recorded_at="2025-01-24T16:30:00")))


@pytest.mark.parametrize("bad", ["F 1", "F/1", "../etc", "é", "<script>", "", "F#1", "a b"])
def test_ids_use_the_id_charset(bad):
    with pytest.raises(ValidationError, match="may use only"):
        fact(T, bad)


def test_good_ids_still_validate():
    for good in ("F:TECHLOG-EI-NSB-2025-01-23T2140Z:aog.mel_relief", "NS31@2025-01-24:14C", "Q-EIDW@2025-01-26:x_y"):
        assert fact(T, good).id == good


@pytest.mark.parametrize("bad", [True, "1200", 12.5, 12.0, None])
def test_cents_are_strict_integers(bad):
    with pytest.raises(ValidationError):
        Coupon(id="c", pnr="p", pax_ref="x", flight_id="f", fare_cents=bad, taxes_cents=0)


def test_json_integers_still_validate_as_cents():
    c = Coupon.model_validate_json(b'{"id":"c","pnr":"p","pax_ref":"x","flight_id":"f","fare_cents":45000,'
                                   b'"taxes_cents":6000}')
    assert (c.fare_cents, c.taxes_cents) == (45000, 6000)


def test_lists_of_ids_and_optional_ids_are_checked():
    with pytest.raises(ValidationError):
        Flight(id="NS1@2025-01-24", number="NS1", date="2025-01-24", origin="DUB", dest="LHR", sched_dep=T,
               sched_arr=T, aircraft="EI-NSB", status="cancelled", pax=1, inbound_flight_id="bad id")
    assert "case_refs" in Question.model_fields and "holds" in Question.model_fields
