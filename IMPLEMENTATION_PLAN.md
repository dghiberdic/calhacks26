# StormCheck: Implementation Plan (v2, reviewed)

> **Read order for agents:** this file → `CONTRACTS.md` (binding) → your `THREAD_<NAME>.md` → `CLAUDE.md`.
> `FINAL_IDEA.md` is the pitch; this file wins on any conflict.
> **Owners:** David = Engine & API · Filip = World, Intelligence & Books · Justin = Frontend, Pitch & Docs.
> **v2** folds in five reviews: Hyphenate CTO, Hyphenate CEO + workshop engineer, an airline claims/OCC professional, a Big 4 airline auditor, and a staff engineer. All numbers below were recomputed by script.

---

## 0. What we are building

StormCheck fills two seats at **Northstar Air**: the **Passenger Claims Accountant** and the **Revenue Accountant**. Between those seats sits one operational step: working out *what really caused each cancellation*.

Northstar Air is fictional: an EU-licensed Irish carrier, IFRS in EUR, about €1.1B revenue, about 65 aircraft, Dublin hub.

The morning after a storm, StormCheck:
1. Reads real weather (METAR), the schedule, the OCC cancellation log, the tech log (AMOS-style), the PSS (Altéa/Navitaire-style coupons and reaccommodation), CRM and claims.
2. Decides each cancellation's cause deterministically, with evidence and a calibrated confidence.
3. Works out EU261 entitlements.
4. Drafts refunds, payouts and the **EU261 compensation liability** (a reduction of passenger revenue under IFRS 15).
5. Asks a person only about the 1% where evidence disagrees, and asks the *right* person: the Claims Lead, Legal, or the Controller.

Each ruling becomes a scoped, versioned rule, so the question is never asked twice. Every euro can be traced with `blame` to a log line, a weather hour, a rule, and the person who ruled. **It writes only drafts: case recommendations and parked journals. It never releases a payment run.**

**Pitch line:** "Today this runs on a human runtime: a 5 a.m. cancel list coded 'weather', a spreadsheet, and a Monday spent emailing maintenance 'was it really weather?'. StormCheck books it the morning after and asks only about the 1%."

## 1. The demo world (binding)

### 1.1 Real data
| Data | Source | Notes |
|---|---|---|
| METAR (EIDW and any judge station or date) | Iowa Environmental Mesonet `asos.py` CSV (no key, **1 request/s/IP**: fetch the 24 months in **one** request); NOAA AWC `api/data/metar` for the last 30 days | Pin the demo station-days in the repo. Irish local time = UTC in winter, UTC+1 in summer. |
| Airport-day traffic | Eurocontrol `airport_traffic_2025.csv` | EIDW on 24 Jan 2025 had **179 departures** vs. ~292–316 normal. About 119 departures and 109 arrivals were cancelled (reported, Cirium). Met Éireann red warning for Dublin ran 06:00–11:00, orange until 16:00. |
| Distances | OurAirports `airports.csv`, great circle per Art. 7(4), R = 6,371 km | DUB–BOS 4,804 · JFK 5,103 · ORD 5,896 · YYZ 5,261 · CDG 786 · FRA 1,086 · BCN 1,486 · MAD 1,452 · LIS 1,643 · FCO 1,886 · ATH 2,876 · MUC 1,381 · AMS 750 · LHR 449 (km) |
| Law | EU261 Arts 3, 5, 7, 8, 9, 14, 15; CJEU C-549/07 *Wallentin-Hermann* (¶26 hidden defect), C-257/14 *van der Lans*, C-74/19 *TAP* (previous rotation, direct causal link + reasonable measures), C-12/11 *McDonagh* (care), C-139/11 *Moré* (limitation: Ireland 6 years) | Reg (EU) 2026/2202 is in force from 22 Oct 2026 but **applies from 23 Oct 2027**. It appears as a **static future-dated rule card** only; no engine logic. |
| ATA / MEL | FAA JASC (ATA Spec 100); EASA MMEL categories (B = 3 days, C = 10 days) | For the A320 family, an engine-driven pump leak beyond AMM limits has **no MEL relief**. |
| Claim propensity | Steer 2020 (European Commission): cancellations 18%, all disruption types 37.5% (2018) | Northstar's long-haul **expected ultimate claim rate is 35%**: history to M18 plus a tail judgment. Medium haul 27%, short haul 20%. Northstar already sends the Art. 14(2) rights notice, and the curves were learned under that practice. |

**Honest framing (say exactly this):** "Real Dublin weather, real airport traffic, real distances and real EU law. Northstar's schedule, logs, passengers and claims are simulated on top, with the mess left in." **BTS is not used**: it covers US domestic flights only.

### 1.2 Hero day: Storm Éowyn, Dublin, Fri 24 Jan 2025
- **Real METAR at EIDW:** gusts ≥40 kt from 03:00 to 12:30Z, peaking at G56KT at 07:00 and 12:00. From 16:00Z: 9–14 kt, gusts ≤25 kt.
- **Storm window** (binding; `engine/timeline.py` computes it from data and **never hard-codes it**): contiguous obs with gust ≥35 kt, or sustained ≥30 kt, or visibility <0.5 SM, or wxcodes containing SN / FZ / TS / GR. Gaps under 2 h are merged.
  - On the real data this gives **02:30–15:00Z**. There is also a separate minor window at 23:30Z–00:30Z on 23–24 Jan; tests target the main window.
  - Windows are computed **at both ends**: departure at STD, arrival at STA.
