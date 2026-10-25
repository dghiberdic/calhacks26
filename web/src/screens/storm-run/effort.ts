import type { LearningStep } from "@/api/types";
import { count, eur } from "@/lib/format";

/**
 * The by-hand estimate is an estimate, so its totals are said roughly (insights spec): hours to the nearest 5,
 * euros to the nearest €100. 451.4 → "about 450 hours"; anything that rounds to 0 reads "under 5 hours".
 */
export function roughHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours) || hours <= 0) return "no hours";
  const r = Math.round(hours / 5) * 5;
  return r === 0 ? "under 5 hours" : `about ${count(r)} hours`;
}

/** 1,742,915 cents → "€17,400". */
export function roughEur(cents: number | null | undefined): string {
  if (cents === null || cents === undefined || !Number.isFinite(cents)) return eur(null);
  return eur(Math.round(cents / 10_000) * 10_000);
}

/** One line's hours in the table: "318 h", "1.5 h", "45 min", "0 h". */
export function hoursCell(hours: number): string {
  if (!Number.isFinite(hours) || hours <= 0) return "0 h";
  if (hours < 1) return `${Math.max(5, Math.round((hours * 60) / 5) * 5)} min`;
  if (hours < 10) return `${Number(hours.toFixed(1))} h`;
  return `${count(Math.round(hours))} h`;
}

/**
 * The reuse line for a run after the first: how many learned rules it reused and the cases they settled.
 * null for the first run on the timeline, a run that isn't on it, or one that reused nothing.
 */
export function reuseFor(steps: LearningStep[] | undefined, runId: string): { rules: number; cases: number } | null {
  const i = (steps ?? []).findIndex((s) => s.run_id === runId);
  if (i < 1) return null;
  const step = steps![i];
  return step.reused.length ? { rules: step.reused.length, cases: step.cases_settled_by_reused_rules } : null;
}
