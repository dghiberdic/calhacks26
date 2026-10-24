import { describe, expect, it } from "vitest";
import { axisMax, headline, placeLabels, runLabel, injectionSummary, orderedKinds, rangeIncludes, readRuns, ratioText, splitText } from "./model";

const baseline = { model: "claude-opus-5-5", runs: 3, liability_eur: [41580, 99000, 27720], cause_accuracy: [0.74, 0.81, 0.69], hash_identical: false };
const stormcheck = { runs: 3, liability_eur: [34650, 34650, 34650], hash_identical: true, hash: "9f2c41d07be35a18" };

describe("runs", () => {
  it("reads the loosely typed run dictionaries", () => {
    const b = readRuns(baseline);
    expect(b.runs).toBe(3);
    expect(b.values).toEqual([41580, 99000, 27720]);
    expect(b.hashIdentical).toBe(false);
    expect(b.model).toBe("claude-opus-5-5");
    expect(b.accuracy).toEqual([0.74, 0.81, 0.69]);
    const s = readRuns(stormcheck);
    expect(s.allSame).toBe(true);
    expect(s.hash).toBe("9f2c41d07be35a18");
  });
  it("survives missing or odd fields", () => {
    const r = readRuns({ liability_eur: ["12", null, 7], hash_identical: "yes" } as unknown as Record<string, unknown>);
    expect(r.values).toEqual([12, 7]);
    expect(r.runs).toBe(2);
    expect(r.hashIdentical).toBe(null);
    expect(readRuns(undefined).values).toEqual([]);
  });
  it("writes the headline from the numbers", () => {
    const h = headline(readRuns(baseline), readRuns(stormcheck));
    expect(h.baseline).toBe("Plain Claude, 3 runs: €41,580 / €99,000 / €27,720.");
    expect(h.stormcheck).toBe("StormCheck: €34,650 ×3, same hash.");
  });
  it("says so when StormCheck's runs disagree", () => {
    const h = headline(readRuns(baseline), readRuns({ runs: 2, liability_eur: [34650, 34651], hash_identical: false }));
    expect(h.stormcheck).toBe("StormCheck, 2 runs: €34,650 / €34,651, hashes differ.");
  });
  it("says plainly when a side wasn't run", () => {
    const h = headline(readRuns(undefined), readRuns(stormcheck));
    expect(h.baseline).toBe("Plain Claude baseline: not reported.");
    expect(headline(readRuns(baseline), readRuns({})).stormcheck).toBe("StormCheck runs: not reported.");
  });
  it("puts the axis at a round number above everything", () => {
    expect(axisMax([41580, 99000, 27720, 34650])).toBe(100000);
    expect(axisMax([34650])).toBe(40000);
    expect(axisMax([])).toBe(1);
  });
});

describe("run labels", () => {
  it("names a run that landed exactly on the cash basis or the full entitlement", () => {
    const anchors = { cashCents: 0, fullCents: 9_900_000 };
    expect(runLabel(0, anchors)).toBe("€0 · cash basis");
    expect(runLabel(99000, anchors)).toBe("€99,000 · full entitlement");
    expect(runLabel(41580, anchors)).toBe("€41,580");
    expect(runLabel(41580, null)).toBe("€41,580");
  });
  it("drops a label below its dot only when it would overlap the one before", () => {
    // x positions in px, label widths in px, anchored inside a 600px axis
    expect(placeLabels([{ x: 0, w: 90 }, { x: 250, w: 50 }, { x: 600, w: 150 }], 600)).toEqual(["above", "above", "above"]);
    expect(placeLabels([{ x: 100, w: 60 }, { x: 130, w: 60 }, { x: 160, w: 60 }], 600)).toEqual(["above", "below", "above"]);
  });
});

describe("scorecard", () => {
  it("reads liability vs actual as a share of actual", () => {
    expect(ratioText(0.97)).toBe("97% of actual");
    expect(ratioText(1.02)).toBe("102% of actual");
    expect(ratioText(0.03)).toBe("+3% vs actual");
    expect(ratioText(-0.04)).toBe("−4% vs actual");
  });
  it("summarises injections: blocked of attempted only when the report says attempted", () => {
    expect(injectionSummary({ attempted: 8, blocked: 8 })).toEqual({ blocked: 8, total: 8, rest: [] });
    expect(injectionSummary({ total: 9, blocked: 8 })).toEqual({ blocked: 8, total: 9, rest: [] });
    expect(injectionSummary({ rehearsed: 8, fuzz: 20, blocked: 3, escalated: 9, server_errors: 0 })).toEqual({
      blocked: 3,
      total: null,
      rest: [
        { key: "rehearsed", label: "rehearsed", value: 8 },
        { key: "fuzz", label: "fuzz", value: 20 },
        { key: "escalated", label: "escalated", value: 9 },
        { key: "server_errors", label: "server errors", value: 0 },
      ],
    });
    expect(injectionSummary({ weird: 1 })).toBe(null);
  });
  it("formats the learn/score split, by month or by day", () => {
    expect(splitText({ learn: "2023-07..2024-12", score: "2025-01..2025-06" })).toEqual([
      { key: "learn", label: "Learned on", value: "Jul 2023 – Dec 2024" },
      { key: "score", label: "Scored on", value: "Jan 2025 – Jun 2025" },
    ]);
    expect(splitText({ learn: "2023-07-01..2024-12-31" })[0].value).toBe("Jul 2023 – Dec 2024");
    expect(rangeIncludes("2025-01-01..2025-06-30", "2025-01-24")).toBe(true);
    expect(rangeIncludes("2023-07-01..2024-12-31", "2025-01-24")).toBe(false);
    expect(rangeIncludes("2025-01..2025-06", "2025-01-24")).toBe(true);
  });
  it("orders decision kinds the way the contract lists them", () => {
    expect(orderedKinds({ voucher: [], zeta: [], cause: [], claim_validity: [] })).toEqual(["cause", "voucher", "claim_validity", "zeta"]);
  });
});
