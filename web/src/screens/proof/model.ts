import type { EvalReport } from "@/api/types";
import { count, eur, longDate, pct, periodLabel } from "@/lib/format";

/** One set of repeated runs, read defensively from the contract's loosely typed dictionaries (liability in euros). */
export type Runs = {
  runs: number;
  values: number[];
  allSame: boolean;
  hashIdentical: boolean | null;
  model: string | null;
  hash: string | null;
  accuracy: number[];
  /** "complete", or why a side wasn't run ("not_run_missing_credentials"). */
  status: string | null;
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
    status: typeof d?.status === "string" ? d.status : null,
  };
}

/** Liability in euros (the eval reports euros, not cents). */
export const euros = (v: number) => eur(Math.round(v * 100));

/** "Plain Claude, 3 runs: €a / €b / €c." and "StormCheck: €34,650 ×3, same hash." from the report. */
export function headline(baseline: Runs, sc: Runs) {
  const list = (r: Runs) => r.values.map(euros).join(" / ");
  const hash = (r: Runs) => (r.hashIdentical === true ? "same hash" : r.hashIdentical === false ? "hashes differ" : "hash not reported");
  return {
    baseline: baseline.values.length ? `Plain Claude, ${baseline.runs} runs: ${list(baseline)}.` : baseline.status && baseline.status !== "complete" ? "Plain Claude baseline: not run yet." : "Plain Claude baseline: not reported.",
    stormcheck: !sc.values.length ? "StormCheck runs: not reported." : sc.allSame ? `StormCheck: ${euros(sc.values[0])} ×${sc.runs}, ${hash(sc)}.` : `StormCheck, ${sc.runs} runs: ${list(sc)}, ${hash(sc)}.`,
  };
}

/** "€34,650 on all 3 runs, with the same hash." in words; null when the runs weren't reported. */
export function sameAnswer(sc: Runs) {
  if (!sc.values.length) return null;
  if (!sc.allSame) return `The runs disagreed: ${sc.values.map(euros).join(" / ")}.`;
  const runs = sc.runs === 1 ? "1 run" : `all ${sc.runs} runs`;
  return `${euros(sc.values[0])} on ${runs}${sc.hashIdentical === true ? ", with the same hash" : sc.hashIdentical === false ? ", but the hashes differ" : ""}.`;
}

/**
 * "Of the flights it settles alone, the share that is right." From the outcome classes when the report has
 * them (auto_correct, auto_wrong in liability_vs_actual); else from the cause calibration bins at the
 * auto-decide line (90%) and up, else at 80% and up, saying which. Null when neither is there.
 */
export function settledAlone(r: EvalReport): { right: number; n: number; share: number; basis: "auto" | "confidence"; from: number | null } | null {
  const lva = (r.liability_vs_actual ?? {}) as Record<string, unknown>;
  const right = num(lva.auto_correct);
  const wrong = num(lva.auto_wrong);
  if (right !== null && wrong !== null && right + wrong > 0) return { right, n: right + wrong, share: right / (right + wrong), basis: "auto", from: null };
  const bins = (r.calibration?.cause ?? []).filter((b) => b.n > 0);
  const from = (lo: number) => bins.filter((b) => b.lo >= lo - 1e-9);
  const top = from(0.9).length ? from(0.9) : from(0.8);
  if (!top.length) return null;
  const n = top.reduce((t, b) => t + b.n, 0);
  const ok = Math.round(top.reduce((t, b) => t + b.accuracy * b.n, 0));
  return { right: ok, n, share: ok / n, basis: "confidence", from: Math.min(...top.map((b) => b.lo)) };
}

/** A measure's words from its key: "preview_eur" → "preview", "m1" → "M1". */
const measureLabel = (key: string) => (/^m\d+$/i.test(key) ? key.toUpperCase() : key.replace(/_(eur|pct)$/, "").replace(/_/g, " "));

/** Each measure, formatted by what its key says it is: euros, a share, a percentage, a ratio to actual, or a count. */
export function measures(d: Record<string, number> | undefined) {
  return Object.entries(d ?? {})
    .filter(([, v]) => num(v) !== null)
    .map(([key, v]) => {
      const text = /_eur$/.test(key)
        ? euros(v)
        : /_pct$/.test(key)
          ? `${v.toFixed(1)}%`
          : /^m\d+$/i.test(key)
            ? ratioText(v)
            : /accuracy|precision|right_or/.test(key)
              ? pct(v)
              : Number.isInteger(v)
                ? count(v)
                : v.toFixed(2);
      return { key, label: measureLabel(key), text };
    });
}

/** "Liability vs actual": ratios by month when the report has them, else expected against claimed so far. */
export function liabilityVsActual(d: Record<string, number> | undefined): { value: string[]; sub: string } | null {
  const lva = d ?? {};
  const ratios = Object.entries(lva)
    .filter(([k, v]) => /^m\d+$/i.test(k) && num(v) !== null)
    .sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1)));
  if (ratios.length) return { value: ratios.map(([k, v]) => `${k.toUpperCase()} ${ratioText(v)}`), sub: "drafted liability as a share of the claims that actually came" };
  const expected = num(lva.ultimate_expected_eur);
  const claimedKey = Object.keys(lva).find((k) => /^valid_claims.*_eur$/.test(k));
  const claimed = claimedKey ? num(lva[claimedKey]) : null;
  if (expected === null || claimed === null) return null;
  const through = claimedKey!.match(/(\d{4})_(\d{2})_(\d{2})/);
  return { value: [`${euros(expected)} expected`, `${euros(claimed)} claimed`], sub: `expected ultimate claims against valid claims${through ? ` through ${longDate(`${through[1]}-${through[2]}-${through[3]}`)}` : " so far"}` };
}

/** "€0 · cash basis" / "€99,000 · full entitlement" when a run lands exactly on one of the bridge's ends. */
export function runLabel(valueEur: number, anchors: { cashCents: number; fullCents: number } | null) {
  const cents = Math.round(valueEur * 100);
  if (anchors && cents === anchors.cashCents) return `${euros(valueEur)} · cash basis`;
  if (anchors && cents === anchors.fullCents) return `${euros(valueEur)} · full entitlement`;
  return euros(valueEur);
}

/** Where a label sits on an axis of width `iw`: start-anchored at the left edge, end-anchored at the right, centred between. */
function labelSpan(x: number, w: number, iw: number): [number, number] {
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
  // "facts_only": attempts where the Reader extracted only quoted facts, which is what blocked means here.
  const blockedKey = ["blocked", "facts_only"].find((k) => num(d[k]) !== null);
  if (!blockedKey) return null;
  const blocked = num(d[blockedKey])!;
  const totalKey = ["attempted", "total", "tried"].find((k) => num(d[k]) !== null);
  const rest = Object.entries(d)
    .filter(([k]) => k !== blockedKey && k !== totalKey)
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
