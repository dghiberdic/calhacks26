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

## D3 · `engine/eu261.py` (+ `engine/geo.py`, `engine/dsl.py`)

- **Status order per coupon:** out_of_scope → staff_ticket → exempt_notice → (decision) no_compensation / held → owed, then the voucher check (owed or needs_ruling). The flight-level question (held) dominates a coupon-level one (an unsigned voucher on a held flight stays `held`).
- **Distances.** `world.meta["distances_km"]` wins when it pins the pair (keys `DUB-BCN`, `BCN-DUB`, `DUBBCN`, `DUB:BCN`, or a flat `{dest: km}`); otherwise great circle with R = 6,371 km from `World.airports`, falling back to the bundled `airportsdata` table for codes the world lacks. Rounded to 0.1 km. airportsdata coordinates give DUB–BCN 1,485.2 km (plan: 1,486), so the margin is 14.8 km with the fallback and exactly 14 with the plan's pinned value. Both read "14 km under the €400 band" (`int`).
- **`band_margin_km`** is the distance to the threshold that would change the band: ≤1,500 → 1,500 − d; intra-EU >1,500 → d − 1,500 (there is no 3,500 km edge intra-EU); other 1,500–3,500 → the nearer of the two edges; >3,500 → d − 3,500. "Intra-EU" means both ends are in EU261 territory (EU27 + IS/LI/NO + CH), so DUB–LHR is not intra-EU.
- **Art. 7(2) reduction** needs all of: a reroute election (`reroute_partner` or `reaccommodated_own`); an arrival delay that does not exceed 2 h / 3 h / 4 h for the coupon's band (≤, "does not exceed"); and an *active* `APPLY_7_2_REDUCTION` rule (e.g. `R-MINED-REDUCE`) whose scope and condition match, in force at `known_at`. A shadow or late-recorded rule gives no reduction (NS31 = 10,320,000 instead of 9,900,000). The rule ref is in `rules_applied`.
- **Art. 5(1)(c) notice:** `pax.notice_days` = (STD − `Flight.notified_at`) in days. (i) ≥14 days is exempt. (ii)/(iii) also need the rerouted *departure* time, which `Election` doesn't carry. `notice_exemption` takes `departure_advance_min` from a caller that knows it. Without it the carrier hasn't shown the condition, so the passenger is **not** exempt (conservative, pro-passenger).
- **Scope (Art. 3):** origin in EU261 territory → (1)(a); else destination in territory on an EU carrier → (1)(b); else `out_of_scope`. Out-of-scope and staff tickets (Art. 3(3)) get `care_due = False`, because the whole Regulation doesn't apply to them. Every in-scope coupon gets `care_due = True`, including extraordinary ones (McDonagh).
- **Refunds (Art. 8):** a known `refund_initiated` **or** `bsp_refund` sets `refund_already_initiated` and `refund_due = 0`. Two refund events on one coupon, or a chargeback after a refund, are flagged in `reason` ("duplicate refund … flagged, not repeated"). Otherwise a `refund` election gives `refund_due = fare + taxes`; a refund voucher election gives 0 (settled by voucher). Refund ≠ waiver: the 32 bot-refunded NS31 coupons stay `owed` €600.
- **Vouchers (Art. 7(3)):** the latest known `voucher_in_lieu_of_compensation` event counts. If signed (`signed_acceptance_sha256` set), the status is `owed` with offset = min(amount, compensation); `compensation_cents` stays gross (Books accrues gross). If unsigned and no voucher rule applies → `needs_ruling` (the engine does not pre-answer Q1). If a voucher rule applies, the strongest wins: `DENY_OFFSET` (R-CL-1) → owed, offset 0; `ALLOW_OFFSET` → owed with offset.
- **Held** (decision `needs_legal`) accrues at the full band amount with no 7(2) reduction, so Books' segment-rate accrual gives the golden knock-on numbers.
- **Only cancelled flights** get entitlements. Delays (Sturgeon ≥3 h) are out of scope for the demo and return [].
- **`rules_applied`** on an entitlement = the decision's rules + the coupon-level rules (reduction, voucher). D5's citation counting has to count flight-level rules once per decision, not per coupon.
- **DSL (`engine/dsl.py`)** was written here because entitlement rules need it; D4 builds precedence/authority/grounding on top. A missing feature reads as `None` (comparisons are false; `exists` false). A type mismatch is false, never an exception. An invalid rule never fires. Scope keys are the allowlisted features plus the context keys `storm`, `cohort`, `flight`, `station`, `segment`, `coupon`. `case:<v>` values constrain like literals (`case:true`/`case:false` parse as booleans).
- **Bitemporal:** a rule fires only if `status == active`, `recorded_at ≤ known_at`, and `valid_from` is None or ≤ the flight date.
