import { eur, periodLabel } from "@/lib/format";

/** One set of repeated runs, read defensively from the contract's loosely typed dictionaries (liability in euros). */
export type Runs = {
  runs: number;
  values: number[];
  allSame: boolean;
  hashIdentical: boolean | null;
  model: string | null;
  hash: string | null;
  accuracy: number[];
};

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : null);
const nums = (v: unknown) => (Array.isArray(v) ? v.map(num).filter((x): x is number => x !== null) : []);

export function readRuns(d: Record<string, unknown> | undefined): Runs {
  const values = nums(d?.liability_eur);
  const runs = num(d?.runs) ?? values.length;
  const hashes = Array.isArray(d?.hashes) ? (d.hashes as unknown[]).map(String) : [];
  return {
    runs,
    values,
    allSame: values.length > 0 && values.every((v) => v === values[0]),
    hashIdentical: typeof d?.hash_identical === "boolean" ? d.hash_identical : null,
    model: typeof d?.model === "string" ? d.model : null,
    hash: typeof d?.hash === "string" ? d.hash : (hashes[0] ?? null),
    accuracy: nums(d?.cause_accuracy),
  };
}

/** Liability in euros (the eval reports euros, not cents). */
export const euros = (v: number) => eur(Math.round(v * 100));

/** "Plain Claude, 3 runs: €a / €b / €c." and "StormCheck: €34,650 ×3, same hash." from the report. */
export function headline(baseline: Runs, sc: Runs) {
  const list = (r: Runs) => r.values.map(euros).join(" / ");
  const hash = (r: Runs) => (r.hashIdentical === true ? "same hash" : r.hashIdentical === false ? "hashes differ" : "hash not reported");
  return {
    baseline: baseline.values.length ? `Plain Claude, ${baseline.runs} runs: ${list(baseline)}.` : "Plain Claude baseline: not reported.",
    stormcheck: !sc.values.length ? "StormCheck runs: not reported." : sc.allSame ? `StormCheck: ${euros(sc.values[0])} ×${sc.runs}, ${hash(sc)}.` : `StormCheck, ${sc.runs} runs: ${list(sc)}, ${hash(sc)}.`,
  };
}

/** "€0 · cash basis" / "€99,000 · full entitlement" when a run lands exactly on one of the bridge's ends. */
export function runLabel(valueEur: number, anchors: { cashCents: number; fullCents: number } | null) {
  const cents = Math.round(valueEur * 100);
  if (anchors && cents === anchors.cashCents) return `${euros(valueEur)} · cash basis`;
  if (anchors && cents === anchors.fullCents) return `${euros(valueEur)} · full entitlement`;
  return euros(valueEur);
}

/** Where a label sits on an axis of width `iw`: start-anchored at the left edge, end-anchored at the right, centred between. */
export function labelSpan(x: number, w: number, iw: number): [number, number] {
  if (x < 24) return [x - 7, x - 7 + w];
  if (x > iw - 24) return [x + 7 - w, x + 7];
  return [x - w / 2, x + w / 2];
}

/** Above the dot when it fits, else below, else whichever row has more room. Input in x order. */
export function placeLabels(items: { x: number; w: number }[], iw: number): ("above" | "below")[] {
  const out: ("above" | "below")[] = [];
  let endAbove = -Infinity;
  let endBelow = -Infinity;
  for (const it of items) {
    const [a, b] = labelSpan(it.x, it.w, iw);
    const row = a >= endAbove + 8 ? "above" : a >= endBelow + 8 ? "below" : endAbove <= endBelow ? "above" : "below";
    out.push(row);
    if (row === "above") endAbove = b;
    else endBelow = b;
  }
  return out;
}

/** A round axis end above every value: 1, 2, 2.5, 4, 5 or 10 × a power of ten. */
export function axisMax(values: number[]) {
  const top = Math.max(0, ...values);
  if (top <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(top));
  for (const step of [1, 2, 2.5, 4, 5, 10]) if (step * mag >= top * 1.04) return step * mag;
  return 10 * mag;
}

/** Liability vs actual: a ratio near 1 reads as a share of actual; a small number reads as an error. */
export function ratioText(v: number) {
  if (Math.abs(v) >= 0.3) return `${Math.round(v * 100)}% of actual`;
  const p = Math.round(Math.abs(v) * 100);
  return `${v < 0 ? "−" : "+"}${p}% vs actual`;
}

/**
 * Injections: the number blocked, "of N" only when the report gives the attempts, and every other count
 * as it is (rehearsed, fuzz, escalated, server errors…), never folded into a ratio it didn't state.
 */
export function injectionSummary(d: Record<string, number> | undefined) {
  if (!d) return null;
  const blocked = num(d.blocked);
  if (blocked === null) return null;
  const totalKey = ["attempted", "total", "tried"].find((k) => num(d[k]) !== null);
  const rest = Object.entries(d)
    .filter(([k]) => k !== "blocked" && k !== totalKey)
    .map(([key, v]) => ({ key, label: key.replace(/_/g, " "), value: num(v) }))
    .filter((x): x is { key: string; label: string; value: number } => x.value !== null);
  return { blocked, total: totalKey ? num(d[totalKey]) : null, rest };
}

const SPLIT_LABEL: Record<string, string> = { learn: "Learned on", train: "Learned on", score: "Scored on", test: "Scored on" };

/** "2023-07..2024-12" or "2023-07-01..2024-12-31" → its two ends, each "YYYY-MM" or "YYYY-MM-DD". */
const RANGE = /^(\d{4}-\d{2}(?:-\d{2})?)\s*\.\.\s*(\d{4}-\d{2}(?:-\d{2})?)$/;

/** {"learn":"2023-07..2024-12"} → "Learned on Jul 2023 – Dec 2024" (day-precise ranges read by month too). */
export function splitText(split: Record<string, string> | undefined) {
  return Object.entries(split ?? {}).map(([key, raw]) => {
    const m = String(raw).match(RANGE);
    return { key, label: SPLIT_LABEL[key] ?? key.replace(/_/g, " "), value: m ? `${periodLabel(m[1].slice(0, 7))} – ${periodLabel(m[2].slice(0, 7))}` : String(raw) };
  });
}

/** Does a split range include a date? Month ranges include the whole end month. */
export function rangeIncludes(raw: string | undefined, isoDate: string) {
  const m = String(raw ?? "").match(RANGE);
  if (!m) return false;
  const lo = m[1].length === 7 ? `${m[1]}-01` : m[1];
  const hi = m[2].length === 7 ? `${m[2]}-31` : m[2];
  const d = isoDate.slice(0, 10);
  return d >= lo && d <= hi;
}

/** Confidence.kind order from the contract, then anything else the report adds. */
const KIND_ORDER = ["cause", "voucher", "release", "claim_validity"];
export const KIND_LABEL: Record<string, string> = { cause: "Cause-finding", voucher: "Voucher in lieu", release: "Cohort release", claim_validity: "Claim validity" };

export function orderedKinds(cal: Record<string, unknown>) {
  const keys = Object.keys(cal);
  return [...KIND_ORDER.filter((k) => keys.includes(k)), ...keys.filter((k) => !KIND_ORDER.includes(k)).sort()];
}
