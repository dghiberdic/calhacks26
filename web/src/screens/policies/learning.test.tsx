import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { LearningStep, Rule } from "@/api/types";
import { LEARNING } from "@/mocks/data/insights";
import { LearnedAndReused } from "./Learning";
import { learningLead } from "./model";

afterEach(cleanup);

const rules = [
  { id: "R-CL-1", version: 1, title: "No signed acceptance, no offset" },
  { id: "R-LEG-1", version: 1, title: "Knock-on returns are extraordinary only if nothing could fly them" },
] as Rule[];

const show = (steps: LearningStep[]) =>
  render(
    <MemoryRouter>
      <LearnedAndReused steps={steps} rules={rules} />
    </MemoryRouter>,
  );

describe("Learned and reused", () => {
  it("opens with the drop in questions, then one row per storm or event, in order", () => {
    show(LEARNING);
    expect(screen.getByRole("heading", { name: "Learned and reused" })).toBeInTheDocument();
    expect(screen.getByTestId("learning-lead")).toHaveTextContent("questions asked went 3 → 1 → 1, and 52 cases were settled without asking.");
    const rows = screen.getAllByTestId("learning-step");
    expect(rows.map((r) => within(r).getByText(/ · \d{1,2} \w{3} \d{4}$/).textContent)).toEqual(["Storm Éowyn · 24 Jan 2025", "Storm Herminia · 26 Jan 2025", "Iberian blackout · 28 Apr 2025"]);
    expect(rows[0]).toHaveTextContent("3 questions asked · 12 settled without asking");
    expect(rows[1]).toHaveTextContent("1 question asked · 31 settled without asking");
    expect(rows[1]).toHaveTextContent("Reused the Claims Lead's voucher rule: 31 cases settled without asking.");
  });

  it("makes each reused rule a chip that links to its policy", () => {
    show(LEARNING);
    const herminia = screen.getAllByTestId("learning-step")[1];
    const chip = within(herminia).getByRole("link", { name: /No signed acceptance, no offset/ });
    expect(chip).toHaveAttribute("href", "/policies#R-CL-1@1");
    expect(chip).toHaveTextContent("No signed acceptance, no offset · 31");
    expect(chip).toHaveAttribute("title", "R-CL-1@1, learned from Claims Lead ruling on Storm Éowyn (Q-1)");
    const blackout = screen.getAllByTestId("learning-step")[2];
    expect(within(blackout).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/policies#R-MIN-1@1", "/policies#R-LEG-1@1", "/policies#R-LEG-2@1"]);
  });

  it("names the rules a run first confirmed from GET /rules, or by ref when unlisted", () => {
    show(LEARNING);
    const eowyn = screen.getAllByTestId("learning-step")[0];
    expect(within(eowyn).getByRole("link", { name: /^new No signed acceptance, no offset$/ })).toHaveAttribute("href", "/policies#R-CL-1@1");
    expect(within(eowyn).getByRole("link", { name: /^new R-CTL-1@1$/ })).toBeInTheDocument();
  });

  it("says it plainly with a single step, and renders nothing with none", () => {
    expect(learningLead(LEARNING.slice(0, 1))).toBe("Storm Éowyn asked 3 questions. Each answer becomes a rule that later runs reuse.");
    const { container } = show([]);
    expect(container).toBeEmptyDOMElement();
  });
});
