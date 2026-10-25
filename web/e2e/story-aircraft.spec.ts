import { expect, test } from "./fixtures";

test("the story loads the downloaded aircraft and matching still without render errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  const model = page.waitForResponse((r) =>
    new URL(r.url()).pathname.endsWith("/idg-a320neo/stormcheck.glb"),
  );
  await page.goto("/story");
  const blueprint = page.locator('[data-section="blueprint"]');
  await blueprint.scrollIntoViewIfNeeded();
  expect((await model).ok()).toBeTruthy();
  await expect(blueprint.locator("canvas")).toBeAttached();
  // Finish the pinned blueprint reveal, including the camera's walk to engine 2.
  await blueprint.evaluate((el) => {
    const spacer = el.parentElement!;
    window.scrollTo(
      0,
      spacer.getBoundingClientRect().top + window.scrollY + innerHeight * 2.65,
    );
  });
  await expect(blueprint.locator(".bp-canvas")).toHaveCSS("opacity", "1");
  await expect(blueprint.locator(".bp-caption-3d")).toHaveCSS("opacity", "1");
  const still = page.locator('[data-section="interlude"] img');
  // The still continuously drifts. Scroll its section without waiting for the image to stop moving.
  await page
    .locator('[data-section="interlude"]')
    .evaluate((el) => el.scrollIntoView());
  await expect(still).toHaveAttribute("src", /poster-2560.webp\?v=[a-f0-9]+$/);
  await expect
    .poll(() =>
      still.evaluate(
        (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
      ),
    )
    .toBeTruthy();
  expect(errors).toEqual([]);
});

test("the shared sketches and branded still fit a phone with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/story");
  const blueprint = page.locator('[data-section="blueprint"]');
  await blueprint.scrollIntoViewIfNeeded();
  await expect(blueprint.locator(".bp-side")).toHaveAttribute("aria-label", /StormCheck Airbus A320neo/);
  for (const selector of [".bp-side", ".bp-plan"]) {
    const box = await blueprint.locator(selector).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  }
  await expect(blueprint.locator("canvas")).toHaveCount(0);
  const interlude = page.locator('[data-section="interlude"]');
  await interlude.scrollIntoViewIfNeeded();
  const image = interlude.locator("img");
  await expect(image).toHaveAttribute("alt", /StormCheck A320neo/);
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
});
