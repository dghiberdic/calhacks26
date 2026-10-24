import { expect, test } from "@playwright/test";

// THREAD_JUSTIN J11: the /pitch deck. Arrow keys move through every slide, the seats line and
// "2 Claude roles + 1 deterministic engine" are on their slides, and the URL keeps the slide.
const SLIDES = ["cover", "business", "judged", "architecture", "real", "cfo"];
const SEATS_LINE =
  "StormCheck fills two seats at Northstar Air, the Passenger Claims Accountant and the Revenue Accountant, with one step between them: what really caused each cancellation. It drafts every payout and the EU261 compensation liability; the Claims Lead approves every payment.";

// These tests type and click, so they run in order in one worker, after one warm-up: a cold Vite server
// pre-bundles dependencies on first load (and may reload the page once), which would swallow key presses.
test.describe.configure({ mode: "default" });

test.beforeAll(async ({ browser }) => {
  test.setTimeout(120_000);
  const page = await browser.newPage();
  await page.goto("/pitch/2");
  await expect(page.getByTestId("slide-judged")).toBeVisible({ timeout: 90_000 });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 90_000 });
  await page.close();
});

test("arrow keys walk the whole deck, forward and back", async ({ page }) => {
  await page.goto("/pitch");
  await expect(page).toHaveURL(/\/pitch\/0$/);
  await expect(page.getByTestId("slide-cover")).toBeVisible();
  await expect(page.getByTestId("seats-line")).toHaveText(SEATS_LINE);

  for (let i = 1; i < SLIDES.length; i++) {
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL(new RegExp(`/pitch/${i}$`));
    await expect(page.getByTestId(`slide-${SLIDES[i]}`)).toBeVisible();
    if (SLIDES[i] === "architecture") {
      const headline = page.getByRole("heading", { name: "2 Claude roles + 1 deterministic engine." });
      await expect(headline).toBeVisible();
      await expect(headline).toHaveText(/2 Claude roles\s*\+\s*1 deterministic engine/);
      await expect(page.getByTestId("sits-on-top")).toHaveText(/Sits on top of\s*Altéa\/Navitaire,\s*NetLine,\s*AMOS,\s*Accelya;\s*writes only parked journals\./);
    }
  }

  // The last slide holds; going back retraces the deck.
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/\/pitch\/5$/);
  for (let i = SLIDES.length - 2; i >= 0; i--) {
    await page.keyboard.press("ArrowLeft");
    await expect(page).toHaveURL(new RegExp(`/pitch/${i}$`));
    await expect(page.getByTestId(`slide-${SLIDES[i]}`)).toBeVisible();
  }
});

test("clicker keys, Home/End and digits jump; a reload stays on the slide", async ({ page }) => {
  await page.goto("/pitch/0");
  await expect(page.getByTestId("slide-cover")).toBeVisible(); // the deck is lazy-loaded: wait for it before typing
  await page.keyboard.press("PageDown");
  await expect(page).toHaveURL(/\/pitch\/1$/);
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/\/pitch\/2$/);
  await page.keyboard.press("PageUp");
  await expect(page).toHaveURL(/\/pitch\/1$/);
  await page.keyboard.press("End");
  await expect(page).toHaveURL(/\/pitch\/5$/);
  await page.keyboard.press("Home");
  await expect(page).toHaveURL(/\/pitch\/0$/);
  await page.keyboard.press("3");
  await expect(page).toHaveURL(/\/pitch\/3$/);

  await page.reload();
  await expect(page).toHaveURL(/\/pitch\/3$/);
  await expect(page.getByTestId("slide-architecture")).toBeVisible();
});

test("a click on the right half moves on, the left half goes back", async ({ page }) => {
  await page.goto("/pitch/2");
  await expect(page.getByTestId("slide-judged")).toBeVisible();
  const { width, height } = page.viewportSize()!;
  await page.mouse.click(width * 0.8, height * 0.5);
  await expect(page).toHaveURL(/\/pitch\/3$/);
  await page.mouse.click(width * 0.2, height * 0.5);
  await expect(page).toHaveURL(/\/pitch\/2$/);
});

test("the figures on the slides come from the API (golden numbers)", async ({ page }) => {
  await page.goto("/pitch/1");
  await expect(page.getByText(/5,292\s+passengers, one storm/)).toBeVisible();
  await page.goto("/pitch/2");
  await expect(page.getByText(/172\s+payouts drafted, pending Claims Lead approval/)).toBeVisible();
  await page.goto("/pitch/5");
  const bridge = page.getByTestId("cfo-bridge");
  await expect(bridge).toContainText("€34,650");
  await expect(bridge).toContainText("€99,000");
  await expect(bridge).toContainText("€0");
  await expect(page.getByRole("heading", { name: "Not €0. Not €99,000." })).toBeVisible();
});

test("out-of-range slides land on the deck, and Esc goes back to the app", async ({ page }) => {
  await page.goto("/pitch/99");
  await expect(page).toHaveURL(/\/pitch\/5$/);
  await expect(page.getByTestId("slide-cfo")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
});
