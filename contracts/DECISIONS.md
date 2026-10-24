# contracts/DECISIONS.md (David lane B judgment calls)

## D0a: stub server + api fixtures

**Fixtures**
- **Built by a script.** `scripts/build_stub_fixtures.py` turns hand-entered plan numbers (§1.2–1.4, CONTRACTS §5) into validated `contracts.models` instances and writes `contracts/fixtures/api/*.json`. Nothing is hand-typed JSON, so a typo fails at build time. Rebuild with `make stub-fixtures`. D0b's `scripts/build_api_fixtures.py` (golden + fakes) supersedes it.
- **The storm fixture holds the whole day,** not just the brief's minimum: all 27 cancellations plus the 11 that operated. The map and timeline need every arc and tick, and the counters must reconcile (5,292 pax).
- **There is a `flight_*.json` for every cancelled flight.** Operated flights return 404 on `/flights/{id}`, because `FlightFile.decision` is required and they have no decision.
- **Overnight inbound IDs use the local departure date,** per `Flight.date`: `NS20@2025-01-23`, `NS30@2025-01-23`, `NS40@2025-01-23`, `NS50@2025-01-23`.
- **Both storm windows are listed,** sorted by start: the minor one 23:30–00:30Z (peak 38) and the main one 02:30–15:00Z (peak 56). Choose the main window by duration or peak; `windows[0]` is the minor one.
- **`window_margin_min`** is the non-negative distance in minutes to the nearest edge of the main DUB window. It is measured at the DUB end (STD for DUB departures, STA for DUB arrivals). `in_window_*` says which side.
- **The outstation end is `"out"`** for every flight (no outstation METAR in the stub).
- **`Q-3` (Controller, Isha release, 72%) is included** even though the brief named only Q1 and Q2. The plan's headline is "3 questions · 3 people", and counters come from the API.
- **Counters:**
  - `drafted` = 172 (NS31 payouts drafted)
  - `held` = 530 (passengers on the 3 knock-on flights held for Legal)
  - `rules_cited` = 37 citations (23 weather decisions cite R-REG-ART5-3 plus 14 Art. 7(2) reductions)
  - extra keys: `recoded` = 1, `weather` = 23
- **Money:** `entitlement_cents` = 9,900,000 (owed entitlements only, i.e. NS31). `liability_drafted_cents` = 8,214,600 (the storm day-1 golden number, including held knock-on accruals).
- **Invented details** (the plan doesn't give them; D0b's golden world replaces them):
  - STA of outbound sectors (block times)
  - tails other than EI-NSB, EI-NSN and EI-NSL
  - the 11 operated flights' numbers and destinations (incl. BRU/MAN/EDI/CPH/ZRH)
  - the spares and reroute lines for NS113 and NS115 (patterned on NS117)
  - the CRM/claim quotes for 14C
  - chain-ladder 3,726,667 and credibility z 0.31
  - `eval.json`, which is a **placeholder** (only `stormcheck_runs` comes from the contract). Don't quote its numbers.
- **Plan nit:** §1.2 says weather at 21:40Z was 13 kt. The nearest obs (21:30Z) is 14 kt; 21:00Z is 13 kt. The fixture quotes the 21:30Z obs.
- **Hard-control rule cards** (`R-HC-*`) and the static Reg 2026/2202 card use `condition: {"all": []}`. They are code or display-only; the new `Rule.title` carries the text.

**Contract additions** (additive; logged in CHANGELOG)
- `Rule.title` and `StormRun.airports`.
- Envelope models for the shapes CONTRACTS §3 gave only as dict literals.
- `LockResponse.locked` is the period string. `Health.mode` = `"stub"` here, and `impl` is a dict.

**Stub behaviour**
- **State is in memory:** clock, rulings, proposals, rules, journal approvals, locks and the trace. It lasts until `POST /api/reset` or a restart. The clock starts at 2025-01-25T06:00Z ("the morning after").
- **Auth:** `POST /api/session` issues `<b64 Session>.<hmac>`, signed with a fixed, non-secret stub key. A missing, malformed or forged token is treated as `judge` (fail closed).
  - Human principals are `<role>:<name-slug>`. Agents and the judge are the bare role.
- **Questions:**
  - Scoping: `claims_lead`, `legal`, `controller` and `ops` see only questions routed to them. `judge`, `cfo` and no-token see all.
  - Filtering: `?status=open` returns both open and reminded (both unanswered). A question becomes `reminded` once the clock passes `remind_at` (asked_at + 3 h).
