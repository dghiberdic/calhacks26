import { describe, expect, it } from "vitest";
import type { BlameStep, Commit, FlightRow, Rule, StormRun } from "@/api/types";
import { suggestTargets, compareFrameworkRef, denialTag, evidenceTarget, isTab, orderPrincipals, principalLabel, principalRole, receiptText, ruleRefIn, shortHash, stepKind } from "./model";

const commit = (over: Partial<Commit> = {}): Commit => ({
  hash: "9f2c41ab77de0c55aa13",
  parent: null,
  kind: "fact",
  at: "2025-01-23T21:40:00Z",
  actor: "agent.reader",
  payload_hash: "p",
  payload_ref: "fact:1",
  message: "m",
  ...over,
});

describe("tabs and hashes", () => {
  it("accepts only the four tabs", () => {
    expect(isTab("blame")).toBe(true);
    expect(isTab("nope")).toBe(false);
    expect(isTab(null)).toBe(false);
  });
  it("prints a git-style prefix", () => {
    expect(shortHash("9f2c41ab77de0c55")).toBe("9f2c41a");
    expect(shortHash("sha256:9f2c41ab77", 8)).toBe("9f2c41ab");
    expect(shortHash(null)).toBe("");
  });
});

describe("principals", () => {
  it("finds the role in any principal spelling", () => {
    expect(principalRole("agent.drafter")).toBe("agent.drafter");
    expect(principalRole("claims_lead")).toBe("claims_lead");
    expect(principalRole("person:controller")).toBe("controller");
    expect(principalRole("legal:Niamh Walsh")).toBe("legal");
    expect(principalRole("agent:crm_bot")).toBe("agent.crm_bot");
    expect(principalRole("Claims Lead")).toBe("claims_lead");
    expect(principalRole("auditor.external")).toBeNull();
  });
  it("puts people before agents", () => {
    expect(orderPrincipals(["agent.drafter", "ops", "claims_lead", "agent.reader"])).toEqual(["claims_lead", "ops", "agent.reader", "agent.drafter"]);
  });
  it("labels principals for people", () => {
    expect(principalLabel("agent.drafter")).toBe("Drafter agent");
    expect(principalLabel("someone.else")).toBe("someone.else");
  });
});

describe("denials and controls", () => {
  it("names the reason a request was denied", () => {
    expect(denialTag("SoD: preparer ≠ approver")).toBe("SoD");
    expect(denialTag("sod_violation")).toBe("SoD");
    expect(denialTag("Segregation of duties")).toBe("SoD");
    expect(denialTag("period 2025-01 is locked")).toBe("locked period");
    expect(denialTag("PII is redacted for ops")).toBe("PII");
    expect(denialTag("Rate limited.")).toBe("Rate limited");
  });
  it("links evidence endpoints to the screen that shows them", () => {
    expect(evidenceTarget("/api/access/matrix")?.to).toBe("/trace?tab=access");
    expect(evidenceTarget("GET /api/access/log")?.to).toBe("/trace?tab=access#denied");
    expect(evidenceTarget("/api/rules")?.to).toBe("/policies");
    expect(evidenceTarget("/api/books/invariants")?.to).toBe("/close#invariants");
    expect(evidenceTarget("/api/somewhere")).toBeNull();
  });
  it("sorts SOC 2 references naturally", () => {
    expect(["PI1.1", "CC8.1", "CC6.3", "CC7.2", "CC6.1"].sort(compareFrameworkRef)).toEqual(["CC6.1", "CC6.3", "CC7.2", "CC8.1", "PI1.1"]);
  });
});

describe("blame", () => {
  const step = (label: string, kind: Commit["kind"], quote?: string): BlameStep => ({ label, quote, commit: commit({ kind }) });
  it("styles each step by what it is", () => {
    expect(stepKind(step("€34,650 EU261 compensation liability", "journal_event"))).toBe("money");
    expect(stepKind(step("Entitlement · 158 × €600 + 14 × €300", "entitlement"))).toBe("entitlement");
    expect(stepKind(step("Rule R-LEG-1@1", "rule_event"))).toBe("rule");
    expect(stepKind(step("Ruling by Legal", "ruling", "A return sector…"))).toBe("ruling");
    expect(stepKind(step("Fact aog.before_window = true", "fact"))).toBe("fact");
    expect(stepKind(step("Decision · technical · recoded 71 → 41", "decision"))).toBe("decision");
    expect(stepKind(step("Span in the tech log", "fact", "23JAN 21:40Z EI-NSB DUB N/S."))).toBe("span");
    expect(stepKind(step("METAR obs 21:30Z", "fact", "EIDW 232130Z 22013KT 9999 FEW020 07/03 Q0998"))).toBe("metar");
    expect(stepKind(step("Weather at the time", "fact", "EIDW 232130Z 22013KT 9999"))).toBe("metar");
  });
  it("finds rule references", () => {
    expect(ruleRefIn("Rule R-LEG-1@1 cited")).toBe("R-LEG-1@1");
    expect(ruleRefIn("Rule R-CL-1")).toBe("R-CL-1");
    expect(ruleRefIn("no rule here")).toBeNull();
  });
  it("writes a plain-text receipt with the link", () => {
    const text = receiptText("NS31@2025-01-24", [step("METAR obs", "fact", "EIDW 232130Z")], "https://x.test");
    expect(text).toContain("01  METAR obs");
    expect(text).toContain('"EIDW 232130Z"');
    expect(text).toContain("/trace?tab=blame&target=NS31%402025-01-24");
  });
});

describe("blame targets", () => {
  const row = (number: string, cause: string, extraordinary: string, recoded = false): FlightRow =>
    ({
      flight: { id: `${number}@2025-01-24`, number, status: "cancelled" },
      decision: { cause, extraordinary, recoded, recode_label: recoded ? "71 → 41" : null },
    }) as unknown as FlightRow;
  const run = { flights: [row("NS100", "weather", "extraordinary"), row("NS117", "knock_on", "needs_legal"), row("NS31", "technical", "not_extraordinary", true)] } as unknown as StormRun;
  const rules = [
    { id: "R-CL-1", version: 1, tier: "claims_lead_ruling", authority_required: "claims_lead", origin_example: "NS31@2025-01-24:14C", status: "active" },
    { id: "R-LEG-1", version: 1, tier: "legal_ruling", authority_required: "legal", origin_example: "NS117@2025-01-24", status: "active" },
    { id: "R-MINED-1", version: 2, tier: "mined", authority_required: "claims_lead", status: "active" },
  ] as unknown as Rule[];

  it("finds the recoded liability first, then weather, knock-on and the rulings", () => {
    const t = suggestTargets(run, rules);
    expect(t.map((x) => x.id)).toEqual(["NS31@2025-01-24", "NS100@2025-01-24", "NS117@2025-01-24", "NS31@2025-01-24:14C", "R-CL-1@1", "R-LEG-1@1"]);
    expect(t[0]).toMatchObject({ title: "NS31 liability", hint: "recoded 71 → 41" });
    expect(t[3].title).toBe("NS31 · 14C · Claims Lead ruling");
  });

  it("copes with nothing loaded yet", () => {
    expect(suggestTargets(undefined, undefined)).toEqual([]);
  });
});
