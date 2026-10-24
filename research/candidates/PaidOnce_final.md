# PaidOnce

**What we're building:** the trade-settlement seat at a $400M snack brand. Every Monday it settles each retailer deduction against the promo deal it pays for, and keeps the trade accrual (the number auditors argue with) tied to the GL. It asks a person only when sources disagree, asks the right person, and never asks twice.

**Seats:** Deductions Analyst + Trade Accountant at Northbay Snacks. Account managers confirm deal facts. The AR Manager and Controller approve. *It drafts, never posts.*

---

### `example · the-business`
## A snack brand.
**The job: settle every retailer deduction against its promo, each Monday.** `[6 retailers & distributors]` `[8,000 deductions a year]`

| **Learns.** `self-learning` | **Runs.** `ai-automated` | **Escalates.** `needs-review` | **Improves.** `new-policy` |
|---|---|---|---|
| Reads a year of remittances and promo deals to learn how each retailer deducts. **Learned** • Kroger deducts 45–90 days after a promo • Walmart audits back two years | Every Monday, settles each deduction and drafts the accrual true-up. • ~150 deductions settled a week • True-up draft ready Tuesday | Promo #412's deal ends March 31. The Walmart buyer's email says April 14. **(WM)** Routed to the Walmart account manager. `confidence 36% · sources disagree` • Holds that one $3,000 | Account manager: "The buyer's written extension stands." • Saved as policy for Walmart • Email linked to the deal • Never asked again |

↻ *Next Monday: two extensions settled, buyer email cited.*

### `example · judged`
## The snack brand, judged.
**Its deductions, against the four questions.**

| **Real.** `real-enough` | **Hireable.** `would-you-hire-it` | **New.** `something-new` | **Wow.** `wow-moment` |
|---|---|---|---|
| Real remittance layouts and Walmart sales data, deductions planted, mess left in. • Promo IDs typed three ways • Answer key: every deduction labeled | One role: trade settlement. Drafts it, never posts it. • Asks the account manager, not the CFO • Every dollar traces to a promo line | The money retailers quietly keep, not another invoice bot. • The accrual auditors flag, tied every week • Rules that differ retailer to retailer | Catches one promo paid twice, to Kroger and its wholesaler. • Shows both claims, same 41 stores • Holds the second until fixed |

---

## The moment (the video opens here, 20s)
| Time | On screen |
|---|---|
| 0–4s | "Northbay promised Kroger **$20,000** to put its chips on sale." Bar: **$20,000 set aside.** |
| 4–8s | "Kroger took the $20,000 off its next payment." Bar → **$0**. Green: *settled*. |
| 8–13s | "Some Kroger stores get chips through a wholesaler, KeHE. Three months later KeHE bills **$20,000, same sale.**" Bar → **−$20,000**, red: *"Paying for one sale twice."* |
| 13–17s | Both claims side by side, overlap highlighted: **same 41 stores, same 2 weeks.** The deal funds Kroger directly, so KeHE's claim is held and a dispute is drafted. `confidence 93% · same stores, same weeks` |
| 17–20s | **"Paid once. Second claim disputed."** Click to see the trace: claim → the $20,000 line in the deal → the rule that held it. |

## How it works (simple enough to see)
- **2 AI roles + 1 engine.**
  - **Reader:** turns messy emails, deals and remittances into facts. Every fact quotes its source.
  - **Drafter:** writes disputes, journal entries, and the answer to "why?".
  - **Deterministic engine:** does all matching, math, rules, routing and the ledger. *The LLM reads the mess; it never does the math.*
- **Trust order:** signed deal > buyer's written amendment > remittance reason code > account manager's memory. When a human picks the winner, that becomes a scoped, versioned rule.
- **Confidence** comes from match evidence (deal found, dates, stores, amount, precedent), calibrated on past months.
- **Rejections teach.** The Controller rejects an early release and says why: "Kroger post-audits; wait 120 days." That becomes a rule. PaidOnce then *proposes* it for Walmart and asks once.
- **Git-like trace.** Every decision is a commit. `blame` any dollar back to the deal line, the rule, and who ruled. Revert a rule and replay what flips. Closed periods stay locked.
- **Right person, limited access.** An account manager sees only their own retailer and can rule on facts, never on write-offs. Agents see only what their role allows. SOC 2-style controls are the floor.
- **The judge's desk.** Paste your own deduction or email, make a ruling, then hit *Run next Monday* and watch the same case settle with no question.

## Proof it works
- Learns on months 1–6, scored on months 7–12.
- Planted errors (double-dips, expired promos, wrong rates, duplicates, injected emails) come with an answer key written by a teammate who doesn't touch the engine.
- **First slide:** *"On months it never saw: X% settled straight-through, $Y paid-twice caught, 0 repeat questions, subledger = GL to the cent."*
- **Real:** remittance layouts, Walmart (M5) volumes, the ledger and the eval. **Simulated:** deductions, emails and people (LLM personas; a human can take over).

## The CFO pitch
"Your $25M trade accrual runs on a policy written down nowhere: one accountant's spreadsheet and three account managers' inboxes. That human runtime is why Q4 swung $1.8M and your auditors wrote it up. PaidOnce runs that policy every Monday. It settles each deduction against the promise it pays for, ties the accrual to the GL with a trace your auditor can click, and stops you paying Kroger and its wholesaler for the same discount. It brings in a person only for the 1% where the deal and the email disagree, asks the one person who knows, and never asks twice."

*Who doesn't need it:* a brand selling to one retailer with no wholesalers. Their ERP and a spreadsheet are fine.

## Scope
- **Build:** Walmart, Kroger and KeHE. Promo deductions only. The double-dip, the ask-once loop, `blame`/replay, the accrual tie-out, the CFO screen, and the judge's desk.
- **Cut:** shortages and fines, portal submission, real EDI parsing (we use CSV in the real 820 layout), and fancy generalization.

*Details (journal entries, invariants, data model, live-injection fixes): `research/candidates/PaidOnce_details.md`.*
