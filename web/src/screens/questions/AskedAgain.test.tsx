import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { setTransport } from "@/api/client";
import type { Question, Rule } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { runOfMark } from "@/app/TimeScrubber";
import { QuestionCard } from "./QuestionCard";
import { questionReason, widenLabel } from "./lib";

const ASKED: Question = {
  id: "Q-EIDW@2025-01-26:voucher_in_lieu_unsigned",
  case_refs: ["NS30@2025-01-25:23F"],
  pattern: "voucher_in_lieu_unsigned",
  routed_to: "claims_lead",
  asked_at: "2025-01-27T06:00:00Z",
  title: "Does a €300 service-desk voucher 'in lieu of compensation' offset 23F's €600?",
  found: "23F (NS30) holds a €300 service-desk voucher 'in lieu of compensation' with no signed acceptance on file.",
  why_flagged: "Art. 7(3) needs signed acceptance for an offset.",
  recommends: "No signed acceptance, no offset: pay cash; the voucher stays as goodwill.",
  recommended_option: "Pay €600 cash; the voucher stays as goodwill",
  options: ["Pay €600 cash; the voucher stays as goodwill", "Offset the voucher: pay the balance in cash"],
  evidence: [],
  confidence: { score: 0.39, kind: "voucher", label: "voucher confidence", features: {}, calibration_version: "cal-1" },
  reason_tag: "out-of-scope",
  holds: ["NS30@2025-01-25:23F"],
  holds_cents: 60000,
  status: "open",
  asked_again: {
    rule_ref: "R-CL-1@1",
    rule_title: "No signed acceptance, no offset",
    reason: "Your rule R-CL-1 covers flights leaving the EU. NS30 Boston → Dublin arrives into the EU, so it asks instead of stretching your ruling.",
    widen: { rule_id: "R-CL-1", question: "Also cover flights arriving into the EU (e.g. BOS→DUB)?" },
  },
};

const WIDENED: Rule = {
  id: "R-CL-1", version: 2, kind: "voucher", tier: "claims_lead_ruling", authority_required: "claims_lead", action: "deny_offset",
  scope: {}, condition: {}, grounding: {}, times_cited: 0, valid_from: null, recorded_at: "2025-01-27T06:00:00Z", status: "active",
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const calls: string[] = [];

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia;
  setTransport(async (path, init) => {
    if (init.method === "POST") calls.push(path);
    if (path === "/rules/R-CL-1/widen" && init.method === "POST") return json({ rule: WIDENED, checks: {}, would_flip: { rule_ref: "R-CL-1@2", known_at: "2025-01-27T06:00:00Z", flips: [], total_delta_cents: 0 }, widen_next: null });
    if (path === "/rules") return json([]);
    if (path.startsWith("/questions")) return json([]);
    return json({ error: { code: "not_found", message: "Not here." } }, 404);
  });
});
afterEach(cleanup);

function renderCard(role: "claims_lead" | "legal") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter>
          <QuestionCard question={ASKED} role={role} flow={{ step: "answer" }} onFlow={() => {}} />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("a question asked again outside a rule's scope", () => {
  it("says so at the top of the card, with a one-click widen and the answer form kept below", async () => {
    renderCard("claims_lead");
    const banner = screen.getByTestId("asked-again");
    expect(banner).toHaveTextContent("Asked again · outside your rule’s scope");
    expect(banner).toHaveTextContent("NS30 Boston → Dublin arrives into the EU");
    expect(screen.getByRole("button", { name: "Submit ruling" })).toBeInTheDocument();
    await userEvent.click(within(banner).getByRole("button", { name: "Also cover flights arriving into the EU (e.g. BOS→DUB)" }));
    await waitFor(() => expect(calls).toContain("/rules/R-CL-1/widen"));
    // The server applied it (status active): no separate confirm.
    expect(calls.filter((c) => c.includes("/confirm"))).toEqual([]);
  });

  it("reads the reason as outside your rule's scope, never sources disagree", () => {
    expect(questionReason(ASKED)).toBe("outside your rule's scope");
    expect(questionReason({ ...ASKED, asked_again: null, reason_tag: "sources-disagree" })).toBe("sources disagree");
    expect(widenLabel({ asked_again: { ...ASKED.asked_again!, widen: null } })).toBe("Also cover flights arriving into the EU");
  });

  it("shows other seats why, without the widen button", () => {
    renderCard("legal");
    const banner = screen.getByTestId("asked-again");
    expect(within(banner).queryByRole("button", { name: /Also cover/ })).toBeNull();
    expect(banner).toHaveTextContent("Only the Claims Lead can widen R-CL-1.");
  });
});

describe("Known at marks", () => {
  it("land on the run they trigger, from the server's run_id or the label", () => {
    expect(runOfMark({ label: "Storm Herminia", run_id: "EIDW@2025-01-26" })).toBe("EIDW@2025-01-26");
    expect(runOfMark({ label: "Storm Herminia" })).toBe("EIDW@2025-01-26");
    expect(runOfMark({ label: "Iberian blackout · 28 Apr 2025" })).toBe("EIDW@2025-04-28");
    expect(runOfMark({ label: "January close" })).toBeNull();
  });
});
