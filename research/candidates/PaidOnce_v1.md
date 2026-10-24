# IDEA v1: Shortfall

All five judges picked Candidate A in panel round 1: the CEO, the CTO, the workshop engineer, the accounting consultant (CPA) and the buyer CFO. This version folds in all of their fixes.

## One sentence
**Every retailer deduction is settled against the promise it pays for, and the trade accrual (the number the auditor argues with) ties out to the cent every Monday.**

## Company and seats
- **Northbay Snacks**, a fictional US snack brand with $500M gross and $400M net. Its trade spend is about $100M.
  - Sells to Walmart, Kroger, Target and Costco, plus UNFI and KeHE distributors.
  - Carries about **$25M of trade accrual**, which a trade accountant rebuilds in a spreadsheet every month.
  - Its **Q4 true-up swung $1.8M** last year, and the auditors wrote up a significant deficiency.
- **Seats:** Deductions Analyst and Trade Accountant.
  - The KAMs confirm facts, the AR Manager approves write-offs under $5k, and the Controller approves JEs and anything larger.
  - "Drafts it, never posts it."
- **Demo world:** 12 months, about 8,000 deductions (about 154 a week), and 3 deduction types: promo, shortage and OTIF fine.
  - It's synthetic, with an answer key, using volumes and prices from Kaggle M5 Walmart data.
  - **We say so plainly: M5 is sales data and the deductions are planted.**

## What it does (two functions with one operational step between them)
1. **Trade accrual, estimate.** At each sale, accrue expected promo cost as ASC 606 variable consideration, at expected value and subject to the constraint: deal rate × shipped volume × the redemption rate learned from history.
   - Money the retailer will deduct goes to a **contra-AR allowance**.
   - Billbacks owed to distributors go to an **accrued liability**.
2. **Operational step.** Read each remittance (an 820 layout as CSV, or a portal export), match every deduction to its invoice, promo deal, POD and shipment, and then draft a dispute packet. It does not submit to retailer portals.
3. **Deduction settlement and accrual true-up.** Valid promo deductions relieve the allowance. Shortages and OTIF fines become **contra-revenue**, not opex or bad debt. Invalid ones are held, disputed, and reserved in an **allowance for invalid deductions**. Stale balances are released **only when the learned deduction-lag curve allows it**, and the release runs through revenue as a change in estimate.

## Learns → Runs → Escalates → Improves
- **Learns** (`self-learning`): reads 12 months of remittances, promo deals and past write-offs.
  - Learned: • Kroger deducts promos 45–90 days after they end • Walmart post-audits reach back about 2 years
  - It also learns redemption rates per retailer and promo type.
- **Runs** (`ai-automated`): every Monday it matches each deduction, drafts the disputes, and drafts the accrual true-up.
  - • ~150 deductions settled each week • True-up JE ready Tuesday, drafted and not posted
- **Escalates** (`needs-review`):
  - The case: Walmart took $18,400 for promo #412. The signed deal ended Mar 31, but the Walmart buyer's email added two weeks.
  - **No learned rule covers an emailed extension.** That's why confidence is low; the trust order doesn't settle it.
  - Routed to the **Walmart KAM**, `confidence 36% · sources disagree`. • Holds that one deduction (the rest of the remittance clears)
- **Improves** (`new-policy`): the KAM rules, "A buyer's written extension stands."
  - • Saved as policy **for Walmart**, with the email linked to #412 • True-up of +1,500 cases = +$3,000 accrued • Never asked again
  - ↻ *Next Monday: two Walmart extensions settled on their own, buyer email cited.* Kroger's first emailed extension is **asked again**, this time to the **Kroger KAM**. The scope stops at Walmart, because a KAM can only see and rule for their own retailer.
- **Rejection → rule → generalization:**
  - The Controller rejects a proposed $5,000 release on Kroger #388: "Don't release Kroger promos before 120 days. They post-audit."
  - That becomes rule R-07, scoped to Kroger releases.
  - Shortfall then **proposes** applying it to Walmart (whose lag curve has a longer tail) and asks once.
  - Widening a rule follows a fixed ladder: this retailer and type → all retailers for this type → all types. Each step needs a separate yes.

