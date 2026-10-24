# world/ decisions (Filip lane A)

Judgment calls made while implementing, newest last. Each one says what we chose and why.

## F1 · METAR fetch + pins

1. **Pinned files are verbatim IEM CSV.** Every pin is IEM `format=onlycomma` output (`station,valid,sknt,gust,drct,vsby,wxcodes,metar`),
   split per UTC day. `EIDW@2025-01-23/24/26.csv` are row-for-row identical to `contracts/fixtures/golden/eidw_*.csv`
   (a test enforces this). IEM writes `BOS` for `KBOS`; the loader sets `MetarObs.station` to the ICAO that was asked for.
2. **Bundles can be sparse.** A day counts as pinned when a daily file exists, or when some `<ICAO>_*.csv.gz` bundle has rows
   for that day. The filename range is only a label. This lets one loader serve the full EIDW 24-month bundle and the
   small `<ICAO>_storms_*` bundles (storm days only).
3. **Ranges are half-open `[start, end)` in UTC.** Naive datetimes count as UTC. Results are sorted and deduplicated on (valid, raw).
   **`fetch_metar` never returns `[]`:** no data means `WorldError("no_metar")`.
4. **Offline mode with partial coverage returns what is pinned.** Only a range with no pinned rows at all is a "miss"
   (`no_metar`). Missing hours become `in_window=unknown` in the engine, which routes them to Ops. That is the honest outcome.
5. **Cache/live mode fetches only the missing span.** The network is asked for the span between the first and last missing
   UTC days, and the result is merged with the pinned days. If the network fails, any partial pinned data is still returned.
   For METAR, `live` behaves like `cache`: the pins are immutable historical observations, so there is nothing to refresh.
6. **Rate limits.** There is a module-level `Throttle`: 1.0 s for IEM (1 request/s/IP) and 1.0 s for AWC. The pin script
   raises IEM spacing to 1.5 s. Responses 429/502/503/504 are retried up to 4 attempts, with backoff of 2 s, 4 s, 8 s or the
   `Retry-After` value (capped at 30 s).
   - **Interactive requests** use the 8 s timeout and do **not** retry timeouts or connection errors. They fall through to
     AWC, so a desk request on bad wifi fails fast.
   - **The pin script** retries transport errors and uses a 300 s timeout, because a 24-month response is about 4 MB.
7. **Gust QC.** A gust more than 50 kt above the mean wind is dropped (`gust=None`), but `raw` keeps the METAR verbatim.
   The real case is EIDW `091130Z 35008G100KT` on 2024-12-09 (Q1041, a calm day). Without QC it would create a false
   one-report storm window on a background day.
8. **AWC normalisation.** The `METAR `/`SPECI ` prefix is stripped from `rawOb` to match IEM's raw format. `visib "6+"` becomes
   6.0 SM; IEM writes 9999 m as 6.21 SM, and both are far above every threshold. `wdir "VRB"` becomes `drct=None`.
9. **Éowyn "gusts ≥40 kt from 03:00 to 12:30Z" describes a span, not every report.** In the real data the first ≥40 kt report
   is at 03:00Z and the last at 12:30Z, but there is one lull inside the span: 11:30Z `24018G32KT`. The test asserts the
   span and that the 11:30Z lull is the *only* report under 40 kt inside it. The data was not changed and the test was not weakened.
10. **Storm-day rule (plan §5, "gust ≥35 kt for ≥3 h").** A storm day is a UTC day on which a gust ≥35 kt is reported in
    **≥3 distinct UTC clock hours** (routine and SPECI reports both count).
    - The alternative reading, total duration of ≥35 kt reports, would drop Herminia: it has only 3 half-hourly reports,
      i.e. 1.5 h, yet the plan lists it.
    - **Ciarán is not a storm day at EIDW.** It had one hour of G37 on 2023-11-01; it hit the Channel, not Dublin. The plan's
      example list includes Ciarán, but the data decides. Babet, Gerrit, Henk, Conall and Lilian also don't qualify at EIDW.
    - Result: **26 EIDW storm days**, 22 in the learn split and 4 in the score split (Éowyn, Herminia, 2025-02-23,
      2025-02-26). See `data/pinned/STORM_DAYS.md`.
