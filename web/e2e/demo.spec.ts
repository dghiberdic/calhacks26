import { expect, test, type Page } from "./fixtures";

/**
 * The 3:00 demo (pitch/DEMO_SCRIPT.md), clicked end to end as a presenter would. Navigation stays inside the
 * app (sidebar links, buttons), never page.goto after the first load: in mock mode a reload resets the world,
 * and on the real server the order of writes is the story. Paste texts are the plan's, character for character.
 */

const TEXT = {
  challenge: "The storm would have grounded it anyway",
  q1: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
  q2: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).",
  q3: "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year limitation.",
};
const ROLE_LABEL = { judge: "Judge", claims_lead: "Claims Lead", legal: "Legal", controller: "Controller" } as const;

test.describe.configure({ mode: "serial", timeout: 240_000 });

async function viewAs(page: Page, role: keyof typeof ROLE_LABEL) {
  await page.getByTestId("role-switcher").click();
  await page.getByTestId(`role-${role}`).click();
  await expect(page.getByTestId("role-switcher")).toHaveAccessibleName(new RegExp(`Viewing as ${ROLE_LABEL[role]}`));
}

/** Sidebar navigation (client-side, so the world survives). Names can carry a badge: "Questions 3 open". */
async function go(page: Page, nav: string) {
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: new RegExp(`^${nav}`) }).click();
}

/** Answer the one open card containing `marker` as the current seat, then confirm the rule it drafts. */
async function rule(page: Page, marker: string | RegExp, text: string, option?: string | RegExp) {
  const card = page.locator("article", { hasText: marker }).first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  if (option) await card.getByRole("radio", { name: option }).check();
  else await expect(card.getByRole("radio", { checked: true })).toHaveCount(1); // the recommendation, preselected
  await card.getByRole("textbox").fill(text);
  await card.getByRole("button", { name: /Submit ruling|Reject and preview the rule/ }).click();
  await expect(card.getByTestId("rule-preview")).toBeVisible();
  await card.getByRole("button", { name: "Confirm as policy" }).click();
  await expect(card.getByText("Never asked again")).toBeVisible();
}

test("the demo, clicked through", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // 0:00 · Storm Run, as the Judge: the overnight story settles on NS31.
  await page.goto("/");
  await expect(page.getByTestId("storm-headline")).toContainText("5,292 passengers", { timeout: 60_000 });
  await expect(page.locator('g[data-flight="NS31"]')).toHaveAttribute("data-verdict", "notweather", { timeout: 15_000 });
  const callout = page.getByTestId("not-weather-callout");
  await expect(callout).toContainText("71 → 41");
  await expect(page.getByTestId("ns31-liability")).toContainText("€34,650");

  // 0:20 · NS31's file: the tech log outranks the batch code; a bare assertion doesn't move it.
  await callout.getByRole("link", { name: /Open the flight file/ }).click();
  await expect(page).toHaveURL(/\/flights\/NS31/);
  const challenge = page.getByTestId("challenge");
  await expect(challenge).toBeVisible({ timeout: 30_000 });
  await challenge.getByRole("textbox").fill(TEXT.challenge);
  await challenge.getByRole("button", { name: "Submit challenge" }).click();
  await expect(page.getByTestId("challenge-result")).toContainText("Decision stands.");

  // 1:00 · The Claims Lead rules on the 14C voucher; the ruling becomes a policy.
  await go(page, "Questions");
  await viewAs(page, "claims_lead");
  await rule(page, "14C", TEXT.q1);

  // 1:20 · Legal: one ruling for the three knock-on returns.
  await viewAs(page, "legal");
  await rule(page, /knock-on|return sector/i, TEXT.q2);

  // 1:40 · The Controller rejects releasing Storm Isha's tail; the rejection is a rule too.
  await viewAs(page, "controller");
  // The rejection: the server's own "Reject: …"/"Keep the … tail" option, or the one the UI adds.
  await rule(page, "Isha", TEXT.q3, /^Reject|^Keep the expected tail/);

  // 1:50 · Liability & Close, still as the Controller: the CFO bridge, and 2140 ties to the GL.
  await go(page, "Liability & Close");
  await expect(page.getByRole("heading", { name: /Cash basis .* full entitlement .* drafted .*±5pp/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("ties-to-gl").first()).toBeVisible();

  // 2:00 · Judge's Desk: a day of the judge's choosing (here, the next storm).
  await viewAs(page, "judge");
  await go(page, "Judge's Desk");
  await expect(page.getByRole("heading", { name: "Name an airport and a date." })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /Storm Herminia/ }).click();
  await expect(page.getByTestId("desk-run-result")).toHaveAttribute("data-run-id", /EIDW@2025-01-26/, { timeout: 30_000 });

  // 2:30 · Proof: plain Claude against StormCheck, with the honest label.
  await go(page, "Proof");
  await expect(page.getByTestId("proof-headline")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("honest-label")).toBeVisible();

  expect(errors, "no uncaught errors during the demo").toEqual([]);
});
