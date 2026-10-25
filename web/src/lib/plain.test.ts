import { describe, expect, it } from "vitest";
import { plainIds, plainMemo } from "./plain";

describe("plainIds", () => {
  it("names storm cohorts and segments in words, and leaves flight ids alone", () => {
    expect(plainIds("Reduce the EIDW@2024-01-21 long_haul_gt3500 cohort to nil at M12?")).toBe("Reduce the Storm Isha (21 Jan 2024) long-haul cohort to nil at M12?");
    expect(plainIds("NS31@2025-01-24 stays")).toBe("NS31@2025-01-24 stays");
    expect(plainIds("LPPT@2025-04-28")).toBe("Lisbon, 28 Apr 2025");
    expect(plainIds("IFRS 15.56 constraint · short_le1500 20%")).toBe("IFRS 15.56 constraint · short-haul 20%");
    expect(plainIds("a short delay")).toBe("a short delay");
  });
});

describe("plainMemo", () => {
  it("writes the books' money as euros without zero cents, and flight ids as words", () => {
    expect(plainMemo("EU261 compensation liability (estimated) · NS31@2025-01-24 · full Art. 7 entitlement €99,000.00 × 35% = €34,650.00")).toBe(
      "EU261 compensation liability (estimated) · NS31 · 24 Jan · full Art. 7 entitlement €99,000 × 35% = €34,650",
    );
    expect(plainMemo("Service-desk voucher in lieu of compensation · NS31@2025-01-24:14C: €300.00, unsigned")).toBe("Service-desk voucher in lieu of compensation · NS31 · 24 Jan · 14C: €300, unsigned");
    expect(plainMemo("excess €1,234.50 → 6110 · retained -€3,600.00")).toBe("excess €1,234.50 → 6110 · retained (€3,600)");
    expect(plainMemo("Care accrued · EIDW@2025-01-24: 27 flights €5,000.00")).toBe("Care accrued · Storm Éowyn (24 Jan 2025): 27 flights €5,000");
    expect(plainMemo("out-of-period: event 2025-01-24 falls in locked period 2025-01; booked in open period 2025-02")).toBe(
      "out-of-period: event 24 Jan 2025 falls in locked period Jan 2025; booked in open period Feb 2025",
    );
    expect(plainMemo("NS31 · 14 refund vouchers at ticket value incl. taxes (€7,140) · Dr 2125 / Cr 1110")).toBe("NS31 · 14 refund vouchers at ticket value incl. taxes (€7,140) · Dr 2125 / Cr 1110");
  });
});
