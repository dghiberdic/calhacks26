import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { setTransport } from "@/api/client";
import type { AccessDecision, AccessMatrix, Blame, Commit, ControlMapping, TraceEvent } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import TraceScreen from ".";

const c = (hash: string, kind: Commit["kind"], message: string, parent: string | null, actor = "agent.engine"): Commit => ({ hash, parent, kind, at: `2025-01-25T09:0${hash.length % 9}:00Z`, actor, payload_hash: `p${hash}`, payload_ref: `x:${hash}`, message });
const COMMITS: Commit[] = [
  c("a1aaaaaaaa", "fact", "tech_log TL-1 · aog=true", null, "agent.reader"),
  c("b2bbbbbbbbb", "llm_call", "Reader extracted 4 facts", "a1aaaaaaaa", "agent.reader"),
  c("c3ccccccccccc", "decision", "NS31 recoded 71 → 41", "b2bbbbbbbbb"),
];
const BLAME: Blame = {
  target: "NS31@2025-01-24",
  steps: [
    { label: "€34,650 EU261 compensation liability · NS31", commit: COMMITS[2] },
    { label: "Span · tech log TL-1", quote: "23JAN 21:40Z EI-NSB DUB N/S. NO MEL RELIEF. A/C AOG.", commit: COMMITS[0] },
    { label: "METAR obs · EIDW 23 Jan 21:30Z", quote: "EIDW 232130Z 22013KT 9999 FEW020 07/03 Q0998", commit: COMMITS[0] },
  ],
};
const MATRIX: AccessMatrix = {
  principals: ["agent.drafter", "ops", "claims_lead"],
  resources: ["passenger_pii", "payouts"],
  cells: { claims_lead: { passenger_pii: "read", payouts: "approve" }, ops: { passenger_pii: "redacted", payouts: "none" }, "agent.drafter": { passenger_pii: "none", payouts: "write" } },
};
const LOG: AccessDecision[] = [
  { at: "2025-01-25T09:02:00Z", principal: "agent.drafter", action: "approve_payout", resource: "JE-000123", allowed: false, reason: "SoD: an agent that drafts a payout can never approve it" },
  { at: "2025-01-25T09:41:00Z", principal: "claims_lead", action: "confirm_rule", resource: "R-CL-1@1", allowed: true, reason: "author holds the authority" },
];
const CONTROLS: ControlMapping[] = [
  { control: "Denial log", framework_ref: "CC7.2", implemented_by: "server/acl.py", evidence_endpoint: "/api/access/log" },
  { control: "ACL broker", framework_ref: "CC6.1", implemented_by: "server/acl.py", evidence_endpoint: "/api/access/matrix" },
];

const EVENTS: TraceEvent[] = [
  { seq: 1, at: "2025-01-25T05:59:15Z", kind: "decision", actor: "agent.engine", summary: "NS31 recoded 71 → 41 · 172 payouts drafted", ref: "NS31@2025-01-24", chip: "DRAFTED", amount_cents: 3_465_000 },
  { seq: 2, at: "2025-01-25T06:41:12Z", kind: "access_denied", actor: "agent.drafter", summary: "agent.drafter approve_payout → DENIED · SoD", ref: "NS31@2025-01-24", chip: "DENIED", amount_cents: null },
];

