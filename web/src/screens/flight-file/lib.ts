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
  window_margin_h: "Hours clear of the window",
  window_margin_min: "Minutes clear of the window",
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
  // Negative margin, or a band with nothing above it, means the edge is below; otherwise the next band up.
  if (e.band_margin_km < 0 || next === undefined) return `${km} · ${count(margin)} km inside the €${e.band_eur} band`;
  return `${km} · ${count(margin)} km under the €${next} band`;
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
  needs_ruling: "Needs a ruling",
  exempt_notice: "Notice ≥14 days (exempt)",
  staff_ticket: "Staff tickets",
  out_of_scope: "Out of scope",
  refunds: "Refunds",
  refunds_already_initiated: "Refunds already initiated",
  vouchers: "Refund vouchers",
  reaccommodated: "Reaccommodated",
  reaccommodated_own: "Reaccommodated on Northstar",
  reroute_partner: "Partner reroutes",
  reduced_50pct: "Art. 7(2) 50% reduction",
  art7_2_50pct: "Art. 7(2) 50% reduction",
  claims: "Claims received",
  claims_received: "Claims received",
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

export type SummaryItem = { key: string; label: string; text: string; kind: "money" | "count" | "rate" | "text" };

/** Turn the summary dict into display rows: cents → €, rates → %, counts → "5,292". Nested values are skipped. */
export function summaryItems(summary: Record<string, unknown> | null | undefined): SummaryItem[] {
  if (!summary) return [];
  const out: SummaryItem[] = [];
  for (const [key, value] of Object.entries(summary)) {
    if (value === null || value === undefined || typeof value === "object") continue;
    const label = summaryLabel(key);
    if (typeof value === "number") {
      if (key.endsWith("_cents")) out.push({ key, label, text: eur(value), kind: "money" });
      else if (/rate|pct|share/.test(key) && value <= 1) out.push({ key, label, text: pct(value), kind: "rate" });
      else out.push({ key, label, text: count(value), kind: "count" });
    } else if (typeof value === "boolean") {
      out.push({ key, label, text: value ? "yes" : "no", kind: "text" });
    } else {
      out.push({ key, label, text: String(value), kind: "text" });
    }
  }
  return out;
}

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

/** Timeline kinds in plain words and whether their text is machine text (mono). */
export function markKind(mark: TimelineMark): { label: string; machine: boolean; tone: "ink" | "metar" | "slate" | "flight" } {
  const k = String(mark.kind ?? mark.source_id ?? "").toLowerCase();
  if (k.includes("tech")) return { label: "Tech log", machine: true, tone: "ink" };
  if (k.includes("mcc")) return { label: "MCC", machine: true, tone: "ink" };
  if (k.includes("spares")) return { label: "Spares", machine: true, tone: "ink" };
  if (k.includes("occ")) return { label: "OCC", machine: true, tone: "slate" };
  if (k.includes("metar") || k.includes("window") || k.includes("weather")) return { label: "METAR", machine: true, tone: "metar" };
  if (k.includes("crm") || k.includes("refund") || k.includes("email")) return { label: "CRM", machine: false, tone: "slate" };
  if (k.includes("schedule") || k.includes("std") || k.includes("flight") || k.includes("departure")) return { label: "Schedule", machine: false, tone: "flight" };
  if (k.includes("claim")) return { label: "Claim", machine: false, tone: "slate" };
  return { label: k ? featureLabel(k) : "Event", machine: false, tone: "slate" };
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
