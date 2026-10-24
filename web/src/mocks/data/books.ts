// Books (Filip's lane) as the mock sees them: the CONTRACTS §5 chart of accounts, the journal as at the
// Feb close (Jan locked), and every view computed FROM the journal, so the 2140 rollforward always ties.
// Plan §1.3 numbers:
//   NS31: 3,465,000 new → (360,000) Jan claims → Jan close 3,105,000 → (930,000) Feb claims (15×€600 + 1×€300)
//         → +399,000 change in estimate → 2,574,000 = (35% − 9%) × 9,900,000 (BF at M1; A/E = 1,290,000 / 891,000 = 1.448)
//   knock-on accruals 1,922,400 + 1,987,200 + 840,000 = 4,749,600 · Isha tail 360,000 = (35% − 29%) × 6,000,000
//   care accrued 22,700,000 → invoiced 22,130,000 → 570,000 reversal · 2125 refund clearing ends at 0
import type { CfoMetrics, ClaimCurve, CurveSegment, EstimateCard, InvariantResult, JournalEntry, JournalLine, Rollforward, RollforwardRow } from "@/api/types";

export const ACCOUNTS: Record<string, string> = {
  "1000": "Bank",
  "1110": "Card acquirer",
  "2000": "Trade payables",
  "2100": "Air traffic liability (ATL)",
  "2110": "Taxes payable",
  "2120": "Refunds payable",
  "2125": "Refund clearing",
  "2131": "Refund vouchers",
  "2132": "Compensation vouchers",
  "2140": "EU261 compensation liability (estimated)",
  "2141": "EU261 compensation payable",
  "2150": "Accrued care",
  "2160": "Interline payable",
  "2170": "Legal costs provision (IAS 37)",
  "4000": "Passenger revenue",
  "4010": "Breakage",
  "4090": "EU261 compensation (reduction of passenger revenue)",
  "6100": "Care",
  "6110": "Rerouting",
  "6120": "Claims legal",
};

export const COHORT_LH = "EIDW@2025-01-24";
export const COHORT_MED = "EIDW@2025-01-24:medium_1500_3500";
export const COHORT_SHORT = "EIDW@2025-01-24:short_le1500";
export const COHORT_ISHA = "EIDW@2024-01-21";

export const dr = (account: string, cents: number, dims: Record<string, string> = {}): JournalLine => ({ account, account_name: ACCOUNTS[account], dr_cents: cents, cr_cents: 0, dims });
export const cr = (account: string, cents: number, dims: Record<string, string> = {}): JournalLine => ({ account, account_name: ACCOUNTS[account], dr_cents: 0, cr_cents: cents, dims });

type JeInit = Omit<JournalEntry, "period" | "ias8_class" | "reverses" | "estimate_ref" | "source_decision_id" | "approver" | "built_from" | "ties_to"> & Partial<JournalEntry>;
export function je(init: JeInit): JournalEntry {
  return { period: init.event_date.slice(0, 7), ias8_class: "none", reverses: null, estimate_ref: null, source_decision_id: null, approver: null, built_from: 0, ties_to: [], ...init };
}

const storm = { storm: "EIDW@2025-01-24" };
const lh = { ...storm, flight: "NS31@2025-01-24", segment: "long_haul_gt3500", cohort: COHORT_LH };

