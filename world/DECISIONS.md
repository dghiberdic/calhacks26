# world/ decisions (Filip lane A)

## F3c integration with the shared world

The team's new world/plant.py implementation owns controlled error and ambiguity coverage. The local experimental hidden-crew draw was removed when integrating upstream, so this branch preserves the shared generator, compact answer keys and all of its acceptance tests. The supplemental error_cases.py corpus remains a separate schema-valid regression input set. Evaluation expands the shared answer key in memory; it does not replace its labels or committed compact format.

## F3d · Judge-day WorldAPI

- `world.api.WorldImpl` supplies the public load/weather/airport/day interfaces. `world.generate.generate_day`
  is also a module-level entry point discovered by the existing server. `generate_day_full` returns the World plus
  its ground truth (`Truth`, the desk's answer key), which never goes into the World.
- Requested weather remains real and unchanged. Future days and unknown airports are rejected before simulation;
  offline runs never need an LLM or network.
- Three EU-origin and one non-EU-origin revenue coupons receive unsigned in-lieu vouchers. Existing signed vouchers
  are preserved; other coupons are selected rather than deleting evidence of consent.

### F3d finish (second pass, 24 Oct)

Filip's first version had the right public shape; the reviewer's list of weaknesses was checked against the code
and output, and each one was real. Fixed underneath the same API (`WorldImpl`, `generate_day(icao, local_day, seed)`,
the three `WorldError` codes):

1. **The judge's local day, not Dublin's.** `local_day` is the airport's calendar day (tz from `world/airports.py`).
   The sectors are every Northstar sector whose airport-side time (STA there for arrivals, STD there for departures)
   falls inside it. That is the engine's own `storm_flights` rule, so the desk world and the run agree. Boston's
   10 Jan is NS31@10 Jan (lands 18:10 local) and NS30@10 Jan (leaves 19:10 local = 00:10Z on the 11th), not the
   previous evening's NS30. A short-haul outbound and its return always travel together. EIDW is Dublin's whole
   world day, with the same sectors and METAR windows as `generate_world`.
   Only flights that have landed by now are included; if none has, that is `future_date` ("haven't landed yet").
2. **METAR for every hour the flights need, at both ends.** Each station is fetched once over its sectors' span
   ±4 h via `fetch_metar` (pinned → IEM → AWC), across UTC days. Previously only the requested date as a UTC day was
   fetched, so Boston's evening departure had no weather off the pins. The judge's station and Dublin are required
   (`no_metar` otherwise, with a plain message); the context station (BOS) is optional; on the hub day,
   outstations use pins only (35 live requests would be far too slow). `meta.desk.metar` records pinned/retrieved.
3. **Plants are re-simulated, never edited in.** The old version overwrote flight status and truth after the run,
   labelled knock-ons 93, and left the original OCC lines in place (EGLL Isha: NS121 sat in two OCC entries; KBOS:
   NS31 had two AOGs and its truth rewritten as a knock-on). Now a planted fault is a `DayPlan` AOG (with its AMOS,
   MCC, OCC and spares lines produced by `DaySim`), and the day is simulated again. Tests check one OCC entry per
   cancelled flight with the flight's code, one AOG write-up, no flying on the grounded aircraft, and truth and
   coupons that agree.
4. **The fault is at DUB.** The contradicted code goes on a Dublin departure, observed calm at both ends (reports
   within ±1 h, no storm conditions, latent severity 0), whose aircraft is at DUB. It is written up 5 h to 90 min
   before STD, after the aircraft's last arrival in the full network rotation. Candidates whose return is also calm
   come first; at the hub, non-EU routes come first. If a DUB standby spare would cover it, that spare class is
   unavailable all day (`meta.desk.planted.spares_unavailable`), so every spares-log line tells one story.
5. **No extra artificial faults.** One root fault per day. Its rotation supplies the non-EU departure at a non-EU
   airport (the return knocks on). The only other plants are the EU-airport context case (below), and an honest
   RSN 41 AOG only when a side has no owed cancellation at all. Calm-day tests check one AOG and one weather-coded
   OCC entry.
6. **No invented NS980/981 control rotation.** It was a copy of NS100 on a spare slot, and on LFPG it drew the
   contradiction away from the judge's route. A non-EU departure *is* needed on EU-airport days for the "asks
   again" beat (R-CL-1's scope is `flight.departs_eu`), and Justin's Q-d is the same observation. So, as in golden's
   Herminia mini-day, the real BOS→DUB inbound (NS30) landing in Dublin that day joins as context
   (`meta.desk.context_flights`, listed in `meta.storms[id].flight_ids`). It gets an honest AOG at BOS typed RSN 41,
   written up during its turn, unless it is already an owed cancellation. In the 2–3 weeks when US and EU
   daylight-saving times differ, NS31 lands as NS30 is due out, so the write-up is on arrival.
   **Caveat for Q-d:** the engine's `run_storm(station=<EU airport>)` selects flights by station, so it won't see
   the context flight. The server's composed run honours `meta.storms[id].flight_ids` and does.
7. **`load` reads `.json.gz`** (by gzip magic, not the name). `write_world` writes canonical JSON, or deterministic
   gzip with no name and mtime 0.

Further calls:
- **Vouchers go on owed coupons first** (planted-fault passengers first), via `pax.FlightPax.in_lieu`, so the R-CL-1
  beat has something to settle. **Isha day at EGLL (2024-01-21)** can't have an owed non-EU case: the only Dublin
  departure observed calm is NS100 at 06:10Z, and both LHR→DUB legs are then inside the storm: NS101 lands at 09:15Z
  beside 09:30Z G39 at Dublin, and NS121 leaves LHR at 17:25Z in G35 and lands into G44. Stranded sectors whose ends are stormy are truth "weather", the generator's rule (golden NS101).
  The non-EU voucher therefore sits on a weather cancellation with nothing owed, and a test pins that. For the desk
  "asks again" beat use **KBOS 2024-01-10** or a calm EGLL day (e.g. 2024-05-15), where it is owed.
- **The OCC storm day** for the desk is ≥2 distinct clock hours with storm conditions at Dublin or the judge's
  station within the desk spans. It drives the storm-day batch and spare odds. The name is from `STORM_NAMES` by date.
- **`DaySim` hooks** (full world byte-identical; `test_committed_answer_key_is_reproducible` passes):
  - an optional fixed `sectors=` list;
  - an optional station as a third element of `DayPlan.aog`;
  - a flight with a planted OCC code is batch-listed only when `plan.batch` says so. Every full-world plan entry on a
    storm day is already in `plan.batch`, and no random draws move.
  - Everything else desk-specific lives in `generate.DeskSim` (METAR windows, blocked spares).
- **`network.adhoc_pair`** (desk-only) no longer flies a DUB standby spare: a spare can't stand in for itself.
- **Timing tests use `time.process_time()`.** `test_one_day_simulates_fast` is back at its original 1.5 s bound
  (an earlier commit had loosened it to 5 s wall-clock). The judge-day test is < 2 s CPU with the METAR caches
  cleared. Measured: EGLL Isha cold ≈0.35 s, warm ≈0.08 s; the EIDW hub day cold ≈1.2 s (bundle parsing), warm
  ≈0.2 s.

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
   Greenland are not EU261 territory. **Per-airport exclusions** (24 Oct, to agree with `engine/geo.py`): northern
   Cyprus (Ercan ECN/LCEN, Geçitkale GEC/LCGK; Protocol 10), RAF Akrotiri (AKT/LCRA; Protocol 3) and Svalbard
   (LYR/ENSB; EEA Protocol 40) are outside, although their country codes (CY, NO) are in. A test checks that
   `world.airports` and `engine.geo` agree on these and on ordinary airports. None of them is in the network, so the
   full world and the answer key are unchanged.
5. **`iata`** falls back to the ICAO code when an airport has no IATA code (the `Airport` model requires a string).
   IATA collisions resolve to the large airport.
6. **`distance_km`** is the great circle with R = 6371 km on OurAirports coordinates, rounded to 0.1 km so hashes
   are stable. All 14 plan §1.1 distances match within 0.6 km.
7. **`band_eur`/`band_margin_km`** (Art. 7(1)) live here too, because the generator's answer key needs the true
   entitlement without importing the engine: ≤1500 km €250; intra-EU >1500 km or 1500–3500 km €400; else €600.
   Exactly 1500 km is €250.

## F3a · Network, days, latent causes

1. **Network** (`world/network.py`): 35 routes from DUB (29 EU/UK, 6 North America), 82 sectors a day. The morning
   wave reuses the plan's numbers, times and tails (NS100–NS118, return times as in §1.2); the afternoon wave is the
   plan's 11 "everyone else flew" departures (NS120–NS140); a midday wave adds 14 more pairs; long haul is NS20/21 JFK,
   NS30/31 BOS (A321XLR), NS40/41 ORD, NS50/51 YYZ, NS60/61 EWR (XLR), NS70/71 IAD. Tails: EI-NS* narrowbodies (incl.
   the golden XLRs EI-NSB/EI-NSN), EI-NW* A330s (as in the stub), EI-NLA spare XLR, EI-NT* DUB standby spares.
   A test checks every tail's rotation is location-consistent with ≥30 min turns, in winter and summer time.
2. **Times.** DUB departures are fixed in Dublin local time (so summer days shift by an hour in UTC); returns leave
   the outstation `turn` minutes after the outbound's STA; long-haul inbounds leave North America at a fixed origin
   local time the evening before. A flight's `date` (and id) is its local departure date at the origin, so the
   overnight inbounds of world day D are `NS20@D-1` (as in CONTRACTS).
3. **World days.** 26 storm days recomputed from the pinned EIDW METAR (plan §5 rule) + 40 background days (28 learn,
   12 score), ranked by sha256 with a fixed salt independent of the generator seed so pinned outstation METAR always
   covers them. Background days skip storm days and 2025-01-23..27 (golden).
4. **Outstation METAR** for all 66 world days is pinned (`uv run python -m world.pin_metar network`): one multi-station
   IEM request per contiguous run, UTC day D for every station plus D-1 for North America, as sparse
   `<ICAO>_world_2023-07_2025-07.csv.gz` bundles (1.9 MB). The F1 loader reads them unchanged. This also gives the
   engine real (calm) outstation METAR for LIS/FCO/MUC on Éowyn day, which engine D1 asked for.
   In the world, outstation obs are trimmed to ±3 h around that station's sectors; EIDW keeps D-1 18:00Z → D+1 06:00Z.
   Keys are `<ICAO>@<world day>` (the mini-world convention).
5. **Latent causes** (`world/causes.py`), drawn with an RNG keyed by (seed, flight id), so a flight comes out the
   same whichever days are generated:
   - weather: per-sector cancellation probability from the real METAR within ±45 min of STD (origin) and STA (dest):
     G35–39 0.08, G40–44 0.2, G45–49 0.42, G50–54 0.75, G55+ 0.92; sustained ≥30/35 kt 0.45/0.7; fog, FZ, SN, GR, TS
     smaller. These are not the engine's window thresholds, so window edges are genuinely uncertain.
   - internal AOG (1.2 % per tail-day; half the night before at DUB like NS31, half after an arrival), external hits
     (bird 0.15 %/sector, lightning 1.2 % on storm days), crew (0.15 %, 0.6 % after 13Z on storm days), ATC strike
     days (5 % of calm days; FR/ES/IT/PT/CH routes cancel at 30 %).
   - rotation: the aircraft is not at the origin (or is >3 h late). A spare at DUB takes over the rotation; a spare
     ferried ex-DUB rescues an outstation sector if it departs ≤3 h late (the flight then operates delayed). A
     cancelled return whose aircraft is stranded ferries home empty once both ends drop below 0.25 severity.
     A stranded sector whose own ends still show storm conditions is truth **weather**, not knock-on (golden: NS101's
     STA is in the DUB window); a stranded sector calm at both ends is **knock_on** (the C-74/19 pattern).
6. **Truth (the law as Northstar's Legal rules it):** weather, ATC, bird/lightning → extraordinary; internal AOG and
   crew → not; **concurrent** (aircraft AOG while the storm would also cancel) → not extraordinary, expected route
   Legal; **knock-on** with an extraordinary root → extraordinary iff no spare within 3 h AND the earliest reroute was
   offered (R-LEG-1, plan §1.2), expected route Legal; knock-on with an internal root → not extraordinary.
7. **OCC.** Storm days get one batch "CNL LIST → NETLINE, RSN 71" (INBD long haul RSN 72) about 70 min before the
   first weather cancellation (not before 04:00Z). It includes every weather/concurrent cancellation, their knock-ons,
   and 80 % of other cancellations already known at batch time: that is how a technical cancellation gets miscoded 71
   (NS31). Other cancellations get single OCC lines with the root's code (41/51/64/67/82/93; 30 % of AOGs on a windy
   day are typed 71). `notified_at` is the IROPS SMS time.

## F0 · Golden embed

1. **Golden days are not simulated.** `generate_world` skips every `meta.storms[*].local_date` of golden
   (2025-01-24 Éowyn, 2025-01-26 Herminia mini-day) and splices golden in verbatim (`world/golden.py::embed`).
   The Herminia day therefore has only golden's 8 flights. Generating the rest of that day around it would collide
   with golden's own narrative (e.g. its spares line "EI-NSW covering NS100/NS102").
2. **Byte-for-byte check.** `golden_slice(world)` filters every list by golden's ids (preserving golden's order) and
   takes `meta["golden"]`, golden's metar keys and real_context. Its canonical hash equals golden's (test), and
   `meta.golden_hash` records it. `embed` raises on any id collision.
