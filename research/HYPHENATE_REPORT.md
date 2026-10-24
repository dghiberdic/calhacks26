# Hyphenate: what the company actually does, and what that means for our build

Sources (fetched 2026-10-23): hyphenate.ai (home, platform, O2C, P2P, treasury, controller, about), the CEO's essay "What We Mean by Autonomous Finance" (Aug 13 2026), the HiBid and Kiteworks case studies, and TechCrunch's launch article (Sep 29 2025).

> **Corrections from the workshop (2026-10-23, supersede anything below):**
> - **Target companies:** $100M+ revenue (not $50M+).
> - **"Drafts it, never runs it":** run the routine work, **hold only the exception**, and let a human approve money movement. §6's "makes the payment" overstates this.
> - **Every escalation shows a confidence %** plus a reason (`no precedent` / `sources disagree`), and is routed to the *specific* right person (e.g. the store manager, not HQ).
> - **Rejections are learning signals:** a rejection comes with an explanation, which becomes a rule (and may generalize). A ruling is saved as policy and **never asked again**.
> - **Git-like traceability:** every rule is rooted in a precedent or explicit guidance. Accounting is formally verifiable. JADE = their internal "judgement and decision engine" (not public).
> - **Access limits:** limited data access for people *and* agents. SOC 2 is the bare minimum.
> - **Scope:** one function, or two composed with an operational step between them. Single-digit agents at most. Pitch to the CFO. Only complex processes ("Stripe already does it for some").
> - **Mini Melts** is expanding into treasury and lease management. Customers average 6 modules.
> - See `sources/workshop_photos/TRANSCRIPT.md` for their exact pitch format.

## 1. In one paragraph
Hyphenate (formerly **Maximor**, renamed Oct 2026) sells **AI agents that do the accounting work of a company's finance team**. They don't replace the accounting system; they sit on top of it (NetSuite, SAP, Intacct, QuickBooks…). The agents read the company's data, contracts and past decisions, work out the company's unwritten rules, and then **do the work themselves**: book entries, reconcile accounts, recognize revenue, apply cash, run the month-end close. When they're unsure they ask a human, **and remember the answer**. Every action carries its own evidence, so an auditor can trace it.

## 2. Company facts
- **Founders:**
  - **Ramnandan Krishnamurthy (CEO)** was a founding member of Microsoft's digital-transformation group, leading finance and data projects for Fortune 500 clients such as Coca-Cola.
  - **Ajay Krishna Amudan (CTO)** rebuilt Microsoft's internal revenue systems.
  - They've worked together for 14 years, since IIT-Madras.
- **Size:** about 18 people at launch, in New York plus Bengaluru. They're hiring engineers, accountants and a new-grad generalist in NYC. Their careers page says: *"If you have closed the books at two in the morning, we especially want to hear from you."*
- **Money:** $9M seed in Sep 2025 (Foundation Capital lead). Angels include CFOs from Ramp, Gusto, MongoDB and Zuora, Big Four partners, Aravind Srinivas (Perplexity) and Tien Tzuo (Zuora). They claim 35x revenue growth in 9 months and later 86x.
- **Target customer:** **mid-market companies with $100M+ revenue (per the workshop; launch press said $50M+)**, US/IFRS, often multi-entity. They also offer human accountants as an optional review layer, or a full service for companies with no finance team.

## 3. Customers (what they've actually shipped)
| Customer | What it is | What Hyphenate does there | Result |
|---|---|---|---|
| **HiBid** | Auction marketplace, $2.5B GMV, 4 revenue streams / 50+ sub-streams | Revenue recognition + cash reconciliation from the data warehouse, billing engine and payment processors | Close went from 3 weeks to 5 days. **The CFO had tried Claude Code / Codex first; they "couldn't consistently produce controlled, accurate, auditable data."** Next: "extend agents from cash *inflows* into cash *outflows*" (accruals, prepaids, fixed assets) |
| **Kiteworks** | Cybersecurity company, 10 legal entities, 7 currencies, 66 accounts, 20+ banks | Treasury and cash: match, classify, reconcile and post bank activity, intercompany, daily cash position | 98% straight-through processing; cash team went from 20 accountants to 5; live in under 4 weeks |
| **Mini Melts USA** | **Consumer-goods / food distributor on SAP** | Orders, sales triage, invoicing and refunds end to end; "catch errors at entry, surface unbilled invoices" | 16,640 hours saved per year |
| **Dura Software** | Software holding company | Close | 7 days faster close; 70% less back-office headcount and consulting |
| **Rently** | Proptech | Close | Close went from 8 days to 4; 2 hires avoided |

## 4. The product (five modules on one shared "context layer")
| Module | What it does |
|---|---|
| **Order-to-Cash** | Reads contracts from the CRM, does ASC 606 revenue recognition (performance obligations, SSP, waterfalls), sends invoices, runs an AI collections agent, applies cash |
| **Treasury / Cash** | Pulls every bank, entity and currency feed; matches each bank line to bills and invoices; produces a daily bank reconciliation and a rolling 13-week forecast. **"Every suggestion carries a confidence score and its evidence, and nothing posts to the ERP without a click."** |
| **Procure-to-Pay** | Reads bills in any format and codes them to GL, class and entity; handles multi-line allocations; matches to POs; **proposes accruals with the entry previewed**; ages open items; configurable approvals; tracks bills from receipt to disbursement. **Note:** the site says "pay when ready", and payment *execution and payment controls* are barely described. |
| **GL accounting / Close** (controller page) | Subledgers (prepaids, fixed assets, ASC 842 leases, R&D capitalization), accruals from history, open POs and budget, intercompany eliminations, reconciliations with workpapers, flux commentary "in your team's voice", **controls monitoring** (manual entries tracked by who posted them; "material variances hold the books open"; period lock-down) |
| **Reporting** | One ledger mapped to any chart of accounts, board decks, plain-language Q&A where every number traces back to its source entry |