- **In-window status:** `in | out | unknown`. `unknown` means there is no METAR obs within ±60 min, and it routes to Ops at <0.6 confidence.
- **The OCC cancel list** (ops log, a batch at 05:12Z):
  `05:12Z OCC DM: STORM ÉOWYN CNL LIST → NETLINE, RSN 71. NS100/101 NS102/103 NS104/105 NS106/107 NS108/109 NS110/111 NS112/113 NS114/115 NS116/117 NS118 NS21 NS41 NS51 NS31. INBD NS20 NS30 NS40 NS50 RSN 72. ASM SENT. IROPS SMS 05:20Z.`
  Delay codes are IATA: 71 = departure-station weather, 72 = destination weather, 41 = aircraft defect, 93 = rotation.

**Northstar's 27 cancellations** (`pax` comes from the manifest):

| Group | Flights (STD → STA UTC, pax) | Truth |
|---|---|---|
| **Outbound weather (13)** | NS100 DUB–LHR 06:10 (186) · NS102 DUB–CDG 06:40 (180) · NS104 DUB–AMS 07:05 (174) · NS106 DUB–FRA 07:30 (188) · NS108 DUB–BCN 08:15 (192) · NS110 DUB–MAD 09:00 (190) · NS112 DUB–LIS 09:40 (178) · NS114 DUB–FCO 10:20 (184) · NS116 DUB–MUC 11:00 (170) · NS21 DUB–JFK 11:05 (268, A330) · NS41 DUB–ORD 12:10 (254, A330) · NS51 DUB–YYZ 13:00 (241, A330) · NS118 DUB–ATH **12:40** (183) | weather (71), inside the window at DUB |
| **Return sectors, weather (6)** | NS101 LHR–DUB 08:00→09:15 (182) · NS103 CDG–DUB 08:50→10:30 (176) · NS105 AMS–DUB 09:15→10:40 (170) · NS107 FRA–DUB 09:50→11:20 (185) · NS109 BCN–DUB 11:15→13:40 (188) · NS111 MAD–DUB 11:55→14:20 (186) | weather: the STA falls inside the DUB window |
| **Overnight inbounds (4)** | NS20 JFK–DUB 23:30→05:50 (262) · NS30 BOS–DUB 00:10→05:30 (168, XLR EI-NSN) · NS40 ORD–DUB 23:00→05:40 (249) · NS50 YYZ–DUB 23:45→05:35 (236) | destination weather (72) |
| **Knock-on returns (3) → Legal** | **NS113 LIS–DUB 13:20→15:55 (178)** · **NS115 FCO–DUB 14:10→17:00 (184)** · **NS117 MUC–DUB 14:05→16:20 (168, EI-NSL)** | outbound cancelled by the storm; the return is calm at both ends → C-74/19 pattern |
| **NS31 DUB–BOS 16:30 (172, A321XLR EI-NSB)** | | **technical (41)**, recoded from 71 |

**Total: 5,292 passengers.** All counts in the UI and pitch come **from the API**, never hand-typed.

**Operated flights:** the generator includes 11 Northstar departures between 15:30 and 17:30Z that operated normally ("everyone else flew").

**NS31, the airtight hero case:**
- **Tech log (AMOS-style):** `23JAN 21:40Z EI-NSB DUB N/S. HYD FLUID ENG 2 LWR COWL. GND RUN: ECAM HYD Y ENG 2 PUMP LO PR. EXT LEAK EDP CASE DRAIN PORT, EXCEEDS AMM LIMIT. EDP RPLCMT REQD. NO MEL RELIEF. A/C AOG.`
  Weather at 21:40Z: 13 kt, no gust. This is **before** any storm window.
- **MCC log:** `22:15Z: NO EDP IN DUB STORES; POOL UNIT EX-TLS VIA CDG 25JAN ETA 14:00Z, RTS EST 20:00Z.` The ETA was quoted before the storm, so "the storm delayed the part" is false.
- **Spares log:** `No long-range tail at DUB. XLR EI-NSN at BOS (NS30 CNL 72); A330s at JFK/ORD/YYZ (NS20/40/50 CNL); A320/A321neo lack range.` This answers "why not swap?". Spares are legally irrelevant for NS31, because a technical fault is not extraordinary, so the Art. 5(3) "reasonable measures" test doesn't apply. **The engine must not score NS31 on spares.**
- **Root cause internal:** this is derived **by the engine** from `engine/ata_table.py` (ATA 2913 pump leak → internal), not by the LLM.
- **Verdict:** `technical · owed · recoded 71 → 41 · cause-finding confidence 91% · fault logged before storm`. 172 payouts drafted, pending Claims Lead approval.

**Knock-on returns** (e.g. NS117 MUC–DUB):
- NS116 DUB–MUC was cancelled by the storm, so EI-NSL never reached Munich.
- At NS117's STD (14:05Z) Munich was calm. At its STA (16:20Z) Dublin was 11 kt.
- **Spares:** `No tail at MUC. Earliest ferry ex-DUB 15:30Z → MUC dep 18:25Z = STD+4h20.` Passengers were offered the earliest reroute (LH via FRA).
- This is a legal pattern. **One question to Legal covers all 3 flights:** `confidence 47% · no precedent`.
- **Legal's ruling (scripted):** "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19)." This becomes `R-LEG-1@1`, scoped `knock_on ∧ ¬spare_within_3h ∧ reroute_earliest_offered`. All 3 settle the same morning, and the rule is cited 3×.

