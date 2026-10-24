import { describe, expect, it } from "vitest";
import type { Rule } from "@/api/types";
import { byOrigin, caseClause, caseKeys, isId, splitSource, withoutCaseScope, droppedCaseKeys, familyFromHash, families, flightOf, originOf, parseSupport, regulationTitle, staticCardFacts, validFromText } from "./model";

const rule = (over: Partial<Rule>): Rule => ({
  id: "R-X-1",
  version: 1,
  kind: "voucher",
  scope: {},
  condition: { all: [] },
  action: "deny_offset",
  tier: "claims_lead_ruling",
  authority_required: "claims_lead",
  valid_from: "2025-01-24T00:00:00Z",
  recorded_at: "2025-01-25T09:00:00Z",
  status: "active",
  ...over,
});

describe("origin", () => {
  it("groups by where a rule came from", () => {
    expect(originOf(rule({ tier: "mined" }))).toBe("learned");
    expect(originOf(rule({ tier: "legal_ruling", action: "set_extraordinary" }))).toBe("ruled");
    expect(originOf(rule({ tier: "claims_lead_ruling" }))).toBe("ruled");
    expect(originOf(rule({ tier: "controller_ruling", kind: "release", action: "keep_tail" }))).toBe("rejected");
    expect(originOf(rule({ tier: "regulation" }))).toBe("regulation");
    expect(originOf(rule({ tier: "hard_control" }))).toBe("hard");
  });

  it("orders each group by precedence, then citations", () => {
    const groups = byOrigin([
      rule({ id: "R-CL-1", tier: "claims_lead_ruling", times_cited: 31 }),
      rule({ id: "R-LEG-1", tier: "legal_ruling", action: "set_extraordinary", times_cited: 3 }),
      rule({ id: "R-REG-2202", tier: "regulation", static_card: true }),
      rule({ id: "R-REG-7", tier: "regulation" }),
    ]);
    expect(groups.ruled.map((f) => f.id)).toEqual(["R-LEG-1", "R-CL-1"]);
    expect(groups.regulation.map((f) => f.id)).toEqual(["R-REG-7", "R-REG-2202"]);
  });
});

describe("versions", () => {
  it("applies the newest live version and keeps the rest as history", () => {
    const [f] = families([rule({ version: 2, status: "active", supersedes: "R-X-1@1" }), rule({ version: 1, status: "retired" })]);
    expect(f.versions.map((v) => v.version)).toEqual([1, 2]);
    expect(f.current.version).toBe(2);
    expect(f.pending).toBeNull();
  });

  it("shows a widened draft as pending until it is confirmed", () => {
    const [f] = families([rule({ version: 1, status: "active" }), rule({ version: 2, status: "proposed" })]);
    expect(f.current.version).toBe(1);
    expect(f.pending?.version).toBe(2);
  });

  it("keeps the active version in force while a newer one sits in shadow", () => {
    const [f] = families([rule({ version: 1, status: "active" }), rule({ version: 2, status: "shadow", supersedes: "R-X-1@1" })]);
    expect(f.current.version).toBe(1);
    expect(f.pending?.version).toBe(2);
  });

  it("shows a fresh ruling's shadow version as the card until it is confirmed", () => {
    const [f] = families([rule({ version: 1, status: "shadow" })]);
    expect(f.current.version).toBe(1);
    expect(f.pending).toBeNull();
  });

  it("falls back to the newest version when a revert retired everything", () => {
    const [f] = families([rule({ version: 1, status: "retired" })]);
    expect(f.current.version).toBe(1);
  });
});

