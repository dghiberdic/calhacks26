import { describe, expect, it } from "vitest";
import { plainIds } from "./plain";

describe("plainIds", () => {
  it("names storm cohorts and segments in words, and leaves flight ids alone", () => {
    expect(plainIds("Reduce the EIDW@2024-01-21 long_haul_gt3500 cohort to nil at M12?")).toBe("Reduce the Storm Isha (21 Jan 2024) long-haul cohort to nil at M12?");
    expect(plainIds("NS31@2025-01-24 stays")).toBe("NS31@2025-01-24 stays");
    expect(plainIds("LPPT@2025-04-28")).toBe("Lisbon, 28 Apr 2025");
    expect(plainIds("IFRS 15.56 constraint · short_le1500 20%")).toBe("IFRS 15.56 constraint · short-haul 20%");
    expect(plainIds("a short delay")).toBe("a short delay");
  });
});
