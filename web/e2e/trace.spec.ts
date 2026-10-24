import { expect, test } from "@playwright/test";

// J5 · Trace: commits, blame, access and controls, each deep-linkable with ?tab=.

test("commits read like git log, including llm_call commits", async ({ page }) => {
  await page.goto("/trace");
  await expect(page.getByRole("tab", { name: "Commits" })).toHaveAttribute("aria-selected", "true");
  const list = page.getByRole("list", { name: "Commits, newest first" });
  await expect(list.locator("li[data-hash]").first()).toBeVisible();
  await page.getByRole("button", { name: /^llm_call \d+$/ }).click();
  await expect(list.locator("li[data-hash]").first()).toContainText("llm_call");
  await list.locator("li[data-hash] > button").first().click();
  await expect(list.getByText("payload", { exact: true }).first()).toBeVisible();
});

test("the blame chain ends in a METAR observation", async ({ page }) => {
  await page.goto("/trace?tab=blame");
  const chain = page.getByTestId("blame-chain");
  await expect(chain).toBeVisible();
  const steps = chain.locator(":scope > li");
  expect(await steps.count()).toBeGreaterThan(2);
  await expect(steps.last()).toContainText("METAR");
});

test("the denied log shows DENIED · SoD", async ({ page }) => {
  await page.goto("/trace?tab=access");
  const log = page.getByTestId("denied-log");
  await expect(log).toBeVisible();
  await expect(log).toContainText("DENIED · SoD");
  await expect(page.getByRole("table")).toContainText("redacted");
});

test("view as Ops: passenger PII stays masked for Ops, in the clear only for the Claims Lead", async ({ page }) => {
  await page.goto("/trace?tab=access");
  const panel = page.getByRole("region", { name: "PII mask" });
  await expect(panel.getByText("Masked for you too, as Judge.")).toBeVisible();
  await panel.getByRole("button", { name: "View as Claims Lead" }).click();
  await expect(panel.getByText("Masked for you too", { exact: false })).toHaveCount(0);
  await expect(panel.getByRole("article", { name: "Ops's view" }).getByRole("img", { name: "redacted" }).first()).toBeVisible();
});

test("controls are a SOC 2 mapping, not a certification", async ({ page }) => {
  await page.goto("/trace?tab=controls");
  await expect(page.getByRole("heading", { name: "SOC 2 is the floor" })).toBeVisible();
  await expect(page.getByText("mapping · not a certification")).toBeVisible();
  await expect(page.getByRole("list", { name: "Control mapping" }).locator("li").first()).toBeVisible();
});

test("tabs work from the keyboard and keep the URL in step", async ({ page }) => {
  await page.goto("/trace?tab=commits");
  await page.getByRole("tab", { name: "Commits" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Blame" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=blame/);
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Controls" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=controls/);
});
