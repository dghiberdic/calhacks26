# Candidate B: physician productivity pay (wRVU comp) at a hospital system's medical group

## Function
Each month, close every provider's productivity pay:
1. Price posted charges in wRVUs using each provider's own contract terms.
2. Net out draws.
3. Draft the incentive accrual and the payroll file.

This is the closest real-world version of Hyphenate's coffee-chain tip-pool pattern. Many people get paid from messy operational data, the rules differ by contract, and one role drafts it and never runs it.

## Why it's real
- **Scale.** About 75% of organizations use individual productivity in incentives (SullivanCotter), and the average incentive bonus is about $49K (Medscape). A 300-physician group pays out about $15M a year in variable comp.
- **Errors are expensive:**
  - Stark Law is strict liability. Mercy Springfield settled for $34M, and Community Health Network for $345M.
  - At Wheaton Franciscan, a retroactive comp change was ruled a breach of the physicians' contracts.
- **The rate table moves.** The 2021 CMS changes raised established office-visit wRVUs by 28–46%, and contracts name a specific table year.
- **Who does it today:** a physician comp analyst plus payroll. The comp admin and the department chair approve, and compliance checks fair market value (FMV). It runs on spreadsheets.

## Slide draft
**Cascade Health Partners ($1.4B system).** The job: close every provider's productivity pay each month. [14 clinics] [310 providers]

| Card | Content |
|---|---|
| **Learns** | Reads 12 months of charge exports, contracts and payroll runs. Learned: • $/wRVU by contract tier • co-surgeons split credit 50/50 |
| **Runs** | On close day 2, prices every posted charge, nets out draws, and drafts the accrual and payroll. • 310 incentive lines across 14 clinics • accrual ready on day 3 |
| **Escalates** | Dr. Okafor's contract pays on 2020 wRVU values, but the billing feed priced her 99214s at 2024 values. Routed to the compensation administrator. `confidence 44% · contract vs. rate table` • Holds that one physician's bonus |
| **Improves** | Comp admin: "Legacy contracts pay on the table named in the contract until renewal." • Applied to all 23 contracts with that clause • Never asked again |

**Wow:** catches a knee replacement credited 100% to *both* co-surgeons.

**Time:** a claim paid in March and denied in June becomes a clawback against the next draw, and is booked as a receivable.

## Mechanics
- **Trust rules:**
  - Posted billing charges (after voids and denials) beat the EHR.
  - Signed contract > amendment > email. An email never overrides the contract without a ruling.
  - Use the rate table the contract names.
  - FTE comes from HR, and paid amounts from the payroll register.
  - Anything over the FMV cap goes straight to compliance.
- **Privacy:**
  - Agents see the CPT code, date, provider and a hashed claim ID, never patient names (HIPAA minimum necessary).
  - Each physician's pay is visible only to that physician, their chair, the comp admin and the CFO.
- **Accounting:**
  - Incentive accrual each month: Dr Comp Expense / Cr Accrued Incentive.
  - Employer payroll-tax accrual.
  - Draws are recorded as advances.
  - A draw overpayment becomes a clawback receivable, which needs a collectibility judgment.
  - Locums are paid on a 1099, employees on a W-2.
- **Data:**
  - CMS Medicare Physician & Other Practitioners by Provider and Service (real per-provider volumes)
  - CMS fee-schedule RVU files (2020 vs. 2024)
  - NPPES
  - Synthea
- **Risks:**
  - Healthcare jargon (wRVU, CPT, Stark) could lose the judges, the same "niche" problem the winery idea had.
  - It may read as hospital billing software.
