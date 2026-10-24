# Beyond storms: what survived a four-expert critique (Justin, Sat 24 Oct, ~11:15 PDT)

Nothing here changes a golden number or the 3:00 script. There are five small asks, all after CP2; the rest is pitch, already written into `pitch/QA.md`, `DEVPOST.md` and `/pitch` on PR #3.

## How it was judged
Ten candidate expansions "to more things regarding planes" went through two rounds of four independent expert reviews. Each reviewer was told to try to kill every idea and to check its facts against sources:
1. **Passenger-rights lawyer:** EU261 / UK261 / APPR / Montreal. Read the adopted Reg 2026/2202 text (PE-CONS 39/26).
2. **Accounting:** an airline revenue-accounting director and a Big-4 audit partner (IFRS 15, IAS 37, ISA 540). Read `books/books.py`, `books/ops.py` and `engine/eu261.py`.
3. **Operations:** an OCC duty manager and an MRO reliability engineer. Checked what data really exists, and searched the AD registers.
4. **Pitch:** a Hyphenate-track judge and a seed investor. Weighed demo time, story and risk.

Round 2 put the ideas only one reviewer had proposed (N1–N6, P1) in front of all four.

## Verdicts
| Idea | Lawyer | Accounting | Ops | Judge | Outcome |
|---|---|---|---|---|---|
| C1 Delays ≥3 h (Sturgeon) | pitch | pitch, roadmap #1 | pitch | pitch | **PITCH, roadmap #1** |
| C2 Causes beyond weather (ATC, strikes, bird strike…) | build narrow | pitch | build thin | pitch | **PITCH**, plus the QA crib |
| C3 Regime packs (UK261, APPR, US) and the 2027 rules | pitch | pitch | pitch | pitch | **PITCH**, wording fixed below |
| C4 Recovery from OEM/MRO/handler (Art. 13) | flag only | kill | kill | Q&A | **KILL**, one Q&A line |
| C5 Baggage (Montreal) | kill | kill | kill | kill | **KILL** |
| C6 Claims inbox, agencies, limitation | build narrow | build thin | build thin | already ships (inj. 02, 06) | **small refinements** (asks 4–5) |
| C7 Per-tail reliability forecast | kill | kill | kill | kill | **KILL** |
| C8 Codeshare / wet lease | Q&A | kill | kill | kill | **KILL**, one Q&A line |
| C9 OpenSky traffic on the Desk | kill | kill | gated | kill | **KILL**: no gate times, licence limits, a live API on stage |
| C10 Parametric weather cover | kill | kill | kill | kill | **KILL** |
| N1 Weather defence file (lawyer) | build | build | build | build | **BUILT** (Justin, display-only) |
| N2 Hindsight test, ISA 540 ¶14 (accounting) | build ≤2 h | build | build ≤1 h | pitch | **OPTIONAL** (Filip, after CP3 items) |
| N3 ATFM slot message as tier-1 evidence (ops) | pitch | pitch | build if time | kill | **PITCH** |
| N4 EASA AD check (ops) | manual | manual | manual | manual | **DONE MANUALLY** (below) |
| N5 Assignment notice → Legal (lawyer) | build | build | after CP2 | pitch | **OPTIONAL** after CP2 |
| N6 Cause → law table | build | pitch | build, labelled | pitch | **PITCH** (QA crib) |
| P1 2026/2202 card text / rescope R-CTL-1 | build text | build text | text only | pitch | **ASK 5** (text only); **KILL** the rescoping |

## Already done (Justin, PR #3)
- **Every weather flight file now has a "Defence prepared · Art. 5(3)" panel:**
  - the named circumstance (261/2004 Art. 5(3), recital 14)
  - the flight's own METAR inside the computed window
  - how long until the window closed ("why not wait?")
  - what OCC knew before the 05:12 decision
  - the evidence against us (179 departures still ran)
  - the refunds and care still owed

  It's display-only: verdicts and € are unchanged. It's the answer to a real hazard: the press reported Ryanair departures from DUB around 09:30Z on 24 Jan, inside our window.
- **QA.md, DEMO_SCRIPT, DEVPOST and the `/pitch` CFO slide** now carry the surviving expansion story in wording the lawyer and the auditor checked.