### 1.3 Money: CPA-verified, IFRS 15 variable consideration (IFRIC Sept 2019)

**NS31 day 1**
- **Coupons:** 172. Fare €450 (carrier surcharges YQ/YR are part of the fare) plus taxes €60.
  - ATL 2100: €77,400. Taxes payable 2110: €10,320.
- **Elections:**
  - 32 refunds: ATL €14,400 + tax €1,920 = €16,320, paid within 7 days (Art. 8). The CRM bot *initiated* these for direct-sold coupons between 06:02 and 09:40Z.
  - 14 vouchers: ticket value incl. taxes €7,140 → 2131.
  - 112 reaccommodated on 25–27 Jan, all >4 h late. Their ATL stays in 2100, and revenue is recognised when they fly.
  - 14 partner reroutes via LHR, +3 h 40 min. These go through FIM, net: ATL €6,300 + tax €840 → 2160 interline payable. The partner bills through IATA SIS in 2–3 months.
- **Entitlement:**
  - 158 × €600 + 14 × €300 = **€99,000**.
  - The 14 partner reroutes get the 50% reduction (Art. 7(2)(c): >3,500 km band, arrival within 4 h). Applying it is Northstar's policy, mined from history: "41 of 42".
- **Day 1, with 6 claims arrived overnight and still unassessed:**
  - **Dr 4090 EU261 compensation (reduction of passenger revenue) €34,650 / Cr 2140 EU261 compensation liability €34,650** (= 35% × €99,000).
  - That is not €0 (cash basis) and not €99,000 (the full Art. 7 entitlement if every passenger claims).
- **Policy disclosure:** the reduction is presented in full within passenger revenue (IAG approach). IFRIC left open whether it is capped at nil, and the 32 refunded passengers have a nil transaction price.

**NS31 rollforward to Feb 28, the CPA's "they understand this" screen:**
- Jan: 6 claims approved (Dr 2140 / Cr 2141 €3,600, at face value) → Jan close €31,050.
- Feb: 16 more claims (15 × €600 + 1 × €300 = €9,300) → €21,750 before re-estimate.
- **Feb month end** (M1 = first month-end at least 28 days after the event):
  - Expected at M1 = 9% × €99,000 = €8,910. Actual = €12,900. A/E = 1.45 (€-weighted).
  - Three methods: expected-loss €21,750, **Bornhuetter-Ferguson €25,740 (selected)**, chain-ladder (shown).
  - BF remaining = (35% − 9%) × €99,000 = **€25,740**.
  - **Change in estimate: Dr 4090 €3,990 / Cr 2140 €3,990.** Controller approval required; applied prospectively per IAS 8.36.
- **Rollforward line:** €34,650 new → (€3,600) Jan → (€9,300) Feb → +€3,990 → **€25,740 = (35% − 9%) × €99,000** · `TIES TO GL 2140` · Jan locked, untouched.
- **Sensitivity:** ±5 pp on the ultimate = ±€4,950.

**Storm day 1, total EU261 liability = €82,146**
- NS31: €34,650.
- Held knock-on returns, accrued under the IFRS 15.56 constraint at segment rates:
  - NS113: 178 × €400 × 27% = €19,224
  - NS115: 184 × €400 × 27% = €19,872
  - NS117: 168 × €250 × 20% = €8,400
- After Legal's ruling, the €47,496 is a change in estimate (Dr 2140 / Cr 4090) in the open period, leaving €34,650.
- Weather flights: "no compensation; refunds and care still due".

**Q1, the voucher in lieu**
- On 24 Jan the T2 service desk issued passenger 14C a €300 voucher "in lieu of compensation". There is no signed acceptance (Art. 7(3)).
- On issue: Dr 4090 / Cr 2132 compensation-voucher liability €300 (goodwill).
- After `R-CL-1`:
  - The €600 cash is owed: Dr 2140 / Cr 2141 €600 when the claim is approved.
  - The voucher stays as goodwill. If it is voided while unredeemed: Dr 2132 / Cr 4090.
  - A *signed* in-lieu voucher would instead settle in kind: Dr 2140 / Cr 2132 €300. The residual remains claimable under Art. 15(2) if the passenger wasn't informed.

**CRM-bot handoff (idempotency proof)**
- The bot posted refunds to 2125 refund clearing: Dr 2125 / Cr 1110 card acquirer €16,320 (for its 32).
- Books posts Dr 2100 / Dr 2110 / Cr 2125. **2125 = 0 proves no double refund.**
- The bot's 06:02 emails told those passengers "weather, no compensation", so the Drafter drafts **32 corrected rights notices** (Art. 14(2)).
- The chip reads **"Drafter saw 0 PII · names merged in code"**.

**Care, all flights**
- Accrued night of 24 Jan: Dr 6100 / Cr 2150 €227,000.
- Feb invoices: Dr 2150 €227,000 / Cr 2000 trade payables €221,300 / Cr 6100 €5,700.
- Care is owed even when the circumstances are extraordinary (McDonagh).