describe("support, scope and dates", () => {
  it("reads mined support", () => {
    expect(parseSupport("41 of 42")).toEqual({ hits: 41, of: 42 });
    expect(parseSupport("1,204 of 1,210 decisions")).toEqual({ hits: 1204, of: 1210 });
    expect(parseSupport("most")).toBeNull();
    expect(parseSupport(null)).toBeNull();
  });

  it("finds the case-only scope a widen can drop", () => {
    const before = rule({ scope: { cohort: "case:EIDW@2024-01-21", "flight.departs_eu": true } });
    expect(caseKeys(before)).toEqual(["cohort"]);
    expect(droppedCaseKeys(before, rule({ scope: { "flight.departs_eu": true } }))).toEqual([{ key: "cohort", value: "EIDW@2024-01-21" }]);
    expect(droppedCaseKeys(before, before)).toEqual([]);
  });

  it("never states a scope key the condition already tests", () => {
    const r = rule({
      scope: { "voucher.in_lieu": true, "voucher.signed": false, "flight.departs_eu": true, "voucher.amount_cents": "case:30000" },
      condition: { all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { f: "voucher.signed", op: "eq", v: false }] },
    });
    expect(withoutCaseScope(r).scope).toEqual({ "flight.departs_eu": true });
  });

  it("splits a regulation's source line into citation, text and gloss", () => {
    expect(splitSource("EU261 Art. 5(3): extraordinary circumstances which could not have been avoided · weather inside the window")).toEqual({
      cite: "EU261 Art. 5(3)",
      body: "extraordinary circumstances which could not have been avoided",
      gloss: "weather inside the window",
    });
    expect(splitSource("Preparer ≠ approver")).toEqual({ cite: null, body: "Preparer ≠ approver", gloss: null });
    expect(isId("NS31@2025-01-24:14C")).toBe(true);
    expect(isId("41 of 42 past reroutes")).toBe(false);
  });

  it("keeps case-only scope out of the sentence and names it plainly", () => {
    const r = rule({ scope: { cohort: "case:EIDW@2024-01-21", "flight.route_region": "case:EU_US", "flight.departs_eu": true } });
    expect(withoutCaseScope(r).scope).toEqual({ "flight.departs_eu": true });
    expect(caseClause("cohort", "case:EIDW@2024-01-21")).toBe("cohort = Storm Isha");
    expect(caseClause("curve.segment", "case:long_haul_gt3500")).toBe("segment = long haul gt3500");
    expect(caseClause("flight.route_region", "case:EU_US")).toBe("the route is EU–US");
  });

  it("says when a null valid_from applies to past flights", () => {
    expect(validFromText(rule({ valid_from: null })).short).toBe("past flights too");
    expect(validFromText(rule({ valid_from: "2025-03-01T00:00:00Z" })).short).toBe("from 1 Mar 2025");
  });
});

describe("static regulation card", () => {
  it("takes its dates and window from the rule", () => {
    const reg = rule({
      id: "R-REG-2026-2202",
      tier: "regulation",
      static_card: true,
      recorded_at: "2026-10-22T00:00:00Z",
      valid_from: "2027-10-23T00:00:00Z",
      condition: { all: [{ f: "claim.age_months", op: "le", v: 9 }] },
    });
    const facts = staticCardFacts(reg);
    expect(facts.title).toBe("Reg (EU) 2026/2202");
    expect(facts.inForce).toBe("2026-10-22T00:00:00Z");
    expect(facts.appliesFrom).toBe("2027-10-23T00:00:00Z");
    expect(facts.claimWindowMonths).toBe(9);
  });

  it("prefers the title the rule gives itself", () => {
    expect(regulationTitle({ id: "R-REG-1", origin_example: "Reg (EU) 2026/2202 · in force 22 Oct 2026" })).toBe("Reg (EU) 2026/2202");
    expect(regulationTitle({ id: "R-REG-EU261", origin_example: null })).toBe("R-REG-EU261");
  });
});

describe("links", () => {
  it("reads deep links and origin examples", () => {
    expect(familyFromHash("#R-CL-1@1")).toBe("R-CL-1");
    expect(familyFromHash("#R-LEG-1")).toBe("R-LEG-1");
    expect(familyFromHash("")).toBeNull();
    expect(flightOf("NS31@2025-01-24:14C")).toBe("NS31@2025-01-24");
    expect(flightOf("EIDW@2024-01-21")).toBeNull();
  });
});
