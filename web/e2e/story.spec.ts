import { expect, test, type Page } from "@playwright/test";

/** Uncaught errors and console errors, collected for the whole visit. */
function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  return errors;
}

// The scroll story: Storm Éowyn from the API (the mock world by default). Reduced motion shows every
// beat in its final state with no pins, so these checks don't depend on scroll timing.
test.describe("story, reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("tells NS31's recode and links to the storm run", async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/story");
    await expect(page.getByRole("heading", { level: 1, name: "Every storm leaves a bill." })).toBeVisible();

    // The board flips NS31 to TECH 41 with its full Art. 7 entitlement, from the API.
    await expect(page.locator('[data-flight="NS31"]').first()).toHaveAttribute("data-tone", "notweather");

    const recode = page.getByTestId("story-recode");
    await recode.scrollIntoViewIfNeeded();
    await expect(recode).toContainText("71 → 41");
    await expect(recode).toContainText("cause-finding confidence 91%");
    await expect(page.locator('[data-section="verdict"]')).toContainText("€34,650");

    const closing = page.getByTestId("story-closing");
    await closing.scrollIntoViewIfNeeded();
    const run = closing.getByRole("link", { name: /Open the storm run/ });
    await expect(run).toHaveAttribute("href", "/");
    await expect(closing.getByRole("link", { name: "See the pitch" })).toHaveAttribute("href", "/pitch");
    await expect(closing.getByRole("link", { name: "Bring your own storm" })).toHaveAttribute("href", "/desk");
    expect(errors).toEqual([]);
  });

  test("the closing link opens the storm run", async ({ page }) => {
    await page.goto("/story");
    const closing = page.getByTestId("story-closing");
    await closing.scrollIntoViewIfNeeded();
    await closing.getByRole("link", { name: /Open the storm run/ }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("storm-headline")).toContainText("5,292");
  });
});

test("story with motion: scrolling to the board flips NS31 to TECH", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/story");
  await expect(page.getByRole("heading", { level: 1, name: "Every storm leaves a bill." })).toBeVisible();
  // Past the pinned hero to the departures board; the re-check fires when NS31's row is on screen.
  const ns31 = page.locator('[data-flight="NS31"]').first();
  await expect(ns31).toBeAttached({ timeout: 15_000 });
  await ns31.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.4));
  await expect(ns31).toHaveAttribute("data-tone", "notweather", { timeout: 10_000 });
  await expect(ns31).toContainText("TECH 41");
  expect(errors).toEqual([]);
});
