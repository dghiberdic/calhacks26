import { beforeEach, describe, expect, it } from "vitest";
import type { EffortEstimate, LearningStep } from "@/api/types";
import { roughEur, roughHours } from "@/screens/storm-run/effort";
import { createMockFetch, resetMockWorld } from ".";

const get = async <T>(path: string): Promise<{ status: number; body: T }> => {
  const res = await createMockFetch({ latencyMs: [0, 0] })(path, { method: "GET" });
  return { status: res.status, body: (await res.json()) as T };
};

beforeEach(() => resetMockWorld());

describe("mock insights", () => {
  it("estimates golden Éowyn at about 450 hours (≈ €17,000) by hand and about 45 with StormCheck", async () => {
    const { status, body } = await get<EffortEstimate>(`/runs/${encodeURIComponent("EIDW@2025-01-24")}/effort`);
    expect(status).toBe(200);
    expect(body.name).toBe("Storm Éowyn · 24 Jan 2025");
    expect(body.inputs).toMatchObject({ cancelled_flights: 27, passengers: 5292, questions: 3, month_ends: 18 });
    expect(roughHours(body.manual_hours)).toBe("about 450 hours");
    expect(roughHours(body.with_stormcheck_hours)).toBe("about 45 hours");
    expect(body.manual_cost_cents).toBeGreaterThan(1_650_000);
    expect(body.manual_cost_cents).toBeLessThan(1_800_000);
    expect(roughEur(body.manual_cost_cents)).toMatch(/^€17,\d00$/);
    expect(Number.isInteger(body.manual_cost_cents) && Number.isInteger(body.cost_saved_cents)).toBe(true);
    expect(body.lines.reduce((s, l) => s + l.manual_hours, 0)).toBeCloseTo(body.manual_hours, 6);
    expect(body.errors_caught).toEqual([
      expect.objectContaining({ label: "NS31 recoded 71 → 41", amount_cents: 9_900_000 }),
      expect.objectContaining({ label: "32 refunds the CRM bot had already made, not repeated", amount_cents: 1_632_000 }),
    ]);
  });

  it("estimates any other run from its own counts, and 404s an unknown one", async () => {
    const herminia = await get<EffortEstimate>(`/runs/${encodeURIComponent("EIDW@2025-01-26")}/effort`);
    expect(herminia.status).toBe(200);
    expect(herminia.body.manual_hours).toBeGreaterThan(herminia.body.with_stormcheck_hours);
    expect((await get(`/runs/${encodeURIComponent("EIDW@1999-01-01")}/effort`)).status).toBe(404);
  });

  it("tells the learning story: 3 → 1 → 1 questions, 31 voucher cases settled on Herminia", async () => {
    const { status, body } = await get<LearningStep[]>("/learning");
    expect(status).toBe(200);
    expect(body.map((s) => s.questions_asked)).toEqual([3, 1, 1]);
    expect(body[0].new_rules).toEqual(["R-CL-1@1", "R-LEG-1@1", "R-CTL-1@1"]);
    expect(body[1].reused).toEqual([expect.objectContaining({ rule_ref: "R-CL-1@1", cases: 31 })]);
    expect(body[2].new_rules).toEqual(["R-LEG-2@1"]);
  });
});
