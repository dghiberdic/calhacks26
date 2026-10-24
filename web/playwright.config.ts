import { defineConfig, devices } from "@playwright/test";

// Runs against the mock world by default (no backend needed). Against the stub or the real server:
//   E2E_API_MODE=http API_TARGET=http://localhost:8000 pnpm e2e
const mode = process.env.E2E_API_MODE ?? "mock";
const port = Number(process.env.E2E_PORT ?? 5281);

export default defineConfig({
  testDir: "e2e",
  // A cold dev server compiles each screen on its first visit, and on a busy laptop that alone can take 20 s.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // The mock world lives in each page, so tests run in parallel; the stub and the server hold one shared
  // world, so there they run one at a time, each from a reset (e2e/fixtures.ts).
  fullyParallel: mode === "mock",
  // /story and /pitch run WebGL and a video; more than two at once starves a laptop and tests time out
  // (8 of 51 failed at the default worker count, 0 at two). E2E_WORKERS overrides.
  workers: mode === "mock" ? Number(process.env.E2E_WORKERS ?? 2) : 1,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${port}`, trace: "retain-on-failure" },
  // The Chrome already on the machine: no Playwright browser download.
  projects: [{ name: "chrome", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: {
    // mock and recorded are Vite modes (src/api/client.ts reads them); http proxies /api to API_TARGET.
    command: `pnpm exec vite --port ${port} --strictPort${mode === "http" ? "" : ` --mode ${mode}`}`,
    url: `http://localhost:${port}`,
    // Never reuse whatever already listens on the port: it may be another app. A busy port fails loudly.
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
