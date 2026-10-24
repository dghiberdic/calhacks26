import { expect, test, type Page } from "./fixtures";

/** Uncaught errors and console errors, collected for the whole visit. */
function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  return errors;
}

/** A cold dev server pre-bundles three.js and friends on the first visit; the first check gets room for it. */
const LOADED = { timeout: 45_000 };

/**
 * Words and marks that make copy read as generated; the story is held to plain, checkable sentences.
 * Checked against the page's text, its aria-labels and its alt text.
 */
const BANNED = /\b(seamless|leverag|unlock|empower|revolutioni[sz]|cutting-edge|harness|robust|delve|elevate|streamline|game-changer|comprehensive|effortless|intelligent|ai-(powered|driven|automated)|self-learning|next-gen|state-of-the-art|transform|journey|landscape|ecosystem|synergy|holistic|dive into|tapestry|supercharge|smart|magic|insights?|actionable|at scale|powerful|world-class|unleash|reimagine|innovative|frictionless|intuitive|end-to-end|stunning|immersive|delight|crafted|elegant|beautiful|the future of|imagine|introducing)\b/i;

// The scroll story: Storm Éowyn from the API (the mock world by default). Reduced motion shows every
// beat in its final state with no pins, so these checks don't depend on scroll timing.
test.describe("story, reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("tells NS31's recode and links to the storm run", async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/story");
    await expect(page.getByRole("heading", { level: 1, name: "Storm Éowyn" })).toBeVisible(LOADED);
    await expect(page).toHaveTitle("Storm Éowyn, 24 Jan 2025 · StormCheck");

    // The board flips NS31 to TECH 41 with its full Art. 7 entitlement, from the API.
    await expect(page.locator('[data-flight="NS31"]').first()).toHaveAttribute("data-tone", "notweather");

    const recode = page.getByTestId("story-recode");
    await recode.scrollIntoViewIfNeeded();
    await expect(recode).toContainText("71 → 41");
    await expect(recode).toContainText("cause-finding confidence 91%");
    await expect(page.locator('[data-section="verdict"]')).toContainText("€34,650");
    await expect(page.locator('[data-section="trace"]')).toContainText(/€34,650 traces back to a log line in \d+ steps\./);

    const closing = page.getByTestId("story-closing");
    await closing.scrollIntoViewIfNeeded();
    const run = closing.getByRole("link", { name: /Open the storm run/ });
    await expect(run).toHaveAttribute("href", "/");
    await expect(closing.getByRole("link", { name: "See the pitch" })).toHaveAttribute("href", "/pitch");
    await expect(closing.getByRole("link", { name: "Bring your own storm" })).toHaveAttribute("href", "/desk");
    expect(errors).toEqual([]);
  });

  test("copy: plain words, no dashes or exclamations, every number from the API", async ({ page }) => {
    await page.goto("/story");
    await expect(page.getByTestId("story-closing")).toContainText("5,292", LOADED);
    // the page's text once, the way a reader (or a screen reader) gets it
    const { text, labels } = await page.evaluate(() => ({
      text: document.body.innerText,
      labels: [...document.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label") ?? "").concat([...document.querySelectorAll("img")].map((i) => i.alt)),
    }));
    for (const s of [text, ...labels]) {
      expect(s, "banned word").not.toMatch(BANNED);
      expect(s, "em dash").not.toContain("—");
    }
    expect(text, "exclamation mark").not.toContain("!");
    // The split-flap board and the odometers draw their glyphs in CSS: the text reads each value once.
    expect(text).not.toMatch(/0\n0\n6\n6/);
    expect(text).toContain("16:30");
    // Satellite credit, in small type.
    await expect(page.locator('[data-section="hero"]')).toContainText("© EUMETSAT");
  });

  test("the closing link opens the storm run", async ({ page }) => {
    await page.goto("/story");
    const closing = page.getByTestId("story-closing");
    await closing.scrollIntoViewIfNeeded();
    await expect(closing).toBeVisible(LOADED);
    await closing.getByRole("link", { name: /Open the storm run/ }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("storm-headline")).toContainText("5,292");
  });
});

test("story with motion: scrolling to the board flips NS31 to TECH", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/story");
  await expect(page.getByRole("heading", { level: 1, name: "Storm Éowyn" })).toBeVisible(LOADED);
  // Past the pinned hero to the departures board; the re-check fires when NS31's row is on screen.
  const ns31 = page.locator('[data-flight="NS31"]').first();
  await expect(ns31).toBeAttached({ timeout: 15_000 });
  await ns31.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.4));
  await expect(ns31).toHaveAttribute("data-tone", "notweather", { timeout: 10_000 });
  await expect(ns31).toContainText("TECH 41");
  expect(errors).toEqual([]);
});

test("story with motion: the storm's clock runs (Meteosat loop and ERA5 hours)", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/story");
  const stamp = page.locator('[data-section="hero"] .hero-copy .micro');
  // the first paint holds 12:00Z on the 24th; once the satellite loop plays, the hour moves on
  await expect(stamp).toContainText("24 Jan 2025, 12:00Z", LOADED);
  await expect(stamp).not.toContainText("24 Jan 2025, 12:00Z", { timeout: 30_000 });
  expect(errors).toEqual([]);
});
