"""€-basis claim curves per segment (CONTRACTS §5 curves.json: LH-v1 M1 .09 M3 .17 M6 .24 M12 .29 M18 .32 ult .35).

Loaded from contracts/fixtures/golden/curves.json when it exists and parses; otherwise built-in defaults with the
same values. Interpolation between points is linear; beyond the last observed point the curve runs linearly to the
ultimate at the 6-year limitation (month 72). Medium/short curves without their own points reuse the LH shape
scaled to their ultimate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

from contracts.models import ClaimCurve

from .money import rate

LONG, MEDIUM, SHORT = "long_haul_gt3500", "medium_1500_3500", "short_le1500"
SEGMENTS = (LONG, MEDIUM, SHORT)
BAND_SEGMENT = {600: LONG, 400: MEDIUM, 250: SHORT}
LIMITATION_MONTH = 72

DEFAULT_CURVES_PATH = Path(__file__).resolve().parent.parent / "contracts" / "fixtures" / "golden" / "curves.json"
DEFAULT_LH_POINTS = ((1, "0.09"), (3, "0.17"), (6, "0.24"), (12, "0.29"), (18, "0.32"))
DEFAULT_ULTIMATE = {LONG: "0.35", MEDIUM: "0.27", SHORT: "0.20"}
DEFAULT_VERSION = {LONG: "LH-v1", MEDIUM: "MH-v1", SHORT: "SH-v1"}
DEFAULT_TAIL_NOTE = "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% for cancellations)"


def segment_of_band(band_eur: int) -> str:
    return BAND_SEGMENT[int(band_eur)]


def normalize_segment(s: str | None) -> str:
    t = (s or "").strip().lower()
    if t in SEGMENTS:
        return t
    if t.startswith(("long", "lh")) or "gt3500" in t:
        return LONG
    if t.startswith(("med", "mh")) or "1500_3500" in t:
        return MEDIUM
    if t.startswith(("short", "sh")) or "le1500" in t:
        return SHORT
    raise ValueError(f"unknown curve segment {s!r}")


@dataclass(frozen=True)
class Curve:
    segment: str
    version: str
    ultimate: Fraction
    points: tuple[tuple[int, Fraction], ...]
    n_by_point: tuple[int, ...]
    observed_through_month: int
    tail_note: str = DEFAULT_TAIL_NOTE

    def rate_at(self, age: int) -> Fraction:
        """Expected cumulative € claim rate at development age `age` (months, M1 = 1)."""
        if age <= 0:
            return Fraction(0)
        if age >= LIMITATION_MONTH:
            return self.ultimate
        pts = [(0, Fraction(0)), *self.points]
        for (m0, r0), (m1, r1) in pairwise(pts):
            if m0 <= age <= m1:
                return r0 + (r1 - r0) * Fraction(age - m0, m1 - m0)
        m_last, r_last = pts[-1]
        return r_last + (self.ultimate - r_last) * Fraction(age - m_last, LIMITATION_MONTH - m_last)

    def remaining_rate(self, age: int) -> Fraction:
        return self.ultimate - self.rate_at(age)

    def to_model(self) -> ClaimCurve:
        last = self.points[-1][1] if self.points else self.ultimate
        return ClaimCurve(
            segment=self.segment,
            points=[(m, round(float(r), 4)) for m, r in self.points],
            n_by_point=list(self.n_by_point),
            observed_through_month=self.observed_through_month,
            ultimate=round(float(self.ultimate), 4),
            tail_factor=round(float(self.ultimate / last), 4) if last else 1.0,
            tail_note=self.tail_note,
            version=self.version,
        )


def _scaled(points: tuple[tuple[int, Fraction], ...], from_ult: Fraction, to_ult: Fraction):
    return tuple((m, r * to_ult / from_ult) for m, r in points)


def default_curves() -> dict[str, Curve]:
    lh_pts = tuple((m, rate(r)) for m, r in DEFAULT_LH_POINTS)
    lh_ult = rate(DEFAULT_ULTIMATE[LONG])
    out = {}
    for seg in SEGMENTS:
        ult = rate(DEFAULT_ULTIMATE[seg])
        pts = lh_pts if seg == LONG else _scaled(lh_pts, lh_ult, ult)
        out[seg] = Curve(seg, DEFAULT_VERSION[seg], ult, pts, tuple(0 for _ in pts), lh_pts[-1][0])
    return out


def _points(raw: Any) -> tuple[tuple[int, Fraction], ...]:
    pts: list[tuple[int, Fraction]] = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            pts.append((int(str(k).upper().lstrip("M")), rate(v)))
    elif isinstance(raw, list):
        for p in raw:
            if isinstance(p, dict):
                m = p.get("month", p.get("m", p.get("age")))
                pts.append((int(str(m).upper().lstrip("M")), rate(p.get("rate", p.get("value")))))
            else:
                pts.append((int(p[0]), rate(p[1])))
    return tuple(sorted(pts))


def _items(data: Any) -> list[dict]:
    if isinstance(data, dict):
        for key in ("curves", "segments"):
            if key in data:
                return _items(data[key])
        if "segment" in data:
            return [data]
        return [dict(v, segment=v.get("segment", k)) for k, v in data.items() if isinstance(v, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def parse_curves(data: Any) -> dict[str, Curve]:
    """Tolerant parser for curves.json (list of ClaimCurve-like objects, or a dict keyed by segment)."""
    defaults = default_curves()
    parsed: dict[str, dict] = {}
    for item in _items(data):
        try:
            parsed[normalize_segment(item.get("segment"))] = item
        except ValueError:
            continue
    out: dict[str, Curve] = {}
    lh = parsed.get(LONG)
    lh_pts = _points(lh.get("points")) if lh and lh.get("points") else defaults[LONG].points
    lh_ult = rate(lh["ultimate"]) if lh and "ultimate" in lh else defaults[LONG].ultimate
    for seg in SEGMENTS:
        item, d = parsed.get(seg), defaults[seg]
        if not item:
            out[seg] = d
            continue
        ult = rate(item["ultimate"]) if "ultimate" in item else d.ultimate
        pts = _points(item.get("points")) if item.get("points") else _scaled(lh_pts, lh_ult, ult)
        n = tuple(int(x) for x in item.get("n_by_point", [])) or tuple(0 for _ in pts)
        if len(n) != len(pts):
            n = tuple(0 for _ in pts)
        out[seg] = Curve(seg, str(item.get("version", d.version)), ult, pts, n,
                         int(item.get("observed_through_month", pts[-1][0] if pts else 0)),
                         str(item.get("tail_note", DEFAULT_TAIL_NOTE)))
    return out


def load_curves(path: str | Path | None = None) -> tuple[dict[str, Curve], str]:
    """Returns (curves, source) where source is the file path or "builtin-defaults"."""
    p = Path(path) if path else DEFAULT_CURVES_PATH
    if p.is_file():
        try:
            return parse_curves(json.loads(p.read_text())), str(p)
        except (ValueError, KeyError, TypeError, IndexError):
            pass
    return default_curves(), "builtin-defaults"
