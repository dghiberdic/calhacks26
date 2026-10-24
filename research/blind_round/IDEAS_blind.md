# Four candidate projects for the Hyphenate track (blind review)

Every candidate uses the same architecture, so judge the *idea* rather than the stack:
- **Two LLM roles:**
  - a Reader that turns messy documents into facts, each with a verbatim quote of its source
  - a Drafter that writes journal entries, letters and explanations
- **One deterministic engine** that handles all matching, math, rules, confidence scoring, routing and the ledger.
- **Ask once, never twice.** Each escalation goes to a named role with a confidence score and a reason. The human's ruling becomes a scoped, versioned rule. A rejection that comes with an explanation also becomes a rule, and the system proposes widening it one step at a time. Anything outside a rule's scope gets asked again.
- **Git-like tracing.** `blame` traces any dollar back to its source, rule and ruling, and replay shows the effect of a rule change.
- **Access limits** apply to both people and agents. Duties are segregated. Everything is drafted and nothing posts on its own.
- **A judge's desk** lets judges inject their own scenario live.
- **Proof:** the system learns on months 1–6 and is scored on months 7–12 against a planted answer key written by a teammate.
- **Team:** 2–4 students with robotics, satellite and hardware backgrounds. About 36 hours to build, with a 3-minute pitch and 2 minutes of Q&A.

---

## Idea 1: StormCheck (airline)
**Company:** Northstar Air, fictional, $2.8B, 9 transatlantic routes.
**Job:** after each disruption, settle what every passenger is owed and keep the provision for claims not yet filed.
**Seats:** Passenger Claims Accountant + Revenue Accountant. Claims Lead, Legal and the Controller stay human.
**Functions:**
1. Passenger settlement: refunds, EU261 cash compensation (€250/400/600 by distance unless the cause was "extraordinary"), and vouchers.
2. The operational step in between: decide the *real cause* of each cancellation from ops and tech logs versus weather data.
3. The compensation provision for claims not yet filed (ASC 450 / IAS 37).

- **Learns:** reads two years of ops logs, claims and payouts. Learned: • 70% of eligible passengers claim within a year • Pay 50% if rebooked arrival is within 4h
- **Runs:** the morning after each disruption, sets each flight's cause and drafts the refunds, payouts and provision true-up. • 2,900 passengers sorted by 9 AM
- **Escalates:** the CRM says a passenger accepted a $300 gate voucher; her AirHelp claim says she never agreed. Routed to the Claims Lead. `confidence 39% · sources disagree` • Holds that one €600
- **Improves:** Claims Lead: "No signed acceptance, no offset." • Saved for all EU routes • Never asked again
- **Rejection example:** the Controller rejects releasing the provision at 12 months: "UK claims run six years."

**Moment (20s):** A storm map over Dublin shows 14 flights cancelled, all coded "weather", €0 owed. Real METAR data marks 13 as truly inside the storm window. Flight NS31's tech log shows a hydraulic leak logged at 07:55, *before* the storm, so it was a technical fault and not weather (CJEU Wallentin-Hermann). Counter: **212 passengers × €600 = €127,200** drafted and held for the Claims Lead. `confidence 91% · fault logged before storm`

**Real data:**
- BTS flight-level delay-cause data
- Iowa Mesonet METAR weather history
- EU261 text and CJEU case law
- DOT 2024 automatic-refund rule
- Simulated: passengers and tech logs

**Accounting:**
- Refunds: Dr Air Traffic Liability / Cr Refunds Payable.
- Vouchers: a voucher liability with breakage.
- Compensation: a provision, presented as expense or contra-revenue (a policy choice).
- Care costs: accrued.
- A March storm drives claims for years, and a lookback test checks the estimate.
- Ops can't see passenger PII (GDPR).

**Stakes:** Southwest's 2022 meltdown cost over $750M, including a $140M DOT fine.
**Risks:** whether a cause was "extraordinary" is partly a legal call, so the system decides facts and Legal rules once per new pattern. Airlines' rev-accounting stacks are specialized.

