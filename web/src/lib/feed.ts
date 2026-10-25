import type { Cents, TraceEvent } from "@/api/types";

/** An event's shape: its chip, actor and kind, and its summary with ids and amounts blanked. */
const shapeOf = (e: TraceEvent) =>
  `${e.chip}|${e.actor}|${e.kind}|${e.summary.replace(/\b[A-Z]{2,3}\d+[A-Z]?(?:@[\w:.-]+)?/g, "#").replace(/[€$]?\d[\d,.:]*/g, "#")}`;

export type FeedItem = { kind: "one"; event: TraceEvent } | { kind: "run"; key: string; events: TraceEvent[]; cents: Cents | null };

/**
 * The live feed with runs folded: `min` or more consecutive events of the same shape (172 "Drafted Dr 4090 /
 * Cr 2140 for …" in a row) become one row with their count and, when every one has an amount, their total.
 * Shared by the Trace's Live tab and the Desk's day result.
 */
export function collapseRuns(events: TraceEvent[], min = 4): FeedItem[] {
  const out: FeedItem[] = [];
  for (let i = 0; i < events.length; ) {
    const shape = shapeOf(events[i]);
    let j = i + 1;
    while (j < events.length && shapeOf(events[j]) === shape) j++;
    const run = events.slice(i, j);
    if (run.length >= min) {
      const cents = run.every((e) => e.amount_cents !== null && e.amount_cents !== undefined) ? run.reduce((t, e) => t + (e.amount_cents ?? 0), 0) : null;
      out.push({ kind: "run", key: `run-${run[0].seq}`, events: run, cents });
    } else for (const e of run) out.push({ kind: "one", event: e });
    i = j;
  }
  return out;
}