/** The journal as at the Feb close. Day-1 drafts are parked ("drafted, pending approval"); StormCheck never posts. */
export function baselineJournal(): JournalEntry[] {
  return [
    // Storm Isha cohort (before StormCheck): estimate in Jan 2024, 29% claimed by M12
    je({ id: "JE-000041", event_date: "2024-01-22", memo: "Storm Isha long-haul cohort · EU261 compensation liability at 35% × €60,000", lines: [dr("4090", 2_100_000, { storm: COHORT_ISHA, cohort: COHORT_ISHA, segment: "long_haul_gt3500" }), cr("2140", 2_100_000, { storm: COHORT_ISHA, cohort: COHORT_ISHA, segment: "long_haul_gt3500" })], kind: "compensation_estimate", status: "posted", preparer: "controller", approver: "cfo", ties_to: ["2140"] }),
    je({ id: "JE-000042", event_date: "2024-12-31", memo: "Storm Isha cohort · claims approved Feb–Dec 2024 (29% of €60,000), summarised", lines: [dr("2140", 1_740_000, { cohort: COHORT_ISHA }), cr("2141", 1_740_000, { cohort: COHORT_ISHA })], kind: "claim_approved", status: "posted", preparer: "agent.engine", approver: "claims_lead", ties_to: ["2140", "2141"] }),
    je({ id: "JE-000043", event_date: "2024-12-31", memo: "Storm Isha cohort · claims paid 2024, summarised", lines: [dr("2141", 1_740_000, { cohort: COHORT_ISHA }), cr("1000", 1_740_000)], kind: "claim_paid", status: "posted", preparer: "agent.engine", approver: "controller" }),
    // Storm Éowyn, day 1 (24 Jan)
    je({ id: "JE-000099", event_date: "2025-01-24", memo: "CRM bot: 32 NS31 refunds initiated 06:02–09:40Z through the card acquirer", lines: [dr("2125", 1_632_000, lh), cr("1110", 1_632_000)], kind: "refund", status: "posted", preparer: "agent.crm_bot", source_decision_id: "NS31@2025-01-24", built_from: 1 }),
    je({ id: "JE-000101", event_date: "2025-01-24", memo: "NS31 EU261 compensation liability · 35% expected ultimate claim rate × €99,000 full Art. 7 entitlement · drafted, pending approval", lines: [dr("4090", 3_465_000, lh), cr("2140", 3_465_000, lh)], kind: "compensation_estimate", status: "draft", preparer: "agent.engine", source_decision_id: "NS31@2025-01-24", estimate_ref: `EST:${COHORT_LH}:day1`, built_from: 3, ties_to: ["2140"] }),
    je({ id: "JE-000102", event_date: "2025-01-24", memo: "NS113 held for Legal (Q-2) · accrued at the 27% medium-haul segment rate (IFRS 15.56) · drafted, pending approval", lines: [dr("4090", 1_922_400, { ...storm, flight: "NS113@2025-01-24", segment: "medium_1500_3500", cohort: COHORT_MED }), cr("2140", 1_922_400, { ...storm, flight: "NS113@2025-01-24", segment: "medium_1500_3500", cohort: COHORT_MED })], kind: "compensation_estimate", status: "draft", preparer: "agent.engine", source_decision_id: "NS113@2025-01-24", built_from: 4, ties_to: ["2140"] }),
    je({ id: "JE-000103", event_date: "2025-01-24", memo: "NS115 held for Legal (Q-2) · accrued at the 27% medium-haul segment rate (IFRS 15.56) · drafted, pending approval", lines: [dr("4090", 1_987_200, { ...storm, flight: "NS115@2025-01-24", segment: "medium_1500_3500", cohort: COHORT_MED }), cr("2140", 1_987_200, { ...storm, flight: "NS115@2025-01-24", segment: "medium_1500_3500", cohort: COHORT_MED })], kind: "compensation_estimate", status: "draft", preparer: "agent.engine", source_decision_id: "NS115@2025-01-24", built_from: 4, ties_to: ["2140"] }),
    je({ id: "JE-000104", event_date: "2025-01-24", memo: "NS117 held for Legal (Q-2) · accrued at the 20% short-haul segment rate (IFRS 15.56) · drafted, pending approval", lines: [dr("4090", 840_000, { ...storm, flight: "NS117@2025-01-24", segment: "short_le1500", cohort: COHORT_SHORT }), cr("2140", 840_000, { ...storm, flight: "NS117@2025-01-24", segment: "short_le1500", cohort: COHORT_SHORT })], kind: "compensation_estimate", status: "draft", preparer: "agent.engine", source_decision_id: "NS117@2025-01-24", built_from: 4, ties_to: ["2140"] }),
    je({ id: "JE-000105", event_date: "2025-01-24", memo: "NS31 · 32 CRM-bot refunds matched: ATL and taxes relieved once; 2125 refund clearing back to 0 (no double refund)", lines: [dr("2100", 1_440_000, lh), dr("2110", 192_000, lh), cr("2125", 1_632_000, lh)], kind: "refund", status: "draft", preparer: "agent.engine", source_decision_id: "NS31@2025-01-24", built_from: 2, ties_to: ["2125"] }),
    je({ id: "JE-000106", event_date: "2025-01-24", memo: "NS31 · 14 refund vouchers at ticket value incl. taxes (€7,140)", lines: [dr("2100", 630_000, lh), dr("2110", 84_000, lh), cr("2131", 714_000, lh)], kind: "voucher", status: "draft", preparer: "agent.engine", source_decision_id: "NS31@2025-01-24", built_from: 2 }),
    je({ id: "JE-000107", event_date: "2025-01-24", memo: "NS31 · 14 partner reroutes via LHR (FIM, net); the partner bills through IATA SIS in 2–3 months", lines: [dr("2100", 630_000, lh), dr("2110", 84_000, lh), cr("2160", 714_000, lh)], kind: "reroute_fim", status: "draft", preparer: "agent.engine", source_decision_id: "NS31@2025-01-24", built_from: 2 }),
    je({ id: "JE-000108", event_date: "2025-01-24", memo: "NS31/14C · €300 service-desk voucher in lieu of compensation · unsigned · goodwill (reduction of passenger revenue)", lines: [dr("4090", 30_000, { ...lh, coupon: "NS31@2025-01-24:14C" }), cr("2132", 30_000, { ...lh, coupon: "NS31@2025-01-24:14C" })], kind: "voucher_in_lieu", status: "draft", preparer: "agent.engine", source_decision_id: "NS31@2025-01-24", built_from: 2 }),
    je({ id: "JE-000109", event_date: "2025-01-24", memo: "Care, night of 24 Jan: hotels, meals, transport for every cancelled flight (owed even when extraordinary, C-12/11 McDonagh)", lines: [dr("6100", 22_700_000, storm), cr("2150", 22_700_000, storm)], kind: "care_accrual", status: "draft", preparer: "agent.engine", built_from: 41 }),
    je({ id: "JE-000110", event_date: "2025-01-28", memo: "NS31 · 6 overnight claims approved at face value (6 × €600)", lines: [dr("2140", 360_000, lh), cr("2141", 360_000, lh)], kind: "claim_approved", status: "approved", preparer: "agent.engine", approver: "claims_lead", source_decision_id: "NS31@2025-01-24", built_from: 6, ties_to: ["2140", "2141"] }),
    // February
    je({ id: "JE-000201", event_date: "2025-02-03", memo: "NS31 · 6 January claims paid", lines: [dr("2141", 360_000, lh), cr("1000", 360_000)], kind: "claim_paid", status: "approved", preparer: "agent.engine", approver: "claims_lead", built_from: 6, ties_to: ["2141"] }),
    je({ id: "JE-000202", event_date: "2025-02-20", memo: "NS31 · 16 claims approved at face value (15 × €600 + 1 × €300)", lines: [dr("2140", 930_000, lh), cr("2141", 930_000, lh)], kind: "claim_approved", status: "approved", preparer: "agent.engine", approver: "claims_lead", source_decision_id: "NS31@2025-01-24", built_from: 16, ties_to: ["2140", "2141"] }),
    je({ id: "JE-000203", event_date: "2025-02-25", memo: "Care invoices for 24 Jan received: €221,300 to trade payables · €5,700 accrual reversed", lines: [dr("2150", 22_700_000, storm), cr("2000", 22_130_000, storm), cr("6100", 570_000, storm)], kind: "care_invoice", status: "draft", preparer: "controller", built_from: 38, ties_to: ["2150"] }),
    je({ id: "JE-000204", event_date: "2025-02-28", memo: "NS31 cohort · Feb month end (M1): A/E 1.448 · Bornhuetter-Ferguson (35% − 9%) × €99,000 = €25,740 · +€3,990 change in estimate (IAS 8.36) · drafted, pending approval", lines: [dr("4090", 399_000, lh), cr("2140", 399_000, lh)], kind: "change_in_estimate", ias8_class: "change_in_estimate", status: "draft", preparer: "controller", estimate_ref: `EST:${COHORT_LH}:2025-02`, source_decision_id: "NS31@2025-01-24", built_from: 22, ties_to: ["2140"] }),
  ];
}

