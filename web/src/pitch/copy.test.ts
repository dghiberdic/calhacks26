import { describe, expect, it } from "vitest";
import { HONEST_FRAMING, REAL_CARD, SEATS_LINE } from "./copy";

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
});
