import { copyProblem } from "../src/pitch/copy";
import { expect, test, type Page } from "./fixtures";

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

test("a clicker pressed twice before the deck re-renders still moves twice", async ({ page }) => {
  await page.goto("/pitch/1");
  await expect(page.getByTestId("slide-business")).toBeVisible();
  await page.evaluate(() => {
    for (let i = 0; i < 2; i++) window.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", cancelable: true }));
  });
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

test("the figures on the slides come from the API (golden numbers)", async ({ page, request }) => {
  // The drafted count is the API's: 172 in the mock world, 171 on the real engine (14C's €600 is held for Q1).
  const drafted =
    (process.env.E2E_API_MODE ?? "mock") === "mock"
      ? 172
      : ((await (await request.get("/api/storms/EIDW%402025-01-24")).json()) as { counters: { drafted: number } }).counters.drafted;
  await page.goto("/pitch/1");
  await expect(page.getByText(/5,292\s+passengers, one storm/)).toBeVisible();
  await page.goto("/pitch/2");
  await expect(page.getByText(new RegExp(`${drafted.toLocaleString("en-US")}\\s+payouts drafted, pending Claims Lead approval`))).toBeVisible();
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

/** Every text node on the slide, one per entry, so words in neighbouring elements never run together. */
const slideText = (page: Page, id: string) =>
  page.getByTestId(`slide-${id}`).evaluate((el) => {
    const parts: string[] = [];
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) if (walk.currentNode.textContent?.trim()) parts.push(walk.currentNode.textContent.trim());
    return parts.join(" \n ");
  });

test("each slide names itself in the tab, and none of its words read as generated", async ({ page }) => {
  await page.goto("/pitch/0");
  for (let i = 0; i < SLIDES.length; i++) {
    if (i > 0) await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId(`slide-${SLIDES[i]}`)).toBeVisible();
    await expect(page).toHaveTitle(`Pitch · ${i + 1}/${SLIDES.length} · StormCheck`);
    const text = await slideText(page, SLIDES[i]);
    expect(text.length, `slide ${i} has words to read`).toBeGreaterThan(60);
    expect(copyProblem(text), `slide ${i} (${SLIDES[i]}) reads:\n${text}`).toBeNull();
  }
  // The Business cards carry plain tags, the same four the app uses.
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight");
  const business = page.getByTestId("slide-business");
  for (const tag of ["from its own history", "overnight", "asks a person", "becomes policy"]) await expect(business.getByText(tag, { exact: true })).toBeVisible();
  await expect(business).not.toContainText("self-learning");
  await expect(business).not.toContainText("ai-automated");
});

/** The marker's distance along the CFO line, from its transform. */
const markerX = (page: Page) => page.getByTestId("cfo-marker").evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).m41);

test("it moves: the cover drifts, the storm strip recodes NS31, the CFO marker slides to the drafted figure", async ({ page }) => {
  await page.goto("/pitch/0");
  await expect(page.getByTestId("slide-cover")).toBeVisible();
  await expect.poll(() => page.getByTestId("cover-camera").evaluate((el) => el.getAnimations().filter((a) => a.playState === "running").length)).toBeGreaterThan(0);
  const first = await page.screenshot();
  await page.waitForTimeout(500);
  expect(first.equals(await page.screenshot()), "two frames 500 ms apart on the cover").toBe(false);

  await page.goto("/pitch/2");
  const strip = page.getByTestId("storm-strip");
  await expect(strip).toBeVisible();
  // It opens on OCC's codes and settles on the re-check; the recoded flight ends red.
  await expect(strip).toHaveAttribute("data-phase", "3", { timeout: 15_000 });
  await expect(strip.locator("[data-verdict='notweather']")).toHaveCount(1);

  await page.goto("/pitch/5");
  await expect(page.getByTestId("cfo-marker")).toBeVisible();
  expect(await markerX(page), "the marker starts at €0").toBeLessThan(40);
  await expect.poll(() => markerX(page), { timeout: 10_000 }).toBeGreaterThan(100);
  await expect(page.getByTestId("cfo-drafted")).toContainText("€34,650");
});

test("with reduced motion every slide lands in place and nothing drifts", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/pitch/0");
  await expect(page.getByTestId("slide-cover")).toBeVisible();
  expect(await page.getByTestId("cover-camera").evaluate((el) => el.getAnimations().length)).toBe(0);
  await expect(page.getByTestId("cover-flow")).toHaveCount(0);

  await page.goto("/pitch/2");
  await expect(page.getByTestId("storm-strip")).toHaveAttribute("data-phase", "3");

  await page.goto("/pitch/5");
  await expect(page.getByTestId("cfo-marker")).toBeVisible();
  const landed = await markerX(page);
  expect(landed, "the marker is already on the drafted figure").toBeGreaterThan(100);
  await page.waitForTimeout(400);
  expect(await markerX(page)).toBe(landed);
});
