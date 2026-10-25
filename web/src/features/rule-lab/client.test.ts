import { afterEach, describe, expect, it, vi } from "vitest";
import scoped from "./recorded/scoped.json";
import { loadRuleLabReport } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("Rule Lab evidence transport", () => {
  it("shows a fresh engine result as live evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(scoped))));
    const result = await loadRuleLabReport("scoped");
    expect(result.source).toBe("live");
    expect(result.report.verdict).toBe("ready_for_review");
    expect(result.report.summary.intended_cases).toBe(32);
  });
});

it("keeps the story usable without a lab server and labels saved results", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  const result = await loadRuleLabReport("broader_scope");
  expect(result.source).toBe("recorded");
  expect(result.report.verdict).toBe("blocked");
  expect(result.report.cases.find(c => c.id === "non-eu-boundary")?.passed).toBe(false);
});

it("does not show a result for the wrong candidate as live evidence", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(scoped))));
  const result = await loadRuleLabReport("wrong_authority");
  expect(result.source).toBe("recorded");
  expect(result.report.verdict).toBe("blocked");
  expect(result.report.simulation_ran).toBe(false);
});

it("rejects a malformed passing result", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({...scoped, checks: []}))));
  expect((await loadRuleLabReport("scoped")).source).toBe("recorded");
});

it("cancels a superseded request without substituting saved evidence", async () => {
  const controller = new AbortController(); controller.abort();
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  await expect(loadRuleLabReport("scoped", controller.signal)).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
