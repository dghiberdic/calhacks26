import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { StormRun } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Hero } from "./Hero";

vi.mock("@/components/storm/StormTimeline", () => ({ StormTimeline: () => <div>Timeline</div> }));
afterEach(cleanup);

const run = {
  id: "EIDW@2025-01-24", station: "EIDW", date: "2025-01-24",
  windows: [], metar: [], learned: [], questions: [], feed: [],
  real_context: { metar_source: "pinned real METAR" },
  counters: { cancelled: 1, passengers: 172 },
  flights: [{ flight: { id: "NS31@2025-01-24", number: "NS31", origin: "DUB", dest: "BOS", status: "cancelled", ops_cause_code: "71" },
    decision: { cause: "technical", extraordinary: "not_extraordinary", recoded: true, recode_label: "71 → 41", outcome: "auto", evidence: [], reason: "Fault logged before storm", confidence: { score: 0.91, label: "cause-finding confidence", features: {}, caps: [] } } }],
} as unknown as StormRun;

describe("judge-facing storm introduction", () => {
  it("explains the product and makes the finding visible without waiting", () => {
    render(<MemoryRouter><TooltipProvider><Hero run={run} onSelectFlight={() => {}} focusLiability={3465000} /></TooltipProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("The cause changes the compensation.");
    expect(screen.getByTestId("storm-summary")).toHaveTextContent("172 passengers");
    expect(screen.getByTestId("not-weather-callout")).toHaveTextContent("Aircraft fault");
    expect(screen.getByTestId("finding-liability")).toHaveTextContent("€34,650");
    expect(screen.getByTestId("finding-liability")).toHaveTextContent("Drafted, pending approval");
    expect(screen.getByRole("link", { name: "See the evidence" })).toHaveAttribute("href", "/flights/NS31%402025-01-24");
    expect(screen.getByText(/Real weather.*simulated airline records/)).toBeVisible();
  });
  it("does not substitute an amount when the flight has no estimate", () => {
    render(<MemoryRouter><TooltipProvider><Hero run={run} onSelectFlight={() => {}} /></TooltipProvider></MemoryRouter>);
    expect(screen.queryByTestId("finding-liability")).not.toBeInTheDocument();
  });
  it.each([
    { metar_source: "synthetic (mock mode, no network)" },
    { metar_source: "pinned", mockRaw: true },
  ])("labels generated weather accurately", ({ metar_source, mockRaw }) => {
    const mockRun = {
      ...run,
      real_context: { metar_source },
      metar: mockRaw ? [{ raw: "EIDW 241500Z RMK MOCK" }] : [],
    } as unknown as StormRun;
    render(<MemoryRouter><TooltipProvider><Hero run={mockRun} onSelectFlight={() => {}} /></TooltipProvider></MemoryRouter>);
    expect(screen.getByText(/Simulated weather.*simulated airline records/)).toBeVisible();
    expect(screen.queryByText(/Real weather.*simulated airline records/)).not.toBeInTheDocument();
  });
});
