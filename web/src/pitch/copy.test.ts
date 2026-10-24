import { describe, expect, it } from "vitest";
import { ARCHITECTURE_HEADLINE, CARD_TAGS, copyProblem, COVER_IMAGE_CREDIT, HONEST_FRAMING, REAL_CARD, SEATS_LINE } from "./copy";

describe("pitch copy", () => {
  it("keeps the seats line verbatim (THREAD_JUSTIN J11)", () => {
    expect(SEATS_LINE).toBe(
      "StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment.",
    );
  });

  it("keeps the honest framing and the Real card in plan wording", () => {
    expect(HONEST_FRAMING.replace("’", "'")).toBe(
      "Real Dublin weather, real airport traffic, real distances and real EU law. Northstar's schedule, logs, passengers and claims are simulated on top, with the mess left in.",
    );
    expect(REAL_CARD).toBe("Real Dublin weather, traffic and EU law; simulated logs, mess left in");
  });

  it("tags the Business cards in plain words, the same four the app uses", () => {
    expect(CARD_TAGS).toEqual({ learns: "from its own history", runs: "overnight", escalates: "asks a person", improves: "becomes policy" });
  });

  it("every fixed line reads clean", () => {
    for (const line of [SEATS_LINE, HONEST_FRAMING, REAL_CARD, ARCHITECTURE_HEADLINE, COVER_IMAGE_CREDIT, ...Object.values(CARD_TAGS)]) expect(copyProblem(line), line).toBeNull();
  });
});

describe("copyProblem", () => {
  it("catches the banned words in any form", () => {
    expect(copyProblem("A seamless flow")).toMatch(/seamless/);
    expect(copyProblem("It transforms how claims work")).toMatch(/transform/);
    expect(copyProblem("self-learning")).toMatch(/self-learning/);
    expect(copyProblem("ai-automated")).toMatch(/ai-automated/);
    expect(copyProblem("Introducing StormCheck")).toMatch(/introducing/);
    expect(copyProblem("The future of claims")).toMatch(/the future of/);
  });

  it("catches the patterns", () => {
    expect(copyProblem("Fast — and exact")).toMatch(/em dash/);
    expect(copyProblem("It works!")).toMatch(/exclamation/);
    expect(copyProblem("Why wait for Monday?")).toMatch(/rhetorical/);
    expect(copyProblem("Built with AI")).toMatch(/AI/);
    expect(copyProblem("It's not a bot, it's a seat.")).toMatch(/It's not X/);
  });

  it("leaves plain copy, ranges, quoted questions and lookalike words alone", () => {
    expect(copyProblem("It drafts. It never pays.")).toBeNull();
    expect(copyProblem("storm 02:30–15:00Z · Jul 2023 – Dec 2024")).toBeNull();
    expect(copyProblem("Rights notices and every “why?” answer")).toBeNull();
    expect(copyProblem("Claims Lead: “No signed acceptance, no offset.”")).toBeNull();
    expect(copyProblem("OpenAI and transformers are not on this slide")).toBeNull();
  });
});
