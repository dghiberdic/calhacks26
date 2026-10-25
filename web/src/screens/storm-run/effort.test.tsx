import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EffortEstimate, LearningStep } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { hoursCell, reuseFor, roughEur, roughHours } from "./effort";
import { WithoutStormCheck } from "./WithoutStormCheck";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

/** Golden Éowyn, as the insights spec's assumptions give it (27 flights, 5,292 passengers). */
const EOWYN: EffortEstimate = {
  run_id: "EIDW@2025-01-24",
  name: "Storm Éowyn · 24 Jan 2025",
  inputs: { cancelled_flights: 27, passengers: 5292, expected_claims: 953, questions: 3, refunds: 265, cohorts: 1, month_ends: 18 },
  lines: [
    { task: "Find what really caused each cancellation", role: "ops analyst", basis: "27 flights × 1.5 h", manual_hours: 40.5, with_stormcheck_hours: 0.5, rate_eur_per_hour: 45, source: null },
    { task: "Decide each claim", role: "claims handler", basis: "953 expected claims × 20 min", manual_hours: 317.67, with_stormcheck_hours: 31.77, rate_eur_per_hour: 31, source: "Steer (2020) for the European Commission" },
    { task: "Research the legal and policy questions", role: "in-house counsel", basis: "3 questions × 4 h", manual_hours: 12, with_stormcheck_hours: 0.75, rate_eur_per_hour: 100, source: null },
    { task: "Reconcile refunds and vouchers", role: "claims handler", basis: "265 refunds × 3 min", manual_hours: 13.25, with_stormcheck_hours: 0, rate_eur_per_hour: 31, source: null },
    { task: "Book and re-estimate the liability", role: "revenue accountant", basis: "1 cohort", manual_hours: 68, with_stormcheck_hours: 11, rate_eur_per_hour: 61, source: "Chartered Accountants Ireland / Barden 2026" },
  ],
  manual_hours: 451.42,
  with_stormcheck_hours: 44.02,
  hours_saved: 407.4,
  manual_cost_cents: 1_742_900,
  with_stormcheck_cost_cents: 175_300,
  cost_saved_cents: 1_567_600,
  errors_caught: [
    { label: "NS31 recoded 71 → 41", amount_cents: 9_900_000, detail: "Coded weather, but the plane was broken." },
    { label: "32 refunds the CRM bot had already made, not repeated", amount_cents: 1_632_000, detail: null },
    { label: "1 claim duplicates another", amount_cents: null, detail: null },
    { label: "Bot refund run held", amount_cents: 51_000, detail: "€510 would have been paid twice." },
  ],
  assumptions_note: "Estimate from the assumptions below; not measured at a real airline.",
};

const wrap = (ui: React.ReactNode) => render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>);

describe("effort rounding", () => {
  it("says totals roughly: hours to the nearest 5, euros to the nearest €100", () => {
    expect(roughHours(451.42)).toBe("about 450 hours");
    expect(roughHours(44.02)).toBe("about 45 hours");
    expect(roughHours(1_002.6)).toBe("about 1,005 hours");
    expect(roughHours(2.4)).toBe("under 5 hours");
    expect(roughHours(0)).toBe("no hours");
    expect(roughEur(1_742_900)).toBe("€17,400");
    expect(roughEur(1_745_000)).toBe("€17,500");
    expect(roughEur(1_700_000)).toBe("€17,000");
  });
  it("writes each line's hours plainly", () => {
    expect(hoursCell(317.67)).toBe("318 h");
    expect(hoursCell(40.5)).toBe("41 h");
    expect(hoursCell(1.5)).toBe("1.5 h");
    expect(hoursCell(8)).toBe("8 h");
    expect(hoursCell(0.75)).toBe("45 min");
    expect(hoursCell(0.5)).toBe("30 min");
    expect(hoursCell(0.01)).toBe("5 min");
    expect(hoursCell(0)).toBe("0 h");
  });
});

describe("WithoutStormCheck", () => {
  it("leads with one sentence and explains the loaded cost", async () => {
    wrap(<WithoutStormCheck effort={EOWYN} />);
    expect(screen.getByTestId("effort-headline")).toHaveTextContent("Done by hand, this storm is about 450 hours of work (≈ €17,400). With StormCheck: about 45 hours of review.");
    await userEvent.click(screen.getByRole("button", { name: "€17,400" }));
    expect((await screen.findAllByText(/salary plus about 30%/)).length).toBeGreaterThan(0);
  });
  it("folds the lines, the errors caught and the assumptions behind Details", async () => {
    wrap(<WithoutStormCheck effort={EOWYN} noun="power cut" />);
    expect(screen.getByTestId("effort-headline")).toHaveTextContent(/^Done by hand, this power cut is/);
    const details = screen.getByText("How we got this").closest("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(screen.getByText("How we got this"));
    const rows = within(details).getAllByRole("row");
    expect(rows).toHaveLength(EOWYN.lines.length + 1);
    expect(rows[2]).toHaveTextContent("Decide each claim");
    expect(rows[2]).toHaveTextContent("318 h → 32 h");
    expect(rows[2]).toHaveTextContent("claims handler · €31/h");
    expect(rows[1]).toHaveTextContent("41 h → 30 min");
    const errors = within(screen.getByTestId("errors-caught")).getAllByRole("listitem");
    expect(errors.map((li) => li.textContent)).toEqual(["NS31 recoded 71 → 41: €99,000. Coded weather, but the plane was broken.", "32 refunds the CRM bot had already made, not repeated: €16,320", "1 claim duplicates another", "Bot refund run held. €510 would have been paid twice."]);
    expect(within(details).getByText(/not measured at a real airline/)).toBeInTheDocument();
    expect(within(details).getByText("Source: Steer (2020) for the European Commission")).toBeInTheDocument();
    expect(within(details).getAllByText(/^Source:/)).toHaveLength(2);
  });
  it("shows nothing when there is no work to estimate", () => {
    const { container } = wrap(<WithoutStormCheck effort={{ ...EOWYN, manual_hours: 0 }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("reuseFor", () => {
  const step = (run_id: string, reused: number, cases: number): LearningStep => ({
    run_id,
    name: run_id,
    known_at: "2025-01-25T06:00:00Z",
    questions_asked: 1,
    cases_settled_by_reused_rules: cases,
    reused: Array.from({ length: reused }, (_, i) => ({ rule_ref: `R-${i}@1`, title: `Rule ${i}`, learned_from: "history", cases })),
    new_rules: [],
    note: "",
  });
  const steps = [step("EIDW@2025-01-24", 1, 12), step("EIDW@2025-01-26", 1, 31), step("EIDW@2025-04-28", 2, 9), step("EIDW@2025-05-01", 0, 0)];
  it("counts the rules a later run reused and the cases they settled", () => {
    expect(reuseFor(steps, "EIDW@2025-01-26")).toEqual({ rules: 1, cases: 31 });
    expect(reuseFor(steps, "EIDW@2025-04-28")).toEqual({ rules: 2, cases: 9 });
  });
  it("says nothing for the first run, a run off the timeline, one that reused nothing, or no data", () => {
    expect(reuseFor(steps, "EIDW@2025-01-24")).toBeNull();
    expect(reuseFor(steps, "LEMD@2025-04-28")).toBeNull();
    expect(reuseFor(steps, "EIDW@2025-05-01")).toBeNull();
    expect(reuseFor(undefined, "EIDW@2025-01-26")).toBeNull();
  });
});
