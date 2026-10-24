import { expect, test, type Page } from "./fixtures";

// J7 · Judge's Desk. Runs against the mock world by default (E2E_API_MODE=http for the stub or server).

// A cold dev server compiles the whole app on the first request; with every worker arriving at once
// that can take most of a minute, so the first load gets room and each test a longer budget.
test.describe.configure({ timeout: 120_000 });

async function openDesk(page: Page) {
  await page.goto("/desk");
  await expect(page.getByRole("heading", { name: "Name an airport and a date." })).toBeVisible({ timeout: 60_000 });
}

async function pickAirport(page: Page, typed: string) {
  const airport = page.getByRole("combobox", { name: "Airport" });
  await airport.click();
  await airport.fill(typed);
  await page.keyboard.press("Enter"); // the top match is highlighted; Enter picks it
}

async function runDay(page: Page, airport: string, date: string) {
  await pickAirport(page, airport);
  const field = page.getByLabel("Local date");
  await field.fill(date);
  await field.press("Enter");
}

test("Dublin on 24 Jan 2025 renders a run", async ({ page }) => {
  await openDesk(page);
  await runDay(page, "dub", "24 Jan 2025");

  const result = page.getByTestId("desk-run-result");
  await expect(result).toBeVisible({ timeout: 15_000 });
  await expect(result).toHaveAttribute("data-run-id", /EIDW@2025-01-24/);
  await expect(page.getByTestId("desk-headline")).toContainText(/cancelled|storm window/);
  await expect(page.getByTestId("desk-flights")).toBeVisible();
  await expect(result.getByRole("img", { name: /METAR/ })).toBeVisible();
  // The run is shareable: the URL says which day it was.
  await expect(page).toHaveURL(/icao=EIDW&date=2025-01-24/);
});

test("a future date shows the plain 422 message next to the inputs, and the form still works", async ({ page }) => {
  await openDesk(page);
  await runDay(page, "dub", "1 Jan 2099");

  const problem = page.getByTestId("desk-error");
  await expect(problem).toBeVisible({ timeout: 15_000 });
  await expect(problem).toHaveAttribute("data-code", "future_date");
  await expect(problem).toHaveAttribute("role", "alert");
  // A sentence for a person: not a code, not JSON, not a stack trace.
  const text = (await problem.innerText()).trim();
  expect(text.length).toBeGreaterThan(10);
  expect(text).not.toMatch(/future_date|\{|Traceback|Error:/);
  await expect(page.getByLabel("Local date")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("desk-run-result")).toHaveCount(0);

  // Fix the date and run again from the same form.
  const field = page.getByLabel("Local date");
  await field.fill("24 Jan 2025");
  await field.press("Enter");
  await expect(page.getByTestId("desk-run-result")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("desk-error")).toHaveCount(0);
});

test("all 8 rehearsed scenarios render a result", async ({ page }) => {
  test.setTimeout(180_000);
  await openDesk(page);
  const scenarios = page.getByTestId("desk-scenario");
  await expect(scenarios).toHaveCount(8, { timeout: 30_000 });

  for (let i = 0; i < 8; i++) {
    const button = scenarios.nth(i);
    const id = await button.getAttribute("data-scenario-id");
    expect(id).toBeTruthy();
    await expect(button).toBeEnabled({ timeout: 20_000 });
    await button.click();

    const answer = page.locator(`[data-testid="inject-answer"][data-scenario-id="${id}"]`);
    await expect(answer).toBeVisible({ timeout: 20_000 });
    const result = answer.getByTestId("inject-result");
    await expect(result).toBeVisible();
    // The submitted text, the facts (or why there are none), the dropped count, and what changed.
    await expect(result.getByTestId("inject-document")).not.toBeEmpty();
    await expect(result.getByTestId("inject-dropped")).toBeVisible();
    await expect(result.getByText("What changed")).toBeVisible();
    await expect(page.getByTestId("inject-error")).toHaveCount(0);
  }
});

test("an unknown airport is a plain message, not a crash", async ({ page }) => {
  await openDesk(page);
  await runDay(page, "ZZZZ", "24 Jan 2025");
  const problem = page.getByTestId("desk-error");
  await expect(problem).toBeVisible({ timeout: 15_000 });
  await expect(problem).toHaveAttribute("data-code", /unknown_airport|no_metar|validation/);
  await expect(page.getByRole("heading", { name: "Name an airport and a date." })).toBeVisible();
});
