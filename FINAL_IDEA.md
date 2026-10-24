# StormCheck

**What we're building:** the disruption-liability seats at an airline. The morning after every storm, StormCheck works out the *real* cause of each cancelled flight from real weather and the aircraft's own logs. It then drafts what every passenger is owed and the EU261 compensation liability. It asks a person only when the evidence disagrees. It asks the right person, and it never asks twice.

**Seats:** StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant. Between them sits one step: working out what really caused each cancellation. StormCheck drafts every payout and the EU261 compensation liability, and the Claims Lead approves every payment. *It drafts. It never pays.*

*Numbers and wording here follow `IMPLEMENTATION_PLAN.md` v2. It wins on any conflict.*

---

### `example · the-business`
## An airline.
**The job: settle what every passenger is owed after each storm.** `[€1.1B Irish carrier]` `[5,292 passengers, one storm]`

| **Learns.** `self-learning` | **Runs.** `ai-automated` | **Escalates.** `needs-review` ★ | **Improves.** `new-policy` |
|---|---|---|---|
| Reads 18 months of ops logs, claims and payouts to learn who's owed what. **Learned** • 35% of owed long-haul passengers claim • Takes the 50% reroute cut (41 of 42) | The morning after a storm, it sets each flight's real cause and drafts every refund, payout and the liability. • 5,292 passengers sorted by 9 AM • Liability draft ready for the Controller | CRM says a passenger took a €300 voucher at the service desk. Her claim says she never agreed. **(CL)** Routed to the Claims Lead. `confidence 39% · sources disagree` • Holds that one €600 | Claims Lead: "No signed acceptance, no offset." • Saved as policy for every flight leaving the EU • Never asked again |

↻ *Next storm: 31 voucher cases settled, ruling cited.*

### `example · judged`
## The airline, judged.
**Its storm night, against the four questions.**

| **Real.** `real-enough` | **Hireable.** `would-you-hire-it` | **New.** `something-new` | **Wow.** `wow-moment` ★ |
|---|---|---|---|
| Real Dublin weather, traffic and EU law. Simulated logs, with the mess left in. • Cause codes that lie • Answer key: every passenger checked | One role: disruption liability. Drafts it, never pays it. • Asks the Claims Lead, not the CFO • Every euro traces to a log line | The cancellation's real cause, not another invoice bot. • Passengers feel it every storm • Rules that differ route to route | Catches a "weather" cancellation that was a broken plane. • Shows the weather and the tech log • Drafts 172 payouts for sign-off |

---

## The moment (the video opens here, 20s)
| Time | On screen |
|---|---|
| 0–4s | Storm Éowyn, Dublin, 24 Jan 2025. Northstar's operations centre coded **all 27 cancellations "weather" (71)** at 05:12. |
| 4–9s | Real METAR is laid over the timeline: the storm ran 02:30–15:00Z. The 23 cancellations inside it turn grey ("weather · no compensation; refunds and care still due"). 11 departures flew 15:30–17:30Z. |
| 9–14s | NS31 to Boston was scheduled for 16:30, after the storm. Its tech log, from the night before at 21:40: hydraulic pump leak, **no MEL relief**, aircraft grounded. Red: **"Not weather. Broken plane." · 71 → 41** |
| 14–17s | 172 passengers × the full entitlement = €99,000 if every passenger claims. StormCheck drafts the **EU261 compensation liability at the 35% expected claim rate: €34,650**. Not €0, not €99,000. `cause-finding confidence 91% · fault logged before storm` |
| 17–20s | **"172 payouts drafted, pending Claims Lead approval."** Click to see the trace: € → tech-log line → METAR hour → rule → CJEU *Wallentin-Hermann* / *van der Lans*. |

## How it works (simple enough to see)
- **2 Claude roles + 1 deterministic engine.**
  - The **Reader** turns messy logs, CRM notes and claim emails into facts. Every fact quotes its source, and the value is re-checked against the quote.
  - The **Drafter** writes rights notices, journal memos and "why?" answers. It sees zero PII.
  - The **engine** decides the facts: storm windows at both ends of each flight, the cause, EU261 bands, rules, confidence, routing, and the books.
  - *Claude reads the mess. It never decides who is owed.*
