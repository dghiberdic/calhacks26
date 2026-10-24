"""curves.json loading (format-tolerant, golden-equivalent) and the IAS 8.5 evidence-availability branch."""
from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from books import Books
from books.curves import default_curves, load_curves
from books.periods import age_months, first_month_end

from .helpers import (
    CONTROLLER,
    EOWYN,
    KNOCK_ONS,
    FixedClock,
    flight_id,
    liability_delta,
    recode_to_extraordinary,
    storm,
    ts,
)

DAY1 = ts("2025-01-25T07:00:00Z")
LH = {"segment": "long_haul_gt3500", "points": [[1, 0.09], [3, 0.17], [6, 0.24], [12, 0.29], [18, 0.32]],
      "n_by_point": [412, 398, 377, 341, 290], "observed_through_month": 18, "ultimate": 0.35, "tail_factor": 1.09375,
      "version": "LH-v1"}
FORMATS = {
    "list_of_claim_curves": [LH, {"segment": "medium_1500_3500", "ultimate": 0.27, "version": "MH-v1"},
                             {"segment": "short_le1500", "ultimate": 0.20, "version": "SH-v1"}],
    "dict_by_version": {"LH-v1": LH, "MH-v1": {"ultimate": 0.27}, "SH-v1": {"ultimate": 0.2}},
    "wrapped_month_keys": {"curves": {"long_haul_gt3500": {"points": {"M1": 0.09, "M3": 0.17, "M6": 0.24,
                                                                      "M12": 0.29, "M18": 0.32},
                                                           "ultimate": 0.35}}},
}


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_curves_json_formats_give_golden_numbers(tmp_path: Path, clock: FixedClock, fmt: str):
    path = tmp_path / "curves.json"
    path.write_text(json.dumps(FORMATS[fmt]))
    curves, source = load_curves(path)
    assert source == str(path)
    for seg, d in default_curves().items():
        assert curves[seg].ultimate == d.ultimate and curves[seg].points == d.points, (fmt, seg)
    books = Books(":memory:", clock, curves_path=path)
    world, decisions, ents = storm(["NS31", *KNOCK_ONS], DAY1)
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    assert books.gl_balance("2140") == 8_214_600
    if fmt == "list_of_claim_curves":
        assert books.curve("long_haul_gt3500").n_by_point == [412, 398, 377, 341, 290]


def test_malformed_curves_json_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "curves.json"
    path.write_text("{not json")
    curves, source = load_curves(path)
    assert source == "builtin-defaults" and curves == default_curves()


def test_curve_interpolation_and_m1():
    lh = default_curves()["long_haul_gt3500"]
    assert lh.rate_at(0) == 0 and lh.rate_at(1) == Fraction(9, 100) and lh.rate_at(12) == Fraction(29, 100)
    assert lh.rate_at(2) == Fraction(13, 100) and lh.rate_at(13) == Fraction(295, 1000)
    assert lh.rate_at(72) == lh.rate_at(200) == Fraction(35, 100)
    assert first_month_end(date(2025, 1, 24)) == date(2025, 2, 28)       # Jan 31 is only 7 days after
    assert first_month_end(date(2024, 1, 21)) == date(2024, 2, 29)
    assert age_months(date(2025, 1, 24), "2025-01") == 0 and age_months(date(2025, 1, 24), "2025-02") == 1
    assert age_months(date(2024, 1, 21), "2025-01") == 12


def test_ias8_5_evidence_available_before_lock_is_a_prior_period_error(books: Books, clock: FixedClock):
    world, decisions, ents = storm(["NS31", *KNOCK_ONS], DAY1)
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    before = [e for e in ents if e.flight_id in {flight_id(n) for n in KNOCK_ONS}]
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)
    jan = books.rollforward("2025-01")

    jes = books.post_recode(before, recode_to_extraordinary(before), clock.now(),
                            evidence_received_at=ts("2025-01-25T10:30:00Z"))
    assert jes and all(j.kind == "out_of_period_adjustment" and j.ias8_class == "prior_period_error" for j in jes)
    assert all(j.period == "2025-02" for j in jes)
    assert "prior-period error, corrected in current period (immaterial)" in jes[0].memo
    assert books.rollforward("2025-01") == jan                           # Jan untouched
    feb = books.rollforward("2025-02")
    assert feb.ties_to_gl
    assert feb.rows[0].out_of_period_cents == sum(liability_delta(j) for j in jes) < 0

    # the next month-end re-bases every segment on BF, so the knock-ons end at nil and NS31 at (35% − 9%) × E
    clock.set(ts("2025-02-28T22:00:00Z"))
    books.month_end("2025-02", clock.now())
    assert books.gl_balance("2140") == 2_574_000
    assert books.segment_balances(EOWYN) == {"long_haul_gt3500": 2_574_000, "medium_1500_3500": 0,
                                             "short_le1500": 0}


def test_new_evidence_after_lock_is_a_change_in_estimate(books: Books, clock: FixedClock):
    world, decisions, ents = storm(["NS31", *KNOCK_ONS], DAY1)
    books.post_storm(EOWYN, world, decisions, ents, DAY1)
    before = [e for e in ents if e.flight_id in {flight_id(n) for n in KNOCK_ONS}]
    clock.set(ts("2025-02-03T09:00:00Z"))
    books.lock_period("2025-01", CONTROLLER)                             # locked 2025-02-03T09:00Z
    clock.set(ts("2025-02-03T11:00:00Z"))
    jes = books.post_recode(before, recode_to_extraordinary(before), clock.now(),
                            evidence_received_at=ts("2025-02-03T10:00:00Z"))   # arrived after the lock
    assert jes and all(j.kind == "recode" and j.ias8_class == "change_in_estimate" for j in jes)
    assert all(j.period == "2025-02" for j in jes)