- **Answering:**
  - The session role must equal `routed_to`, else 403 `forbidden` plus an `access_denied` trace event.
  - Answering Q-1, Q-2 or Q-3 returns the scripted proposals R-CL-1, R-LEG-1 and R-CTL-1. Q-3 always produces a `rejection` ruling.
  - `confirm`, `widen` and `reject` also work on those canned rule ids before any answer, so screens can be built in any order.
- **Approving journals:**
  - An agent session gets 403 `sod_violation`.
  - Preparer == approver gets 403 `sod_violation`.
  - A role outside controller/cfo/claims_lead gets 403 `forbidden`.
- **Desk:**
  - An unknown ICAO (not in airportsdata) gets 422 `unknown_airport`.
  - A date after today gets 422 `future_date`.
  - EIDW 2025-01-24 returns the Éowyn run.
  - Anything else returns an empty run with a `message`.
- **Inject:** a regex fallback (`fallback_used: true`). Prompt-injection phrases give 0 facts and `dropped_unverifiable` 1. A rehearsed scenario's text puts its `expected` outcome into `message`. It never returns a 500.
- **Errors:** every 4xx is `{"error":{"code","message"}}`, including FastAPI's own validation errors (code `validation`).
- **SSE (`/api/stream`):**
  - Sends `event: trace`, `id: <seq>`, `data: <TraceEvent JSON>` every `STUB_SSE_INTERVAL` s (default 2).
  - Starts after `Last-Event-ID` (default 0).
  - When the log is exhausted it appends replayed copies of `trace.json` events with fresh, monotonic seqs (`STUB_SSE_LOOP=0` stops after one pass). Replays show in `/api/trace` but not in `StormRun.feed`.
  - Events created by POSTs are streamed and appended to `StormRun.feed`.
  - Heartbeat: an SSE comment ping every 15 s.
  - The route declares `response_model=TraceEvent` (ignored at runtime because it returns a Response), so every route has one. The OpenAPI 200 content is `text/event-stream` with a `$ref` to TraceEvent.
- **CORS:** `http://localhost:5173` and `http://127.0.0.1:5173`, all methods and headers.
- **`contracts/openapi.json` is checked by a test** (`test_openapi_json_is_up_to_date`). Any model change that alters the schema needs `make openapi`, per CONTRACTS.

## D0b: golden world (`scripts/build_golden.py` → `contracts/fixtures/golden/world.json`)

**Built, never hand-edited.** The builder types in plan §1.2–1.4 and generates the rest deterministically (seeded per flight: seats, PNRs, fares, which coupon took which election). `test_world_validates_and_is_up_to_date` rebuilds in-process and fails if `world.json` or `curves.json` is stale. No engine code is imported: the world is an input.

**METAR: all real, none synthetic.** `data/pinned` had no LPPT/LIRF/EDDM/KBOS for these days, so instead of synthesizing calm outstation weather I fetched the real IEM archive once and pinned it next to the EIDW files (`lppt/lirf/eddm/kbos_2025-01-23_25.csv`, `kbos/eddf/lemd_2025-01-25_27.csv`). All are calm (max gust ≤29 kt, no storm obs), so the D1 note is satisfied with real data: NS113/115/117 are `out` at the outstation STD, NS31 is `out` at BOS STA. `meta.metar_synthetic` is `[]`; `meta.metar[<key>]` records file, source and range. Keys are `<ICAO>@<storm local day>`; a list can start the evening before (EIDW@2025-01-24 starts 23 Jan 18:00Z, which covers the 21:40Z tech-log obs). Consumers merge lists per station by key prefix. No METAR for the outbound weather flights' outstations (LHR, CDG, …): those ends are `unknown`, which doesn't matter because the DUB end is `in`.

**Distances.** `meta.distances_km` pins `DUB-XXX` to the plan §1.1 table. Recomputed on OurAirports coordinates (R = 6,371 km) every value matches when rounded to the km except ORD (5,895.5 → plan 5,896; same €600 band, plan value kept). The engine reads `meta.distances_km` first, so BCN's margin is exactly 14 km. Airport rows are embedded in the builder (copied from OurAirports) so the golden world doesn't change when `data/pinned/airports.csv` does.

**Flights.** Éowyn = the D0a schedule (27 cancelled + 11 operated). NS31 STA 23:45Z (7h15 block). Overnight inbounds were notified 23 Jan 21:30Z (before their STD); the 05:12Z OCC batch only lists them. `meta.storms[<id>].flight_ids` says which flights belong to which storm run (NS20/30/40/50 carry `@2025-01-23`, NS30 of Herminia `@2025-01-25`).