3. **Shared keys: golden wins.** Airports are identical (same OurAirports coordinates). `meta.distances_km` merges, and
   golden's rounded plan distances win for its routes (DUB–BCN 1,486 → "14 km under"). The generator's other routes
   keep 0.1 km great-circle values.
4. **History and opening balances:** golden's 42 reroute-reduction cases ("41 of 42") and the Isha cohort are used
   as is. Generated history never re-mines the same policy, so the headline support stays "41 of 42".
5. **Golden ground truth** comes from golden's own `meta.groups` (the plan §1.2 truth table), never from the engine:
   weather groups → weather/extraordinary; knock-on → knock_on, extraordinary under R-LEG-1, expected route Legal;
   NS31 and Herminia's h_technical → technical/not extraordinary. NS31@24JAN and NS106@26JAN (coded 71, AOG in the
   tech log) are tagged `miscoded_technical`.
6. **Id and source conventions follow golden:** `TECHLOG-<tail>-<stamp>`, `MCC-<stamp>-<tail>`, `OCC-<stamp>[-<number>]`,
   `SPARES-<stamp>-<number>`, sources `SRC-<record id>`, METAR sources `SRC-METAR-<ICAO>@<day>` holding IEM CSV text,
   tech-log sources holding the AMOS export block. Fleet types follow golden's `meta.fleet`.

