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
    baseline: `Plain Claude, ${baseline.runs} runs: ${list(baseline)}.`,
    stormcheck: sc.allSame ? `StormCheck: ${euros(sc.values[0])} ×${sc.runs}, ${hash(sc)}.` : `StormCheck, ${sc.runs} runs: ${list(sc)}, ${hash(sc)}.`,
  };
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

export function injectionSummary(d: Record<string, number> | undefined) {
  if (!d) return null;
  const blocked = num(d.blocked);
  const total = num(d.attempted) ?? num(d.total) ?? num(d.tried);
  return blocked !== null && total !== null ? { blocked, total } : null;
}

const SPLIT_LABEL: Record<string, string> = { learn: "Learned on", train: "Learned on", score: "Scored on", test: "Scored on" };

/** {"learn":"2023-07..2024-12"} → "Learned on Jul 2023 – Dec 2024". */
export function splitText(split: Record<string, string> | undefined) {
  return Object.entries(split ?? {}).map(([key, raw]) => {
    const m = String(raw).match(/^(\d{4}-\d{2})\s*\.\.\s*(\d{4}-\d{2})$/);
    return { key, label: SPLIT_LABEL[key] ?? key.replace(/_/g, " "), value: m ? `${periodLabel(m[1])} – ${periodLabel(m[2])}` : String(raw) };
  });
}

/** Does a "YYYY-MM..YYYY-MM" range include a date? */
export function rangeIncludes(raw: string | undefined, isoDate: string) {
  const m = String(raw ?? "").match(/^(\d{4}-\d{2})\s*\.\.\s*(\d{4}-\d{2})$/);
  if (!m) return false;
  const ym = isoDate.slice(0, 7);
  return ym >= m[1] && ym <= m[2];
}

/** Confidence.kind order from the contract, then anything else the report adds. */
const KIND_ORDER = ["cause", "voucher", "release", "claim_validity"];
export const KIND_LABEL: Record<string, string> = { cause: "Cause-finding", voucher: "Voucher in lieu", release: "Cohort release", claim_validity: "Claim validity" };

export function orderedKinds(cal: Record<string, unknown>) {
  const keys = Object.keys(cal);
  return [...KIND_ORDER.filter((k) => keys.includes(k)), ...keys.filter((k) => !KIND_ORDER.includes(k)).sort()];
}
