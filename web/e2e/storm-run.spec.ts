import { expect, test } from "./fixtures";

// THREAD_JUSTIN J1: the NS31 red tick, "€34,650", "71 → 41" and "5,292" are all visible.
test("Storm Run tells the overnight story", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("storm-headline")).toContainText("5,292");
  // The timeline settles: NS31's tick ends red ("Not weather"), the callout appears with the recode.
  const ns31 = page.locator('g[data-flight="NS31"]');
  await expect(ns31).toHaveAttribute("data-verdict", "notweather", { timeout: 10_000 });
  const callout = page.getByTestId("not-weather-callout");
  await expect(callout).toContainText("Not weather.");
  await expect(callout).toContainText("71 → 41");
  await expect(page.getByTestId("ns31-liability")).toContainText("€34,650");
});

test("a tick opens its flight file", async ({ page }) => {
  await page.goto("/");
  const ns31 = page.locator('g[data-flight="NS31"]');
  await expect(ns31).toHaveAttribute("data-verdict", "notweather", { timeout: 10_000 });
  // Click the bar itself, without force, so Playwright waits for NS31 to finish sliding out of the window.
  await ns31.locator("rect").click();
  await expect(page).toHaveURL(/\/flights\/NS31/);
});
