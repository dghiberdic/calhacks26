# engine/ decisions (lane A, David)

Judgment calls made while implementing, one line of reasoning each. Newest at the bottom of each section.

## D1 · `engine/timeline.py`

**Computed windows on the pinned real METAR.** These come from data and are not hard-coded:

| File | Window (UTC) | Peak | Counting obs |
|---|---|---|---|
| `eidw_2025-01-23_25.csv` | 2025-01-23 23:30 → 2025-01-24 00:30 (minor) | G38 | 2 |
| `eidw_2025-01-23_25.csv` | **2025-01-24 02:30 → 15:00 (main)** | G56 | 24 |
| `eidw_2025-01-26.csv` (Herminia) | **2025-01-26 11:30 → 13:00** | G43 | 3 |

The real data matches every expectation in plan §1.2 and THREAD_DAVID D1. Nothing contradicted the plan.

- **Merge rule: "under 2 h" is strict.** The minor window's last counting obs (00:30, G35) and the main window's first (02:30, G39) are exactly 2 h apart, so they do not merge. That is why the minor window stays separate, as the plan says it should.
- **Edges are inclusive.** A time exactly on `start` or `end` is `in`, with margin 0.
- **`unknown` is checked first.** If no obs falls within ±60 min (inclusive) of `t`, the answer is `unknown` even if a window passed in covers `t`. With gaps under 2 h merged, every point inside a window built from the same obs is under 60 min from a counting obs, so this only matters when the obs and windows passed in disagree.
- **Margin sign.** `margin_min` is positive when outside a window (minutes to the nearest edge of the nearest window), negative when inside (minutes to the nearer edge), and 0 on an edge. It is `None` when there are no windows. This matches CONTRACTS "NS31 is outside the DUB window with margin ≥60" (NS31 STD 16:30Z gives +90). `EndPosition.margin_min` is also `None` when the position is `unknown`.
- **A hole of 2 h or more in the data splits a window.** If obs are missing mid-storm, the counting obs on either side are ≥2 h apart, so they form two windows. Times within 60 min of the last storm obs before the hole read `out` with a small margin (≤60). Times further into the hole read `unknown`. This follows the binding definition literally. D2 should treat a small positive margin as weak evidence of calm.
- **Matching wx codes.** Each present-weather token has its `+`/`-` stripped and is split into 2-letter groups (`-FZRA` → FZ, RA; `+TSRAGR` → TS, RA, GR), and the check is against {SN, FZ, TS, GR}. On real codes this gives the same result as a substring test, and it can't produce cross-group false positives. Recent-weather groups (`RETS`) would count. The pinned days contain none: the IEM `wxcodes` column holds only present weather (`-RA`, `RA`, `-RADZ`).
- **`peak_gust_kt`** is the highest gust of any obs inside the window. When an obs reports no gust, its sustained wind is used instead. A fog-only window can therefore have a small "peak".
- **`obs_count`** is the number of counting obs that formed the window, not every obs inside its span (the main window spans 26 obs, 24 of them counting).
- **Station id.** `load_iem_csv` uses the ICAO at the head of the raw METAR (`KBOS`), because IEM's `station` column uses 3-letter ids for US stations (`BOS`). An explicit `station=` argument wins. Empty cells and IEM's `M` become `None`. Output is sorted by time.
- **Outstations without METAR are `unknown`, never assumed calm.** `departure_position(NS117, [], [])` returns `unknown`. If `world.json` only carries EIDW, every outstation departure end (LHR, CDG, MUC, LIS, FCO, BOS…) is `unknown`. In that case the D2 knock-on rule ("out at both ends") cannot fire without outstation METAR. Lane B: put calm outstation METAR in `world.metar` for at least LIS/FCO/MUC on 2025-01-24, or D2 will have to decide what `unknown` at the outstation means.
- **Naive datetimes raise `ValueError`.** Engine times must be tz-aware UTC.

## Purity (`engine/tests/test_purity.py`)

- The test is an AST scan of `engine/**.py` and `books/**.py`. It skips `books/` until it exists, skips `tests/` dirs and `conftest.py` (test code makes no decisions), and asserts that at least one engine file was scanned.
- **Banned:**
  - any import of `anthropic`, `random`, `secrets`, or `numpy.random`;
  - `datetime.now`, `datetime.utcnow`, `date.today` (including through `import datetime as dt` and `from datetime import datetime as X`), whether called or merely referenced;
  - `time.time`, `time.time_ns`, `uuid.uuid1`, `uuid.uuid4`, `os.urandom`;
  - dynamic imports of the banned modules (`__import__`, `importlib.import_module`).

  `time`, `uuid` and `os.urandom` go a little beyond the letter of rule 1. They are the same wall-clock and randomness sources under other names.
- The injected `clock.now()` / `self.clock.now()` stays allowed. Positive and negative self-tests keep the checker honest.
