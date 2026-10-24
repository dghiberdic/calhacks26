import { expect, test } from "./fixtures";

// In order, after one warm-up: a cold Vite server pre-bundles dependencies on the first load.
test.describe.configure({ mode: "default" });

test.beforeAll(async ({ browser }) => {
  test.setTimeout(120_000);
  const page = await browser.newPage();
  await page.goto("/proof");
  await expect(page.getByTestId("proof-headline")).toBeVisible({ timeout: 90_000 });
  await page.close();
});

test("the headline: plain Claude's different numbers against StormCheck's one, same hash", async ({ page }) => {
  await page.goto("/proof");
  const headline = page.getByTestId("proof-headline");
  await expect(headline).toContainText(/Plain Claude, \d+ runs: €[\d,]+( \/ €[\d,]+)+\./);
  await expect(headline).toContainText(/StormCheck: €[\d,]+ ×\d+, same hash\./);
});

test("the honest label is on the page, not hidden", async ({ page }) => {
  await page.goto("/proof");
  const label = page.getByTestId("honest-label");
  await label.scrollIntoViewIfNeeded();
  await expect(label).toBeVisible();
  await expect(label).toContainText(/calibrated on synthetic labels; validates the pipeline, not the world/i);
});

test("the scorecard and the reliability bins render from the eval", async ({ page }) => {
  await page.goto("/proof");
  for (const tile of ["Straight-through", "Miscodes caught", "False holds", "Repeat questions", "Out-of-scope automated", "Liability vs actual"]) {
    await expect(page.getByText(tile, { exact: true })).toBeVisible();
  }
  const cards = page.locator('[data-testid^="reliability-"]');
  await expect(cards.first()).toBeVisible();
  await expect(cards.first()).toContainText("coverage@0.9");
  await expect(page.getByRole("heading", { name: "Real vs simulated" })).toBeVisible();
});
