import { describe, expect, it } from "vitest";
import type { JournalEntry } from "@/api/types";
import { bandMarginText, breakdownText, draftedLiability, electionsOf, featureLabel, legalGloss, markKind, reductionOf, splitRecode, statusesOf, summaryItems, summaryText } from "./lib";

describe("flight file helpers", () => {
  it("splits the recode so the losing code can be struck", () => {
    expect(splitRecode("71 → 41")).toEqual({ from: "71", to: "41" });
    expect(splitRecode("71->41")).toEqual({ from: "71", to: "41" });
    expect(splitRecode(null)).toBeNull();
  });

  it("states the band margin from the entitlement's own numbers", () => {
    expect(bandMarginText({ distance_km: 1486, band_eur: 250, band_margin_km: 14 })).toBe("1,486 km · 14 km under the €400 band");
    expect(bandMarginText({ distance_km: 4804, band_eur: 600, band_margin_km: 1304 })).toBe("4,804 km · 1,304 km into the €600 band");
    // The middle band can move either way; an unsigned margin doesn't say which edge is nearer.
    expect(bandMarginText({ distance_km: 1886, band_eur: 400, band_margin_km: 386 })).toBe("1,886 km · 386 km from the nearest band edge");
  });

  it("reads the drafted liability off the compensation-estimate journal (Cr 2140)", () => {
    const je = (kind: JournalEntry["kind"], cr: number): JournalEntry => ({
      id: "JE-1",
      event_date: "2025-01-24",
      period: "2025-01",
      memo: "",
      kind,
      status: "draft",
      preparer: "agent.engine",
      lines: [
        { account: "4090", account_name: "EU261 compensation", dr_cents: cr },
        { account: "2140", account_name: "EU261 compensation liability", cr_cents: cr },
      ],
    });
    expect(draftedLiability([je("compensation_estimate", 3_465_000), je("refund", 1_632_000)])).toBe(3_465_000);
    expect(draftedLiability([je("refund", 1)])).toBeNull();
  });

  it("formats the loose summary dict by key and keeps unknown keys", () => {
    const items = summaryItems({ coupons: 172, full_entitlement_cents: 9_900_000, claim_rate: 0.35, elections: { refund: 32 }, status_line: "172 payouts drafted", band_eur: 600, something_new: 3 });
    expect(items.map((i) => [i.label, i.text])).toEqual([
      ["Coupons", "172"],
      ["Full Art. 7 entitlement if every passenger claims", "€99,000"],
      ["Expected ultimate claim rate", "35%"],
      ["Something new", "3"],
    ]);
    expect(electionsOf({ elections: { reroute_partner: 14, refund: 32, voucher: 0 } })).toEqual([
      ["refund", 32],
      ["reroute_partner", 14],
    ]);
  });

  it("reads the server's own lines and nested figures", () => {
    const summary = {
      status_line: "172 payouts drafted, pending Claims Lead approval",
      statuses: { needs_ruling: 1, owed: 171 },
      compensation_breakdown: [
        { count: 158, band_eur: 600 },
        { count: 14, band_eur: 300 },
      ],
      reduction_7_2: { coupons: 14, rule_ref: "R-MIN-1@1", support: "41 of 42", label: "Art. 7(2)(c) 50% cut" },
    };
    expect(summaryText(summary, "status_line")).toBe("172 payouts drafted, pending Claims Lead approval");
    expect(summaryText(summary, "band_label")).toBeNull();
    expect(statusesOf(summary)).toEqual([
      ["owed", 171],
      ["needs_ruling", 1],
    ]);
    expect(breakdownText(summary)).toBe("158 × €600 + 14 × €300");
    expect(reductionOf(summary)).toEqual({ coupons: 14, ruleRef: "R-MIN-1@1", support: "41 of 42", label: "Art. 7(2)(c) 50% cut" });
  });

  it("names features, citations and timeline marks in plain words", () => {
    expect(featureLabel("aog_before_window")).toBe("Grounded before the storm");
    expect(featureLabel("brand_new_feature")).toBe("Brand new feature");
    expect(legalGloss("CJEU C-549/07")).toMatch(/Wallentin-Hermann/);
    expect(legalGloss("EU261 Art.5(3)")).toMatch(/extraordinary/);
    expect(markKind({ kind: "tech_log" })).toMatchObject({ label: "Tech log", machine: true });
    expect(markKind({ kind: "metar" }).tone).toBe("metar");
  });
});