**Herminia mini-day (EIDW@2025-01-26, window 11:30–13:00Z, real).** Only the flights the Q1 beat needs, plus 4 that operated:
- NS106 DUB–FRA 07:30 (AOG EI-NSF, flap PCU actuator leak, OCC coded **71**, so a recode 71 → 41) with 17 unsigned in-lieu vouchers (€200);
- NS110 DUB–MAD 09:00 (AOG EI-NSH, AOA sensor, coded 41) with 14 (€200);
- NS30@2025-01-25 BOS–DUB dep 26 Jan 00:10Z (AOG EI-NSN at BOS, EDP leak, coded 41) with 1 (€300): the case that asks again;
- NS114 DUB–FCO 12:00 inside the window (weather).
Every AOG is logged before the window with no MEL relief, and both ends are calm (real KBOS/EDDF/LEMD). The return sectors of the AOG tails are left out (not needed; would add technical knock-ons). No care rows for Herminia, so the care golden numbers stay Éowyn's.

**NS31 coupons and elections** (plan §1.3 exact): 172 × €450 + €60. 32 refunds (bot), 14 refund vouchers, 112 reaccommodated on NS31 25–27 Jan (all +29 h or more), 14 partner reroutes via LHR at +220 min. Fixed seats so fixtures and demo scripts can name them: 14C (Q1, reaccommodated), 3A (first bot refund 06:02Z), 5B (chargeback), 26E (BSP duplicate), 9B/7C/12A (direct overnight claims), 17E/17F (agency overnight claims), 11D (voucher), 22F (reroute; the Feb €300 claim).
- **The BSP duplicate is the one OTA-sold coupon the bot refunded** (31 of the 32 bot refunds are direct-sold). The OTA also refunded it through BSP. That's the realistic reason a bot + BSP duplicate happens, and it keeps the plan's "32 bot refunds" exact.
- The chargeback (25 Jan 02:47Z) is on a different bot-refunded coupon. Injection 04 (3A) is a second, live one.
- Other flights: refund 16% / voucher 8% / partner reroute 6% / reaccommodated 70%, and **every reroute arrives later than its band's Art. 7(2) limit**, so no flight other than NS31 raises a reduction question (the knock-on numbers stay at the full band).

**CRM.** Each bot refund has a matching `rights_email_sent` with the wrong "weather, no compensation" text (the 32 corrected notices). The 14 NS31 refund vouchers have `voucher_issued` events. 14C: `voucher_in_lieu_of_compensation` 14:20Z, €300, `signed_acceptance_sha256 = None`, the service-desk source says "SIGNATURE: NOT CAPTURED".

