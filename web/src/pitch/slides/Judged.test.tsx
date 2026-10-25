import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CfoMetrics, StormRun } from "@/api/types";
import { Judged } from "./Judged";

vi.mock("./StormStrip", () => ({ StormStrip: () => null }));
afterEach(cleanup);

describe("pitch case example", () => {
  it("does not attribute the aggregate CFO liability to the recoded flight", () => {
    const run = {
      counters: { drafted: 171 },
      flights: [{ flight: { number: "NS31", pax: 172 }, decision: { recoded: true, recode_label: "71 → 41" } }],
    } as unknown as StormRun;
    const { container } = render(<Judged data={{ run, cfo: { drafted_liability_cents: 9_876_500 } as CfoMetrics }} />);
    expect(screen.getByText("Code corrected: 71 → 41")).toBeInTheDocument();
    expect(screen.getByText("Passenger entitlements recalculated")).toBeInTheDocument();
    expect(container.textContent).not.toContain("€98,765");
    expect(container.textContent).toContain("171 payouts drafted, pending Claims Lead approval");
  });
});
