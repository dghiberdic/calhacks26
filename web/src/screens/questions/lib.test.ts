import { describe, expect, it } from "vitest";
import type { Question, ReplayDiff, Rule } from "@/api/types";
import { caseCount, caseHref, caseLabel, findProposalRule, MASK_RE, nextStormLine, readableRule, REJECT_RE, reminderText, seatPhrase, settledHereLine } from "./lib";

const q = (over: Partial<Question> = {}): Question => ({
  id: "Q-1",
  case_refs: ["NS31@2025-01-24:14C"],
  pattern: "voucher_in_lieu_unsigned",
  routed_to: "claims_lead",
  asked_at: "2025-01-25T06:00:00Z",
  title: "",
  found: "",
  why_flagged: "",
  recommends: "",
  recommended_option: "a",
  options: ["a"],
  evidence: [],
  confidence: { score: 0.39, kind: "voucher", label: "confidence", features: {}, calibration_version: "cal-v1" },
  reason_tag: "sources-disagree",
  ...over,
});

describe("question helpers", () => {
  it("words the reminder from asked_at, remind_at and status", () => {
    expect(reminderText(q({ status: "reminded", remind_at: "2025-01-25T09:00:00Z" }))).toBe("Waiting on Claims Lead 3h · reminder sent");
    expect(reminderText(q({ status: "open", remind_at: "2025-01-25T09:00:00Z" }))).toBe("Waiting on Claims Lead · reminder due 09:00Z");
    expect(reminderText(q({ status: "open", remind_at: null }))).toBeNull();
    const withOthers = { ...q({ status: "reminded", remind_at: "2025-01-25T09:00:00Z" }), others_settled: 4761 };
    expect(reminderText(withOthers)).toBe("Waiting on Claims Lead 3h · reminder sent · 4,761 others settled");
  });

  it("counts and labels the cases one question covers", () => {
    expect(caseCount(["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"])).toBe("3 flights");
    expect(caseCount(["NS31@2025-01-24:14C"])).toBe("1 passenger");
    expect(caseLabel("NS31@2025-01-24:14C")).toBe("NS31 · 14C");
    expect(caseLabel("EIDW@2024-01-21")).toBe("Storm Isha cohort");
    expect(caseHref("NS31@2025-01-24:14C")).toBe("/flights/NS31%402025-01-24");
    expect(caseCount(["R-CTL-1"])).toBe("1 rule");
    expect(caseHref("R-CTL-1@1")).toBe("/policies#R-CTL-1");
  });

  it("says the seat the way a sentence needs it", () => {
    expect(seatPhrase("claims_lead")).toBe("the Claims Lead");
    expect(seatPhrase("legal")).toBe("Legal");
    expect(seatPhrase("ops")).toBe("Ops");
  });

  it("reads the next storm off the confirm replay, nothing typed in", () => {
    const replay: ReplayDiff = {
      rule_ref: "R-CL-1@1",
      known_at: "2025-01-26T13:00:00Z",
      flips: [
        ...Array.from({ length: 31 }, (_, i) => ({ entity_id: `NS2${i}@2025-01-26:1A`, field: "status", before: "needs_ruling", after: "owed" })),
        { entity_id: "NS30@2025-01-26:8C", field: "status", before: "owed", after: "needs_ruling" },
        { entity_id: "NS31@2025-01-24:14C", field: "voucher_offset_cents", before: 30000, after: 0 },
      ],
      total_delta_cents: 0,
    };
    expect(nextStormLine(replay, ["NS31@2025-01-24:14C"])).toEqual({
      settled: "Next storm (Herminia): 31 cases settled, ruling cited",
      asks: "1 outside the rule's scope asks again",
    });
    expect(nextStormLine({ ...replay, flips: replay.flips.slice(-1) }, ["NS31@2025-01-24:14C"])).toBeNull();
  });

  it("says what a confirmed ruling settled on its own storm", () => {
    const replay: ReplayDiff = {
      rule_ref: "R-LEG-1@1",
      known_at: "2025-01-25T09:00:00Z",
      flips: [
        { entity_id: "NS113@2025-01-24", field: "extraordinary", before: "needs_legal", after: "extraordinary", delta_cents: -1_922_400 },
        { entity_id: "NS115@2025-01-24", field: "extraordinary", before: "needs_legal", after: "extraordinary", delta_cents: -1_987_200 },
        { entity_id: "NS117@2025-01-24", field: "extraordinary", before: "needs_legal", after: "extraordinary", delta_cents: -840_000 },
      ],
      total_delta_cents: -4_749_600,
    };
    expect(settledHereLine(replay, ["NS113@2025-01-24", "NS115@2025-01-24", "NS117@2025-01-24"])).toBe("3 flights settled, ruling cited 3× · Δ (€47,496)");
    expect(settledHereLine({ ...replay, flips: [] }, ["NS113@2025-01-24"])).toBeNull();
  });

  it("finds the proposed rule a release question is about", () => {
    const rule = (over: Partial<Rule>): Rule => ({ id: "R", version: 1, kind: "release", scope: {}, condition: {}, action: "deny_release", tier: "mined", authority_required: "controller", valid_from: null, recorded_at: "", status: "proposed", ...over });
    const isha = q({ case_refs: ["EIDW@2024-01-21"], reason_tag: "release-proposal" });
    expect(findProposalRule([rule({ id: "R-X", status: "active" }), rule({ id: "R-REL", origin_example: "EIDW@2024-01-21" })], isha)?.id).toBe("R-REL");
    expect(findProposalRule([rule({ id: "R-X", status: "active" })], isha)).toBeNull();
  });

  it("knows an option that rejects a release proposal from one that only defers it", () => {
    expect(REJECT_RE.test("Reject: never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.")).toBe(true);
    expect(REJECT_RE.test("Keep the €3,600 and re-test next quarter.")).toBe(false);
    // The contract stub's wording for the same rejection.
    expect(REJECT_RE.test("Keep the expected tail until the six-year limitation")).toBe(true);
    expect(REJECT_RE.test("Derecognise the remaining €3,600 now: no new claims in 3 months.")).toBe(false);
  });

  it("names each fact of a rule once: scope the condition already states is dropped, case-only scope stays", () => {
    const rule = {
      condition: { all: [{ f: "voucher.in_lieu", op: "eq", v: true }, { not: { f: "voucher.signed", op: "eq", v: true } }] },
      scope: { "voucher.in_lieu": true, "voucher.signed": false, "flight.departs_eu": true, "voucher.amount_cents": "case:30000" },
    };
    expect(readableRule(rule).scope).toEqual({ "flight.departs_eu": true, "voucher.amount_cents": "case:30000" });
  });

  it("recognises server PII masks", () => {
    expect("gave [redacted:pii] (14C)".split(MASK_RE)).toEqual(["gave ", "[redacted:pii]", " (14C)"]);
    expect("gave ████ (14C)".split(MASK_RE)[1]).toBe("████");
  });
});
