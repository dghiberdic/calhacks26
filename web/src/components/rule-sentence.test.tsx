import { describe, expect, it } from "vitest";
import { clauseText } from "./rule-sentence";

describe("clauseText", () => {
  it("says an `in` list with commas and a final 'or', never a bare comma", () => {
    expect(clauseText({ f: "pax.election", op: "in", v: ["reroute_partner", "reaccommodated_own"] })).toBe("the passenger chose reroute partner or reaccommodated own");
    expect(clauseText({ f: "pax.election", op: "nin", v: ["refund", "voucher", "reroute_partner"] })).toBe("the passenger didn't choose refund, voucher or reroute partner");
    expect(clauseText({ f: "pax.election", op: "eq", v: "refund" })).toBe("the passenger chose refund");
    expect(clauseText({ f: "flight.ops_cause_code", op: "in", v: ["71", "72"] })).toBe("OCC coded it 71 or 72");
  });
});
