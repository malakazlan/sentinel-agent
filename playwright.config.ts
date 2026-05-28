import { defineConfig, devices } from "@playwright/test";

/**
 * Drives Sentinel end-to-end: spins up the FastAPI backend and the Next.js
 * dev server, then exercises a real Gemini-3.1 pipeline run.
 *
 * Costs ~$0.10 of Vertex calls per run. Treat as a release-gate test, not
 * a CI-on-every-PR test.
 */
export default defineConfig({
  testDir: "./web/tests-e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "playwright-report" }]],
  timeout: 10 * 60 * 1000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: ".\\.venv\\Scripts\\python.exe -m uvicorn sentinel.api.main:app --port 8000",
      url: "http://localhost:8000/health",
      timeout: 60_000,
      reuseExistingServer: true,
    },
    {
      command: "npm run dev",
      cwd: "./web",
      url: "http://localhost:3000",
      timeout: 60_000,
      reuseExistingServer: true,
    },
  ],
});