## F3b · Passengers, claims, care

1. **Coupons only on cancelled flights** (entitlements exist only for cancellations; delays are out of the demo's
   scope, as in engine D3). One coupon per manifest passenger, seats `1A, 1B, …`, PNRs of 1–4 (lead booker = first of a
   multi-pax PNR). Fares by band: €45–260 / €90–380 / €280–950 plus taxes; channel direct 70 %, OTA 20 %, GDS agency
   10 %; ~1 % staff ID90 (Art. 3(3)).
2. **Elections** (plan mix, per PNR with 15 % individual deviation): reaccommodated own 64 % (8 % arrive within the
   Art. 7(2) limit, the rest 2 h–2 days late), refund 19 %, partner reroute 9 % (55 % within the limit), voucher 8 %.
3. **CRM bot** initiates refunds only on direct-sold refund coupons, minutes to hours after the cancellation, with
   "RSN WX CNL" and the "weather, no compensation" email when OCC typed 71/72 (the NS31 story: the bot trusts the
   OCC code). Non-direct refunds come back via BSP 1–9 days later. Refund-voucher elections get `voucher_issued`.
4. **Service-desk vouchers in lieu** on 3 % of revenue coupons, 60 % with a signed-acceptance hash (Art. 7(3)).
5. **Raw sources are kept where they are evidence:** every claim, in-lieu voucher and BSP record has its
   `SRC-<record id>`, every cancelled flight a `SRC-MANIFEST-<flight>`, and each flight one CRM-bot email template.
   The bulk CRM records (bot refunds, bot emails, refund vouchers) carry their text on the `CrmEvent` itself, with
   no duplicate Source, and there is no per-flight PSS CSV (the coupons are the PSS). This takes the full world from
   77 MB to 58 MB of JSON. Golden keeps its own sources verbatim.