---

## Idea 2: PaidOnce (snack brand)
**Company:** Northbay Snacks, fictional, $400M net, selling to Walmart, Kroger and Target and through wholesalers.
**Job:** settle every retailer deduction against its promo deal each Monday, and keep the trade-promotion accrual tied to the GL.
**Seats:** Deductions Analyst + Trade Accountant. Account managers confirm facts; the AR Manager and Controller approve.
**Functions:**
1. Retailers short-pay invoices, saying "the rest was for the promo."
2. The operational step in between: match each deduction to its deal, shipments and evidence, and draft disputes.
3. Settle the trade accrual under ASC 606 (variable consideration): apply, true up, and release when a further claim is no longer probable.

- **Learns:** reads a year of remittances and promo deals to learn how each retailer deducts. Learned: • Kroger deducts 45–90 days after a promo • Walmart audits back two years
- **Runs:** every Monday, settles each deduction and drafts the accrual true-up. • ~150 deductions a week
- **Escalates:** promo #412's deal ends March 31; the Walmart buyer's email says April 14. Routed to the Walmart account manager. `confidence 36% · sources disagree` • Holds that one $3,000
- **Improves:** Account manager: "The buyer's written extension stands." • Saved as policy for Walmart • Never asked again
- **Rejection example:** the Controller rejects an early release: "Kroger post-audits; wait 120 days."

**Moment (20s):** "Northbay promised Kroger $20,000 to put its chips on sale." A reserve bar shows $20,000 set aside. Kroger takes $20,000 off its next payment and the bar reaches $0. Three months later a wholesaler bills **$20,000 for the same sale**, and the bar goes to −$20,000 and turns red. The two claims cover the same 41 stores and the same 2 weeks. The deal funds Kroger directly, so the wholesaler's claim is held and disputed. `confidence 93% · same stores, same weeks` "Paid once."

**Real data:**
- Kaggle M5 Walmart store/SKU sales and prices
- Public X12 820 remittance layouts
- Public retailer deduction-code guides
- EDGAR 10-Ks (Energizer lists trade-promotion accruals as a critical audit matter)
- Simulated: the deductions themselves

**Accounting:**
- The accrual goes to a contra-AR allowance, or to an accrued liability for wholesaler billbacks.
- Deductions receivable, plus an allowance for invalid deductions.
- Fines and concessions are contra-revenue.
- Releases are changes in estimate.
- Checks: per-promo rollforward, and subledger = GL.

**Stakes:** trade spend is about 20% of gross sales, and deductions are 1–3% of gross.
**Risks:**
- CPG jargon (deduction, billback, accrual).
- Deduction-recovery vendors exist (Glimpse, HighRadius).
- "A snack brand" isn't a vivid company.

---

## Idea 3: Settle Night (concert promoter)
**Company:** Redline Presents, fictional, $700M, 30 venues.
**Job:** settle each artist's pay on show night, then post the revenue release and the tour's cross-collateralization ledger.
**Seats:** Settlement Accountant + Event Revenue Accountant. The box office manager, tour accounting and the Controller stay human.
**Functions:**
1. Show-night artist settlement ("$250k guarantee or 85% of net, whichever is higher") and expense allocation.
2. The operational step in between: confirm the box office count, comps and show expenses.
3. Release deferred event revenue, and track recoupable advances across a tour.

- **Learns:** reads two seasons of settlement sheets, deal memos and agent emails. Learned: • Ads split across shows by tickets sold • This agency cross-collateralizes every leg
- **Runs:** each show night, drafts the settlement as scanning closes. • 6 shows a night • Sheets ready before load-out
- **Escalates:** the box office logged 1,180 comps, but the deal caps comps at 400. Routed to the box office manager. `confidence 44% · no precedent` • Holds that one payout
- **Improves:** "Comps over the cap are priced at the cheapest public tier." • Saved for this agency's deals • Never asked again