**Q3, Controller rejection → rule (time)**
- The Storm Isha cohort (EIDW@2024-01-21, long-haul) has entitlement €60,000 and 29% claimed by M12, leaving a liability of €3,600.
- The engine proposes releasing it (`confidence 72% · no new claims in 3 months`).
- The Controller rejects: "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation." This becomes `R-CTL-1@1`.
- StormCheck then asks once more: "All storm cohorts?" That is the rejection generalising.

### 1.4 Escalations in the demo (scripted inputs; the engine itself is generic)
| # | Case | Routed to | Tag | Ruling → rule | Payoff |
|---|---|---|---|---|---|
| Q1 | NS31/14C, the service-desk voucher in lieu: CRM says accepted, her claim says she never agreed, and there's no signature hash | Claims Lead | `confidence 39% · sources disagree` | "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill." → `R-CL-1@1`, scope `voucher.in_lieu ∧ ¬voucher.signed ∧ flight.departs_eu` ("every flight leaving the EU") | **Next storm, Herminia (real, Sun 26 Jan 2025, EIDW gusts 43 kt, 11:30–13:00Z):** 31 unsigned in-lieu cases on EU departures settle, ruling cited. 1 case on **BOS→DUB** (doesn't depart the EU) **asks again**. |
| Q2 | NS113/NS115/NS117 knock-on returns (one question) | Legal | `confidence 47% · no precedent` | as in §1.2 → `R-LEG-1@1` | 3 flights settled, rule cited 3× · €47,496 change in estimate |
| Q3 | Isha cohort release proposal at M12 | Controller | `confidence 72% · no new claims in 3 months` (a release proposal) | rejection → `R-CTL-1@1` | "All storm cohorts?", asked once |
| Q5 | Q1 unanswered for 3 h | Claims Lead (reminder) | chip only | none | "Waiting on Claims Lead 3h · reminder sent · N others settled", with N from the API |

There is no near-threshold question: distance is deterministic, so the UI shows the band margin ("1,486 km · 14 km under the €400 band") instead.

**Challenge (defends), on NS31:**
- Text "The storm would have grounded it anyway" is classified as an assertion. Reply: **"Decision stands."** It cites the METAR (gusts ≤25 kt from 16:00Z), 11 departures that operated 15:30–17:30Z, and the AOG logged 23 Jan 21:40Z with no MEL relief.
- Text "Airbus operator notice: hidden defect in this EDP batch" is classified as a new legal pattern (C-549/07 ¶26), routed to Legal at `confidence 52% · no precedent`.
- Challenge facts are trust tier 4. **They route; they never flip a decision.**

## 2. Architecture

```
 Feeds: METAR (IEM/AWC) · schedule · OCC log · tech/MCC log (AMOS-like) · PSS coupons (Altéa/Navitaire-like) · CRM · claims · spares
                    │
   [Reader · Claude]  messy text → typed Facts; every Fact quotes a verbatim span; contracts/parse.py re-parses the
                      typed value FROM the span (mismatch → dropped). The Reader never decides anything.
                    │       contracts/normalize.py: World → Facts (one fields registry, contracts/fields.py)
   [Engine · deterministic · "JADE-like judgment"]
       timeline (windows at both ends, in|out|unknown) → cause (ATA table, rotation, positive tier-1 evidence required to recode)
       → EU261 entitlement → rules@version (precedence, authority, scope grounding, conflicts) → confidence (per decision kind)
       → route/hold (+ reminders) → ACL broker (people AND agents)
                    │
   [Books · deterministic]  obligation register → parked journal drafts → 2140 rollforward → claim curves (BF) → invariants
                    │
   [Trace]  event-sourced: every fact / decision / rule / ruling / JE event / LLM call is a content-hashed commit
            · blame · replay(known_at) · revert · audit export · `make verify`
                    │
   [Drafter · Claude]  rights notices, JE memos, "why?", challenge classification, rule drafts from rulings
                       (numbers in prose must appear in the evidence, else fall back to a template)
                    │
   FastAPI + SSE  ──►  Web (React)  · role sessions (signed tokens per principal)
```

**Binding rules:**
1. **The LLM never decides who is owed, never computes an amount, and never derives the root cause.** `engine/` and `books/` must not import `anthropic`, call `datetime.now()`, or call `random` (enforced by an AST test). One injected `Clock` drives everything (`/api/clock`).
2. **Every LLM call is a commit (`kind="llm_call"`)** carrying the prompt hash, `response.model` (fallbacks can change it), the request id, the principal, and the input fact ids. Its output is stored as Facts or Drafts. **Replay never calls the LLM.**
3. **Rules come only from** mined history, rulings, rejections and regulation versions. There is no rule editor. Rule `action` is an enum, not free JSON. Grounding covers **condition and scope**: ungrounded scope keys are copied from the case and tagged `case:`; `widen` removes one per yes.
4. **Precedence:** `hard_control` > `regulation` > `legal_ruling` > `controller_ruling` > `claims_lead_ruling` > `mined`. A `statutory_floor` hard control means only Legal can lower EU261 compensation.
5. **Hard controls are code:**
   - Preparer ≠ approver.
   - Payouts need Claims Lead approval.
   - No writes to a locked period.
   - Materiality gate: auto-draft only if the per-flight liability is **< €50k and** confidence ≥ 0.90.
   - A rule's author must hold the authority for what the rule automates.
   - External parties (emails, claims) never satisfy an internal approval.
   - No `now()` inside a decision.