/** The Feb month-end drafts (what POST /books/month-end {period:"2025-02"} returns). */
export const MONTH_END_IDS: Record<string, string[]> = { "2025-02": ["JE-000204"] };

// ---------- views computed from the journal ----------
const balanceOf = (entries: JournalEntry[], account: string, filter: (l: JournalLine, e: JournalEntry) => boolean = () => true) =>
  entries.reduce((sum, e) => sum + e.lines.filter((l) => l.account === account && filter(l, e)).reduce((s, l) => s + (l.cr_cents ?? 0) - (l.dr_cents ?? 0), 0), 0);

export const glBalance = (entries: JournalEntry[], account: string, throughPeriod?: string) => balanceOf(entries.filter((e) => !throughPeriod || e.period <= throughPeriod), account);

/** 2140 rollforward for `period`, by cohort. `entitlementOf` gives each cohort's full Art. 7 entitlement (from the engine). */
export function rollforward(entries: JournalEntry[], period: string, entitlementOf: (cohort: string) => number): Rollforward {
  const cohorts = new Set<string>();
  for (const e of entries) for (const l of e.lines) if (l.account === "2140" && l.dims?.cohort) cohorts.add(l.dims.cohort);
  const rows: RollforwardRow[] = [];
  for (const cohort of [...cohorts].sort((a, b) => (a === COHORT_ISHA ? -1 : b === COHORT_ISHA ? 1 : a.localeCompare(b)))) {
    const onCohort = (l: JournalLine) => l.dims?.cohort === cohort;
    const prior = entries.filter((e) => e.period < period);
    const inP = entries.filter((e) => e.period === period);
    const sumKind = (kinds: JournalEntry["kind"][], side: "dr" | "cr" | "net") =>
      inP.filter((e) => kinds.includes(e.kind)).reduce((s, e) => s + e.lines.filter((l) => l.account === "2140" && onCohort(l)).reduce((t, l) => t + (side === "dr" ? (l.dr_cents ?? 0) : side === "cr" ? (l.cr_cents ?? 0) : (l.cr_cents ?? 0) - (l.dr_cents ?? 0)), 0), 0);
    const opening = balanceOf(prior, "2140", onCohort);
    const row: RollforwardRow = {
      cohort,
      opening_cents: opening,
      new_cents: sumKind(["compensation_estimate"], "net"),
      claims_approved_cents: sumKind(["claim_approved"], "dr"),
      settled_in_kind_cents: sumKind(["voucher_in_lieu"], "dr"),
      change_in_estimate_cents: sumKind(["change_in_estimate"], "net"),
      recode_cents: sumKind(["recode"], "net"),
      out_of_period_cents: sumKind(["out_of_period_adjustment"], "net"),
      derecognised_cents: sumKind(["derecognition"], "dr"),
      closing_cents: 0,
      unclaimed_entitlement_cents: 0,
    };
    row.closing_cents = row.opening_cents + row.new_cents - row.claims_approved_cents - (row.settled_in_kind_cents ?? 0) + row.change_in_estimate_cents + (row.recode_cents ?? 0) + (row.out_of_period_cents ?? 0) - (row.derecognised_cents ?? 0);
    const claimedToDate = entries.filter((e) => e.period <= period && e.kind === "claim_approved").reduce((s, e) => s + e.lines.filter((l) => l.account === "2140" && onCohort(l)).reduce((t, l) => t + (l.dr_cents ?? 0), 0), 0);
    row.unclaimed_entitlement_cents = Math.max(0, entitlementOf(cohort) - claimedToDate);
    if (row.opening_cents || row.closing_cents || row.new_cents || row.claims_approved_cents || row.change_in_estimate_cents || row.derecognised_cents) rows.push(row);
  }
  const closing_total_cents = rows.reduce((s, r) => s + r.closing_cents, 0);
  const gl_balance_cents = glBalance(entries, "2140", period);
  return { period, account: "2140", rows, closing_total_cents, gl_balance_cents, ties_to_gl: closing_total_cents === gl_balance_cents };
}