- **Facts vs. law.** StormCheck decides facts. A new legal pattern goes to Legal once. Example: a return flight from Munich cancelled because the storm stranded its outbound. **One question covers 3 flights.** Legal's ruling becomes a rule and settles all three.
- **Sources that disagree** follow a trust order: tech log and METAR > schedule and manifest > the operations centre's batch code > a passenger's account. When a human picks the winner, that choice becomes a scoped, versioned rule.
- **Rejections teach.** The Controller rejected releasing a year-old storm's liability: "Never release the tail." That became a rule, and StormCheck asks once whether it should apply to all storm cohorts.
- **Git-like trace.** Every decision is a hashed commit. Any euro can be `blame`d back to its source. You can replay what a rule change flips, and `make verify` recomputes everything offline.
- **Right person, limited access.** Ops never sees passenger PII. Agents see only what their role allows. Segregation of duties is enforced in code. SOC 2 is the floor; the controls are mapped on screen.
- **Judge's desk.** Name any airport and date. StormCheck pulls the real weather and runs it. You can inject a tech-log line, a claim or an email.

## The accounting it gets right (IFRS 15, per IFRIC Sept 2019)
| Event | Entry |
|---|---|
| Ticket refunded | Dr ATL + Dr taxes payable / Cr refunds payable. It was never revenue. The CRM-bot refunds clear through 2125, which ends at 0, so nothing is refunded twice. |
| NS31 recoded weather → technical | **Dr 4090 EU261 compensation (reduction of passenger revenue) €34,650 / Cr 2140 EU261 compensation liability €34,650.** That is 35% of €99,000, booked the morning after with 6 claims still unassessed. |
| A claim is approved | Dr 2140 / Cr 2141 compensation payable, at face value: €600 per claim, not €210. |
| Month-end lookback (Feb) | A/E 1.45, so the Bornhuetter-Ferguson estimate is selected. **+€3,990 change in estimate.** Closing balance **€25,740 = (35% − 9%) × €99,000**, `TIES TO GL 2140`. January is locked and untouched. |
| Knock-on returns held for Legal | Accrued at segment rates (€47,496). Legal's ruling turns that into a change in estimate. |
| Care (hotels, meals) | Accrued €227,000, invoiced €221,300 → €5,700 reversal. Care is owed even when the circumstances were extraordinary. |

## Proof it works
- **Data:** learns on 18 months of storms on real Dublin weather, and is scored on the next 6, which include Éowyn. The planted errors come with an answer key generated from ground truth, never from the engine.
- **Headline:** *"Plain Claude, 3 runs: three different numbers. StormCheck: €34,650 ×3, same hash."*
- **Also reported:**
  - % of passengers settled straight-through
  - miscodes caught (€)
  - false holds
  - repeat questions (0)
  - liability vs. actual claims
  - reliability bins ("calibrated on synthetic labels")
- **Real:** IEM METAR, Eurocontrol airport traffic (179 departures that day vs ~300 normal), OurAirports distances, the EU261 text, and CJEU case law.
- **Simulated:** Northstar's schedule, tech logs, passengers and claims, played by LLM personas. A human can take over at any point.

## The CFO pitch
"After every storm, your EU261 liability runs on a policy written down nowhere: a 5 a.m. cancel list coded 'weather', a spreadsheet, and a Monday spent emailing maintenance 'was it really weather?'. That human runtime is how weather cancellations turn into regulator complaints and surprise claims a year later. StormCheck settles every passenger against the real cause, proven from your own logs and the real weather. It keeps the liability right with a trace your auditor can click. It brings in a person only for the 1% where the evidence disagrees, asks the one person who knows, and never asks twice."

- *Who doesn't need it:* a three-route charter that rarely cancels.
- *Where it sits:* on top of Altéa/Navitaire, NetLine, AMOS and Accelya. It writes only parked journals.
- *Where it generalizes:* any company whose liabilities are triggered by an event and depend on what caused it.
