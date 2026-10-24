# Candidate A: "Shortfall": retailer deductions → trade-promotion accrual (CPG brand)

This idea was proposed independently by two ideators, one working from supply chain and one from CFO pain points. This file merges their versions.

## Function
Two accounting functions joined by one operational step:
1. **AR: deduction resolution.** Retailers short-pay invoices, and the remittance (EDI 820/812 or a portal CSV) lists the deductions: promo, shortage, OTIF fine, pricing.
2. **Operational step.** Match each deduction to its evidence: the invoice, the promo agreement or calendar, the POD/BOL, and the ASN (EDI 856). Then draft the dispute packet for the retailer's portal.
3. **Trade-promotion accrual settlement** (ASC 606 variable consideration). Relieve the accrual, true it up, and release stale balances. Write off or rebill.

Time matters here: a March promo gets deducted in June, and a Walmart post-audit can look back about 2 years.

## Why it's real and big
Most of these stats come from vendor blogs, so present them as ranges.
- Trade spend is about 20% of gross sales, the #2 P&L line after COGS (Strategy&).
- Deductions run 1–7% of gross sales. 10–25% of them are invalid, although the only survey (CRF 2012) put the median at 3–5%. Each costs $200–500 to resolve, so items under roughly $150–300 get written off without a look.
- **Energizer's 10-K lists trade promotion accruals as a Critical Audit Matter every year from FY2019 to FY2025** ($190.6M allowance plus $76.1M accrued in FY25). Reynolds' auditor tests "sales incentives" against contracts.
- For an illustrative $400M brand: about $12M a year in deductions, about $2M of it recoverable, and $1.6–2.4M a year spent handling them.
- Dispute windows: Kroger 180 days; Walmart post-audits about 2 years.
- Fit with Hyphenate: the CEO's essay uses a CPG distributor and the cash conversion cycle as its example, and Mini Melts (a CPG distributor) is a customer. Hyphenate's site never mentions deductions or trade spend.
- **Competitors:** Glimpse ($52M raised), HighRadius, Vividly, SupplyPike, Inmar. To stand apart, pitch the *books* (accrual settlement, learned per-retailer policy, traces), not portal scraping.

## Seats
Deductions Analyst and Trade/Revenue Accountant. The KAMs, Logistics, the AR Manager and the Controller stay human.

## Slide draft (Hyphenate format)
**A $400M snack brand.** The job: settle every retailer deduction each week and keep the trade accrual right. [4 retailers · 2 distributors] [8,000 deductions/yr]

| Card | Content |
|---|---|
| **Learns** `self-learning` | Reads 12 months of remittances, promo agreements, broker recap emails and past write-offs. Learned: • Kroger deducts promos 45–90 days after they end • Shortages under $150 were always written off |
| **Runs** `ai-automated` | Every Monday it matches each deduction to a promo, shipment or fine, then drafts the disputes and the accrual true-up. • ~160 deductions settled weekly • Disputes and journal entries drafted, never posted |
| **Escalates** `needs-review` | Walmart deducted $18,400 for promo #412. The signed calendar says the promo ended Mar 31; the broker's recap email says it ran two more weeks. Routed to the Walmart KAM. `confidence 38% · sources disagree`. • Holds that one deduction (the rest of the remittance clears) |
| **Improves** `new-policy` | KAM: "A broker recap wins if the buyer was cc'd. Otherwise the calendar wins." • Saved for every broker and retailer, email linked to promo #412 • Never asked again. ↻ *Next week: two extension claims settled on their own, recap cited* |

**Judged**
- **Real:** real Walmart M5 sales and price data and real X12 820 layouts, with the mess left in. • Promo IDs typed differently in EDI vs. portal exports • Answer key: every deduction labeled
- **Hireable:** Deductions Analyst + Trade Accountant. Drafts, never posts. • Asks the KAM, not the CFO • Every dollar traces to a promo line or shipment
- **New:** the money retailers quietly keep, not another invoice bot. • Learns how *this* team settles • Rules differ retailer by retailer
- **Wow:** catches one promo paid twice: Kroger took it off-invoice *and* the distributor (UNFI/KeHE) claimed a billback for the same stores and weeks. • Shows both claims side by side • Holds the second one and drafts the dispute

## Mechanics
- **Trust rules (which source wins):**
  - Promo terms: signed agreement > buyer-confirmed calendar > broker recap > KAM's memory.
  - Shortages: carrier POD + ASN > retailer receiving > remittance claim.
  - Price: the price file in effect on the ship date.
  - The engine computes every amount.
- **Rejections generalize:**
  - Example: the analyst rejects a $90 OTIF dispute and explains "below $150 it costs more than it recovers; book to OTIF expense, track by DC". That becomes rule R-044, scoped to Walmart OTIF.
  - The system then *proposes* extending the rule to Target at 62% confidence and asks once.
  - Rules that would break a hard control are refused (write-offs over $5k need the Controller).
- **Confidence scoring:**
  - Inputs: deterministic match features (invoice found, deal found, date in window, SKU eligible, POD clean, amount within tolerance), plus precedent count, source agreement, distance from a rule's scope, and the LLM's extraction confidence.
  - ≥90 is drafted automatically, 60–90 goes to batch review, and <60 goes to a named person with the reason.
- **Access control:**
  - A KAM sees only their own retailer. Cross-retailer price terms are sensitive (Robinson-Patman).
  - Logistics sees PODs, not trade rates.
  - KAMs can confirm facts but **can't approve write-offs**, because they're paid on net sales.
  - The AR Manager approves write-offs under $5k. The Controller approves anything larger, plus the journal entry.
  - Agents are scoped the same way: the email reader never sees the GL.
- **Git-like trace:**
  - Each resolution is a chain of commits: ingest 820 line → match invoice and deal@version → apply rule (rooted in a ruling commit) → draft JE → approval.
  - `blame R-031` shows the original example and who made the ruling.
  - Changing a rule replays history and shows which decisions would flip.
- **Formally verifiable:**
  - For each deduction: matched + disputed + written off = amount.
  - For each promo: opening + accrued − applied − released = closing, to the cent.
- **Architecture (4–5 agents + a deterministic engine):** Intake/Reader (LLM) · Matcher (deterministic) · Judge (JADE-like: rules, confidence, routing, turning rulings into rules) · Accrual/Drafter (rollforward, JE, dispute packets) · Auditor (invariants, segregation of duties, defends its decisions).
- **Data for realism:**
  - Kaggle M5 (Walmart store-SKU sales and prices)
  - dunnhumby Complete Journey / Breakfast at the Frat (promo calendars, shelf vs. base price)
  - Kaggle DataCo (scheduled vs. actual ship dates, for OTIF)
  - Stedi X12 820 guides (including Target's)
  - SupplyPike / SPS public deduction-code guides
  - EDGAR 10-Ks (Energizer, Reynolds) to size the allowance
- **Answer key:**
  - About 12 months of data, with 1,200–3,000 deductions.
  - About 15–18% invalid across 7 types, plus traps that are valid but look invalid.
  - Learn on months 1–6, score on months 7–12.
  - Metrics: precision and recall, $ recovered vs. the key, journal-entry correctness, the rollforward tying out to the cent, and repeat escalations after a ruling (target 0).
  - Judges can inject a deduction live.
- **Risks:**
  - Judges may not know the domain. Open on the double-dip, in plain words.
  - The space is crowded. Pitch the accounting and the learning.
  - The stats are soft. Cite them as ranges.
