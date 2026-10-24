import { test as base, expect } from "@playwright/test";

/**
 * Every spec imports `test` from here. Against the mock world each page has its own world, so tests stay
 * parallel and independent. Against the stub or the real server there is one shared world, so each test
 * starts from `POST /api/reset` (and the config runs them one at a time).
 */
export const test = base.extend<{ freshWorld: void }>({
  freshWorld: [
    async ({ request }, use) => {
      // Only a live server (stub or real) holds shared state; the mock world and the recording start fresh per page.
      if ((process.env.E2E_API_MODE ?? "mock") === "http") {
        const res = await request.post("/api/reset");
        expect(res.ok(), "POST /api/reset before the test").toBeTruthy();
      }
      await use();
    },
    { auto: true },
  ],
});

/**
 * Whether the server masks passenger data for seats other than the Claims Lead (CONTRACTS §2 access broker).
 * The contract stub sends no passenger names at all, so the PII beat can't be shown against it yet
 * (contracts/requests/justin.md #21); the mock world and the real server mask.
 */
export async function serverMasksPii(request: import("@playwright/test").APIRequestContext) {
  if ((process.env.E2E_API_MODE ?? "mock") === "mock") return true; // the mock world lives in the page and masks
  const res = await request.get("/api/questions");
  return /\[redacted\]|\[masked\]|\[hidden\]/i.test(await res.text());
}

export { expect };
export type { Locator, Page } from "@playwright/test";
