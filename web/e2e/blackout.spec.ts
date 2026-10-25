import { expect, test, type Page } from "./fixtures";

/**
 * Éowyn's two rulings → Storm Herminia (31 settled, BOS→DUB asked again outside the rule's scope, widened in one
 * click) → the Iberian blackout (one Legal question, 8 flights settled, NS128 and NS129 owed, care accrued). Real
 * server only: `E2E_API_MODE=http API_TARGET=http://localhost:8000 pnpm e2e e2e/blackout.spec.ts`. Navigation stays
 * in the app; the order of writes is the story.
 */

const TEXT = {
  q1: "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill.",
  q2: "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew could operate it within 3 h of STD, and passengers were offered the earliest reroute on any carrier (C-74/19).",
  blackout: "A grid outage is extraordinary for flights scheduled inside its outage window; flights outside it, and their knock-ons, are owed.",
};
const ROLE_LABEL = { judge: "Judge", claims_lead: "Claims Lead", legal: "Legal", controller: "Controller" } as const;

test.describe.configure({ mode: "serial", timeout: 300_000 });

async function viewAs(page: Page, role: keyof typeof ROLE_LABEL) {
  await page.getByTestId("role-switcher").click();
  await page.getByTestId(`role-${role}`).click();
  await expect(page.getByTestId("role-switcher")).toHaveAccessibleName(new RegExp(`Viewing as ${ROLE_LABEL[role]}`));
}

async function go(page: Page, nav: string) {
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: new RegExp(`^${nav}`) }).click();
}

/** Known at → a named mark; the clock move can run a storm, so it gets time. */
async function knownAt(page: Page, mark: RegExp) {
  await page.getByTestId("time-scrubber").click();
  await page.getByRole("button", { name: mark }).click();
}

async function rule(page: Page, marker: string | RegExp, text: string, option?: string | RegExp) {
  const card = page.locator("article", { hasText: marker }).first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  if (option) await card.getByRole("radio", { name: option }).check();
  else await expect(card.getByRole("radio", { checked: true })).toHaveCount(1);
  await card.getByRole("textbox").fill(text);
  await card.getByRole("button", { name: "Submit ruling" }).click();
  await expect(card.getByTestId("rule-preview")).toBeVisible({ timeout: 60_000 });
  await card.getByRole("button", { name: "Confirm as policy" }).click();
  await expect(card.getByText(/Policy saved for matching cases|Never asked again/)).toBeVisible({ timeout: 60_000 });
}

test("Éowyn's rulings carry to Herminia and the blackout, in the browser", async ({ page }) => {
  test.skip((process.env.E2E_API_MODE ?? "mock") !== "http", "needs the real server (E2E_API_MODE=http)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("storm-headline")).toBeVisible({ timeout: 60_000 });

  // Q-1 (Claims Lead) and Q-2 (Legal), each with the recommendation preselected.
  await go(page, "Questions");
  await viewAs(page, "claims_lead");
  await rule(page, "14C", TEXT.q1);
  await viewAs(page, "legal");
  await rule(page, /knock-on|return sector/i, TEXT.q2);

  // Storm Herminia: Known at lands on its run.
  await knownAt(page, /Storm Herminia/);
  await expect(page).toHaveURL(/\/run\/EIDW(%40|@)2025-01-26/, { timeout: 120_000 });
  await expect(page.getByText(/31 cases settled without asking/)).toBeVisible({ timeout: 60_000 });
  const asked = page.getByTestId("asked-again").first();
  await expect(asked).toContainText("Asked again · outside your rule’s scope", { timeout: 30_000 });
  await expect(asked).toContainText("arrives into the EU");
  // The widen is the Claims Lead's: take the seat from the card, then one click.
  await asked.getByRole("button", { name: /View as Claims Lead to widen/ }).click();
  await expect(page.getByTestId("role-switcher")).toHaveAccessibleName(/Viewing as Claims Lead/);
  await page.getByTestId("asked-again").first().getByRole("button", { name: /Also cover flights arriving into the EU/ }).click();
  await expect(page.getByTestId("asked-again")).toHaveCount(0, { timeout: 60_000 });
  // On Questions too: the asked-again card is closed.
  await go(page, "Questions");
  await expect(page.getByRole("heading", { name: /Human review|Questions/, level: 1 })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("article", { hasText: "23F" })).toHaveCount(0);

  // The Iberian blackout: Known at lands on its run, with the grid outage band.
  await knownAt(page, /Iberian blackout/);
  await expect(page).toHaveURL(/\/run\/EIDW(%40|@)2025-04-28/, { timeout: 180_000 });
  await expect(page.locator('[data-window="grid_outage"]').first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: /^Grid outage/ }).first()).toBeVisible();

  // Legal rules once for the outage.
  await go(page, "Questions");
  await viewAs(page, "legal");
  const cards = page.locator("article");
  await expect(cards).toHaveCount(1, { timeout: 30_000 });
  await rule(page, /blackout|outage/i, TEXT.blackout, "Extraordinary inside the outage window");

  // Back on the blackout run: 8 flights settled as extraordinary, NS128 and NS129 owed.
  await page.goto("/run/EIDW%402025-04-28");
  await expect(page).toHaveURL(/\/run\/EIDW(%40|@)2025-04-28/);
  await expect(page.locator('g[data-verdict="weather"]')).toHaveCount(8, { timeout: 60_000 });
  await expect(page.locator('g[data-flight="NS128"]')).toHaveAttribute("data-verdict", "notweather");
  await expect(page.locator('g[data-flight="NS129"]')).toHaveAttribute("data-verdict", "notweather");

  // Liability & Close: the blackout's care accrual.
  await viewAs(page, "controller");
  await go(page, "Liability & Close");
  await expect(page.getByRole("heading", { name: "Liability & Close", level: 1 })).toBeVisible({ timeout: 30_000 });
  const apr = page.getByRole("radio", { name: /Apr 2025/ }).or(page.getByRole("button", { name: /Apr 2025/ })).or(page.getByRole("tab", { name: /Apr 2025/ }));
  if (await apr.count()) await apr.first().click();
  await expect(page.getByText(/€136,720/).first()).toBeVisible({ timeout: 30_000 });

  expect(errors, "no uncaught errors").toEqual([]);
});
