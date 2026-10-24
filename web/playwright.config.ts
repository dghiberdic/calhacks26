import { defineConfig, devices } from "@playwright/test";

// Runs against the mock world by default (no backend needed). Against the stub or the real server:
//   E2E_API_MODE=http API_TARGET=http://localhost:8000 pnpm e2e
const mode = process.env.E2E_API_MODE ?? "mock";
const port = Number(process.env.E2E_PORT ?? 5180);

export default defineConfig({
  testDir: "e2e",
  // A cold dev server compiles each screen on its first visit, and on a busy laptop that alone can take 20 s.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${port}`, trace: "retain-on-failure" },
  // The Chrome already on the machine: no Playwright browser download.
  projects: [{ name: "chrome", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: {
    command: `pnpm exec vite --port ${port} --strictPort${mode === "mock" ? " --mode mock" : ""}`,
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
