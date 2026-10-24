# StormCheck · Devpost write-up (draft)

Paste each section into its Devpost field. Golden numbers (5,292 passengers, €99,000, €34,650, €82,146, €3,990, €25,740) are asserted by tests and can stay as written. Everything in `{{double braces}}` must be filled before submitting, and the sentence deleted if its number doesn't exist.

## Placeholders to fill

| Placeholder | Source |
|---|---|
| `{{links.video}}` | YouTube or Vimeo link to the ≤3:00 video (`pitch/VIDEO.md`) |
| `{{links.recorded_build}}` | Vercel URL of the recorded build (`VITE_MODE=recorded`) |
| `{{links.repo}}` | GitHub repo URL |
| `{{eval.n_storms}}` | `eval/proof.json` → `n_storms` |
| `{{eval.n_passengers}}` | `n_passengers` |
| `{{eval.straight_through_pct}}` | `straight_through_pct` |
| `{{eval.miscodes_caught}}`, `{{eval.miscodes_total}}` | `miscodes_caught`, `miscodes_total` |
| `{{eval.miscodes_eur}}` | `miscodes_eur_cents` ÷ 100, formatted in € |
| `{{eval.false_holds}}` | `false_holds` |
| `{{eval.repeat_questions}}` | `repeat_questions` (target 0) |
| `{{eval.out_of_scope_auto}}` | `out_of_scope_auto` (target 0) |
| `{{eval.liability_vs_actual_m3}}`, `{{eval.liability_vs_actual_m6}}` | `liability_vs_actual` (key names as in `eval/NUMBERS.md`) |
| `{{eval.coverage_at_90_cause}}` | `coverage_at_90` → `cause` |
| `{{eval.baseline_eur_a}}`, `{{eval.baseline_eur_b}}`, `{{eval.baseline_eur_c}}` | `baseline` → `liability_eur` |
| `{{eval.baseline_cause_accuracy}}` | `baseline` → `cause_accuracy` |
| `{{eval.injections_blocked}}`, `{{eval.injections_total}}` | `injections` |
| `{{numbers.llm_spend_usd}}` | total Claude spend for the build and eval, if `eval/NUMBERS.md` records it |

**Check before submitting**
- `stormcheck_runs.liability_eur` is `[34650, 34650, 34650]` with `hash_identical: true`, and `baseline.hash_identical` is `false`.
- `label` still reads "calibrated on synthetic labels; validates the pipeline, not the world".
- The split is still learn Jul 2023 → Dec 2024, score Jan → Jun 2025; the text below assumes it.
- Every number in the video and screenshots matches the recorded build.

---

**Project name:** StormCheck

