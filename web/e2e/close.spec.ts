import type { APIRequestContext } from "@playwright/test";
import { expect, test, type Page } from "./fixtures";

const SEATS: [RegExp, string][] = [
  [/claims[\s_-]?lead/i, "claims_lead"],
  [/controller/i, "controller"],
  [/\bcfo\b/i, "cfo"],
  [/\blegal\b/i, "legal"],
  [/\bops\b/i, "ops"],
];

// These tests switch roles and click, so they run in order in one worker, after one warm-up: a cold Vite
// server pre-bundles dependencies on the first load (and may reload the page once), which would eat a click.
test.describe.configure({ mode: "default" });

test.beforeAll(async ({ browser }) => {
  test.setTimeout(180_000);
  const page = await browser.newPage();
  await page.goto("/close");
  await expect(page.getByRole("heading", { name: "Liability & Close" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("ties-to-gl")).toBeVisible({ timeout: 90_000 });
  // Warm the role switcher too: its first use can trigger the one-time dependency reload.
  await viewAs(page, "controller");
  await page.close();
});

async function viewAs(page: Page, role: string) {
  const label = new RegExp(`Viewing as ${role === "cfo" ? "CFO" : role.replace("_", " ")}`, "i");
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.getByTestId("role-switcher").click();
    await page.getByTestId(`role-${role}`).click();
    try {
      await expect(page.getByTestId("role-switcher")).toHaveAttribute("aria-label", label, { timeout: 15_000 });
      return;
    } catch {
      // a cold dev server can reload the page once while it pre-bundles; try the switch again
    }
  }
  await expect(page.getByTestId("role-switcher")).toHaveAttribute("aria-label", label);
}

test("the CFO bridge, the 2140 rollforward and the estimate render from the API", async ({ page }) => {
  await page.goto("/close");
  // The bridge as one sentence: drafted, neither the cash basis nor the full entitlement.
  await expect(page.getByRole("heading", { name: /What we owe after .*: €[\d,]+ drafted\. Not €[\d,]+ \(cash basis\), and not €[\d,]+ \(if every passenger claimed\)\./ })).toBeVisible();
  await expect(page.getByRole("table", { name: /2140 EU261 compensation liability rollforward/ })).toBeVisible();
  await expect(page.getByTestId("ties-to-gl")).toContainText(/ties to GL 2140/i);
  // The detail is one click away: by cohort, every line with its accounts.
  await page.getByRole("radio", { name: "Rollforward detail" }).click();
  await expect(page.getByRole("table", { name: /2140 EU261 compensation liability rollforward by cohort/ })).toBeVisible();
  // How the estimate works and the controls checks sit behind their own disclosures, named in the summary.
  await expect(page.getByText("Bornhuetter-Ferguson").first()).toBeVisible();
  await page.getByText("Controls checks").click();
  await expect(page.getByTestId("invariants")).toBeVisible();
});

test("the preparer approving their own entry is DENIED · SoD, in place", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/close");
  // A draft prepared by a person (not an agent): that seat is the one to try approving it.
  const cards = page.locator('[data-testid^="je-"]');
  await expect(cards.first()).toBeVisible();
  let target: { id: string; role: string } | null = null;
  for (const card of await cards.all()) {
    const text = await card.innerText();
    const by = text.match(/prepared by\s+(\S+)/i)?.[1] ?? "";
    const seat = SEATS.find(([re]) => re.test(by))?.[1];
    if (seat) {
      target = { id: (await card.getAttribute("data-testid"))!, role: seat };
      break;
    }
  }
  // A server whose drafts are all agent-prepared can't show this from a seat (contracts/requests/justin.md #20).
  test.skip(target === null, "no draft is prepared by a person seat on this server (request #20)");
  await viewAs(page, target!.role);
  const card = page.getByTestId(target!.id);
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByTestId("denied")).toHaveText("DENIED · SoD");
  // In place, not a crash: the rest of the screen is still there.
  await expect(page.getByRole("heading", { name: "Liability & Close" })).toBeVisible();
});

// Character for character the plan's scripted rulings (as web/scripts/record.mjs): LLM calls are cached by exact input.
const SCRIPTED: Record<string, string> = {
  claims_lead: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
  legal: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).",
  controller: "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.",
};
const REJECT = /^\s*reject\b|\bnever release\b|\bdo not release\b|\bdon'?t release\b|^\s*keep the (expected )?tail\b/i;

