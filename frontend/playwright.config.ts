import { defineConfig, devices } from "@playwright/test";

// The smoke test runs against a live API seeded from the recorded EDGAR fixtures.
// `uv run python scripts/e2e.py` creates that database, starts the API (which serves
// the built static export on the same origin) and then runs Playwright with this URL.
const baseURL = process.env.ATLAS_E2E_BASE_URL;
if (!baseURL) {
  throw new Error(
    "ATLAS_E2E_BASE_URL is not set: run `uv run python scripts/e2e.py` from the repo root",
  );
}

export default defineConfig({
  testDir: "e2e",
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
