import type { Entitlement, Flight, FlightDecision, JournalEntry, TimelineMark } from "@/api/types";
import type { VerdictKind } from "@/components/verdict";
import { airport } from "@/lib/airports";
import { count, eur, pct } from "@/lib/format";

/**
 * Display-only lookups and wording for the Flight File. Names, never numbers: every count, € and %
 * on the screen comes from the API.
 */

/** Airport name for an IATA code (shared reference list); the code itself when it isn't listed. */
export const cityOf = (iata: string) => airport(iata)?.name ?? iata;

export const routeText = (f: Pick<Flight, "origin" | "dest">) => `${cityOf(f.origin)} → ${cityOf(f.dest)}`;

/** The one-word headline over a verdict. */
export const VERDICT_HEADLINE: Record<VerdictKind, string> = {
  notweather: "Not weather",
  weather: "Weather",
  held: "Held for a ruling",
  operated: "Operated",
  pending: "Not decided yet",
};

/** What the verdict means for passengers, in the plan's wording (§9). */
export function consequence(kind: VerdictKind): string | null {
  if (kind === "weather") return "no compensation; refunds and care still due";
  if (kind === "held") return "accrued under the IFRS 15.56 constraint until the ruling";
  return null;
}

/** "71 → 41" split so the losing code can be struck. */
export function splitRecode(label: string | null | undefined, decision?: Pick<FlightDecision, "ops_cause_code">) {
  if (!label) return null;
  const parts = label.split(/\s*(?:→|->)\s*/);
  if (parts.length !== 2) return { from: decision?.ops_cause_code ?? null, to: label };
  return { from: parts[0], to: parts[1] };
}

/** Readable names for the calibration features (contracts/calibration_schema.json). */
const FEATURE: Record<string, string> = {
  in_window_dep: "Departure in storm window",
  in_window_arr: "Arrival in storm window",
  window_margin_h: "Hours from the window edge",
  window_margin_min: "Minutes from the window edge",
  aog_before_window: "Grounded before the storm",
  aog_inside_window: "Grounded in storm window",
  root_cause_internal: "Root cause internal (ATA)",
  sources_disagree: "Sources disagree",
  precedent_count: "Precedents",
  knock_on: "Knock-on of a cancellation",
  in_lieu: "Voucher given in lieu",
  signed: "Signed acceptance",
  months_since_last_claim: "Months since the last claim",
  cohort_age_months: "Cohort age in months",
  mel_relief: "MEL relief",
  spare_available: "Spare aircraft available",
};

