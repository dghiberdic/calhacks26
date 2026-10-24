import { expect, test } from "./fixtures";

test("the shell shows every section and switches role", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const label of ["Storm Run", "Flight File", "Questions", "Policies", "Trace", "Liability & Close", "Judge's Desk", "Proof", "Pitch", "The story"]) {
    await expect(nav.getByRole("link", { name: new RegExp(label) })).toBeVisible();
  }
  await page.getByTestId("role-switcher").click();
  await page.getByTestId("role-controller").click();
  await expect(page.getByText("Viewing as Controller")).toBeVisible();
});

test("an unknown page is diverted, not broken", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByText("DIVERTED")).toBeVisible();
});