6. **Event-sourced storage.** SQLite tables are append-only event logs (triggers abort UPDATE/DELETE). Mutable-looking fields (`Rule.status`, `times_cited`, `Question.status`, `JournalEntry.status/approver`) are **views** over events. `/api/reset` copies `data/baseline.db` over the live DB.
7. **Bitemporal decisions:** `decide(flight_id, facts, rules, known_at, calibration_version)`.
   - Facts are used if `recorded_at ≤ known_at`, resolved per (subject, field) by trust tier, then latest.
   - Rules are used if `recorded_at ≤ known_at` and `valid_from ≤ flight.date`. Legal interpretations have `valid_from = null`, so they apply to past flights too. Controller policy applies prospectively.
   - Commit `inputs` include the engine git SHA and the calibration version.
8. **IAS 8.5 evidence-availability test** (not commit timestamps):
   - If the decisive evidence's `received_at` ≤ the period lock and it was unused, that is an **error**. It is corrected in the current period as an immaterial out-of-period adjustment. Materiality is about €14M, so these never trigger a restatement.
   - New claims or a new ruling are a **change in estimate** (IAS 8.36).
9. **Money** is integer euro cents. **Time** is UTC ISO-8601 `Z`. **Hash** = sha256 of `orjson.dumps(model_dump(mode="json"), OPT_SORT_KEYS)`. **IDs** use only `[A-Za-z0-9@.:_-]`: `NS31@2025-01-24`, `NS31@2025-01-24:14C`, `JE-000123:2`.

**Stack** (versions verified Oct 23, frozen in lockfiles):
- **Python 3.12**, uv:
  - FastAPI, Pydantic 2, uvicorn, httpx, orjson, stdlib `sqlite3` (WAL), anthropic 2.x, numpy, scikit-learn (logistic only; no isotonic with ~200 labels), airportsdata (tz), pytest, hypothesis, respx, time-machine.
  - SSE via `fastapi.sse` or sse-starlette. No GZip middleware.
- **Web:** Vite + React 19 + TS + Tailwind 4 + shadcn/ui, Recharts, `d3-scale` + `d3-geo` + `motion`, TanStack Query, `openapi-fetch` + `openapi-typescript`, pnpm.
  - **The map is a static SVG** (d3-geo plus bundled Natural Earth land, public domain, centred on Dublin). It needs no tiles and works offline. Every arc leaves Dublin, so a tile map adds nothing.
- **LLM: `claude-opus-5-5`.**
  - Adaptive thinking, with effort set explicitly: Reader `low`, Drafter `medium`.
  - No `temperature`/`top_p`/`top_k` and no forced `tool_choice` (they return 400).
  - Structured output via `client.messages.parse(..., output_format=Model)`. Citations are incompatible with structured output, so spans are checked by substring.
  - Server-side `fallbacks="default"` per the `claude-api` skill.
  - Batches API for eval. Disk cache.
  - `LLM_MODE=live|cache|offline`. Tests default to `offline`. There's a dollar cap in `llm/client.py`.

**Modes:** `STORMCHECK_MODE=live|cache(default)|offline`. `make demo` runs one process on :8000 that also serves `web/dist`. `make demo-offline` must pass with wifi off.

**Sits on top of (say it in the pitch):**
- It reads Amadeus Altéa / Navitaire (PNRs, coupons, reaccommodation), NetLine/Ops (cancellation messages, delay codes), AMOS (tech log, MEL, AOG orders), Accelya revenue accounting (BSP/SIS), the claims tool and the payment provider.
- It writes only drafts: case recommendations and parked SAP journals.
- In the demo these are simulated feeds behind an `ErpAdapter` interface.

## 3. Screens (Justin)
Hyphenate's grammar, in our own skin: storm navy-slate, cool-blue METAR band, amber = held, red **only** for "Not weather". No crimson, orange, Saans fonts, or "INPUT NEEDED" flag. No rule editor anywhere. No dashboards of flags.

