import { expect, test, type Page } from "@playwright/test";

const SEATS: [RegExp, string][] = [
  [/claims[\s_-]?lead/i, "claims_lead"],
  [/controller/i, "controller"],
  [/\bcfo\b/i, "cfo"],
  [/\blegal\b/i, "legal"],
  [/\bops\b/i, "ops"],
];

async function viewAs(page: Page, role: string) {
  await page.getByTestId("role-switcher").click();
  await page.getByTestId(`role-${role}`).click();
  await expect(page.getByTestId("role-switcher")).toHaveAttribute("aria-label", new RegExp(`Viewing as ${role === "cfo" ? "CFO" : role.replace("_", " ")}`, "i"));
}

test("the CFO bridge, the 2140 rollforward and the estimate render from the API", async ({ page }) => {
  await page.goto("/close");
  await expect(page.getByRole("heading", { name: /Cash basis .* full entitlement .* drafted .*±5pp/ })).toBeVisible();
  await expect(page.getByRole("table", { name: /2140 EU261 compensation liability rollforward/ })).toBeVisible();
  await expect(page.getByTestId("ties-to-gl")).toContainText(/ties to GL 2140/i);
  await expect(page.getByText("Bornhuetter-Ferguson").first()).toBeVisible();
  await expect(page.getByTestId("invariants")).toBeVisible();
});

test("the preparer approving their own entry is DENIED · SoD, in place", async ({ page }) => {
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
  expect(target, "a draft prepared by a person").not.toBeNull();
  await viewAs(page, target!.role);
  const card = page.getByTestId(target!.id);
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByTestId("denied")).toHaveText("DENIED · SoD");
  // In place, not a crash: the rest of the screen is still there.
  await expect(page.getByRole("heading", { name: "Liability & Close" })).toBeVisible();
});

test("month-end drafts the change in estimate: +€3,990", async ({ page }) => {
  await page.goto("/close?period=2025-02");
  await viewAs(page, "controller");
  await page.getByTestId("month-end").click();
  const result = page.getByTestId("month-end-result");
  await expect(result).toContainText("3,990");
  await expect(result).toContainText("change in estimate (IAS 8.36)");
});

test("other seats read the close; they don't act on it", async ({ page }) => {
  await page.goto("/close");
  await viewAs(page, "ops");
  await expect(page.getByTestId("read-only-hint")).toBeVisible();
  await expect(page.getByTestId("month-end")).toHaveCount(0);
});