**Claims.** "6 overnight claims" and "Jan claims (6)" are the **same six** (golden: Jan claims 360,000 = 6 × 60,000, and 14C's claim is the overnight 01:31Z one). 16 Feb claims: 15 × €600 + 22F, which claims €600 but is worth €300 at face value (approved at face value, per books). 22 claims in total, all on NS31, no duplicates (duplicates arrive by injection). 2 overnight + 2 Feb claims come via a fictional agency with POA.

**Care.** `CareCost` has no invoice amount, so each (flight, kind) appears twice: `invoiced=false` (accrual estimate, night of 24 Jan, Σ 22,700,000) and `invoiced=true` (Feb invoice, Σ 22,130,000). Meals €15 and transport €10 per passenger are invoiced as accrued; hotels come in 570,000 under (rooms released). Outstation passengers are put up at the outstation.

**Messy documents (8, `meta.messy_documents`):** the prompt-injection email (tier 4, first in the list), an MCC→OCC forward chain, an OCC shift handover ("NS31 went in the batch too"), the agency letter, a hotel invoice email, the CRM bot's template, a call-centre note for 14C, and an internal forward of the Met Éireann warning. All addresses use `.example`.

**History (`history_cases`).** 42 `reroute_reduction` cases (41 `apply_7_2_reduction`, 1 `no_reduction` goodwill exception), all inside the Art. 7(2) limit, plus 6 `cause` precedents (3 technical, 3 weather; below the miner's support of 8). Features use DSL feature names only. Nothing for knock-ons or unsigned in-lieu vouchers (Q1/Q2 are "no precedent"). All decided inside the learn split (≤ Dec 2024).

**Isha opening balance** = the books test helper's: entitlement 6,000,000, claimed 1,740,000 (29%), balance 360,000, long haul, `as_of` 2024-10-31T23:59:59Z (books uses it as the last-claim date → 3 quiet months at M12).

**Curves.json** = `{"version","basis","source","curves":[ClaimCurve…]}` (books' loader reads the `curves` key). Medium/short points are the LH shape scaled to their ultimate (4 dp). `n_by_point` is labelled simulated.

## D0b: `expected/` (`scripts/build_expected.py`, frozen)
- **Written from plan numbers only.** The script imports no engine or books code; the only world input is which NS31 coupon took which election (for the per-coupon `entitlements_NS31.json`). It refuses to overwrite `expected/` without `--force`; `test_expected.py` checks `SHA256SUMS` covers and matches every file, and re-derives every golden number arithmetically from the plan's rates.
- **Files:** `golden_numbers.json` (CONTRACTS §5 table + counts), `decisions.json` (27 Éowyn + 4 Herminia cancellations: the compared 5-tuple `(cause, extraordinary, recoded, outcome, routed_to)`, `recode_label`, and confidence **bands only**), `questions.json` (Q1–Q3 by pattern, Herminia payoff, challenges), `entitlements_NS31.json`, `journal_NS31.json`, `rollforward_2025-02.json`.
- **Confidence bands:** `auto` decisions carry `{"min": 0.90}` (the materiality gate needs ≥0.90 to auto-draft); knock-ons and Q1 `{"max": 0.60}`; Q3 0.60–0.90. `plan_confidence` is the plan's illustrative value, never compared exactly.
- **Herminia** expected decisions: NS106 technical recoded 71 → 41, NS110 and NS30 technical (OCC already coded 41), NS114 weather.
- **Hints, not contracts:** `scope_features_hint` in the rulings is guidance for D5; only `rule`, `action`, settled/asks-again sets and the € deltas are meant to be asserted.
- **Rollforward Feb:** only the plan's numbers (Éowyn 3,105,000 → −930,000 → +399,000 → 2,574,000; Isha 360,000 kept under R-CTL-1, unclaimed 6,000,000 − 1,740,000). Jan isn't frozen because where the R-LEG-1 release sits (recode vs change-in-estimate column) is Books' call.

## D0b: `fields.py`, `parse.py`, `normalize.py`
- **`fields.py`** registers 120-odd Fact fields: type (`str|int|float|bool|cents|datetime|date|enum|json`), subject kind (`flight|aircraft|coupon|claim|station|storm|care|cohort|source`), unit, the DSL features each feeds, and the parse kind. It also holds the CONTRACTS §4 allowlist (`DSL_FEATURES`, 38 names, plus `DSL_OPS` and the scope context keys) and `ENGINE_DERIVED` (features the engine computes, e.g. windows, distances, `aog.root_cause_internal`, ages, `sources.disagree`). A test checks every DSL feature is either fed by a field or engine-derived.
- **Subjects:** tech-log facts are about `aircraft:<tail>`; MCC and spares facts about each `flight:<id>` they name; METAR about `station:<ICAO>`; PSS, CRM and voucher facts about `coupon:<id>`; claims about `claim:<id>` (with `claim.coupon_id`); care about `care:<id>`; opening balances about `cohort:<id>`; real context about `storm:<id>`.
- **CRM amounts are the fact value** (`crm.refund_initiated = 51000`), so one fact carries both "it happened" and how much; `valid_at` is the event time.
- **`parse.py`** never guesses a currency: `parse_eur` needs `€`/`EUR` (a bare `600` fails), GBP is its own parser. Decimal comma vs. thousands is decided by the last separator and digit count. Times without a date need a reference date (the source's), `not_before` rolls "ETA 14:00Z" written at 22:15Z to the next day, and day-month without a year takes the reference year (with Dec/Jan rollover). Domain booleans have their own wording parsers (`NO MEL RELIEF`, `A/C AOG`, `SIGNATURE: NOT CAPTURED`, "I never agreed…"), because a generic yes/no would read "never agreed" as False.
- **`parse.verify(field, value, span, source_text, ref)`** is the Reader's acceptance test: registered field, verbatim span, re-parsed value equal. It returns a reason code (`unregistered_field`, `span_not_in_source`, `unparseable_span`, `value_mismatch`) for the `dropped_unverifiable` count.
- **`normalize.world_to_facts`** gives ~73k facts on golden in about 1 s (`flight_ids=` narrows it to one flight's world in ~30 ms). Spans are atomic where the document has a natural one (`RSN 71`, `NO MEL RELIEF`, `ATA 2913`, `EUR 510.00`, `STD+4h20`, the METAR raw) and otherwise the whole record line (PSS row, schedule line, care row). A test re-parses every atomic span back to its value. `recorded_at` is the document's `received_at`, except METAR (obs time + 5 min, a real-time feed).
- **`normalize.resolve(facts, sources, known_at)`** implements plan §2 rule 7 (recorded by `known_at`; best trust tier, then latest). The engine may use it or its own; on golden at day 1 it sees exactly the 6 overnight claims.
- The builder adds a `SRC-REALCTX-<storm>` document so real-context numbers are facts with spans too, and puts `PAX n` on schedule lines so operated flights' pax have a span.