/** Q-1 as the API serves it to the Judge: the passenger's name already replaced by the broker. */
const Q1_AS_JUDGE = {
  id: "Q-1",
  case_refs: ["NS31@2025-01-24:14C"],
  found: "On 24 Jan the T2 service desk gave passenger 14C ([redacted]) a €300 voucher. CRM records it as accepted.",
  evidence: [{ fact_id: "f2", source_id: "claim:CLM-1", field: "claim.passenger_name", value: "[redacted]", quote: "[redacted]", role: "context", trust_tier: 4 }],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia;
  Element.prototype.scrollIntoView ??= function () {};
  setTransport(async (path) => {
    if (path.startsWith("/commits")) return json(COMMITS);
    if (path.startsWith("/blame")) return json(BLAME);
    if (path === "/access/matrix") return json(MATRIX);
    if (path === "/access/log") return json(LOG);
    if (path === "/controls") return json(CONTROLS);
    if (path.startsWith("/questions")) return json([Q1_AS_JUDGE]);
    if (path.startsWith("/trace")) return json(EVENTS);
    if (path === "/storms" || path === "/rules") return json([]);
    return json({ error: { code: "not_found", message: "Not here." } }, 404);
  });
});
afterEach(cleanup);

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[url]}>
          <TraceScreen />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Trace screen", () => {
  it("opens on the whole live trace, newest first, with chips and linked refs", async () => {
    renderAt("/trace");
    const list = await screen.findByRole("list", { name: "Trace events, newest first" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("agent.drafter approve_payout → DENIED · SoD");
    expect(rows[0]).toHaveTextContent("DENIED");
    expect(within(rows[1]).getByRole("link", { name: "NS31" })).toHaveAttribute("href", "/flights/NS31%402025-01-24");
    await userEvent.click(screen.getByRole("button", { name: "drafted 1" }));
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(1));
  });

  it("opens blame for a bare ?target= (what Flight File links to)", async () => {
    renderAt("/trace?target=NS31%402025-01-24");
    expect(await screen.findByRole("tab", { name: "Blame", selected: true })).toBeInTheDocument();
    const chain = await screen.findByTestId("blame-chain");
    expect(chain.querySelectorAll(":scope > li")[0]).toHaveTextContent("€34,650");
  });

  it("filters the live trace to a question's events", async () => {
    renderAt("/trace?target=Q-9");
    expect(await screen.findByRole("tab", { name: "Live", selected: true })).toBeInTheDocument();
    expect(await screen.findByText("No events about Q-9 yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show every event, not just Q-9" }));
    expect(await screen.findByRole("list", { name: "Trace events, newest first" })).toBeInTheDocument();
  });

  it("lists commits newest first with their kind, and filters by kind", async () => {
    renderAt("/trace?tab=commits");
    const list = await screen.findByRole("list", { name: "Commits, newest first" });
    const rows = within(list).getAllByRole("button", { expanded: false });
    expect(rows[0]).toHaveTextContent("c3ccccc");
    await userEvent.click(screen.getByRole("button", { name: "llm_call 1" }));
    expect(within(list).getAllByRole("button", { expanded: false })).toHaveLength(1);
    expect(within(list).getByText("Reader extracted 4 facts")).toBeInTheDocument();
  });

  it("opens a commit to its parent and jumps to it", async () => {
    renderAt("/trace?tab=commits");
    const list = await screen.findByRole("list", { name: "Commits, newest first" });
    await userEvent.click(within(list).getByText("NS31 recoded 71 → 41"));
    await userEvent.click(within(list).getByRole("button", { name: /b2bbbbbbbbb/ }));
    expect(within(list).getByRole("button", { expanded: true })).toHaveTextContent("Reader extracted 4 facts");
  });

  it("walks a euro back to a METAR observation", async () => {
    renderAt("/trace?tab=blame&target=NS31%402025-01-24");
    const chain = await screen.findByTestId("blame-chain");
    const steps = chain.querySelectorAll(":scope > li");
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent("€34,650");
    expect(steps[steps.length - 1]).toHaveTextContent("METAR");
    expect(steps[steps.length - 1]).toHaveTextContent("EIDW 232130Z");
  });

  it("shows people and agents in the matrix, and the denial as DENIED · SoD", async () => {
    renderAt("/trace?tab=access");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("rowheader");
    expect(rows.map((r) => r.textContent)).toEqual(["CLClaims Lead", "OPOps", "DRDrafter agent"]);
    const log = await screen.findByTestId("denied-log");
    expect(log).toHaveTextContent("agent.drafterapprove_payout→DENIED · SoD");
    expect(log).not.toHaveTextContent("confirm_rule");
  });

  it("masks passenger PII for the Judge as for Ops, and offers the Claims Lead's seat", async () => {
    renderAt("/trace?tab=access");
    const panel = await screen.findByRole("region", { name: "PII mask" });
    expect(await within(panel).findByText("Masked for you too, as Judge.")).toBeInTheDocument();
    expect(within(panel).getAllByText("hidden").length).toBeGreaterThanOrEqual(4);
    expect(panel).not.toHaveTextContent("[redacted]");
    expect(within(panel).getByRole("button", { name: "View as Claims Lead" })).toBeInTheDocument();
  });

  it("labels the SOC 2 controls as a mapping, sorted, with links to evidence", async () => {
    renderAt("/trace?tab=controls");
    expect(await screen.findByRole("heading", { name: "SOC 2 is the floor" })).toBeInTheDocument();
    expect(screen.getByText("mapping · not a certification")).toBeInTheDocument();
    const items = within(await screen.findByRole("list", { name: "Control mapping" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("CC6.1");
    expect(within(items[1]).getByRole("link", { name: "Evidence for CC7.2: Denied log" })).toHaveAttribute("href", "/trace?tab=access#denied");
  });
});
