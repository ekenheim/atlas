import { defineConfig } from "@playwright/test";

// Unit tests of the frontend's pure modules (`unit/*.test.ts`), run with Playwright's
// test runner so no second test framework is needed. They launch no browser and need
// no API: `npm --prefix frontend run test`.
export default defineConfig({
  testDir: "unit",
  testMatch: "**/*.test.ts",
  forbidOnly: true,
  retries: 0,
  reporter: "list",
});