// ---------- claim curves (curves.json, LH-v1) ----------
export const CURVES: Record<CurveSegment, ClaimCurve> = {
  long_haul_gt3500: { segment: "long_haul_gt3500", basis: "eur", points: [[1, 0.09], [3, 0.17], [6, 0.24], [12, 0.29], [18, 0.32]], n_by_point: [1214, 1214, 1131, 968, 702], observed_through_month: 18, ultimate: 0.35, tail_factor: 1.094, tail_note: "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% for cancellations)", version: "LH-v1" },
  medium_1500_3500: { segment: "medium_1500_3500", basis: "eur", points: [[1, 0.07], [3, 0.13], [6, 0.185], [12, 0.225], [18, 0.245]], n_by_point: [3871, 3871, 3590, 3022, 2240], observed_through_month: 18, ultimate: 0.27, tail_factor: 1.102, tail_note: "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% for cancellations)", version: "MH-v1" },
  short_le1500: { segment: "short_le1500", basis: "eur", points: [[1, 0.05], [3, 0.095], [6, 0.135], [12, 0.165], [18, 0.18]], n_by_point: [9644, 9644, 9015, 7802, 5930], observed_through_month: 18, ultimate: 0.2, tail_factor: 1.111, tail_note: "months 18–72 beyond history: documented judgment (Steer 2020 benchmark 18% for cancellations)", version: "SH-v1" },
};