6. **Coupon truth** (`world/pax.py::coupon_truth`, from the flight's latent truth, never the engine): staff ticket →
   `staff_ticket`; notice ≥14 days → `exempt_notice`; extraordinary → `no_compensation` (refund and care still due);
   otherwise `owed` at the band, halved when rerouted (own or partner) within 2/3/4 h (Northstar's mined policy).
   A signed in-lieu voucher offsets; an unsigned one doesn't (Art. 7(3), R-CL-1), and the voucher stays goodwill.
7. **Claims follow the € curves by quota.** Per cohort (world day) × segment, owed coupons are shuffled and walked in
   order, accumulating entitlement €; each claimant lands in the curve interval where its cumulative € midpoint falls
   (M1 = first month-end ≥28 days after the event), uniformly in that interval. 35 % of M1 claims arrive the night
   after the storm. This reproduces `curves.json` to within half a coupon per point (test: ±1 pp on the learn split).
   Claims stop at M18 (the tail to 35 % is judgment) and at a 2026-07-01 extract horizon. 30 % of valid claims come
   via agencies (power of attorney 65 %, assignment 35 %), 10 % on UK routes cite UK261 (£220).
8. **Invalid claims:** 4 % of passengers on no-compensation flights claim anyway (rejected: extraordinary, staff ticket,
   notice). They don't count toward the curve.
9. **Care:** per cancelled flight, an accrual row per kind (hotel for 35–55 % of passengers, meals for all, transport
   for hotel guests) at 22:00Z on the day, plus a vendor invoice 18–30 days later at 94–102 % of the accrual.
# F3c answer keys and error inputs — 24 October 2026

`answer_key.py` exports independent train/test labels from latent truth and immutable golden inputs, including NS31's 172 coupons and €99,000 face entitlement. Claim labels reject missing agency authority, expired claims, settled vouchers and duplicate coupon claims; they do not copy amounts claimed into amounts owed.

**Stress corpus `knock_on_return` fix (24 Oct, from the F9 eval).** All 10 cases had the return's STA inside Dublin's
storm window (Isha 21 Jan: the window runs 09:30Z → 02:30Z on the 22nd; Éowyn: 02:30–15:00Z). So the engine was
right to call them weather at the arrival end. Now the DUB→CDG outbound leaves at the first storm-condition report
in operating hours (05–20Z), inside a Dublin window. The CDG→DUB return is the first same-day slot, ≥3 h later,
that is observed (a report within ±1 h) and at least 1 h outside every window at both ends. Windows use plan §1.2's
definition, recomputed in `world/` because world may not import the engine. A test checks the result with
`engine.timeline` itself.
- Isha's day has no such slot, so the train cases move to the next day that has one: Jocelyn, 23 Jan 2024 (outbound
  11:00Z, return 14:30Z → 16:30Z, which lands exactly 1 h after the 15:30Z report and 1 h before 17:30Z).
- Test: Éowyn, outbound 05:00Z, return 14:00Z → 16:00Z.
- `data/answer_key/stress.json` was regenerated with the F9 runner's own serialisation; exactly those 10 cases changed.
  `train.json` and `test.json` are untouched.

`error_cases.py` provides a separate 140-case controlled regression corpus (five variants of 14 errors in each split). Weather is real pinned METAR, while flights, people, errors and expected actions are simulated. Ordinary technical scenarios require positive calm observations at both ends; concurrent examples retain actual windy observations. These input variants do not count as independent storms or inflate natural-world accuracy. Assignment/payment events are source documents plus metadata pending a typed settlement-event interface.

## F3c · Planted errors, answer key, history

1. **Planted as latent events, then re-simulated** (`world/plant.py`, `DayPlan` in the generator), so the evidence
   is self-consistent: a miscoded AOG has its AMOS line, MCC line, spares line, and the OCC RSN 71 that contradicts
   it. The planner dry-runs each split, counts natural cases, and tops each type up to **5** with seeded
   choices (up to 5 rounds, since a forced cancellation can change its rotation). Planting runs by default for the
   full world only, so explicit day subsets stay natural and comparable.
   - `miscoded_technical`: AOG the night before at DUB on a tail's first sector (both legs calm); storm days list
     it in the batch, calm days get a single OCC line typed 71 (the METAR contradicts it). One DUB–LHR case per
     split comes first, so the UK261 plant has owed LHR passengers.
   - `lh_technical` (not a plan §5 type, 4 per split): an XLR/A330 AOG at DUB before a long-haul outbound (the NS31
     pattern, batch-coded 71 on storm days). Without it the learn split has no owed long-haul passengers, and the
     LH € curve could not be checked.
   - `concurrent`: an AOG logged inside the storm at DUB before a departure the storm also cancels. Storm conditions
     at the DUB end (severity > 0) are enough; the weather cancellation is forced as well.
   - `knock_on_return`: force the weather cancellation of an outbound that left in storm conditions whose return
     is calm at both ends.
   - `notice_ge_14d`: a planned rotation cancellation on a calm day, `notified_at` 15–30 days before STD (both legs,
     OCC code 09).
   - `manifest_ops_pax_mismatch`: the OCC message types "OPS PAX: NSxxx PAX n" ≠ manifest (manifest wins).
   - **Ambiguity (~5–6 % of cancellations per split):** crew shortages batch-coded 71 inside the storm, AOGs never
     written up in the tech log (batch 71, no tech-log entry), and their knock-ons. Each is flagged `ambiguous`
     with a note, so calibration is not circular.
2. **Claim/CRM-level plants** happen after passengers exist: direct+agency, two agencies, lead booker (PNR-scope
   claim) + member, claim + chargeback on a bot-refunded coupon, agency with `authority=none`, assignment notified
   then a direct claim (pay the assignee; a direct payment would not discharge), CRM-bot + BSP refund, injection
   emails (on no-compensation coupons, with an EMAIL source), UK261 £520 on DUB–LHR (EU261 €250 applies, paid once).
   Natural cases (unsigned in-lieu vouchers, staff tickets) are tagged too.
3. **Claims after the limitation period:** one legacy NS31 flight per split (2017-03-14 / 2018-09-20), restored from
   the PSS archive with only its 6 claimant coupons, and 6 claims received in the split, all time-barred (Ireland
   6 years, C-139/11). Legacy flights are listed in `meta.legacy`, not `meta.days`, and are excluded from the curves.
4. **Answer key** (`uv run python -m world.answer_key` → `data/answer_key/{train,test}.json`, 1.7 MB + 0.5 MB):
   - Per flight: cause, extraordinary, latent cause, OCC code, `recode_expected`, expected route, planted tags,
     ambiguity.
   - Per coupon, compactly: a default row per cancelled flight plus the seats that differ. Refund due follows the
     election, so it is not repeated.
   - Per claim: valid, pay, the coupons it covers, reason, dev month.
   - Per storm: entitlement, owed pay, and claims paid by M1/M3/M6/M12/M18 (actuals for the liability metric).
   - `planted` counts distinct records per type: flights for flight-level types, coupons for claim-level types.
   Golden's coupons and claims are scored by the same `coupon_truth` from golden's flight truth (NS31 = 9,900,000).
   Two tests guard it: the committed key equals a rebuild, and the generator never imports `engine`.
5. **Curves:** `data/answer_key/curves_train.json` holds the € curves learned from the generated learn-split history
   (LH .091/.169/.241/.290/.321 vs plan .09/.17/.24/.29/.32), within ±1 pp at every point (test). It's in lane A's
   `data/answer_key/`, because `contracts/fixtures/golden/curves.json` is David's.
6. **History:** the embedded world keeps golden's 48 history cases ("41 of 42"). A golden-free world gets
   `generated_history`: 42 reroute-reduction cases from learn-split coupons (41 applied, 1 goodwill exception) and
   6 cause rulings.

## PR #6 merge into main (integration agent)

1. **Filip's own resolution was merged as is.** He integrated F3c himself (a56be38) before we merged. `world/answer_key.py`, its tests and the compact `train/test/curves_train.json` are F3c's, byte for byte. His F3d (`generate.py`, `api.py`, `desk_cases.py`) and the `error_cases.py` stress corpus with `stress.json` come in unchanged. A full eval re-run on the merged tree rebuilt all four key files byte-identical.
2. **His first key format (unplanted, `build_answer_key`) was not revived.** He dropped it himself. It also had no planted cases, so F3c's ≥5-per-type acceptance tests would fail on it.
3. **His rule-based claim-validity recomputation was cross-checked against the F3c key and not restored.** Over the full seed-0 world, 6,214 of 6,261 claims agree. Two kinds of disagreement, 47 claims in all:
   - **22 claims, F3c key right.** These are lead-booker PNR-scope claims. The rule ignores `pnr_scope`, so it pays the lead booker for one coupon only (e.g. CLM-NS167-23B-2023-09-07T0746Z: rule €400, key €1,200 covering 23B/23C/23D). It then wrongly accepts the members' later claims (e.g. CLM-NS167-23C-2023-09-27T1734Z: rule €400, key duplicate €0).
   - **25 claims, no money disagreement.** These are claims on coupons settled in kind by a signed voucher. The key labels them valid with €0 due; the rule labels them invalid with €0. Only the label differs.
   The cross-check found no case where the key is wrong, so it stays out.
