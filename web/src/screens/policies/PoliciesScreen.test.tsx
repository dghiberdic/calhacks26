import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { setTransport } from "@/api/client";
import type { ReplayDiff, Rule } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import PoliciesScreen from ".";

const base = { scope: {}, condition: {}, grounding: {}, times_cited: 0, valid_from: null, recorded_at: "2025-01-20T09:00:00Z", status: "active" } as const;
const RULES: Rule[] = [
  { ...base, id: "R-MIN-1", version: 1, kind: "mined_policy", tier: "mined", authority_required: "legal", action: "apply_7_2_reduction", support: "41 of 42", condition: { all: [{ f: "pax.election", op: "eq", v: "reroute_partner" }] }, times_cited: 14 },
  {
    ...base,
    id: "R-CL-1",
    version: 1,
    kind: "voucher",
    tier: "claims_lead_ruling",
    authority_required: "claims_lead",
    action: "deny_offset",
    origin_example: "NS31@2025-01-24:14C",
    scope: { "voucher.signed": false, "voucher.amount_cents": "case:30000" },
    condition: { all: [{ f: "voucher.signed", op: "eq", v: false }] },
    grounding: { signed: "No signed acceptance" },
  },
  { ...base, id: "R-CTL-1", version: 1, kind: "release", tier: "controller_ruling", authority_required: "controller", action: "keep_tail", origin_example: "EIDW@2024-01-21", scope: { cohort: "case:EIDW@2024-01-21" }, status: "shadow" },
  { ...base, id: "REG-2026-2202", version: 1, kind: "regime", tier: "regulation", authority_required: "legal", action: "route_to", static_card: true, origin_example: "Reg (EU) 2026/2202 · in force 22 Oct 2026 · applies from 23 Oct 2027 · 9-month claim window", valid_from: "2027-10-23T00:00:00Z", recorded_at: "2026-10-22T00:00:00Z", status: "shadow" },
  { ...base, id: "HC-SOD-1", version: 1, kind: "routing", tier: "hard_control", authority_required: "controller", action: "route_to", origin_example: "Preparer ≠ approver" },
];
const DIFF: ReplayDiff = { rule_ref: "R-CL-1@1", known_at: "2025-02-28T23:59:00Z", flips: [{ entity_id: "NS31@2025-01-24:14C", field: "voucher_offset_cents", before: 0, after: 30000, delta_cents: -30000 }], total_delta_cents: -30000, locked_periods_untouched: ["2025-01"] };

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia;
  Element.prototype.scrollIntoView ??= function () {};
  setTransport(async (path, init) => {
    if (path === "/rules") return json(RULES);
    if (path.startsWith("/blame")) return json({ target: "R-CL-1@1", steps: [{ label: "Ruling · Claims Lead", quote: "No signed acceptance, no offset: pay €600 cash.", commit: { hash: "a1", parent: null, kind: "ruling", at: "2025-01-25T09:41:00Z", actor: "claims_lead", payload_hash: "p", payload_ref: "ruling:1", message: "m" } }] });
    if (path.endsWith("/revert") && init.method === "POST") return json(DIFF);
    return json({ error: { code: "not_found", message: "Not here." } }, 404);
  });
});
afterEach(cleanup);

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={["/policies"]}>
          <PoliciesScreen />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Policies screen", () => {
  it("groups rules by origin and never offers to write one", async () => {
    renderScreen();
    await screen.findByTestId("rule-R-MIN-1");
    for (const title of ["Learned", "Ruled", "Rejected", "Regulation", "Hard controls are code"]) expect(screen.getByRole("heading", { level: 2, name: title })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/new rule/i);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("There is no rule editor.", { exact: false })).toBeInTheDocument();
  });

  it("gives each card its versioned ref as its id, for links like /policies#R-CL-1@1", async () => {
    renderScreen();
    expect(await screen.findByTestId("rule-R-CL-1")).toHaveAttribute("id", "R-CL-1@1");
    expect(screen.getByTestId("static-regulation-card")).toHaveAttribute("id", "REG-2026-2202@1");
  });

  it("shows mined support, the ruler's grounded words and the case-only scope", async () => {
    renderScreen();
    expect(await screen.findByText("41 of 42")).toBeInTheDocument();
    const cl = screen.getByTestId("rule-R-CL-1");
    expect(await within(cl).findByText("No signed acceptance")).toBeInTheDocument();
    expect(within(cl).getByText("the voucher is €300")).toBeInTheDocument();
    expect(within(screen.getByTestId("rule-R-CTL-1")).getByText("cohort = Storm Isha")).toBeInTheDocument();
  });

  it("shows the static Reg 2026/2202 card with its own dates and no actions", async () => {
    renderScreen();
    const card = await screen.findByTestId("static-regulation-card");
    expect(card).toHaveTextContent("Reg (EU) 2026/2202");
    expect(card).toHaveTextContent("in force 22 Oct 2026 · applies from 23 Oct 2027 · 9-month claim window");
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("reverts only after a confirmation, then shows what flipped", async () => {
    renderScreen();
    const cl = await screen.findByTestId("rule-R-CL-1");
    await userEvent.click(within(cl).getByRole("button", { name: "Revert R-CL-1@1" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Locked periods are never rewritten.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revert and replay" }));
    // The summary sets its figures in their own spans, so match the paragraph's whole text.
    const summary = (_: string, el: Element | null) => el?.tagName === "P" && /flips 1 · Δ \(€300\) · Jan 2025 locked, untouched/.test(el.textContent ?? "");
    expect(await within(dialog).findByText(summary)).toBeInTheDocument();
  });

  it("offers no widen or revert on regulation or hard controls", async () => {
    renderScreen();
    await screen.findByTestId("rule-R-MIN-1");
    const regulation = screen.getByRole("region", { name: "Regulation" });
    expect(within(regulation).queryByRole("button", { name: /revert|widen/i })).toBeNull();
    const hard = screen.getByRole("region", { name: "Hard controls are code" });
    expect(within(hard).queryByRole("button")).toBeNull();
  });
});