## The moment (the video opens on it, 20 seconds, plain words)
| Time | On screen |
|---|---|
| 0–4s | "Northbay promised Kroger **$20,000** to fund a discount on promo #509." Reserve bar: **$20,000 set aside**. |
| 4–8s | Kroger pays an invoice **$18,400 short**: "promo #509". The bar drops to **$1,600**. Green: settled, JE drafted. |
| 8–12s | Three months later, **KeHE bills back $18,400 for the same promo**. The bar tries to go to **−$16,800** and turns red: *"We'd be paying for one discount twice."* |
| 12–16s | Both claims side by side: **the same 41 stores, the same two weeks.** It holds the second claim and drafts the dispute. `confidence 93% · same stores, same weeks` |
| 16–20s | "Paid once. Disputed once. Books tie to the cent." Click the trace: claim → promo agreement line → the rule and ruling applied. |

Why this is ours and not a deduction vendor's: **the ledger catches it.** A uniqueness invariant allows at most one paid claim per promo × store × week × SKU across direct and distributor channels. No deduction tool looks at the retailer and the distributor together.

## The accounting it gets right (what the CPA checked)
| Event | Entry |
|---|---|
| Sale (Walmart #412: $2/case × 10,000 cases at $20) | Dr AR–Walmart 200,000 / Cr Gross Sales 200,000; accrual: Dr Trade Promotion (contra-revenue) 20,000 / Cr Trade Allowance (contra-AR) 20,000 |
| Remittance with deductions | Dr Cash 175,000 + Dr Deductions Receivable 25,000 / Cr AR 200,000 |
| Valid promo deduction matched | Dr Trade Allowance 18,400 / Cr Deductions Receivable 18,400 |
| Shortage confirmed / OTIF fine accepted | Dr Sales Returns or OTIF Penalties (**contra-revenue**) / Cr Deductions Receivable |
| Invalid pricing deduction disputed, reserved at 40% | Dr Deduction Concessions (contra-revenue) 1,600 / Cr Allowance–Invalid Deductions 1,600, then recovered or written off |
| Release of Kroger #388 after the lag curve | Dr Trade Allowance 5,000 / Cr Trade Promotion 5,000 (change in estimate, through revenue) |
| True-up from the KAM ruling | Dr Trade Promotion 3,000 / Cr Trade Allowance 3,000 |
| Double-dip (KeHE billback) | Dr Deductions Receivable 18,400 / Cr AR–KeHE 18,400. **No relief of the allowance**; the claim is held, disputed and reserved |

**Invariants (formally verifiable; checked on every commit):**
1. **Remittance tie:** cash + deductions = invoices closed.
2. **Each deduction:** amount = applied + contra-revenue + recovered + written off + open. Exactly one final state per deduction.
3. **Promo rollforward:** opening + accrued ± true-up − applied − released = closing, to the cent. A negative closing balance means overspend, which raises an exception.
4. **Subledger = GL** for deductions receivable, the trade allowance, accrued trade, and the invalid allowance.
5. **Uniqueness:** at most one paid claim per promo × store × week × SKU across all channels.
6. **Lookback:** prior-period accrual vs. actual settlement, per promo. This is the auditor's retrospective test.
7. **Controls:** every JE balances, preparer ≠ approver, closed periods are locked (late changes become current-period reversing entries), and every line cites its source and rule.

## How it works (the CTO's blueprint, kept simple)
- **3 agents around 1 deterministic engine:**
  - **Reader (LLM):** turns emails, deal PDFs and free-text reason codes into facts. Every fact must quote its source span verbatim, string-checked, or it's discarded. Its only tool is `emit_fact`, so text in an email can't trigger any other action (this is how prompt injection is neutralized).
  - **Judge (JADE-like):** deterministic matching, rules and confidence. The LLM only drafts proposed rules from a human's explanation.
  - **Drafter (LLM):** dispute packets, JE narratives, and answers when someone asks "why?".
  - **Engine (deterministic):** matching, amounts, rollforward, journal entries, invariants, segregation-of-duties checks, routing, replay.
- **Data:** 6 append-only SQLite tables: `source`, `fact`, `rule@version`, `ruling`, `decision`, `journal_line`. The subledger is computed from the journal lines.
- **Confidence:**
  - A logistic model over deterministic features: invoice found, deal found, date in window, SKU eligible, POD clean, amount within tolerance, sources agree, number of precedents, distance from rule scope.
  - **Calibrated on months 1–6.**
  - Caps: no precedent → ≤60; sources disagree → ≤50.
  - We show a **reliability diagram** on months 7–12, so "36%" means cases like this were right about 36% of the time.
  - Thresholds: ≥90 drafts automatically, 60–90 goes to batch review, <60 goes to a named person.
- **Rulings become rules:**
  - The LLM proposes a predicate in a small DSL, with the narrowest scope that fits the literal features of the case.
  - The engine checks that the rule compiles, reproduces the original decision, and touches no hard control.
  - It replays the rule against history ("flips 7 past decisions; 1 contradicts R-019"), and a human confirms.
  - If two rulings overlap with opposite actions, the more senior author decides. The last write never wins silently.
- **Authority:** a rule's author must have at least the authority the rule automates.
  - A KAM can rule on **facts**, such as a promo's dates, but **can't author write-off rules**. KAMs are paid on net sales.
  - This stops rules from being used to launder approvals.
- **Git-like trace:**
  - Every decision is a commit: content hash of input facts + rule@version + engine version + outputs + parent.
  - **`blame`** on any JE line walks back: line → decision → rule → ruling (who, when, verbatim explanation) → source span.
  - **`revert`** a rule: replay every decision that cited it. Open periods are re-drafted; closed periods get reversing entries in the current period.
- **Access, for people and agents alike:**
  - Every query goes through one broker that filters facts by ACL tag. An LLM's context is built only from facts it's allowed to see.
  - KAMs see only their own retailer (confidentiality clauses, and antitrust caution about sharing information).
  - Logistics sees PODs but not rates. The Reader never sees the GL.
  - Escalation packets are redacted to the recipient's scope.
  - SOC 2-style audit logging is the floor.

## Proof it works
- **Learn on months 1–6, score on months 7–12.** The planted errors and answer key are written by a teammate who doesn't touch the Judge.
- **Planted errors:**
  - double-dips
  - expired promos
  - wrong rates
  - shortages where the POD is clean
  - duplicate deductions with a different reference number
  - promo IDs typed three ways
  - an injected instruction in a broker email
  - traps: deductions that are valid but look invalid
- **First-slide number:** *"On months it never saw: X% settled straight-through, $Y of double-paid and invalid deductions caught, 0 repeat questions after a ruling, and the accrual ties to the cent."*
- Also reported:
  - the reliability diagram
  - **accrual lookback error vs. the "last year's %" baseline**, i.e. how much smaller the Q4 true-up would be
  - a plain-LLM baseline run 3 times (variance)
  - SoD attempts blocked
- **Real vs. simulated:**
  - **Real:** M5 volumes and prices, the 820 layout, the ledger, the engine, and the eval.
  - **Simulated:** deductions, emails, PODs, and the people. The KAM and Controller are LLM personas, and a human can take over.

## The CFO pitch
"You carry $25M of trade accrual that's rebuilt in a spreadsheet every month, and last year's $1.8M Q4 swing is what your auditors wrote up. Shortfall keeps that accrual tied out per promotion every week, with evidence your auditor can click. It also catches the retailer-plus-distributor double payments that no deduction tool sees. Your KAM sees only the one claim where the sources disagree, answers it once, and is never asked twice."
(The ROI story: about $1M a year recovered from double payments and invalid write-offs, two analyst seats freed up instead of a third hire, and a Q4 swing under $300K. All are illustrative ranges.)

## Positioning against Glimpse, HighRadius, Vividly and SupplyPike
- They recover money. **We close the books.** We run on top of the ERP and alongside Glimpse, with no rip-out.
- Never pitch portal scraping, dispute win rates, or "$ recovered" as the headline.

## Cut
- Submitting to retailer portals.
- Real X12 parsing (use CSV in the 820 layout).
- Broad generalization UIs.
- Pricing and compliance deduction types, beyond one planted pricing error.
- dunnhumby and DataCo data.
- Soft industry statistics, except a single line: "1–3% of gross sales by most estimates."
