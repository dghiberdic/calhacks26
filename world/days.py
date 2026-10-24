"""Which days the Northstar world covers (F3a): real EIDW storm days plus ~40 background days.

- **Storm days** come from the pinned 24-month EIDW METAR with the plan §5 rule (gust ≥35 kt reported in ≥3 distinct
  UTC clock hours; see `world.metar.storm_days`). Nothing is hard-coded: the list is recomputed from data.
- **Background days** are ordinary days, chosen deterministically (sha256 rank, a fixed salt, independent of the
  generator seed so the pinned outstation METAR always covers them): 28 in the learn split, 12 in the score split.
  They exclude storm days and the golden days around Éowyn/Herminia.
- **Split:** learn Jul 2023 → Dec 2024 ("train"), score Jan → Jun 2025 ("test").
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from world import metar
from world.metar import DaySummary

WORLD_START = date(2023, 7, 1)
WORLD_END = date(2025, 7, 1)          # exclusive
SCORE_START = date(2025, 1, 1)
GOLDEN_DAYS = frozenset({date(2025, 1, 23), date(2025, 1, 24), date(2025, 1, 25), date(2025, 1, 26),
                         date(2025, 1, 27)})
EOWYN = date(2025, 1, 24)
HERMINIA = date(2025, 1, 26)
ISHA = date(2024, 1, 21)
BACKGROUND_LEARN = 28
BACKGROUND_SCORE = 12
BACKGROUND_SALT = "northstar-background-v1"


def split_of(d: date) -> str:
    return "train" if d < SCORE_START else "test"


@dataclass(frozen=True)
class WorldDay:
    day: date
    kind: str                 # "storm" | "background"
    split: str                # "train" | "test"
    summary: DaySummary | None

    @property
    def storm_id(self) -> str:
        return f"EIDW@{self.day.isoformat()}"


@lru_cache(maxsize=1)
def eidw_summaries() -> dict[date, DaySummary]:
    obs = []
    d = WORLD_START
    while d < WORLD_END:
        obs.extend(metar.pinned_day("EIDW", d) or [])
        d += timedelta(days=1)
    return {s.day: s for s in metar.summarize_days(obs, 35)}


@lru_cache(maxsize=1)
def storm_days() -> tuple[date, ...]:
    return tuple(sorted(d for d, s in eidw_summaries().items() if s.hours_gust_ge >= 3))


def _rank(d: date) -> str:
    return hashlib.sha256(f"{BACKGROUND_SALT}:{d.isoformat()}".encode()).hexdigest()


@lru_cache(maxsize=1)
def background_days() -> tuple[date, ...]:
    storms = set(storm_days())
    sums = eidw_summaries()
    cands = [d for d in sums if d not in storms and d not in GOLDEN_DAYS and WORLD_START <= d < WORLD_END
             and sums[d].obs >= 30]
    learn = sorted((d for d in cands if d < SCORE_START), key=_rank)[:BACKGROUND_LEARN]
    score = sorted((d for d in cands if d >= SCORE_START), key=_rank)[:BACKGROUND_SCORE]
    return tuple(sorted(learn + score))


@lru_cache(maxsize=1)
def world_days() -> tuple[WorldDay, ...]:
    sums = eidw_summaries()
    out = [WorldDay(d, "storm", split_of(d), sums.get(d)) for d in storm_days()]
    out += [WorldDay(d, "background", split_of(d), sums.get(d)) for d in background_days()]
    return tuple(sorted(out, key=lambda w: w.day))