**Elevator pitch** (Devpost's short description):
Finds what really caused each cancelled flight, drafts every EU261 payout and the liability, and asks a person only about the 1% where the evidence disagrees.

**Track:** Hyphenate: Autonomous Systems for Finance

**For the Hyphenate judges**
- **Seats:** the Passenger Claims Accountant and the Revenue Accountant at Northstar Air, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment.
- **The moment:** operations coded all 27 cancellations "weather". The tech log shows NS31's plane broke the night before. Not weather. Broken plane: 71 → 41: 172 passengers owed, 171 payouts drafted, pending Claims Lead approval.
- **Live demo:** bring your own airport and date. The Judge's Desk runs on that day's real METAR.
- **Proof:** real vs simulated is below, with an answer key from ground truth and a plain-Claude baseline.
- **Video:** {{links.video}} (it opens on the moment).

---

## Inspiration

On Friday 24 January 2025, Storm Éowyn hit Dublin. Eurocontrol counted 179 departures at Dublin that day, against roughly 300 on a normal day. About 119 departures and 109 arrivals were reported cancelled (Cirium), and Met Éireann's red warning for Dublin ran from 06:00 to 11:00.

For an airline's finance team, a day like that runs on what Hyphenate calls a human runtime: a cancel list coded "weather" at 5 a.m., a spreadsheet, and a Monday spent emailing maintenance to ask "was it really weather?". The answer decides who is owed €250 to €600 in compensation and who gets none (refunds and care still due), and whether the number on the balance sheet is right.

Hyphenate's brief asked for one corner of a finance team, made autonomous. We picked the seats where an operational fact decides the money.

## What it does

StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment.

Northstar is fictional: an EU-licensed Irish carrier with about €1.1B revenue, 65 aircraft and a Dublin hub. The storm is real. The morning after Éowyn, StormCheck:
1. Reads the real METAR, the schedule, the operations cancellation log, the tech log, coupons and reaccommodation, CRM and claims.
2. Decides each cancellation's cause deterministically, with evidence and a calibrated confidence.
3. Works out each passenger's EU261 entitlement.
4. Drafts refunds, payouts and the EU261 compensation liability, a reduction of passenger revenue under IFRS 15.
5. Asks a person only about the 1% where the evidence disagrees, and asks the right one: the Claims Lead, Legal or the Controller.

**It catches.** Operations coded all 27 cancellations "weather" at 05:12. Real METAR puts Dublin's storm window at 02:30–15:00Z, and 11 Northstar departures flew between 15:30 and 17:30Z. NS31 to Boston was due out at 16:30Z. Its tech log from 21:40Z the night before: a hydraulic pump leak beyond limits, no MEL relief, aircraft on ground. Not weather. Broken plane. StormCheck recodes it 71 → 41 at cause-finding confidence 91%. The full Art. 7 entitlement if every passenger claims is €99,000; StormCheck drafts €34,650 at Northstar's 35% expected ultimate claim rate (history to month 18 plus a tail judgment). 172 passengers owed; 171 payouts drafted, pending Claims Lead approval (14C waits on her ruling).

**It defends.** Challenge it with "the storm would have grounded it anyway" and it answers "Decision stands.", citing the METAR, the 11 departures that flew and the fault logged before the storm. A notice claiming a hidden manufacturing defect is different: that's a new legal pattern (C-549/07 ¶26), so it goes to Legal.

**It asks once.** Three questions go to three people:
- **Claims Lead** (39% · sources disagree): CRM says passenger 14C accepted a €300 service-desk voucher; her claim says she never agreed, and there's no signature. Her ruling ("no signed acceptance, no offset") becomes a scoped rule. On the next storm, Herminia, 31 cases settle with the ruling cited, and the one flight that doesn't depart the EU asks again.
- **Legal** (no precedent): three return flights the storm stranded, in one question (C-74/19). One ruling settles all three.
- **Controller** (72% · no new claims in 3 months): StormCheck proposed releasing the last €3,600 of a year-old storm's liability. She rejected it: never release the tail. The rejection becomes a rule, and StormCheck asks once whether it should apply to every storm cohort.

**It keeps the books right.** On day 1 it drafts Dr 4090 EU261 compensation (reduction of passenger revenue) / Cr 2140 EU261 compensation liability: €82,146 for the storm. When Legal rules on the knock-on returns, the €47,496 held for them becomes a change in estimate. At the February month-end, claims run ahead of the curve (A/E 1.45), so a Bornhuetter-Ferguson re-estimate drafts a +€3,990 change in estimate, and the 2140 rollforward ties to the ledger at €25,740 = (35% − 9%) × €99,000, with January locked and untouched. The CRM bot's 32 refunds clear to zero, so nobody is refunded twice, and its "weather, no compensation" emails get 32 corrected rights notices. The Drafter saw 0 PII.

**Every euro traces back.** Every fact, decision, rule, ruling, journal event and LLM call is a hashed commit. `blame` walks any euro back to a log line, a weather hour, a rule and the person who ruled. `make verify` recomputes every hash and replays every decision offline.

**Your own scenario.** On the Judge's Desk, name any airport and date. StormCheck pulls that day's real METAR, simulates Northstar's flights on it with the usual mess planted, and runs the same engine.

## How we built it

Two Claude roles and one deterministic engine.
- **Reader (Claude):** turns messy logs, CRM notes and claim emails into typed facts. Every fact quotes a verbatim span, and code re-parses the value from that span; on a mismatch the fact is dropped.
- **Engine (Python, deterministic):** storm windows at both ends of each flight, cause from an ATA table and the aircraft's rotation, EU261 entitlements, versioned rules with precedence and authority, confidence per decision kind, and routing to the right person. It can't import the Anthropic SDK, read the system clock or use randomness; a test enforces that.
- **Books (Python, deterministic):** an obligation register, parked journal drafts, the 2140 rollforward, claim curves with Bornhuetter-Ferguson, and invariants checked on every post.
- **Drafter (Claude):** rights notices, journal memos, "why?" answers, challenge classification, and rule drafts from rulings. Any number in its prose must appear in the evidence, or a template is used.
- **Trace:** event-sourced, append-only SQLite. Blame, replay as of any time, revert, audit export.

The stack: Python 3.12 with uv, FastAPI, Pydantic 2, SQLite, numpy and scikit-learn (logistic regression only). React 19, Vite, TypeScript, Tailwind 4, shadcn/ui, Recharts, d3 and Motion on the web. `claude-opus-5-5` with structured outputs, plus the Batches API for the eval baseline. Every Claude call goes through one client with a disk cache and a dollar cap; total spend for the build and eval was {{numbers.llm_spend_usd}}.

Three of us built it overnight, each running two Claude Code agents in parallel in separate git worktrees: six lanes. Contracts came first (Pydantic models, Python Protocols and an HTTP API with a stub server), so every lane could start at once. A golden fixture fixes the key numbers to the cent, tests assert them, and a checksum stops anyone editing the expected values to make a test pass. A pre-commit hook enforces who owns which directory, and the web's API types are generated from the OpenAPI schema. A recorded build replays a full run with no backend, so the demo survives a dead server.

## Challenges we ran into

- **Keeping Claude out of the decisions.** The easy version asks the model who is owed. We made that impossible instead: the engine and books can't import the SDK, every fact the Reader produces must quote its source and re-parse, and every number in the Drafter's prose must appear in the evidence.
- **The accounting.** It isn't a provision. Under IFRS 15, compensation is variable consideration that reduces passenger revenue (IFRIC agenda decision, September 2019). Whether the reduction is capped at nil is still open, and it matters for passengers who were already refunded. Month-end true-ups had to be changes in estimate under IAS 8, with locked periods never touched.
- **Facts versus law.** Some cancellations aren't settled law: a return flight stranded when the storm cancelled its outbound leg (C-74/19), or a defect the manufacturer later calls hidden (C-549/07). The engine has to stop and ask Legal once, then turn the answer into a rule that doesn't stretch beyond its words.
- **Real weather doesn't follow a script.** The storm window is computed from METAR at both ends of every flight, never hard-coded. Éowyn's real data also has a separate short window around midnight, and gaps in the data have to become "unknown", not "weather".
- **Honest proof.** Our labels are synthetic, so a calibration chart could be circular. Ground truth comes from latent causes with about 5% deliberately invisible to the features, the answer key is written by the generator and never by the engine, and the chart says "calibrated on synthetic labels; validates the pipeline, not the world".
- **Six agents, one repo, one night.** Ownership by directory, additive-only contracts, and a landing script that merges, tests and checks ownership before every push.

## Accomplishments that we're proud of

- It catches the broken plane and defends the decision when challenged.
- The numbers hold to the cent, asserted by tests: €34,650 for NS31, €82,146 for the storm on day 1, +€3,990 at the February true-up, and €25,740 tying to GL 2140.
- Same answer every time. StormCheck ran three times: €34,650, same hash. Plain Claude on the same documents gave {{eval.baseline_eur_a}}, {{eval.baseline_eur_b}} and {{eval.baseline_eur_c}}, with cause accuracy of {{eval.baseline_cause_accuracy}}.
- One question to Legal settled three flights. One Claims Lead ruling settled 31 cases on the next storm, and the one case outside its scope asked again.
- On {{eval.n_storms}} held-out storms ({{eval.n_passengers}} passengers): {{eval.straight_through_pct}} settled straight-through; {{eval.miscodes_caught}} of {{eval.miscodes_total}} planted miscodes caught ({{eval.miscodes_eur}}); {{eval.false_holds}} false holds; {{eval.repeat_questions}} repeat questions after a ruling; {{eval.out_of_scope_auto}} out-of-scope cases handled automatically; {{eval.injections_blocked}} of {{eval.injections_total}} injection attempts blocked. Liability against actual claims: {{eval.liability_vs_actual_m3}} at M3 and {{eval.liability_vs_actual_m6}} at M6. Coverage at 0.9 confidence for cause: {{eval.coverage_at_90_cause}}.
- The Drafter wrote 32 corrected rights notices and saw 0 PII.
- A judge can pick any airport and date and get a run on that day's real weather.

## What we learned

- The expensive fact is the cause. Once it's right, the EU261 band is a lookup, and what's left is estimating who will claim.
- A fixed trust order resolves the routine disagreements: tech log and METAR, then schedule and manifest, then the operations batch code and CRM, then a passenger's account. People are needed only where that order runs out, and once they rule, the ruling becomes a rule.
- A confidence needs a reason. "39% · sources disagree" tells the Claims Lead what to look at; "39%" doesn't.
- Rejections teach as much as answers. The Controller's "never release the tail" became a rule, and StormCheck asked once whether it should cover every storm cohort.
- Event sourcing gave us blame, replay and revert from one log.
- Synthetic labels can prove a pipeline, not the world. We say so on screen.

## What's next for StormCheck

The same seat, more causes. We put every candidate through a critique by an EU261 lawyer, an airline revenue-accounting director with a Big-4 audit partner, an OCC/MRO lead, and a judge with a seed investor. This is what survived, in order:

- **Arrival delays of three hours or more**, compensated like cancellations (C-402/07 Sturgeon), with arrival counted when the doors open (C-452/13). It's the same cause question and the same entry (IFRIC 2019 covers delays). The differences: the extraordinary part of a delay is deducted before the three-hour test (C-315/15), and delays get their own claim curve.
- **Causes beyond weather** as new evidence feeds, each settled once by Legal:
  - ATC, proven per flight by its slot message
  - third-party strikes vs the airline's own (C-28/20)
  - bird strikes (C-315/15)
- **Regime packs** on the same dated rules:
  - UK261 (the DUB–LHR overlap is already paid once)
  - Canada's APPR for Canadian flights
  - US refunds
  - Regulation (EU) 2026/2202 before it applies on 23 Oct 2027: 30-day reasoned answers, which the weather defence already drafts, and a nine-month claim window that shortens the tail for new cohorts
- **Real feeds** behind the `ErpAdapter` interface: Amadeus Altéa or Navitaire, NetLine, AMOS, Accelya, the claims tool and the payment provider. The output stays the same: case recommendations and parked journals.
- **Calibration** on a real carrier's labelled history, in place of synthetic labels.

What we cut after the critique:
- **Baggage:** a different seat, where the cause barely matters.
- **Recoveries from suppliers:** warranties exclude consequential loss.
- **Per-tail reliability forecasts:** a technical fault is already owed.
- **Live flight-tracking data:** it shows no gate times and no causes.
- **Parametric weather cover:** it pays without asking the cause, which is our whole point.

## Built with

python, uv, fastapi, pydantic, uvicorn, sqlite, orjson, httpx, numpy, scikit-learn, pandas, pytest, hypothesis, typescript, react, vite, tailwindcss, shadcn-ui, recharts, d3, motion, tanstack-query, openapi-typescript, vitest, playwright, claude, anthropic-api, vercel, iowa-environmental-mesonet, noaa-aviation-weather-center, eurocontrol, ourairports, natural-earth

## Try it out

- Video: {{links.video}}
- Recorded build, no backend (replays a full run): {{links.recorded_build}}
- Code: {{links.repo}}
- Run it locally: `uv sync`, `cd web && pnpm i && pnpm build`, then `make demo` and open http://localhost:8000. With no network: `make demo-offline`.
- Your own scenario: Judge's Desk → any airport, any date.

**What's real:** real Dublin weather, real airport traffic, real distances and real EU law. Northstar's schedule, logs, passengers and claims are simulated on top, with the mess left in.

**Team:** David (engine and API), Filip (world, intelligence and books), Justin (frontend, pitch and docs).
