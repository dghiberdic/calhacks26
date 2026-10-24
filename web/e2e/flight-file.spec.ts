import { expect, test } from "./fixtures";

const NS31 = "/flights/NS31%402025-01-24";
/** First paint of a lazily loaded screen on a cold dev server can take a while; the checks after it use the default. */
const LOADED = { timeout: 45_000 };
test.describe.configure({ timeout: 90_000 });

test("NS31's file shows the confidence, the struck weather code and the parked journal", async ({ page }) => {
  await page.goto(NS31);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("NS31", LOADED);
  await expect(page.getByText("cause-finding confidence 91%").first()).toBeVisible();
  // OCC's batch code 71 is outranked by the tech log: that evidence row is struck through.
  await expect(page.getByTestId("evidence").locator(".line-through").first()).toBeVisible();
  await expect(page.getByText(/not yet posted/i).first()).toBeVisible();
});

test("a challenge that only asserts is answered 'Decision stands.'", async ({ page }) => {
  await page.goto(NS31);
  const box = page.getByTestId("challenge");
  await expect(box).toBeVisible(LOADED);
  await box.getByRole("textbox").fill("The storm would have grounded it anyway");
  await box.getByRole("button", { name: "Submit challenge" }).click();
  await expect(page.getByTestId("challenge-result")).toContainText("Decision stands.");
});

test("the flight index leads with NS31, the one flight that wasn't weather", async ({ page }) => {
  await page.goto("/flights");
  const notWeather = page.locator("#verdict-notweather");
  await expect(notWeather.getByRole("link", { name: /NS31/ })).toBeVisible(LOADED);
  await notWeather.getByRole("link", { name: /NS31/ }).click();
  await expect(page).toHaveURL(/\/flights\/NS31/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("NS31", LOADED);
});
