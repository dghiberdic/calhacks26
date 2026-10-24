# Consigned Components: autonomous supplier accounting

Research proposal for the Hyphenate CalHacks track. Updated October 24, 2026.

## Three-sentence pitch

Manufacturers can hold thousands of supplier-owned components without owning them or owing payment for all of them. Our system fills the inventory accountant and supplier accountant seats: it determines when ownership and liability arise, prepares the accounting and settlement work, and brings the right person in when an agreement or exception requires judgment. Each authorized explanation becomes a scoped, versioned decision that the system can reuse, with every amount traceable to its evidence and approval.

## The problem the track asks us to solve

The official brief asks for an autonomous system a company could employ in a small finance function: recurring work across neighboring roles, company history, conflicting sources, human collaboration, limited authority and decisions that remain explainable. A live demonstration must distinguish real from simulated elements and may be challenged with a new scenario. Benchmarks are optional evidence, not prescribed passing thresholds. [Official Hyphenate brief](https://docs.google.com/document/d/1u4iN8R97ILY3kfHTPKC82zdutHrGx4ze5eCAP-J92w4/edit).

Workshop takeaways relayed in team notes sharpen that direction: build company context; automate a function rather than a single check; determine which agreement governs; ask the appropriate human; and retain the reasoning behind the answer so the same question need not recur. Clean, consistent records can still leave the governing business decision unresolved. These are informal workshop takeaways, not additional eligibility rules. A $100M business example, a roughly 2% escalation figure and compliance references do not create requirements absent from the official brief.

The central engineering question is: **Can an accounting function become more autonomous through authorized human decisions while preserving the conditions and limits of those decisions?**

## Why consigned components are a credible setting

Consigned inventory can be physically held by a manufacturer while remaining owned by its supplier. Consumption can trigger ownership transfer and settlement. Oracle also describes configurable rules determining whether movements between locations count as consumption. These are established business and ERP workflows. [Oracle: consigned inventory](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/famml/consigned-inventory.html), [Oracle: consumption rules](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/faims/consigned-inventory-consumption.html).

That creates an accounting problem even when quantities are accurate. A warehouse can report 1,000 components on site, production can report 200 consumed, and a supplier statement can list 1,000 delivered. Each may be correct. The accounting function must establish what the agreement makes the company responsible for, which events change that responsibility, and which entries and settlement documents follow.

Ordinary invoice matching and receipt accruals already exist in major systems. The proposal therefore needs to demonstrate company-specific decision handling, continuity and correct recovery around an ongoing function. [Microsoft: invoice matching](https://learn.microsoft.com/en-us/dynamics365/finance/accounts-payable/accounts-payable-invoice-matching), [Oracle: receipt accruals and reversals](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/fapma/receipt-accounting-for-purchase-orders-set-to-accrue-at-period.html).

## The company and the jobs

Use a fictional electronics contract manufacturer with multiple warehouses, suppliers and agreement versions. Enterprise-scale complexity is a scenario choice; financial and operational records are simulated.

| Role | Responsibility | Authority boundary |
|---|---|---|
| Inventory accountant | Maintain supplier-owned versus company-owned stock, interpret approved consumption mappings, prepare cost and liability effects. | Cannot approve its own exceptional journal or change a supplier agreement. |
| Supplier accountant | Reconcile consumption advice, supplier statements, invoices and credits; prepare settlement recommendations. | Cannot release payments or override unresolved ownership decisions. |
| Warehouse or production manager | Confirm where components moved and how they were used. | Supplies operational evidence; cannot approve financial policy merely by replying. |
| Procurement owner | Verify the applicable agreement or authorized amendment; seek supplier clarification when needed. | Cannot unilaterally alter a bilateral contract through an internal message. |
| Controller | Approve exceptional accounting treatment and journal proposals within defined authority. | Preparation and approval remain separate. |

The business function is supplier accounting for consigned components. Receiving events, usage reports, invoices and period close trigger work automatically. The same case persists through questions, approvals, corrections and settlement preparation.

## The demonstration across three periods

All amounts and treatments below belong to an explicit simulated agreement and accounting policy. They are fixture assumptions, not general accounting advice.

### March: establish ownership and the obligation

- Receive 1,000 supplier-owned components at a fixed fixture price of $10 each.
- The agreement makes issue to production the ownership-transfer event. Mere physical receipt does not trigger the simulated owned-inventory asset or payable liability.
- Production consumes 200 components. The inventory accountant prepares $2,000 of work-in-progress cost and the associated liability under the fixture policy.
- The supplier accountant reconciles the consumption advice and prepares the appropriate invoice or accrual handling. A later invoice must not recognize that cost twice.
- The interface explains why 1,000 received is consistent with only 200 becoming company-owned through consumption.

### April: encounter a new agreement condition

- A verified amendment effective April 1 treats release to a designated production-staging location as consumption. An existing warehouse event mapping does not yet encode that condition.
- A transfer of 100 components reaches that location. The agent identifies the unresolved mapping rather than guessing or treating every transfer as consumption.
- Procurement verifies the amendment and its applicability. The controller approves the corresponding accounting treatment; a missing supplier agreement cannot be replaced by internal approval alone.
- The system preserves the explanation, scope, effective date and approving authority, then prepares the $1,000 effect and completes the relevant handoff.
- A rejected proposal must remain rejected until corrected and appropriately approved. March's locked records retain their historical policy version.

### May: prove learning and its limits

- An equivalent release under the same agreement uses the approved mapping without asking the same interpretive question again. Normal transaction approval controls still apply.
- An ordinary warehouse-to-warehouse transfer does not qualify merely because it resembles the prior movement.
- A different supplier or changed agreement triggers a new evaluation and, if necessary, a new question.
- Re-delivering an event or uploading an invoice twice must not duplicate liability or settlement work.

The memorable moment is visible judgment: correct records initially appear inconsistent; the agent explains the governing agreement, obtains a missing authorized decision, reuses it later and rejects an invalid generalization.

## Agent infrastructure underneath the function

1. **Persistent case state:** obligations, unresolved questions, handoffs and proposed accounting effects survive restarts and period changes.
2. **Evidence with defined meaning:** receiving proves possession; usage reports describe consumption events; agreements govern obligations; approvals authorize defined actions. Avoid a universal source-ranking rule that ignores the question being answered.
3. **Scoped decision records:** agreement and version, supplier/entity, item or location scope, event conditions, effective dates, rationale, examples, counterexamples, author and authority.
4. **Governed learning:** propose a rule from an explanation, verify the person's authority, test its scope and preserve the approved version. A human message alone does not become universal policy.
5. **Controlled accounting effects:** deterministic money calculations, balanced entries, previews, separate approval and safe retries. Balanced entries alone do not prove correct treatment.
6. **Auditable continuity:** reconstruct the evidence and policy applicable at the time, plus the reason for any later correction.

An LLM can extract and organize evidence, identify missing context, formulate questions and explain outcomes. Calculations and permission checks should remain inspectable and reproducible. Model confidence alone must not grant authority to post or pay.

## Minimum interface

- **Work queue:** new events, open obligations, pending questions and blocked proposals.
- **Case view:** evidence, relevant agreement, current decision and proposed accounting effect.
- **Human desk:** precise question, appropriate responder, explanation and approval or rejection.
- **Decision memory:** the approved rule, scope, effective dates and matched precedent.
- **Books and proof:** ownership/liability reconciliation, journal preview, history and expected-versus-actual results.

## Evaluation and judging

Build a planted dataset and independent answer key before running the agent. Include ordinary receipts, usage, staging releases, unrelated transfers, different suppliers, amendment boundaries, missing authority, rejected proposals, delayed invoices and duplicate events.

Measure:

- Correct ownership, cost, liability and accounting period for each case.
- Appropriate escalation and responder selection.
- Redundant questions after an approved interpretation.
- False generalizations to cases outside the rule's scope.
- Unauthorized actions blocked and duplicate effects prevented.
- Correct recovery when the judge changes an agreement or introduces new evidence.
- Evidence coverage for each amount and decision.

Compare against a baseline with the same documents, ordinary matching and human approval. Demonstrate whether the added decision memory and case continuity improve outcomes; do not assume they do.

| Judging criterion | Evidence to show |
|---|---|
| Real enough | A coherent simulated company and agreements, realistic events, explicit answer key and clear disclosure of simulation. |
| Would you hire it? | Two defined accounting seats, completed handoffs, permissions, rejection handling and a clean decision record. |
| Something new | A specific company problem and demonstrated approach to governed learning; no unsupported worldwide-first claim. |
| The moment | Correct reuse of an approved decision followed by a counterexample that makes it stop and reconsider. |

## Research evidence and limits

AccountingBench illustrates how unresolved errors can propagate through successive closes. Its results concern one real SaaS company and older models, so they support the importance of continuity without establishing present-day performance across the industry. [Penrose AccountingBench](https://accounting.penrose.com/).

APEX-Accounting reports errors in accounting and authorization reasoning after relevant evidence was retrieved. Its tasks exclude human clarification, so it cannot validate the entire interactive workflow proposed here. Use its public development materials as inspiration, not a mandatory hackathon threshold. [APEX-Accounting, sections 5–6](https://arxiv.org/html/2607.27189v1).

Hyphenate already markets shared business context, policy learning, human judgment and controlled execution. Oracle already supports consignment accounting. The research establishes a credible, difficult demonstration domain; it does not establish that Hyphenate or competitors lack the underlying capability. Differentiation must be demonstrated through the specific workflow, behavior and proof. [Hyphenate platform](https://hyphenate.ai/platform).

This document specifies a proposed build and evaluation. It does not claim that the system has been implemented, tested, certified or connected to live supplier or payment systems.
