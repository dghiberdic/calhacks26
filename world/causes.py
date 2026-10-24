"""Latent-cause model (F3a): what *really* happens to each Northstar sector on a world day.

Ground truth comes from these latent draws, never from the engine's storm window:
- **weather** at the DUB end or the outstation end: a cancellation probability from the real METAR near STD/STA
  (gust/sustained/visibility/wx), drawn per sector;
- **internal AOG** (no MEL relief, the NS31 family), the night before at DUB or after an arrival;
- **external hit** (bird strike, lightning: extraordinary per C-315/15);
- **crew** shortage (internal), more likely on storm days once crews time out;
- **ATC** industrial action on a few days (extraordinary);
- **rotation**: the aircraft is not where the sector starts, because its previous sector was cancelled (knock-on).
  A spare ferried from DUB can rescue it if it lands the passengers within 3 h of STD.

Severity uses its own thresholds (not the engine's binary window), so a sector inside a window can fly and a
sector at its edge can be cancelled.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime, timedelta

from contracts.models import MetarObs

NEAR = timedelta(minutes=45)


class ObsIndex:
    """Sorted METAR for one station with fast "obs near t" lookup."""

    def __init__(self, obs: Sequence[MetarObs]) -> None:
        self.obs = sorted(obs, key=lambda o: o.valid)
        self.times = [o.valid for o in self.obs]

    def near(self, t: datetime, window: timedelta = NEAR) -> list[MetarObs]:
        lo = bisect.bisect_left(self.times, t - window)
        hi = bisect.bisect_right(self.times, t + window)
        return self.obs[lo:hi]

    def __bool__(self) -> bool:
        return bool(self.obs)


def obs_severity(o: MetarObs) -> float:
    """Probability that conditions in this one report make Northstar cancel a movement (latent model)."""
    g = o.gust if o.gust is not None else (o.sknt or 0)
    if g >= 55:
        s = 0.92
    elif g >= 50:
        s = 0.75
    elif g >= 45:
        s = 0.42
    elif g >= 40:
        s = 0.2
    elif g >= 35:
        s = 0.08
    elif g >= 33:
        s = 0.02
    else:
        s = 0.0
    if (o.sknt or 0) >= 35:
        s = max(s, 0.7)
    elif (o.sknt or 0) >= 30:
        s = max(s, 0.45)
    if o.vsby_sm is not None and o.vsby_sm < 0.5:
        s = max(s, 0.2)
    wx = (o.wxcodes or "").upper()
    if "FZ" in wx:
        s = max(s, 0.3)
    if "SN" in wx:
        s = max(s, 0.25 if "+SN" in wx else 0.12)
    if "GR" in wx:
        s = max(s, 0.25)
    if "TS" in wx:
        s = max(s, 0.1)
    return s


def severity(idx: ObsIndex | None, t: datetime) -> float:
    if not idx:
        return 0.0
    near = idx.near(t)
    return max((obs_severity(o) for o in near), default=0.0)


def thunder_near(idx: ObsIndex | None, t: datetime) -> bool:
    return bool(idx) and any("TS" in (o.wxcodes or "") for o in idx.near(t, timedelta(minutes=90)))


def max_gust_near(idx: ObsIndex | None, t: datetime, window: timedelta = timedelta(minutes=60)) -> int:
    if not idx:
        return 0
    return max(((o.gust or o.sknt or 0) for o in idx.near(t, window)), default=0)


# per-draw base rates
P_AOG_TAIL_DAY = 0.012
P_MEL_TAIL_DAY = 0.05
P_BIRD = 0.0015
P_LIGHTNING_STORM = 0.012
P_CREW = 0.0015
P_CREW_STORM_LATE = 0.006
P_ATC_STRIKE_DAY = 0.05
P_ATC_CANCEL = 0.3
ATC_STRIKE_COUNTRIES = ("FR", "ES", "IT", "PT", "CH")
P_SPARE_CALM = 0.7
P_SPARE_STORM = 0.4
P_OCC_MISBATCH = 0.8          # storm day: a non-weather cancellation known before the batch gets RSN 71 anyway
P_HIDDEN_CREW_IN_WEATHER = 0.30  # positioned weather draws only; yields about 5% ambiguous cancellations overall
P_REROUTE_EARLIEST = 0.85