type Q = { id: string; routed_to: string; status: string; reason_tag?: string; proposal_rule_id?: string | null; options: string[]; recommended_option: string };

/** The scripted demo up to February, on a shared server: Q-1 and Q-2 answered, Q-3's release rejected, January closed and locked. */
async function scriptedFlowToFebruary(request: APIRequestContext) {
  const token: Record<string, string> = {};
  for (const role of ["claims_lead", "legal", "controller"]) token[role] = (await (await request.post("/api/session", { data: { role, name: role } })).json()).token;
  const post = async (role: string, path: string, data?: unknown) => {
    const res = await request.post(`/api${path}`, { data, headers: { Authorization: `Bearer ${token[role]}` } });
    expect(res.ok(), `${role} POST ${path}`).toBeTruthy();
    return res.json();
  };
  const questions = (await (await request.get("/api/questions")).json()) as Q[];
  for (const role of ["claims_lead", "legal", "controller"]) {
    const q = questions.find((x) => x.routed_to === role && x.status !== "answered");
    if (!q) continue;
    const explanation = SCRIPTED[role];
    const answer =
      q.reason_tag === "release-proposal"
        ? q.proposal_rule_id
          ? await post(role, `/rules/${encodeURIComponent(q.proposal_rule_id)}/reject`, { explanation })
          : await post(role, `/questions/${encodeURIComponent(q.id)}/answer`, { decision: q.options.find((o) => REJECT.test(o)) ?? q.recommended_option, explanation })
        : await post(role, `/questions/${encodeURIComponent(q.id)}/answer`, { decision: q.recommended_option, explanation });
    const ruleId = answer?.proposal?.rule?.id;
    if (ruleId) await post(role, `/proposals/${encodeURIComponent(ruleId)}/confirm`);
  }
  await post("controller", "/books/month-end", { period: "2025-01" });
  await post("controller", "/books/lock", { period: "2025-01" });
}

test("month-end drafts the change in estimate: +€3,990 on Storm Éowyn", async ({ page, request }) => {
  test.setTimeout(150_000);
  const http = (process.env.E2E_API_MODE ?? "mock") === "http";
  if (http) await scriptedFlowToFebruary(request);
  await page.goto("/close?period=2025-02");
  await viewAs(page, "controller");
  await page.getByTestId("month-end").click();
  const result = page.getByTestId("month-end-result");
  await expect(result).toContainText("+€3,990");
  await expect(result).toContainText("change in estimate (IAS 8.36) for Storm Éowyn");
  if (http) {
    // Herminia is re-estimated too (no claims by 28 Feb): one plain line per storm, Éowyn's first, then the total.
    const rows = result.getByTestId("month-end-cohort");
    await expect(rows.first()).toHaveText("Storm Éowyn: +€3,990 change in estimate: claims came in faster than expected");
    await expect(rows.nth(1)).toHaveText("Storm Herminia: −€13,929 change in estimate: fewer claims than expected so far");
    await expect(result.getByTestId("month-end-total")).toHaveText("Total: −€9,939 change in estimate");
  }
});

test("other seats read the close; they don't act on it", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/close");
  await viewAs(page, "ops");
  await expect(page.getByTestId("read-only-hint")).toBeVisible();
  await expect(page.getByTestId("month-end")).toHaveCount(0);
});

test("a journal link (#JE-…) opens the entry's period and tab and scrolls to it", async ({ page, request }) => {
  // An entry that isn't a draft (approved or posted), so the link crosses the status tab, and in the mock
  // world (JE-000110, January's six approved NS31 claims) the period too. Picked from the API, not typed in.
  let id = "JE-000110";
  let period = "2025-01";
  if ((process.env.E2E_API_MODE ?? "mock") !== "mock") {
    const entries = (await (await request.get("/api/books/journal")).json()) as { id: string; period: string; status: string }[];
    const settled = entries.find((e) => e.status !== "draft");
    test.skip(!settled, "this server has no approved or posted entry to link to");
    ({ id, period } = settled!);
  }
  await page.goto(`/close#${id}`);
  // Cards render only for the selected period and tab, so the card in view proves both were opened. The
  // URL names the period only when it had to switch away from the one the close opens on.
  await expect(page.locator(`#${id}`)).toBeInViewport();
  if ((process.env.E2E_API_MODE ?? "mock") === "mock") await expect(page).toHaveURL(new RegExp(`period=${period}`));
});
