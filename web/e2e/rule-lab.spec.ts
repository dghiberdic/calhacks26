import { readFile } from "node:fs/promises";
import { expect, test } from "./fixtures";

// Keep this deterministic on a laptop with or without the optional lab service.
test.beforeEach(async ({ page }) => {
  await page.route("**/rule-lab-api/**", route => route.fulfill({status: 503, body: "Lab offline"}));
});

test("the animated story opens Rule Lab and preserves the rule's boundaries", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/story");
  await expect(page.getByRole("heading", {level: 1, name: "Storm Éowyn"})).toBeVisible({timeout: 45_000});
  await page.getByRole("navigation").getByRole("link", {name: "Rule Lab", exact: true}).click();
  const lab = page.getByTestId("rule-lab");
  await expect(page).toHaveURL(/#rule-lab$/);
  await expect(lab.getByRole("heading", {name: "Ready for human review"})).toBeInViewport();
  await expect(lab).toContainText("Saved evidence · simulated cases");
  await expect(lab.getByRole("group", {name: "Should resolve"}).getByRole("button")).toHaveCount(32);
  await expect(lab.getByRole("group", {name: "Must preserve"}).getByRole("button")).toHaveCount(6);

  await lab.getByRole("button", {name: "Widen the scope", exact: true}).click();
  await expect(lab.getByRole("heading", {name: "Candidate blocked"})).toBeVisible();
  const detail = lab.getByRole("region", {name: "Case evidence"});
  await expect(detail).toContainText("NS30@2025-01-25:23F");
  await expect(detail).toContainText("Needs a ruling");
  await expect(detail).toContainText("Owed");

  await lab.getByRole("button", {name: "Drop consent", exact: true}).click();
  await expect(detail).toContainText("Candidate matches: yes · expected: no");
  await expect(lab).toContainText("50/51");
  await lab.getByRole("button", {name: "Change the author", exact: true}).click();
  await expect(lab).toContainText("No candidate simulation ran.");
  await expect(detail).toHaveCount(0);
  await expect(lab).toContainText("7/8");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    lab.getByRole("button", {name: "Export evidence"}).click(),
  ]);
  const exported = JSON.parse(await readFile(await download.path(), "utf8"));
  expect(exported.preset).toBe("wrong_authority");
  expect(exported.simulation_ran).toBe(false);
  expect(exported.isolation.activated_rules).toBe(0);
  expect(errors).toEqual([]);
});

test.describe("small screen with reduced motion", () => {
  test.use({viewport: {width: 390, height: 844}, reducedMotion: "reduce"});

  test("the story workbench fits and opens the app's Rule Lab", async ({ page }) => {
    await page.goto("/story");
    const lab = page.getByTestId("rule-lab");
    await expect(lab.getByRole("heading", {name: "Ready for human review"})).toBeVisible({timeout: 45_000});
    await lab.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("link", {name: "Open Rule Lab in the app"}).click();
    await expect(page).toHaveURL(/\/rule-lab$/);
    await expect(page).toHaveTitle("Rule Lab · StormCheck");
    await expect(page.getByRole("heading", {level: 1, name: "Rule Lab"})).toBeVisible();
    await expect(page.getByTestId("rule-lab")).toContainText("Ready for human review");
  });
});