11. **Judge stations.** Each station gets one IEM request for Jul 2023 → Jun 2025. Days are ranked by **local** day, since
    a judge types a local date and `generate_day` takes a local day.
    - **Day 1** is the highest max gust.
    - **Day 2** is the brief's candidate date with the most storm-condition hours, if it has at least 3; otherwise it is the
      runner-up by max gust among days with at least 3 storm-condition hours. Storm conditions follow plan §1.2: gust ≥35 kt,
      sustained ≥30 kt, visibility <0.5 SM, or SN/FZ/TS/GR in the weather codes.
    - **Coverage:** each pick pins every UTC day its local day overlaps, so a local-day fetch is fully pinned (e.g. KBOS
      local day = UTC D 05:00 → D+1 05:00).
    - **Extra, about 200 kB:** every gust-rule storm day at each judge station also goes into `<ICAO>_storms_2023-07_2025-07.csv.gz`.
    - The chosen days are in `data/pinned/JUDGE_DAYS.md`.
12. **Last 7 days at EIDW** are pinned as complete UTC days, which go stale. Before the demo, re-run
    `uv run python -m world.pin_metar recent`.
13. **`future_date`** is raised when `start > now` (wall clock; `world/` is not under the engine's Clock rule). Network
    requests are clamped to `now`.
    **`unknown_airport`** from `fetch_metar` is only a format check (4 characters); `world/airports.py` does the real lookup.
14. **Pinned size** is about 1.1 MB in total. The EIDW 24-month bundle is 0.55 MB gzipped. Gzip is written with
    `mtime=0`, so re-running the pin script gives byte-identical files.

## F2 · Airports, EU flag, timezones, distances

1. **Pinned subset.** `data/pinned/airports.csv` (≈250 kB, 2,375 rows) is built by `uv run python -m world.pin_airports`
   from OurAirports `airports.csv`: `large_airport` + `medium_airport`, continent EU or NA, **plus** EU261-territory
   countries on other continents (the Canaries are continent AF in OurAirports; Cyprus is AS). Only rows with a
   4-letter ICAO-style code are kept (`icao_code`, then `gps_code`, then `ident`). Sorted by ICAO; re-runs are
   byte-identical.
2. **Timezones** come from `airportsdata` by ICAO, then IATA, then the nearest airportsdata station in the same
   country (a handful of small medium airports). Stored in the CSV so runtime needs no lookup for the subset.
3. **Codes outside the subset** (e.g. a judge types `RJTT`) fall back to `airportsdata` at runtime (lat/lon/tz/
   country). The plan's subset is about the demo network; the desk should not reject a real airport.
4. **EU261 territory (`Airport.eu`)** = EU27 + EEA (IS, LI, NO) + CH, plus the French outermost regions that carry
   their own ISO codes (GP, MQ, GF, RE, YT, MF). Canaries/Madeira/Azores are ES/PT already. The UK, Faroe and
   Greenland are not EU261 territory.
5. **`iata`** falls back to the ICAO code when an airport has no IATA code (the `Airport` model requires a string).
   IATA collisions resolve to the large airport.
6. **`distance_km`** is the great circle with R = 6371 km on OurAirports coordinates, rounded to 0.1 km so hashes
   are stable. All 14 plan §1.1 distances match within 0.6 km.
7. **`band_eur`/`band_margin_km`** (Art. 7(1)) live here too, because the generator's answer key needs the true
   entitlement without importing the engine: ≤1500 km €250; intra-EU >1500 km or 1500–3500 km €400; else €600.
   Exactly 1500 km is €250.
