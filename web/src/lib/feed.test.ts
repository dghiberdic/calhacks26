import { describe, expect, it } from "vitest";
import type { TraceEvent } from "@/api/types";
import { collapseRuns } from "./feed";

describe("collapsing the live feed", () => {
  const ev = (seq: number, summary: string, over: Partial<TraceEvent> = {}): TraceEvent => ({ seq, at: "2025-01-24T09:02:00Z", kind: "journal", actor: "agent.engine", summary, chip: "DRAFTED", amount_cents: 60_000, ...over });
  const drafted = (seq: number, flight: string) => ev(seq, `Drafted Dr 4090 / Cr 2140 for ${flight}@2025-01-24:${seq}A · drafted, pending approval`, { ref: `${flight}@2025-01-24:${seq}A` });
  it("folds a run of same-shaped events into one row with its count and total", () => {
    const items = collapseRuns([ev(9, "Asked Legal: one question, three flights", { chip: "ASKED", amount_cents: null }), drafted(8, "NS31"), drafted(7, "NS31"), drafted(6, "NS113"), drafted(5, "NS113"), ev(4, "Read 80 METAR obs", { chip: "INFO", amount_cents: null })]);
    expect(items.map((i) => (i.kind === "run" ? `run ${i.events.length} ${i.cents}` : `one ${i.event.seq}`))).toEqual(["one 9", "run 4 240000", "one 4"]);
  });
  it("leaves short runs alone, and totals only when every event has an amount", () => {
    expect(collapseRuns([drafted(3, "NS31"), drafted(2, "NS31"), drafted(1, "NS31")]).every((i) => i.kind === "one")).toBe(true);
    const run = collapseRuns([drafted(4, "NS31"), drafted(3, "NS31"), { ...drafted(2, "NS31"), amount_cents: null }, drafted(1, "NS31")])[0];
    expect(run).toMatchObject({ kind: "run", cents: null });
  });
  it("never folds events from different actors or chips", () => {
    expect(collapseRuns([drafted(4, "NS31"), { ...drafted(3, "NS31"), actor: "agent.drafter" }, drafted(2, "NS31"), { ...drafted(1, "NS31"), chip: "HELD" }])).toHaveLength(4);
  });
});
