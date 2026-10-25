import { describe, expect, it } from "vitest";
import type { EvalReport } from "@/api/types";
import { axisMax, headline, injectionSummary, liabilityVsActual, measures, orderedKinds, placeLabels, rangeIncludes, ratioText, readRuns, runLabel, sameAnswer, settledAlone, splitText } from "./model";

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
    expect(headline(readRuns({ runs: 0, liability_eur: [], status: "not_run_missing_credentials" }), readRuns(stormcheck)).baseline).toBe("Plain Claude baseline: not run yet.");
  });
  it("says the same answer every run in words", () => {
    expect(sameAnswer(readRuns(stormcheck))).toBe("€34,650 on all 3 runs, with the same hash.");
    expect(sameAnswer(readRuns({ runs: 2, liability_eur: [34650, 34651], hash_identical: false }))).toBe("The runs disagreed: €34,650 / €34,651.");
    expect(sameAnswer(readRuns({}))).toBe(null);
  });
  it("puts the axis at a round number above everything", () => {
    expect(axisMax([41580, 99000, 27720, 34650])).toBe(100000);
    expect(axisMax([34650])).toBe(40000);
    expect(axisMax([])).toBe(1);
  });
});

describe("settled alone", () => {
  const bin = (lo: number, accuracy: number, n: number) => ({ lo, hi: lo + 0.2, accuracy, n, wilson_lo: 0, wilson_hi: 1 });
  const report = (over: Partial<EvalReport>) => ({ liability_vs_actual: {}, calibration: {}, ...over }) as EvalReport;
  it("reads the outcome classes when the report has them: right of those settled with no person", () => {
    expect(settledAlone(report({ liability_vs_actual: { auto_correct: 54, auto_wrong: 3, auto_precision: 0.947 } }))).toEqual({ right: 54, n: 57, share: 54 / 57, basis: "auto", from: null });
  });
  it("falls back to the calibration bins at 90% and up, else 80% and up, and says which", () => {
    const cal = { cause: [bin(0, 0, 34), bin(0.6, 0.43, 14), bin(0.8, 0.939394, 33)] };
    expect(settledAlone(report({ calibration: cal }))).toEqual({ right: 31, n: 33, share: 31 / 33, basis: "confidence", from: 0.8 });
    expect(settledAlone(report({ calibration: { cause: [bin(0.8, 0.5, 10), { ...bin(0.9, 1, 20), hi: 1 }] } }))).toMatchObject({ right: 20, n: 20, from: 0.9 });
  });
  it("is null when nothing says it", () => {
    expect(settledAlone(report({}))).toBe(null);
    expect(settledAlone(report({ calibration: { cause: [bin(0.2, 0.7, 7)] } }))).toBe(null);
  });
});

describe("measures", () => {
  it("formats each measure by what its key says it is", () => {
    const m = measures({ preview_eur: 826616, flight_cause_and_extraordinary_accuracy: 0.4842105, non_golden_cancellations: 64, auto_flights_pct: 33.3333, m1: 0.97 });
    expect(m).toEqual([
      { key: "preview_eur", label: "preview", text: "€826,616" },
      { key: "flight_cause_and_extraordinary_accuracy", label: "flight cause and extraordinary accuracy", text: "48%" },
      { key: "non_golden_cancellations", label: "non golden cancellations", text: "64" },
      { key: "auto_flights_pct", label: "auto flights", text: "33.3%" },
      { key: "m1", label: "M1", text: "97% of actual" },
    ]);
  });
  it("reads liability vs actual as ratios when given, else expected against claimed so far", () => {
    expect(liabilityVsActual({ m1: 0.97, m3: 1.02 })).toEqual({ value: ["M1 97% of actual", "M3 102% of actual"], sub: "drafted liability as a share of the claims that actually came" });
    expect(liabilityVsActual({ ultimate_expected_eur: 578650, valid_claims_through_2026_06_30_eur: 438575 })).toEqual({ value: ["€578,650 expected", "€438,575 claimed"], sub: "expected ultimate claims against valid claims through 30 Jun 2026" });
    expect(liabilityVsActual({ preview_eur: 1 })).toBe(null);
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
  it("reads facts-only extractions as blocked when the report doesn't say blocked", () => {
    expect(injectionSummary({ attempted: 2, facts_only: 2, unsafe_extractions: 0 })).toEqual({ blocked: 2, total: 2, rest: [{ key: "unsafe_extractions", label: "unsafe extractions", value: 0 }] });
  });
  it("orders decision kinds the way the contract lists them", () => {
    expect(orderedKinds({ voucher: [], zeta: [], cause: [], claim_validity: [] })).toEqual(["cause", "voucher", "claim_validity", "zeta"]);
  });
});
