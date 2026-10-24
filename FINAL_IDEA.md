# StormCheck

**What we're building:** the disruption-liability seat at an airline. The morning after every storm, it works out the *real* cause of each cancelled flight from real weather data and the aircraft's own logs, then drafts what every passenger is owed and the provision for claims still to come. It asks a person only when the evidence disagrees. It asks the right person, and it never asks twice.

**Seats:** Passenger Claims Accountant + Revenue Accountant at Northstar Air. The Claims Lead, Legal and the Controller stay human. *It drafts, never pays.*

---

### `example · the-business`
## An airline.
**The job: settle what every passenger is owed after each storm.** `[9 transatlantic routes]` `[2,900 passengers a storm]`

| **Learns.** `self-learning` | **Runs.** `ai-automated` | **Escalates.** `needs-review` | **Improves.** `new-policy` |
|---|---|---|---|
| Reads two years of ops logs, claims and payouts to learn who's owed what. **Learned** • About 1 in 3 owed passengers claims • Half pay if rebooked within 4 hours | The morning after a storm, it sets each flight's real cause and drafts every refund, payout and the provision. • 2,900 passengers sorted by 9 AM • Provision draft ready for the Controller | The CRM says a passenger took a $300 voucher at the gate. Her claim says she never agreed. **(CL)** Routed to the Claims Lead. `confidence 39% · sources disagree` • Holds that one €600 | Claims Lead: "No signed acceptance, no offset." • Saved as policy for all EU routes • Never asked again |

↻ *Next storm: 31 voucher cases settled, ruling cited.*

### `example · judged`
## The airline, judged.
**Its storm night, against the four questions.**

| **Real.** `real-enough` | **Hireable.** `would-you-hire-it` | **New.** `something-new` | **Wow.** `wow-moment` |
|---|---|---|---|
| Real flight records, real airport weather, real EU law, with the mess left in. • Cause codes that lie • Answer key: every passenger checked | One role: disruption liability. Drafts it, never pays it. • Asks the Claims Lead, not the CFO • Every euro traces to a log line | The cancellation's real cause, not another invoice bot. • Passengers feel it every storm • Rules that differ route to route | Catches a "weather" cancellation that was a broken plane. • Shows the weather and the tech log • Holds 212 payouts for review |

---

## The moment (the video opens here, 20s)
| Time | On screen |
|---|---|
| 0–4s | Storm map over Dublin. **14 flights cancelled, all coded "weather."** Counter: **€0 owed.** |
| 4–9s | Real airport weather (METAR) is laid over the map: winds above limits from 11:00 to 19:00. 13 flights fall inside the storm and turn grey: *weather, nothing owed.* |
| 9–14s | NS31 to Boston was due at 21:30, after the storm cleared. Every other evening flight left. The tech log shows its plane was **grounded at 07:55 with a hydraulic leak**, before the storm started. Red: **"Not weather. Broken plane."** |
| 14–17s | **212 passengers × €600 = €127,200 owed** if they all claim. StormCheck drafts the provision at the learned claim rate: **€44,520.** `confidence 91% · fault logged before storm` |
| 17–20s | **"212 payouts drafted, held for the Claims Lead."** Click to see the trace: € → tech-log line → METAR hour → the rule (CJEU *Wallentin-Hermann*: technical faults are not extraordinary). |

## How it works (simple enough to see)
- **2 AI roles + 1 engine.**
  - **Reader** turns messy ops notes, tech logs, CRM entries and claim emails into facts. Every fact quotes its source.
  - **Drafter** writes payout letters, journal entries and answers to "why?".
  - **A deterministic engine** does the cause timeline (storm windows from METAR, event times from the logs), the EU261 tiers, the math, the rules, routing and the ledger. *The LLM reads the mess; it never decides who's owed.*
- **Facts vs. law.** StormCheck decides *facts*: when the fault happened, and when the storm was. Each *new legal pattern* goes to Legal once, for example "a crew timed out because of yesterday's storm." Legal's answer becomes a rule.
- **Trust order:** tech log + METAR > ops cause code > gate agent note > the passenger's account. A human picking the winner creates a scoped, versioned rule.
- **Confidence** comes from evidence: timestamps, storm-window margin, matching aircraft, how many precedents. It's calibrated on past storms.
- **Rejections teach.** The Controller rejects releasing the provision after 12 months: "Claims can arrive for years." That becomes a rule. StormCheck proposes it for every route and asks once.
- **Git-like trace.** Every decision is a commit. `blame` any euro back to the log line, the weather hour, the rule and who ruled. Revert a rule and replay what flips.
- **Right person, limited access.** Ops sees flights, not passengers (GDPR). Claims can't edit the tech log. The agents see only what their role allows. SOC 2-style controls are the floor.
- **The judge's desk.** Name any real airport and date. StormCheck pulls the real weather. Type a tech-log line and watch the payouts and the provision move.

## The accounting it gets right
| Event | Entry |
|---|---|
| Cancelled ticket refunded | Dr Air Traffic Liability / Cr Refunds Payable. It was never revenue. |
| Voucher accepted instead of cash | Dr Air Traffic Liability / Cr Voucher Liability, with expected breakage |
| NS31 recoded from weather to technical fault | Dr Passenger Compensation (expense or contra-revenue, per policy) **€44,520** / Cr EU261 Claims Provision. This is exposure × learned claim rate, **not the full €127,200.** |
| Each claim arrives | Dr Provision / Cr Compensation Payable. Payment is approved by the Claims Lead. |
| Hotels and meals for stranded passengers | Accrued, then trued up when the bills land |
| Month-end lookback | Claims filed so far vs. the claim curve. This drives the provision true-up. A release happens only when further claims are no longer probable. |

## Proof it works
- The engine learns on 18 months of storms and is scored on the next 6. The planted causes, vouchers, duplicates and an injected claim email come with an answer key written by a teammate who doesn't touch the engine.
- **First slide:** *"On storms it never saw: X% of passengers settled straight-through, Y miscoded cancellations caught (€Z), 0 repeat questions, provision within N% of actual claims."*
- **Real:** BTS flight-level delay causes, Iowa Mesonet METAR weather history, the EU261 text and CJEU case law. **Simulated:** passengers, tech logs and claims, played by LLM personas. A human can take over.

## The CFO pitch
"After every storm, your claims provision runs on a policy written down nowhere: cause codes typed in a hurry, a spreadsheet, and whoever remembers the last court ruling. That human runtime is how 'weather' cancellations turn into regulator fines and surprise claims a year later. StormCheck settles every passenger against the real cause, proven from your own logs and the real weather, and keeps the provision right with a trace your auditor can click. It brings in a person only for the 1% where the evidence disagrees, asks the one person who knows, and never asks twice."

*Who doesn't need it:* a carrier that never cancels, or a charter with three routes. A spreadsheet is fine there. *Where it generalizes:* any company whose liabilities are triggered by events and depend on what caused them.

## Scope
- **Build:** one storm day at Dublin plus the judge's desk on real METAR; EU261 cancellation tiers; vouchers; the provision with the claim curve; the ask-once loop; `blame`/replay; the CFO screen.
- **Cut:** US DOT refunds (one line in the pitch only), care costs beyond one accrual, delays (cancellations only), crew pay, real reservation-system data.

*Fallback idea (scored 2nd by the blind panel): `research/candidates/PaidOnce_final.md`.*