| # | Screen | Purpose | Key components |
|---|---|---|---|
| 1 | **Storm Run** (home) | What it did overnight, plus the 1% it asked about | Static SVG map of Dublin arcs coloured by verdict. **Storm timeline (hero):** METAR gust/sustained curves, the window band, ticks for cancelled flights, solid ticks for the 11 that operated, the tech-log marker 23 Jan 21:40Z, and the "71 → 41" chip. Headline "5,292 passengers · 3 questions · 3 people" (from the API). **Learns strip** (4 small cards: "Read 18 months of claims · 35% of owed long-haul passengers claim · takes the 50% reroute cut, 41 of 42" → Runs → Escalates with CL/LG/CT avatars → Improves). Activity feed with mono chips. Real-context strip (Eurocontrol 179 departures; red warning 06:00–11:00). |
| 2 | **Flight File** | Why this verdict | Verdict chip and reason line. Evidence ranked by trust tier with verbatim quotes, the losing source struck through (`71` struck, tech log wins). Confidence breakdown (features; caps shown as separate chips). Band margin. Rules cited. Entitlement summary. JE card "NOT YET POSTED · BUILT FROM N SOURCES". **Why?** and **Challenge** (returns "Decision stands." or routes to Legal). The CRM-bot row: "32 refunds already initiated · not repeated · 32 corrected rights notices drafted · Drafter saw 0 PII". |
| 3 | **Questions** (role-scoped) | One question per pattern | Card: what it found / why it flagged it / what it recommends (recommended option **preselected**), confidence, holds, reminder timer. Answer → rule preview (DSL as a sentence, grounding highlights over the ruler's words, checks, "would change N past decisions · Δ€") → Confirm → "Saved as policy · Never asked again". |
| 4 | **Policies** | Learned, ruled, rejected | Cards by origin (Learned "41 of 42" / Ruled / Rejected / Regulation, including the static Reg 2026/2202 card "applies from 23 Oct 2027"). Provenance, version, status, times cited, Widen (one rung), Revert → replay diff. |
| 5 | **Trace** | Git-like record, plus **Access** and **Controls** tabs | Commits; blame chain (€ → entitlement → rule@v → ruling quote → facts → span → METAR obs); replay diff ("flips N · Δ€ · Jan locked, untouched"). **Access tab:** principals × resources matrix, denied log (`agent.drafter approve_payout → DENIED · SoD`), and a "view as Ops" PII mask. **Controls tab:** header "SOC 2 is the floor", mapping (not a certification claim): CC6.1 ACL broker · CC6.3 least privilege/SoD · CC7.2 denial log · CC8.1 versioned rules replayed before confirm · PI1 invariants. |
| 6 | **Liability & Close** | Controller/CFO | **One CFO bridge:** "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)". The 2140 rollforward by cohort with `TIES TO GL 2140`. The **estimate card** (header: pax · entitlement · curve LH-v1, € basis, observed to M18, n per point; three methods with BF selected; A/E and credibility z; constraint note; tail vs. Steer 18% benchmark; preparer and approver). Claim curve chart. JE drafts with [Edit][Approve] (SoD → `DENIED`). Month-end button (+€3,990). Lock period. Invariants list. |
| 7 | **Judge's Desk** | Their own scenario | Airport + local date → real METAR (pinned → IEM → AWC) → run. Inject panel with templated kinds. 8 rehearsed-scenario buttons. Streamed diff of what changed. |
| 8 | **Proof** | How we know | Headline: **"Plain Claude, 3 runs: €a / €b / €c. StormCheck: €34,650 ×3, same hash."** Scorecard, reliability bins with n and Wilson intervals ("calibrated on synthetic labels; validates the pipeline, not the world"), coverage@0.9, real vs. simulated. |
| – | `/pitch` | Slides | the-business (Escalates highlighted) · judged (Wow highlighted) · architecture ("2 Claude roles + 1 deterministic engine") · real/simulated/how we know · CFO line. |

Also: a **role switcher** that calls `POST /api/session` and gets a signed token per principal, and a **time scrubber** (`POST /api/clock`).

## 4. Demo script (3:00 live; the video opens on 0:00–0:35)
| t | Screen | Beat (say) |
|---|---|---|
| 0:00 | 1 | "Northstar, a €1.1B airline. Two seats, the claims and revenue accountants, and one step between them: what really caused each cancellation." |
| 0:10 | 1 | "OCC coded all 27 'weather' at 5 a.m. The METAR says Dublin's storm was over by 15:00, and everyone else flew. NS31's plane broke the night before, with no MEL relief. **Not weather. Broken plane.** 71 → 41. €34,650 at the 35% it learned: not €0, not €99,000. 172 payouts drafted for the Claims Lead's sign-off." |
| 0:35 | 2 | The WX code is struck through. The CRM-bot row: refunds not repeated, rights notices corrected, 0 PII. Challenge "storm anyway" → **"Decision stands."** |
| 1:00 | 3 (Claims Lead) | PII visible to this role · `39% · sources disagree · reminded 3h` · ruling → rule preview (grounded words highlighted) → "Never asked again". |
| 1:25 | 3 (Legal) | One question, three flights → ruling → 3 settled, cited 3×. |
| 1:40 | 3 → 6 (Controller) | Reject the Isha release: "Never release the tail…" → rule → "All storm cohorts?". The rollforward ties to GL 2140. |
| 2:00 | 7 | **"Name an airport and a date."** Real METAR → run → a miscode caught → "↻ N voucher cases settled, ruling cited · the BOS→DUB case asks". |
| 2:35 | 8 | Plain Claude ×3 gives three different numbers; StormCheck gives the same hash ×3. |
| 2:50 | 1 | "A human runtime: a 5 a.m. code and a spreadsheet. StormCheck books it the morning after and asks only about the 1%. A three-route charter doesn't need it." |

**Not in the live demo** (have it ready for Q&A): the Feb true-up and estimate card, Trace/blame, Access/Controls, Policies revert, the time scrubber.

## 5. Proof it works (Filip)
- **World:** Northstar ops on **real EIDW METAR**, built from storm days plus about 40 background days (Jul 2023 → Jun 2025).
  - Storm days are selected from data (gust ≥35 kt for ≥3 h): e.g. Ciarán, Debi, Isha, Jocelyn, Kathleen, Ashley, Darragh, **Éowyn**, **Herminia**.
  - **Ground truth comes from latent causes** (internal fault / weather / rotation / crew), with about 5% deliberate feature-invisible ambiguity, so calibration isn't circular. Ground truth is *not* defined as "inside the engine's window".
- **Split:** learn Jul 2023 → Dec 2024; score Jan → Jun 2025, which includes Éowyn: a storm it never saw.
- **Planted errors** (≥5 of each per split, all in the answer key):
  - technical cancellations miscoded as weather
  - a concurrent cause (AOG inside the window)
  - knock-on returns
  - in-lieu vouchers without a signature
  - duplicates: lead booker plus a member, direct plus agency, two agencies, claim plus chargeback
  - agency claims under `authority=none`
  - an assignment notified, then the passenger is paid directly anyway (doesn't discharge)
  - CRM-bot refund plus a BSP refund on the same coupon
  - notice ≥14 days (exempt)
  - manifest vs. ops pax mismatch
  - injection emails
  - a claim arriving after the limitation period
  - a staff ID90 ticket (Art. 3(3), no compensation)
  - a UK261 £520 claim on DUB–LHR (EU261 €250 applies; pay once)
- **Answer key:** written by Filip's generator from ground truth, **never** from David's engine.
- **Metrics** (`eval/proof.json`):
  - straight-through %
  - miscodes caught (count, €)
  - false holds
  - repeat questions after a ruling (target 0)
  - out-of-scope cases handled automatically (target 0)
  - liability vs. actual at M3 and M6
  - reliability bins and coverage@0.9 (per decision kind; labelled "uncalibrated" where no model exists)
  - **baseline:** plain Claude on the same raw documents, 3 runs, for Éowyn plus 2 storms: accuracy, € spread, hash-identical? no
  - injections blocked

## 6. Thread split: three independent threads (~30 agent-hours each). **Each person runs two agents at once**, in two lanes that never share a directory, each in its own git worktree.

| | **David: Engine & API** | **Filip: World, Intelligence & Books** | **Justin: Frontend, Pitch & Docs** |
|---|---|---|---|
| Lane A | `engine/`: timeline, cause + ATA table, EU261, rules/DSL/precedence/authority/controls, confidence + routing, trace (event store, blame, replay, revert), lifecycle, ACL, frequency miner | `world/` + `eval/`: golden-compatible Éowyn embed, METAR fetch + pins, airports/tz, generator (latent causes, storm and background days, planted errors, answer key), `generate_day`, eval/calibration/baseline/proof | `web/` screens 1–3 + timeline + map + session/role/clock + SSE |
| Lane B | `contracts/` + `server/` + `scripts/`: CP0 contracts (fields, normalize, parse, fakes, stub, golden fixture incl. Herminia and Isha cohort, curves), thin server by 06:00, full API, SSE, desk/inject/challenge/session/audit, modes, `make verify`, smoke tests, landing script, hooks | `books/` + `llm/`: books first (CoA, register, estimate, claims, BF, rollforward, invariants, SoD, preview, CFO), then the LLM client, Reader, Drafter | `web/` screens 4–8 + recorded mode + Vercel + `/pitch` + `pitch/` (DEMO_SCRIPT, VIDEO, QA) + `README.md` + `DEVPOST.md` |

**The only cross-thread interfaces** are `contracts/interfaces.py` Protocols and the HTTP API in `CONTRACTS.md`. Fakes (`contracts/fakes.py`) and the stub server let every lane start immediately.

## 7. Timeline and checkpoints (PDT)
| Checkpoint | When | Must be true (`make smoke-N`) |
|---|---|---|
| **Plan commit** | Sat ~01:00 | Plan docs plus `pyproject.toml`/`uv.lock`, `contracts/models.py`, `contracts/interfaces.py`, `OWNERS`, `.gitattributes`, `.githooks/`, and the real Éowyn and Herminia METAR CSVs, all on `main`. |
| **CP0a** | Sat 01:45 | David-B lands the stub server (every route has `response_model`) with hand-written fixtures for `/storms`, `/storms/{id}`, `/flights/{id}`, `/questions`, plus `openapi.json` and `contracts/tests`. Justin switches from local mocks to the stub. |
| **CP0b** | Sat 04:00 | Full golden fixture (`world.json` incl. Herminia mini-day, Isha cohort opening balance, curves), `expected/` (+ `SHA256SUMS`), all `fixtures/api/*.json`, `fields.py`, `normalize.py`, `parse.py`, fakes. |
| **D10a** | Sat 06:00 | The real server boots golden and serves `/storms`, `/storms/{id}` and `/flights/{id}` from the **real engine**. The other routes come from the stub. |
| **CP1** | Sat 09:00 | On golden: NS31 `technical` (71 → 41); 13 + 6 + 4 weather; 3 knock-on `needs_legal`; Books drafts **3,465,000c** (NS31) and **8,214,600c** (storm). Storm Run renders from the real server. |
| **CP2** | Sat 15:00 | The generator emits a valid world. Inject a tech-log line → SSE fact → decision → commit within 20 s. Q1 → rule → Herminia settles 31 and the BOS→DUB case asks. Blame reaches the METAR row. Desk works for a new airport/date. Real Reader/Drafter are wired in. |
| **CP3** | Sat 22:00 (feature freeze) | Eval and baseline cached; `proof.json` real; `make record` done; Vercel recorded build live; `make demo-offline` passes; all 8 injections plus 20 fuzz inputs end in an answer or a graceful escalation; `make verify` is green. |
| Freeze | Sun 07:00 | Tag `v1.0-demo`. Submit to Devpost by **08:30** (deadline 09:00). At the venue by 08:00. |

**Git rules:**
- Branches: `david`, `filip`, `justin`, plus per-lane `<name>/<lane>-<wp>` branches.
- Land with `scripts/land.sh`: it merges `origin/main`, runs the contracts tests, your suite, and `check_owners.py --range origin/main..HEAD`, then pushes (with retry).
- Merge `main` into your branch hourly.
- Only David-B edits `pyproject.toml`/`uv.lock`; request dependencies in `contracts/requests/<name>.md`. Only Justin-A edits `web/package.json`.
- `contracts/CHANGELOG.md` uses `merge=union`.
- **Mid-night contract change:** anyone may land an *additive*, contracts-only commit (CHANGELOG entry + `make openapi` + tests green) before first using it. Renames wait for morning.

## 8. Risk register
| Risk | Mitigation |
|---|---|
| IEM rate limit or venue wifi | One 24-month request, demo days pinned by 04:00, "cached" badge, AWC fallback, phone hotspot |
| LLM latency or outage live | The whole story is precomputed. Only injections call the LLM (Reader timeout 8 s → labelled regex fallback). `LLM_MODE=offline` works. |
| False "Not weather" on a judge's fog/snow day or a METAR gap | Visibility/wx codes count toward the window; `unknown` → Ops; recoding requires positive tier-1 evidence; AOG inside the window → Legal ("concurrent causes") |
| Agents idle on permission prompts or stopping after one task | Each teammate sets their own Claude Code permission allowlist for repo commands (their choice; documented in README), plus a kickoff prompt: "work through the whole queue, never stop to ask; log judgment calls in `<area>/DECISIONS.md`; heartbeat in `STATUS.md`" |
| A global "never commit" rule blocks agents (e.g. a personal `~/.claude/CLAUDE.md`) | The kickoff prompt explicitly authorizes commit, push and `scripts/land.sh` for this repo. Check the first push at 02:00. |
| An agent edits `expected/` to pass a test | `SHA256SUMS` is checked in `contracts/tests` |
| Contract drift | OpenAPI superset test (real server vs. the stub's `openapi.json`), fixture validation, generated TS types, smoke tests |
| Numbers that don't reconcile | Every count and € in UI, pitch and video comes from the API or the recorded build |
| Demo laptop dies | Spare laptop on the same tag, Vercel recorded build, video |

## 9. Wording (CPA- and airline-checked; use everywhere)
| Don't say | Say |
|---|---|
| "provision" | "EU261 compensation liability" ("provision" only for IAS 37 legal costs, 2170) |
| "expense or contra-revenue" | "reduction of passenger revenue" |
| "€0 owed" (weather) | "no compensation; refunds and care still due" |
| "learned 35%" alone | "35% expected ultimate claim rate (history to M18 + tail judgment)" |
| "worst case €99,000" | "full Art. 7 entitlement if every passenger claims" |
| "confidence 91%" next to € | "cause-finding confidence 91%" |
| "booked" / "paid" for drafts | "drafted, pending approval" (journals are parked) |
| "restatement" | "change in estimate (IAS 8.36)" or "prior-period error, corrected in current period (immaterial)" |
| "release at M12" | "reduce to the expected tail at M12; derecognise at limitation" |
| "gate voucher" | "service-desk voucher" (a cancelled flight has no gate) |
| "$300" | "€300" |
| "Held for the Claims Lead" (NS31) | "172 payouts drafted, pending Claims Lead approval" |
| "the AI decides" | "the engine decides facts; Legal rules on law" |
| "real flight records" | "real Dublin weather, traffic and EU law; simulated logs" |

## 10. Rubric map
| Requirement | Where it's visible |
|---|---|
| Real enough | METAR band; Eurocontrol 179; CJEU and Art. citations in blame; MEL-accurate tech log; Proof |
| Would you hire it | Seats line; drafts only, parked journals; SoD denials; every € traces back; SOC 2 controls tab |
| Knowing when to ask | `confidence NN% · reason` on every question, the right role, "Holds €X" |
| Something new | The cancellation's *real cause* drives the liability; storm timeline at both ends |
| Moment: catches / recovers / defends | NS31 / CRM-bot handoff + Legal settling 3 / "Decision stands." |
| Sources disagree | Struck losing source; the ruling picks the winner → rule |
| Time | Claim curve + BF true-up + locked Jan; rule reused on Herminia; Reg 2026/2202 card |
| Working with others | Reminder chip; Controller rejection; Legal ruling |
| Limits | ACL broker for people and agents; "Drafter saw 0 PII"; SoD in code |
| Explainable / accountable | `blame`, commits, replay, audit export, `make verify` |
| Workshop: self-learning, onboarding | Learns strip (mined at onboarding) |
| Workshop: escalation → rule → never again | Herminia beat: "31 settled, ruling cited", repeat questions = 0 |
| Workshop: rejection generalizes | Controller rejection → "All storm cohorts?" |
| Workshop: right person, no leaks, agents limited, SOC 2 floor | Questions per role; Access/Controls tabs |
| Workshop: one function, simple, CFO, complex only, $100M+ | "Two seats, one step between"; 2 Claude roles + 1 engine; CFO bridge; "a three-route charter doesn't need it"; €1.1B carrier |