How it's built ("5 layers"):
1. All data in one feed: ERP, surrounding systems, *and the unstructured stuff* (email, spreadsheets).
2. **The finance function mapped:** "your policies, derived from the evidence your finance function already leaves behind… your accounting logic, not generic rules."
3. Agents run the work continuously.
4. "**Deterministic, explainable, auditable.** Every figure traces back to its source."
5. It gets smarter with every close and every exception.

Agents **prepare** and humans **review**. The controller page says: *"It proposes. You approve."*

## 5. Their worldview (from the CEO's essay; this is what the judges believe)
- **"Human runtime."** "Every finance team on earth runs on a policy that is written down nowhere." It lives in the controller's head, in an inbox, in `FINAL_v7_USE_THIS.xlsx`. "ERPs record the outcomes of those judgments faithfully. They have never once captured the judgment itself."
- **Do the work, don't flag it.** "Software that stops one step short of doing the work isn't automation. It's homework." *No dashboards that tell a human what's wrong.*
- **Learn, ask, remember.** "Where nothing was ever written down, it asks why… When it's confident, it acts. When it isn't, it escalates, and remembers the answer, so it never asks twice."
- **Evidence on every action.** "Every action it takes carries its own evidence: what it did, why, and based on what."
- **The 1% is the product.** "Intelligence is becoming cheap. Accountability is not… The 99% that runs autonomously is table stakes. Our product is built around the remaining 1%: **knowing when to stop, what to escalate, whom to bring in, and how to show your work.**"
- **Autonomous ≠ automated.** "Automated is a script… breaks the moment anything changes. Autonomous means the system carries the judgment… and knows the boundary of its own confidence."
- **Cross-silo.** Their own example: *"A consumer-goods distributor… cares about one number: how fast a dollar comes back after it goes out. That number lives across payables, receivables, inventory, and cash at once, four things the industry decided decades ago to sell as separate products. Autonomous finance runs them as one."*
- **Tempo.** "Why are **payment terms set at signing and never touched again?** Why does every budget get exactly four looks per year? …bookkeeping couldn't keep up."
- **Trust.** Error and fraud rates are "priced in… discovered at year-end, if at all", because auditors only sample. "When agents do the work, **every single entry is examined**."

## 6. What this means for what to build
**They will reward:**
1. **Unwritten policy learned from precedent.** The system reads past decisions or exceptions, infers the rule, asks "why?" where it's ambiguous, and **never asks the same question twice**. Show the second occurrence being handled on its own, citing the first answer.
2. **Doing, not flagging.** It posts the entry, makes the payment, issues the fix, *then* shows evidence. A dashboard of red flags is "homework."
3. **The 1%: knowing when to stop.** A visible confidence boundary. Show the case it escalates *and why*, and that it brings in the *right* person, not just "a human."
4. **Evidence on every action**, plus deterministic numbers. Their own customer found plain Claude Code / Codex unreliable for this, so "the LLM decides" will lose; "the LLM reads and explains, the engine computes" wins.
5. **Crossing silos.** AP + inventory + AR + cash treated as one problem. The CEO literally wrote this about a distributor.
6. **Something outside their current product.** They're strong on O2C, cash and close for SaaS-like mid-market companies, and thinner on **payment execution and controls** and on **physical-goods businesses**. HiBid's "next step" is cash outflows.

**What will look like their own product (so not "new"):** bill capture and coding, PO matching, accrual proposals, bank reconciliation, ASC 606 waterfalls, flux commentary. Do any of these only as plumbing, never as the headline.

## 7. The single most valuable addition (whatever we build)
**"Ask once, remember forever," shown live:**
1. Exception #1 arrives (e.g. a supplier invoice 4% above the quoted price). There's no rule, so the system asks the Controller **one precise question**, with the evidence attached.
2. The Controller answers in plain English: "accept up to 5% over quote for freight on orders under $2k."
3. The system turns that answer into a **scoped, versioned rule**, shows it, and the Controller confirms it.
4. Exception #2 arrives later. It's handled **with no human involved**, and the decision cites "Rule R-14, from Controller ruling on Oct 3."
5. Exception #3 is *outside* the rule's scope (a $9k order, outside the rule). The system **asks again** instead of over-generalizing.

That sequence is their pitch deck happening live, in a world they haven't seen, and judges will recognize it immediately.

## 8. Lines that will land at their booth (in their own vocabulary)
- "It proposes, the controller approves, and it never asks the same question twice."
- "The LLM reads and explains; a deterministic engine computes every number. Every action carries its evidence."
- "We built for the 1%: knowing when to stop and whom to bring in."

**Avoid:** dashboards of flags ("homework"), "the AI decides", "replaces the finance team" (their line is *people get to do finance*), and any claim that it replaces the ERP.