// ---------- estimate card (BF selected while under 50% developed) ----------
type CohortFacts = { cohort: string; segment: CurveSegment; pax: number; entitlement: number; monthsDeveloped: number; expectedToDatePct: number };

export function estimateCard(entries: JournalEntry[], c: CohortFacts): EstimateCard {
  const curve = CURVES[c.segment];
  const ult = Math.round(curve.ultimate * 100);
  const toDate = Math.round(c.expectedToDatePct * 100);
  const paid = entries.filter((e) => e.kind === "claim_approved").reduce((s, e) => s + e.lines.filter((l) => l.account === "2140" && l.dims?.cohort === c.cohort).reduce((t, l) => t + (l.dr_cents ?? 0), 0), 0);
  const expectedLoss = Math.round((c.entitlement * ult) / 100) - paid;
  const bf = Math.round((c.entitlement * (ult - toDate)) / 100);
  const chainLadder = toDate ? Math.round((paid * ult) / toDate) - paid : expectedLoss;
  const expectedClaims = (c.entitlement * toDate) / 100;
  const me = entries.find((e) => e.kind === "change_in_estimate" && e.lines.some((l) => l.dims?.cohort === c.cohort));
  return {
    cohort: c.cohort,
    segment: c.segment,
    pax: c.pax,
    entitlement_cents: c.entitlement,
    curve_version: curve.version,
    months_developed: c.monthsDeveloped,
    expected_loss_cents: expectedLoss,
    bf_cents: bf,
    chain_ladder_cents: chainLadder,
    selected: "bf",
    actual_vs_expected: expectedClaims ? Math.round((paid / expectedClaims) * 1000) / 1000 : null,
    credibility_z: Math.round((toDate / ult) * 1000) / 1000,
    sensitivity_5pp_cents: Math.round((c.entitlement * 5) / 100),
    constraint_note: `IFRS 15.56: variable consideration only to the extent a significant reversal is highly unlikely. BF selected while under 50% developed (M${c.monthsDeveloped} = ${toDate}% of a ${ult}% ultimate); the tail beyond M18 is a documented judgment against the Steer 2020 benchmark (18% for cancellations).`,
    ias8_class: "change_in_estimate",
    preparer: me?.preparer ?? "agent.engine",
    approver: me?.approver ?? null,
  };
}

// ---------- CFO ----------
export function cfoMetrics(args: {
  as_of: string;
  entries: JournalEntry[];
  fullEntitlement: number;
  drafted: number;
  heldForLegal: number;
  recodes: { count: number; cents: number };
  estimate: EstimateCard;
  bridge: RollforwardRow[];
}): CfoMetrics {
  const care = args.entries.filter((e) => e.kind === "care_invoice").reduce((s, e) => s + e.lines.filter((l) => l.account === "2000").reduce((t, l) => t + (l.cr_cents ?? 0), 0), 0);
  return {
    as_of: args.as_of,
    cash_basis_cents: 0,
    full_entitlement_cents: args.fullEntitlement,
    drafted_liability_cents: args.drafted,
    sensitivity_5pp_cents: Math.round((args.fullEntitlement * 5) / 100),
    method_range_cents: [Math.min(args.estimate.expected_loss_cents, args.estimate.bf_cents, args.estimate.chain_ladder_cents), Math.max(args.estimate.expected_loss_cents, args.estimate.bf_cents, args.estimate.chain_ladder_cents)],
    held_for_legal_cents: args.heldForLegal,
    liability_bridge: args.bridge,
    recodes_count: args.recodes.count,
    recodes_cents: args.recodes.cents,
    refunds_within_7d_pct: 100,
    vouchers_outstanding_cents: glBalance(args.entries, "2131") + glBalance(args.entries, "2132"),
    care_accrued_cents: args.entries.filter((e) => e.kind === "care_accrual").reduce((s, e) => s + e.lines.filter((l) => l.account === "2150").reduce((t, l) => t + (l.cr_cents ?? 0), 0), 0),
    care_invoiced_cents: care,
  };
}

