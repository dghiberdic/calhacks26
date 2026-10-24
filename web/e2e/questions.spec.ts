import { expect, serverMasksPii, test, type Page } from "./fixtures";

const LABEL: Record<string, string> = { claims_lead: "Claims Lead", ops: "Ops", legal: "Legal", controller: "Controller" };

async function viewAs(page: Page, role: keyof typeof LABEL) {
  await expect(page.getByRole("heading", { name: "Questions", level: 1 })).toBeVisible(LOADED);
  await page.getByTestId("role-switcher").click();
  await page.getByTestId(`role-${role}`).click();
  await expect(page.getByTestId("role-switcher")).toHaveAccessibleName(new RegExp(`Viewing as ${LABEL[role]}`));
}

/** First paint of a lazily loaded screen on a cold dev server can take a while; the checks after it use the default. */
const LOADED = { timeout: 45_000 };
test.describe.configure({ timeout: 90_000 });

/** Q1 is the 14C service-desk voucher: its case ref chip reads "NS31 · 14C". */
const q1 = (page: Page) => page.locator("article", { hasText: "14C" });

test("Q1 goes to the Claims Lead and never reaches Ops", async ({ page }) => {
  await page.goto("/questions");
  await viewAs(page, "claims_lead");
  await expect(q1(page).first()).toBeVisible(LOADED);
  await viewAs(page, "ops");
  await expect(page.getByText(/Nothing is waiting on Ops/)).toBeVisible();
  await expect(q1(page)).toHaveCount(0);
});

test("the Claims Lead rules on Q1 with the recommended option, and it is never asked again", async ({ page }) => {
  await page.goto("/questions");
  await viewAs(page, "claims_lead");
  const card = q1(page).first();
  await expect(card).toBeVisible(LOADED);
  // The recommended option comes preselected; the ruling is in the Claims Lead's own words.
  await expect(card.getByRole("radio", { checked: true })).toHaveCount(1);
  await card.getByRole("textbox").fill("No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.");
  await card.getByRole("button", { name: "Submit ruling" }).click();
  await expect(card.getByTestId("rule-preview")).toBeVisible();
  await card.getByRole("button", { name: "Confirm as policy" }).click();
  await expect(card.getByText("Never asked again")).toBeVisible();
});

test("passenger data shows only to the Claims Lead; other seats get it masked", async ({ page, request }) => {
  test.skip(!(await serverMasksPii(request)), "this server sends no passenger names to mask (contracts/requests/justin.md #21)");
  await page.goto("/questions");
  // The judge sees every question read-only, with the passenger's name masked by the server.
  await expect(q1(page).first().getByTitle(/visible to the Claims Lead only/)).toBeVisible(LOADED);
  await expect(q1(page).first().getByRole("button", { name: /View as Claims Lead to answer/ })).toBeVisible();
  await viewAs(page, "claims_lead");
  await expect(q1(page).first().getByText("PII visible to this role")).toBeVisible();
  await expect(q1(page).first().getByTitle(/visible to the Claims Lead only/)).toHaveCount(0);
});