**Moment (20s):** 11:52 PM, 17,400 tickets scanned. The draft pays the $250,000 guarantee because 85% of net is only $237,500. Then a $48,000 radio buy is flagged: the same invoice was charged in last night's Sacramento settlement. Removing it flips the deal to the percentage: **$278,300, +$28,300**. `confidence 94% · same invoice, two shows` "Settled once."

**Real data:**
- Billboard Boxscore grosses and attendance
- Live Nation 10-K ($4B event deferred revenue; artist advances tested for recoverability)
- Public settlement-sheet templates
- Simulated: deals and expenses

**Accounting:**
- Advance ticket sales go to deferred event revenue, released on show night.
- Artist deposits are prepaid.
- Settlement payable, with 30% withholding for foreign artists.
- Merch is booked net as an agent.
- Cross-collateralized shortfalls become recoupable advances, tested for recoverability.

**Risks:** it's close to Hyphenate's own festival-vendor workshop example, and its "same charge, two places" wow resembles their barista slide.

---

## Idea 4: Chargeback (spacecraft builder)
**Company:** a spacecraft and space-infrastructure company modelled on Redwire ($304M revenue in FY2024), running fixed-price satellite programs alongside NASA/USSF cost-plus contracts.
**Job:** every Friday, settle every labor hour and material charge to the right contract, then draft the revenue entry and the government invoice.
**Seats:** Government Contracts Accountant + Billing Analyst. Control account managers (the engineers who own budget slices), program managers and the Controller stay human.
**Functions:**
1. Cost accounting: charge hours to contracts, screening for allowability under FAR Part 31.
2. The operational step in between: the control account manager confirms what work was actually done, checked against cleanroom and test-chamber logs.
3. Revenue and billing: cost-to-cost ASC 606 revenue and loss provisions on fixed-price programs, plus the cost-plus voucher (SF 1034).

- **Learns:** reads 12 months of timesheets, chamber logs and charge history. Learned: • Test labor follows the hardware in the chamber • Internal R&D hours never touch a contract
- **Runs:** every Friday, settles each hour and drafts the revenue entry and voucher. • 9,000 hours across 14 contracts • Voucher draft ready Monday
- **Escalates:** a timesheet says internal R&D, but the linked ticket closes a NASA deliverable. Routed to the NASA program's control account manager. `confidence 34% · sources disagree` • Holds those 22 hours off the voucher
- **Improves:** "If it closes a contract deliverable, it's contract work." • Saved as policy for all programs • Never asked again

**Moment (20s):** Fixed-price satellite SAT-7 just blew its cost estimate by $2.1M, and its margin bar turns red. The same week, 160 hours move onto the NASA cost-plus contract (+$31,360 on the voucher). The test-chamber log shows those 4 engineers were badged in with **SAT-7 in the chamber**. The hours are reclassed to SAT-7, the NASA voucher is redrafted, and SAT-7's loss reserve grows. `confidence 91% · log contradicts charge` "Billed once, to the right customer."

**Real data:**
- USAspending.gov awards (real contract numbers, types, values)
- FAR Part 31 text
- Redwire 10-K estimate-at-completion adjustments (−$17.7M in 2024)
- The 3e Technologies DoD settlement (2006) for shifting hours from fixed-price to cost-plus work
- Simulated: timesheets, chamber logs, tickets

**Accounting:**
- FAR allowability, with penalties for expressly unallowable costs (FAR 42.709).
- Cost-to-cost revenue with cumulative catch-up.
- Loss provisions on fixed-price contracts.
- A reclass changes percent-complete back through prior months ("March affects June").
- Access: ITAR, so non-US persons and agents never see restricted technical data.

**Stakes:** False Claims Act exposure.
**Risks:**
- Government contracting is a narrow world, and "cost-plus" is jargon.
- These companies run Deltek, not NetSuite.
- The core logs are synthetic.