// ---------- invariants (checked on every read) ----------
export function invariants(args: { entries: JournalEntry[]; locked: string[]; lockedWrites: number; rf: Rollforward; cancelled: number; operated: number; scheduled: number }): InvariantResult[] {
  const { entries, rf } = args;
  const unbalanced = entries.filter((e) => e.lines.reduce((s, l) => s + (l.dr_cents ?? 0) - (l.cr_cents ?? 0), 0) !== 0);
  const clearing = glBalance(entries, "2125");
  const selfApproved = entries.filter((e) => e.approver && e.approver === e.preparer);
  const cutoff = entries.filter((e) => e.period !== e.event_date.slice(0, 7));
  const approvedUnpaid = entries.filter((e) => e.kind === "claim_approved").reduce((s, e) => s + e.lines.filter((l) => l.account === "2141").reduce((t, l) => t + (l.cr_cents ?? 0), 0), 0) - entries.filter((e) => e.kind === "claim_paid").reduce((s, e) => s + e.lines.filter((l) => l.account === "2141").reduce((t, l) => t + (l.dr_cents ?? 0), 0), 0);
  const overUnclaimed = rf.rows.filter((r) => r.closing_cents < 0 || (r.unclaimed_entitlement_cents > 0 && r.closing_cents > r.unclaimed_entitlement_cents));
  const fmt = (c: number) => `€${(c / 100).toLocaleString("en-US")}`;
  return [
    { id: "INV-01", description: "2140 rollforward foots and ties to GL 2140", ok: rf.ties_to_gl, detail: `${rf.period}: closing ${fmt(rf.closing_total_cents)} = GL ${fmt(rf.gl_balance_cents)}` },
    { id: "INV-02", description: "Every journal entry balances (Σ Dr = Σ Cr)", ok: unbalanced.length === 0, detail: unbalanced.length ? `unbalanced: ${unbalanced.map((e) => e.id).join(", ")}` : `${entries.length} entries balance` },
    { id: "INV-03", description: "2125 refund clearing = 0 · no double refund", ok: clearing === 0, detail: `2125 balance ${fmt(clearing)} after the 32 CRM-bot refunds` },
    { id: "INV-04", description: "Completeness: scheduled − operated = register = ops-log cancellations", ok: args.scheduled - args.operated === args.cancelled, detail: `${args.scheduled} − ${args.operated} = ${args.cancelled} = ${args.cancelled} on the OCC list` },
    { id: "INV-05", description: "Operated EIDW departures ≤ Eurocontrol's 179", ok: args.operated <= 179, detail: `${args.operated} Northstar departures operated; Eurocontrol counted 179 for the airport` },
    { id: "INV-06", description: "Each coupon relieved once (refund, voucher, own uplift, FIM or breakage); open rebooks stay in 2100", ok: true, detail: "NS31: 32 refund · 14 voucher · 14 FIM · 112 open rebooks in 2100" },
    { id: "INV-07", description: "At most one payment per coupon across channels; paid ≤ entitlement", ok: true, detail: "1 BSP + CRM-bot duplicate caught on NS31/3A: refunded once" },
    { id: "INV-08", description: "0 ≤ cohort liability ≤ unclaimed, unexpired entitlement", ok: overUnclaimed.length === 0, detail: overUnclaimed.length ? `out of range: ${overUnclaimed.map((r) => r.cohort).join(", ")}` : `${rf.rows.length} cohorts within range` },
    { id: "INV-09", description: "Extraordinary → compensation 0; refunds and care remain", ok: true, detail: "weather flights: no compensation; refunds and care still due" },
    { id: "INV-10", description: "No voucher offset without a signed acceptance hash", ok: true, detail: "0 offsets; 33 unsigned in-lieu vouchers kept as goodwill or held" },
    { id: "INV-11", description: "Nothing written to a locked period", ok: args.lockedWrites === 0, detail: args.locked.length ? `${args.locked.join(", ")} locked, untouched` : "no period locked yet" },
    { id: "INV-12", description: "Preparer ≠ approver on every approved entry", ok: selfApproved.length === 0, detail: selfApproved.length ? selfApproved.map((e) => e.id).join(", ") : "SoD held on every approval" },
    { id: "INV-13", description: "Refunds within 7 days (Art. 8), or a refund draft is queued", ok: true, detail: "32 of 32 NS31 CRM-bot refunds within 7 days" },
    { id: "INV-14", description: "Cut-off: JE.period follows event_date", ok: cutoff.length === 0, detail: cutoff.length ? cutoff.map((e) => e.id).join(", ") : "every entry in its event's period" },
    { id: "INV-15", description: "2141 equals the approved-unpaid subledger", ok: glBalance(entries, "2141") === approvedUnpaid, detail: `${fmt(approvedUnpaid)} approved, unpaid` },
  ];
}
