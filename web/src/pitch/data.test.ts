import { describe, expect, it } from "vitest";
import type { CfoMetrics, EvalReport, Question, StormRun } from "@/api/types";
import { claimRate, learnedFacts, monthRange, payoutsDrafted, proofOf, voucherQuestion } from "./data";

const question = (over: Partial<Question>): Question =>
  ({ id: "Q", case_refs: [], pattern: "other", routed_to: "legal", asked_at: "", title: "", found: "", why_flagged: "", recommends: "", recommended_option: "", options: [], evidence: [], confidence: { score: 0.5, kind: "cause", label: "", features: {}, calibration_version: "" }, reason_tag: "no-precedent", ...over }) as Question;

describe("learnedFacts", () => {
  it("splits packed items into short facts and keeps the support on the last one", () => {
    const facts = learnedFacts([
      { text: "Read 18 months of claims · 35% of owed long-haul passengers claim · takes the 50% reroute cut", support: "41 of 42" },
      { text: "Something else", support: "n" },
    ]);
    expect(facts).toEqual([
      { text: "Read 18 months of claims", support: undefined },
      { text: "35% of owed long-haul passengers claim", support: undefined },
      { text: "Takes the 50% reroute cut", support: "41 of 42" },
    ]);
  });
  it("takes whole items when they are already short", () => {
    expect(learnedFacts([{ text: "a", support: null }, { text: "b", support: "2 of 2" }])).toEqual([
      { text: "A", support: undefined },
      { text: "B", support: "2 of 2" },
    ]);
    expect(learnedFacts(undefined)).toEqual([]);
  });
});

describe("selectors", () => {
  it("finds Q1 by pattern, then by the Claims Lead", () => {
    const run = { questions: [question({ id: "Q-2", routed_to: "legal" }), question({ id: "Q-1", routed_to: "claims_lead", pattern: "voucher_in_lieu_unsigned" })] } as unknown as StormRun;
    expect(voucherQuestion(run)?.id).toBe("Q-1");
    const fallback = { questions: [question({ id: "Q-9", routed_to: "claims_lead" })] } as unknown as StormRun;
    expect(voucherQuestion(fallback)?.id).toBe("Q-9");
  });

  it("reads payouts from the counters, else from the recoded flight", () => {
    expect(payoutsDrafted({ counters: { drafted: 172 }, flights: [] } as unknown as StormRun)).toBe(172);
    const run = { counters: {}, flights: [{ flight: { pax: 99 }, decision: { recoded: true } }] } as unknown as StormRun;
    expect(payoutsDrafted(run)).toBe(99);
  });

  it("derives the claim rate from the CFO numbers, never assumes one", () => {
    expect(claimRate({ drafted_liability_cents: 3_465_000, full_entitlement_cents: 9_900_000 } as CfoMetrics)).toBeCloseTo(0.35);
    expect(claimRate({ drafted_liability_cents: 1, full_entitlement_cents: 0 } as CfoMetrics)).toBeUndefined();
    expect(claimRate(undefined)).toBeUndefined();
  });

  it("reads the proof from the eval report (euros, not cents)", () => {
    const p = proofOf({ split: { learn: "2023-07..2024-12", score: "2025-01..2025-06" }, baseline: { liability_eur: [0, 41580, "x"], hash_identical: false }, stormcheck_runs: { liability_eur: [34650, 34650, 34650], hash_identical: true }, miscodes_caught: 11, miscodes_total: 12 } as unknown as EvalReport);
    expect(p?.baselineEur).toEqual([0, 41580]);
    expect(p?.stormcheckSameHash).toBe(true);
    expect(p?.miscodes).toEqual({ caught: 11, total: 12 });
    expect(monthRange(p?.learn)).toBe("Jul 2023 – Dec 2024");
    expect(monthRange("spring")).toBe("spring");
  });

  it("reads straight-through as a fraction whether the eval sends 96.4 or 0.964 (it showed 9640%)", () => {
    expect(proofOf({ straight_through_pct: 96.4 } as unknown as EvalReport)?.straightThrough).toBeCloseTo(0.964);
    expect(proofOf({ straight_through_pct: 0.964 } as unknown as EvalReport)?.straightThrough).toBeCloseTo(0.964);
    expect(proofOf({} as unknown as EvalReport)?.straightThrough).toBeUndefined();
  });
});