## Asks (after CP2; none touches the 3:00)
1. **Crew evidence for the knock-on returns (Filip).** R-LEG-1 says "no aircraft *and crew* within 3 h", but the world only has a spares log. Add one line per return in the spares/crew text, e.g. `standby crew DUB; ferry + NS117 FDP 6h10 of 12h15 (ORO.FTL.205)`. Regenerate `expected/` and `SHA256SUMS` through the normal process, not before CP2.
2. **The red-warning email on weather flights (David, additive).** `SRC-EMAIL-METEIREANN-FWD-2025-01-23T1600Z` ("RED for Dublin 06:00-11:00 fri…", received 23 Jan 16:00Z) is in `world.json` but on no weather flight's timeline. As a timeline mark with `kind: "warning"`, the defence panel shows it under "Known before deciding" with no web change.
3. **2026/2202 card text (David; text only, no logic).** Add these lines:
   - "Amounts (€250/400/600) and the 3 h threshold unchanged."
   - "A carrier relying on extraordinary circumstances names the circumstance and explains the causal link and reasonable measures within 30 days."
   - "New claims within nine months."

   The lawyer also found on-block arrival and a 3-night hotel cap in PE-CONS 39/26; the others couldn't confirm them, so check EUR-Lex before adding those. Don't rescope R-CTL-1: that would edit the rule path the 1:40 beat runs, and every demo cohort predates 2027.
4. **Injection 06 wording (Filip/David).** Limitation depends on the forum (C-139/11 Moré; Rehder C-204/08). Say "after the limitation period that may apply (Ireland: 6 years)" and route to the Claims Lead/Legal instead of asserting it.
5. **Optional, only if CP3 is green early:**
   - **N2 (Filip, ≤1 h):** split eval's `liability_vs_actual` per storm (additive, in `proof.json`), labelled "simulated history, in-sample", since the generator draws claims from the same curves. Justin renders it on Proof if it's there.
   - **N5 (David):** an assignment notice that predates payment goes to Legal, once, with a scope that includes the governing law. A direct payment after notice doesn't discharge the debt: book a receivable from the passenger and never reduce 2140. Keep it off the 3:00 and out of the "3 questions" headline.

## AD check (done, for the "Airbus hidden defect" challenge)
EASA's register was offline, so the search covered FAA-adopted ADs. None covers a defect in the A320-family engine-driven pump itself.
- EASA 2026-0074 (EDP case drain) is for the **A350**.
- EASA 2021-0177 / FAA 2021-18-08 covers pylon rods damaged by EDP pulsation on **Pratt & Whitney** neos. It's not a pump defect.

QA.md answers the challenge with this. An EASA-only or very recent AD wouldn't appear in the Federal Register.

## Wording (proposed additions to IMPLEMENTATION_PLAN §9)
**Never say:**
- "restated under the 2027 rules"
- "highest entitlement"
- "recoverable €" or "recovery receivable"
- "extraordinary means no liability"
- "Dublin was shut"
- "legally compliant"
- "liability per tail"

**Say instead (checked by the lawyer or the auditor):**
- "Where several passenger-rights regimes apply, compensation is not paid twice."
- "Regulation (EU) 2026/2202 applies from 23 October 2027: no effect on today's balances."
- "Third-party recoveries: not recognised until virtually certain (IAS 37.33); never netted against the liability."
- "Next: arrival delays of three hours or more, compensated like cancellations (C-402/07, Sturgeon)."

## Facts the panel corrected (so nobody says them on stage)
- **APPR** covers flights to, from or within Canada only. Our overlap is NS51 DUB–YYZ, not NS31 DUB–BOS.
- **US:** refunds only (14 CFR 260). The compensation proposal was withdrawn on 17 Nov 2025.
- **Delay codes:**
  - IATA delay codes 81–89 aren't all ATC: 84 is destination weather, and 85–89 are security, immigration and airport.
  - Eurocontrol ATFM regulation causes: a strike is "I" (e.g. "IE 82"); "CE 81" means capacity.
- **€34,650 is immaterial** against roughly €14M materiality, so don't say "disclosed contingent asset".
- **A crew member's sudden illness** isn't extraordinary (C-156/22).
- **ADS-B (OpenSky)** gives first-seen and last-seen times, not gate or door times, and has no schedule.