export function featureLabel(key: string): string {
  if (FEATURE[key]) return FEATURE[key];
  const words = key.replace(/[._]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Short glosses for the citations a decision can carry (static legal copy). */
const LEGAL: [RegExp, string][] = [
  [/C-549\/07/, "Wallentin-Hermann: a technical fault is not extraordinary"],
  [/C-257\/14/, "van der Lans: unexpected component failures are not extraordinary"],
  [/C-74\/19/, "TAP: a previous rotation counts only with a direct causal link"],
  [/C-12\/11/, "McDonagh: care is owed even when circumstances are extraordinary"],
  [/C-139\/11/, "Moré: limitation follows national law (Ireland, 6 years)"],
  [/Art\.?\s*5\s*\(3\)/, "No compensation if extraordinary circumstances caused it"],
  [/Art\.?\s*7\s*\(2\)/, "Compensation halved for a reroute arriving on time"],
  [/Art\.?\s*7\s*\(3\)/, "Vouchers only with the passenger's signed agreement"],
  [/Art\.?\s*7/, "Compensation by distance band"],
  [/Art\.?\s*8/, "Refund within 7 days or rerouting"],
  [/Art\.?\s*9/, "Care: meals, hotel, transport"],
  [/Art\.?\s*14/, "Passengers must be told their rights in writing"],
  [/Art\.?\s*15/, "Rights can't be waived or limited"],
  [/IFRS\s*15/, "Variable consideration, reduction of passenger revenue"],
];

export const legalGloss = (citation: string) => LEGAL.find(([re]) => re.test(citation))?.[1] ?? null;

/** "Band margin": how far the great-circle distance sits from the nearest band edge. */
const BANDS = [250, 400, 600] as const;

export function bandMarginText(e: Pick<Entitlement, "distance_km" | "band_eur" | "band_margin_km">): string {
  const km = `${count(Math.round(e.distance_km))} km`;
  const margin = Math.round(Math.abs(e.band_margin_km));
  if (!Number.isFinite(margin)) return km;
  const i = BANDS.indexOf(e.band_eur);
  const next = BANDS[i + 1];
  // The lowest band can only move up and the highest only down; the middle one could go either way.
  if (i === 0 && next !== undefined) return `${km} · ${count(margin)} km under the €${next} band`;
  if (next === undefined || e.band_margin_km < 0) return `${km} · ${count(margin)} km into the €${e.band_eur} band`;
  return `${km} · ${count(margin)} km from the nearest band edge`;
}

/** The compensation liability a decision drafted: Cr 2140 on its compensation-estimate journals. */
export function draftedLiability(journals: JournalEntry[]): number | null {
  const lines = journals.filter((j) => j.kind === "compensation_estimate").flatMap((j) => j.lines.filter((l) => l.account === "2140"));
  if (!lines.length) return null;
  return lines.reduce((s, l) => s + (l.cr_cents ?? 0) - (l.dr_cents ?? 0), 0);
}

/** Labels for the loose `entitlements_summary` dict; unknown keys are humanised, never dropped. */
const SUMMARY_LABEL: Record<string, string> = {
  passengers: "Passengers",
  pax: "Passengers",
  coupons: "Coupons",
  owed: "Owed compensation",
  payouts_drafted: "Payouts drafted",
  no_compensation: "No compensation",
  held: "Held",
  needs_ruling: "Waiting on a ruling",
  exempt_notice: "Notice ≥14 days (exempt)",
  staff_ticket: "Staff tickets",
  out_of_scope: "Out of scope",
  refunds: "Refunds",
  refunds_already_initiated: "Refunds already initiated by the CRM bot",
  vouchers: "Refund vouchers",
  reaccommodated: "Reaccommodated",
  reaccommodated_own: "Reaccommodated on Northstar",
  reroute_partner: "Partner reroutes",
  reduced_50pct: "Art. 7(2) 50% reduction",
  art7_2_50pct: "Art. 7(2) 50% reduction",
  claims: "Claims received",
  claims_received: "Claims received",
  claims_unassessed: "Claims not yet assessed",
  voucher_cases: "Service-desk vouchers in lieu",
  atl_cents: "Air traffic liability (2100)",
  taxes_payable_cents: "Taxes payable (2110)",
  refund_cents: "Refunds elected",
  compensation_cents: "Full Art. 7 entitlement if every passenger claims",
  entitlement_cents: "Full Art. 7 entitlement if every passenger claims",
  full_entitlement_cents: "Full Art. 7 entitlement if every passenger claims",
  liability_cents: "EU261 compensation liability",
  liability_drafted_cents: "EU261 compensation liability",
  drafted_liability_cents: "EU261 compensation liability",
  refund_due_cents: "Refunds due",
  care_cents: "Care accrued",
  claim_rate: "Expected ultimate claim rate",
  expected_claim_rate: "Expected ultimate claim rate",
  ultimate_claim_rate: "Expected ultimate claim rate",
};

export function summaryLabel(key: string) {
  return SUMMARY_LABEL[key] ?? featureLabel(key);
}

export type SummaryItem = { key: string; label: string; text: string; kind: "money" | "count" | "rate" };

/** Keys that are geometry or display text, not figures for the grid (the band and the lines render elsewhere). */
const NOT_A_FIGURE = new Set(["distance_km", "band_eur", "band_margin_km", "care_due"]);

/**
 * The loose summary dict as grid figures: cents → €, rates → %, counts → "5,292". Strings (labels, status
 * lines, ids) and nested values are left to the components that know them; unknown numeric keys still show.
 */
export function summaryItems(summary: Record<string, unknown> | null | undefined): SummaryItem[] {
  if (!summary) return [];
  const out: SummaryItem[] = [];
  for (const [key, value] of Object.entries(summary)) {
    if (typeof value !== "number" || !Number.isFinite(value) || NOT_A_FIGURE.has(key)) continue;
    const label = summaryLabel(key);
    if (key.endsWith("_cents")) out.push({ key, label, text: eur(value), kind: "money" });
    else if (/rate|pct|share/.test(key) && value <= 1) out.push({ key, label, text: pct(value), kind: "rate" });
    else out.push({ key, label, text: count(value), kind: "count" });
  }
  return out;
}

/** A display string the server wrote into the summary (status_line, band_label, …), if it did. */
export function summaryText(summary: Record<string, unknown> | null | undefined, key: string): string | null {
  const v = summary?.[key];
  return typeof v === "string" && v.trim() ? v : null;
}

/** `statuses` ({owed: 171, needs_ruling: 1}) as pairs, largest first. */
export function statusesOf(summary: Record<string, unknown> | null | undefined): [string, number][] {
  const s = summary?.statuses;
  if (!s || typeof s !== "object" || Array.isArray(s)) return [];
  return Object.entries(s as Record<string, unknown>)
    .filter((p): p is [string, number] => typeof p[1] === "number" && p[1] > 0)
    .sort((a, b) => b[1] - a[1]);
}

/** `compensation_breakdown` ([{count, band_eur}]) as "158 × €600 + 14 × €300". */
export function breakdownText(summary: Record<string, unknown> | null | undefined): string | null {
  const b = summary?.compensation_breakdown;
  if (!Array.isArray(b) || !b.length) return null;
  const parts = b.filter((r): r is { count: number; band_eur: number } => !!r && typeof r.count === "number" && typeof r.band_eur === "number").map((r) => `${count(r.count)} × €${count(r.band_eur)}`);
  return parts.length ? parts.join(" + ") : null;
}

export type Reduction = { coupons: number | null; ruleRef: string | null; support: string | null; label: string };

/** `reduction_7_2`: the learned Art. 7(2) cut, if this flight applies it. */
export function reductionOf(summary: Record<string, unknown> | null | undefined): Reduction | null {
  const r = summary?.reduction_7_2;
  if (!r || typeof r !== "object" || Array.isArray(r)) return null;
  const o = r as Record<string, unknown>;
  return {
    coupons: typeof o.coupons === "number" ? o.coupons : null,
    ruleRef: typeof o.rule_ref === "string" ? o.rule_ref : null,
    support: typeof o.support === "string" ? o.support : null,
    label: typeof o.label === "string" ? o.label : "Art. 7(2) 50% reduction",
  };
}

export const capitalize = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** Passenger elections (Election.kind) in plain words, in the order they are drawn. */
export const ELECTION_LABEL: Record<string, string> = {
  refund: "Refund",
  voucher: "Refund voucher",
  reaccommodated_own: "Rebooked on Northstar",
  reroute_partner: "Partner reroute",
  none: "No choice yet",
};

/** `elections` as [kind, count] pairs, when the summary carries it as a {kind: count} map. */
export function electionsOf(summary: Record<string, unknown> | null | undefined): [string, number][] {
  const e = summary?.elections;
  if (!e || typeof e !== "object" || Array.isArray(e)) return [];
  const pairs = Object.entries(e as Record<string, unknown>).filter((p): p is [string, number] => typeof p[1] === "number" && p[1] > 0);
  const order = Object.keys(ELECTION_LABEL);
  return pairs.sort(([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
}

export type MarkKey = "tech" | "mcc" | "spares" | "occ" | "window" | "metar" | "crm" | "pss" | "claim" | "schedule" | "operated" | "other";

/** Timeline kinds in plain words, whether their text is machine text (mono), and how they are drawn. */
export function markKind(mark: TimelineMark): { key: MarkKey; label: string; machine: boolean; tone: "ink" | "metar" | "slate" | "flight" } {
  const k = String(mark.kind ?? mark.source_id ?? "").toLowerCase();
  if (k.includes("tech")) return { key: "tech", label: "Tech log", machine: true, tone: "ink" };
  if (k.includes("mcc")) return { key: "mcc", label: "MCC", machine: true, tone: "ink" };
  if (k.includes("spares")) return { key: "spares", label: "Spares", machine: true, tone: "ink" };
  if (k.includes("occ")) return { key: "occ", label: "OCC", machine: true, tone: "slate" };
  if (k.includes("window")) return { key: "window", label: "Window", machine: true, tone: "metar" };
  if (k.includes("metar") || k.includes("weather")) return { key: "metar", label: "METAR", machine: true, tone: "metar" };
  if (k.includes("crm") || k.includes("refund") || k.includes("email")) return { key: "crm", label: "CRM", machine: false, tone: "slate" };
  if (k.includes("pss")) return { key: "pss", label: "PSS", machine: true, tone: "slate" };
  if (k.includes("claim")) return { key: "claim", label: "Claim", machine: false, tone: "slate" };
  if (k.includes("operated")) return { key: "operated", label: "Operated", machine: false, tone: "slate" };
  if (k.includes("schedule") || k.includes("std") || k.includes("flight") || k.includes("departure")) return { key: "schedule", label: "Schedule", machine: false, tone: "flight" };
  return { key: "other", label: k ? featureLabel(k) : "Event", machine: false, tone: "slate" };
}

export const markText = (m: TimelineMark) => (typeof m.text === "string" ? m.text : typeof m.label === "string" ? m.label : "");

/** Decode a route param that arrived still encoded ("NS31%402025-01-24"). */
export function decodeId(raw: string) {
  try {
    return raw.includes("%") ? decodeURIComponent(raw) : raw;
  } catch {
    return raw;
  }
}

export const flightHref = (id: string) => `/flights/${encodeURIComponent(id)}`;
