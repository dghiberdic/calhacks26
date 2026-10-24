import { describe, expect, it } from "vitest";
import { count, duration, eur, pct, routedTo, shortId, zulu, zuluDay } from "./format";

describe("format", () => {
  it("writes cents as euros, negatives in parentheses", () => {
    expect(eur(3_465_000)).toBe("€34,650");
    expect(eur(-360_000)).toBe("(€3,600)");
    expect(eur(399_000, { signed: true })).toBe("+€3,990");
    expect(eur(0)).toBe("€0");
    expect(eur(null)).toBe("—");
  });
  it("writes counts and percentages", () => {
    expect(count(5292)).toBe("5,292");
    expect(pct(0.91)).toBe("91%");
  });
  it("writes UTC times with Z", () => {
    expect(zulu("2025-01-23T21:40:00Z")).toBe("21:40Z");
    expect(zuluDay("2025-01-23T21:40:00Z")).toBe("23 Jan 21:40Z");
  });
  it("shortens IDs and routes", () => {
    expect(shortId("NS31@2025-01-24")).toBe("NS31");
    expect(shortId("NS31@2025-01-24:14C")).toBe("NS31 · 14C");
    expect(routedTo("claims_lead")).toBe("Routed to the Claims Lead");
    expect(duration(90)).toBe("1 h 30 min");
  });
});
