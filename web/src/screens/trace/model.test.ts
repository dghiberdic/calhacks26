import { describe, expect, it } from "vitest";
import type { BlameStep, Commit, FlightRow, Question, Rule, StormRun } from "@/api/types";
import { REDACTED, blameTarget, chainOrder, eventRef, matchesTarget, piiResource, tabForTarget, timeOrdered, findPiiRecord, isPiiField, splitPii, suggestTargets, compareFrameworkRef, denialTag, evidenceTarget, isTab, orderPrincipals, principalLabel, principalRole, receiptText, ruleRefIn, shortHash, stepKind } from "./model";

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
  it("accepts only the trace tabs", () => {
    expect(isTab("live")).toBe(true);
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

describe("targets", () => {
  it("finds the events about a target", () => {
    expect(matchesTarget("NS31@2025-01-24", "NS31@2025-01-24")).toBe(true);
    expect(matchesTarget("NS31@2025-01-24:14C", "NS31@2025-01-24")).toBe(true);
    expect(matchesTarget("NS31@2025-01-24", "NS31@2025-01-24:14C")).toBe(true);
    expect(matchesTarget("R-CL-1@1", "R-CL-1@2")).toBe(true);
    expect(matchesTarget("R-CL-1", "R-CL-1@1")).toBe(true);
    expect(matchesTarget("R-CL-10@1", "R-CL-1@1")).toBe(false);
    expect(matchesTarget("NS310@2025-01-24", "NS31@2025-01-24")).toBe(false);
    expect(matchesTarget("Q-1", "Q-1")).toBe(true);
    expect(matchesTarget(null, "Q-1")).toBe(false);
  });
  it("opens blame for things with a chain and the feed for questions", () => {
    expect(tabForTarget("NS31@2025-01-24")).toBe("blame");
    expect(tabForTarget("JE-000101")).toBe("blame");
    expect(tabForTarget("R-CL-1@1")).toBe("blame");
    expect(tabForTarget("Q-1")).toBe("live");
  });
});

describe("event refs", () => {
  it("links each ref to where it lives", () => {
    expect(eventRef("NS31@2025-01-24")).toEqual({ to: "/flights/NS31%402025-01-24", label: "NS31" });
    expect(eventRef("NS31@2025-01-24:14C")).toEqual({ to: "/flights/NS31%402025-01-24", label: "NS31 · 14C" });
    expect(eventRef("EIDW@2025-01-26")).toEqual({ to: "/run/EIDW%402025-01-26", label: "Storm Herminia" });
    expect(eventRef("R-MIN-1@1")?.to).toBe("/policies#R-MIN-1");
    expect(eventRef("REG-C549-TECHNICAL@1")?.to).toBe("/policies#REG-C549-TECHNICAL");
    expect(eventRef("JE-000101")?.to).toBe("/close");
    expect(eventRef("Q-1")?.to).toBe("/questions");
    expect(eventRef("tech_log:EI-NSB@2025-01-23")).toEqual({ to: null, label: "tech_log:EI-NSB@2025-01-23" });
    expect(eventRef(null)).toBeNull();
  });
});

describe("chain order", () => {
  const mk = (hash: string, parent: string | null, at: string) => commit({ hash, parent, at });
  it("follows parents, not timestamps", () => {
    const a = mk("a", null, "2025-01-25T05:59:00Z");
    const b = mk("b", "a", "2025-01-25T06:00:00Z"); // a decision stamped with its known-at
    const c = mk("c", "b", "2025-01-25T05:59:30Z");
    const { ordered, linked } = chainOrder([a, c, b]);
    expect(ordered.map((x) => x.hash)).toEqual(["c", "b", "a"]);
    expect(linked).toBe(true);
  });
  it("treats an older parent outside the page as linked", () => {
    const { ordered, linked } = chainOrder([mk("y", "x", "2025-01-26T00:00:00Z"), mk("z", "y", "2025-01-26T01:00:00Z")]);
    expect(ordered.map((c) => c.hash)).toEqual(["z", "y"]);
    expect(linked).toBe(true);
  });
  it("knows when day headers would mislead", () => {
    expect(timeOrdered([{ at: "2025-02-28T23:00:00Z" }, { at: "2025-01-27T05:59:00Z" }])).toBe(true);
    expect(timeOrdered([{ at: "2025-02-28T23:00:00Z" }, { at: "2024-12-31T23:00:00Z" }, { at: "2025-01-27T05:59:00Z" }])).toBe(false);
  });

  it("falls back to time when the page holds two chains", () => {
    const { ordered, linked } = chainOrder([mk("p", null, "2025-01-26T00:00:00Z"), mk("q", null, "2025-01-27T00:00:00Z")]);
    expect(ordered.map((c) => c.hash)).toEqual(["q", "p"]);
    expect(linked).toBe(false);
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
    expect(ruleRefIn("Rule REG-C549-TECHNICAL@1 applied")).toBe("REG-C549-TECHNICAL@1");
  });
  it("finds what a commit's payload can be blamed from", () => {
    expect(blameTarget("decision:NS31@2025-01-24")).toBe("NS31@2025-01-24");
    expect(blameTarget("NS31@2025-01-24:14C")).toBe("NS31@2025-01-24:14C");
    expect(blameTarget("R-MIN-1@1")).toBe("R-MIN-1@1");
    expect(blameTarget("REG-C549-TECHNICAL@1")).toBe("REG-C549-TECHNICAL@1");
    expect(blameTarget("JE-000101")).toBe("JE-000101");
    expect(blameTarget("Q-1")).toBeNull();
    expect(blameTarget("tech_log:EI-NSB@2025-01-23")).toBeNull();
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
    { id: "R-LEG-1", version: 2, tier: "legal_ruling", authority_required: "legal", origin_example: "NS117@2025-01-24", status: "shadow" },
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

describe("the PII record", () => {
  const q = (name: string) =>
    ({
      id: "Q-1",
      found: `The desk gave passenger 14C (${name}) a €300 voucher.`,
      evidence: [
        { fact_id: "f1", source_id: "crm", field: "voucher.signed", value: false, quote: "SIGNATURE: NONE CAPTURED", role: "supports", trust_tier: 3 },
        { fact_id: "f2", source_id: "claim", field: "claim.passenger_name", value: name, quote: name, role: "context", trust_tier: 4 },
      ],
    }) as unknown as Question;

  it("finds the PII column by name, else by its redacted cells", () => {
    const cells = { ops: { flights: "read", coupons: "redacted", claims: "redacted" }, claims_lead: { flights: "read", coupons: "read", claims: "write" } } as const;
    expect(piiResource({ principals: ["ops", "claims_lead"], resources: ["flights", "coupons", "claims"], cells })).toBe("claims");
    expect(piiResource({ principals: ["ops"], resources: ["passenger_pii", "claims"], cells: { ops: { passenger_pii: "redacted", claims: "none" } } })).toBe("passenger_pii");
    expect(piiResource({ principals: ["ops"], resources: ["flights"], cells: { ops: { flights: "read" } } })).toBeNull();
  });

  it("recognises identity fields only", () => {
    expect(isPiiField("claim.passenger_name")).toBe(true);
    expect(isPiiField("claim.email")).toBe(true);
    expect(isPiiField("voucher.signed")).toBe(false);
    expect(isPiiField("flight.route_region")).toBe(false);
  });

  it("finds the served record, in the clear for the Claims Lead and masked for anyone else", () => {
    const clear = findPiiRecord([q("Orla Keane")]);
    expect(clear?.values).toEqual(["Orla Keane"]);
    const masked = findPiiRecord([q(REDACTED)]);
    expect(masked?.values).toEqual([]);
    expect(findPiiRecord([])).toBeNull();
  });

  it("splits text into plain and PII runs", () => {
    expect(splitPii("passenger 14C (Orla Keane) a voucher", ["Orla Keane"])).toEqual([
      { text: "passenger 14C (", pii: false },
      { text: "Orla Keane", pii: true },
      { text: ") a voucher", pii: false },
    ]);
    expect(splitPii(`(${REDACTED})`, []).map((r) => r.pii)).toEqual([false, true, false]);
  });
});
