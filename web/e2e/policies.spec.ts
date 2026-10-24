import { expect, test, type Locator, type Page } from "./fixtures";

// J4 · Policies. Rules come only from history, rulings, rejections and regulation: there is no rule editor.

// A cold dev server compiles each route on first visit, and other lanes share this machine: give the first
// paint room, keep every other expectation at the config's default.
test.describe.configure({ timeout: 60_000 });
const FIRST_PAINT = { timeout: 25_000 };

async function open(page: Page, hash = "") {
  await page.goto(`/policies${hash}`);
  await expect(page.getByRole("heading", { name: "Policies", level: 1 })).toBeVisible(FIRST_PAINT);
  await expect(page.locator('[data-testid^="rule-"]').first()).toBeVisible(FIRST_PAINT);
}

/** A 403 offers the seat with the authority; take it, so the test reads the same in every role. */
async function acceptRoleSwitch(dialog: Locator, done: Locator) {
  const retry = dialog.getByRole("button", { name: /^View as .+ and try again$/ });
  await expect(done.or(retry)).toBeVisible(FIRST_PAINT);
  if (await retry.isVisible()) await retry.click();
  await expect(done).toBeVisible();
}

test("nothing on the page offers a new rule or a rule editor", async ({ page }) => {
  await open(page);
  expect(await page.locator("body").innerText()).not.toMatch(/new rule/i);
  await expect(page.getByRole("button", { name: /new rule|add rule|create rule|edit rule/i })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("textbox")).toHaveCount(0);
});

test("policies are grouped by origin", async ({ page }) => {
  await open(page);
  for (const origin of ["Learned", "Ruled", "Rejected", "Regulation"]) {
    await expect(page.getByRole("heading", { name: origin, level: 2, exact: true })).toBeVisible();
  }
});

test("the Reg (EU) 2026/2202 card is visible, display only", async ({ page }) => {
  await open(page);
  const card = page.getByTestId("static-regulation-card");
  await card.scrollIntoViewIfNeeded();
  await expect(card).toBeVisible();
  await expect(card).toContainText("2026/2202");
  await expect(card).toContainText(/in force/i);
  await expect(card).toContainText(/applies from/i);
  await expect(card.getByRole("button")).toHaveCount(0);
});

test("revert replays history and shows the diff", async ({ page }) => {
  await open(page);
  const revert = page.getByRole("button", { name: /^Revert \S+@\d+$/ }).first();
  await revert.scrollIntoViewIfNeeded();
  await revert.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(/locked periods are never rewritten/i);
  await dialog.getByRole("button", { name: "Revert and replay" }).click();
  await acceptRoleSwitch(dialog, dialog.getByText(/^flips \d+/));
  await expect(dialog.getByText(/^flips \d+ · Δ/)).toBeVisible();
});

test("a versioned link (as Flight File writes it) lands on the card", async ({ page }) => {
  await page.goto("/policies");
  const card = page.locator('[data-testid^="rule-"]').last();
  await expect(card).toBeAttached(FIRST_PAINT);
  const ref = (await card.getAttribute("id"))!;
  expect(ref).toMatch(/@\d+$/);
  await page.goto("about:blank");
  await page.goto(`/policies#${encodeURIComponent(ref)}`);
  await expect(page.locator(`[id="${ref}"]`)).toBeInViewport(FIRST_PAINT);
});

test("a deep link scrolls to its rule", async ({ page }) => {
  await page.goto("/policies");
  const first = page.locator('[data-testid^="rule-"]').last();
  await expect(first).toBeAttached(FIRST_PAINT);
  const id = (await first.getAttribute("data-testid"))!.replace(/^rule-/, "");
  await page.goto("about:blank");
  await page.goto(`/policies#${id}`);
  await expect(page.getByTestId(`rule-${id}`)).toBeInViewport(FIRST_PAINT);
});
