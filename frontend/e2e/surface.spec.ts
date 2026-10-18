import { expect, test, type Page } from "@playwright/test";

import { expectNoLeaks, expectNoOverflow } from "./helpers";

// The surface of each reader page, at desktop and phone width: it does not run past the viewport
// sideways, its Records are closed and render nothing, and its text names no system field (the
// quotes and the Records are left out of that check). Against the database `scripts/e2e.py`
// seeds; the Hypothesis page is read from the second database (`scripts/e2e_hypothesis.py`).
const PROVEN = "Lumentum's laser demand is outrunning its capacity.";

const WIDTHS = [
  { name: "1440", viewport: { width: 1440, height: 900 } },
  { name: "390", viewport: { width: 390, height: 844 } },
] as const;

/** Every Records fold on the page is closed and has rendered nothing; so is the board's Ruled
 * out fold. */
async function expectFoldsClosed(page: Page): Promise<void> {
  const folds = page.locator("details.reader-records");
  for (let index = 0; index < (await folds.count()); index += 1) {
    const fold = folds.nth(index);
    expect(await fold.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false);
    expect(await fold.locator(".records-body").count()).toBe(0);
  }
  const killed = page.locator("details.board-killed");
  for (let index = 0; index < (await killed.count()); index += 1) {
    const fold = killed.nth(index);
    expect(await fold.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false);
    expect(await fold.locator("li").count()).toBe(0);
  }
}

/** A chokepoint of the photonics board, by its constraint (the seed's, `scripts/e2e_board.py`). */
async function openChokepoint(page: Page, name: string): Promise<void> {
  await page.goto("/theme/?id=photonics");
  const board = page.getByRole("region", { name: "Chokepoints" });
  if (name === "Pump laser capacity") await board.locator("details.board-killed summary").click();
  await board.getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByRole("region", { name: "Constraint" })).toBeVisible();
}

async function checkSurface(page: Page): Promise<void> {
  await expectNoOverflow(page);
  await expectFoldsClosed(page);
  await expectNoLeaks(page);
}

for (const width of WIDTHS) {
  test.describe(`at ${width.name}`, () => {
    test.use({ viewport: width.viewport });

    test("Today", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("article.theme-card:not(.theme-card-skeleton)").first()).toBeVisible();
      await expect(page.getByRole("list", { name: "Due" }).first()).toBeVisible();
      await checkSurface(page);
    });

    test("Theme", async ({ page }) => {
      await page.goto("/theme/?id=photonics");
      await expect(page.getByRole("region", { name: "What Atlas believes" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Changes, newest first" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Chokepoints" })).toBeVisible();
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });

    test("Today's Watch", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("region", { name: "Watch" }).getByRole("listitem").first()).toBeVisible();
      await checkSurface(page);
    });

    test("Theme robotics", async ({ page }) => {
      await page.goto("/theme/?id=robotics");
      await expect(page.getByRole("region", { name: "Chokepoints" })).toBeVisible();
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });

    for (const name of [
      "Indium phosphide laser capacity",
      "EML supply for 800G transceivers",
      "Pump laser capacity",
      "Indium phosphide substrate export permits",
    ]) {
      test(`Chokepoint ${name}`, async ({ page }) => {
        await openChokepoint(page, name);
        await checkSurface(page);
        await expect(page.locator("details.reader-records")).toHaveCount(1);
      });
    }

    test("Memo", async ({ page }) => {
      await page.goto("/theme/?id=photonics");
      await page.getByRole("region", { name: "Chokepoints" }).getByRole("link", { name: /^Memo/ }).click();
      await expect(page.getByText("The Watch's memo · not evidence")).toBeVisible();
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });

    test("Belief", async ({ page }) => {
      await page.goto("/beliefs/?step=constraint");
      await page.getByRole("link", { name: PROVEN }).click();
      await expect(page.getByRole("heading", { level: 1, name: PROVEN })).toBeVisible();
      await expect(page.getByRole("region", { name: "Evidence for it" })).toBeVisible();
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });

    test("Issues", async ({ page }) => {
      await page.goto("/issues/");
      await expect(page.getByRole("list", { name: "Research frontier, next action first" })).toBeVisible();
      await checkSurface(page);
    });

    test("Record", async ({ page }) => {
      await page.goto("/record/");
      await expect(page.getByRole("heading", { level: 2, name: "Calls" })).toBeVisible();
      await checkSurface(page);
    });

    test("Company", async ({ page }) => {
      await page.goto("/companies/");
      await page.getByRole("link", { name: "Lumentum" }).click();
      await expect(page.getByRole("region", { name: "What Atlas believes" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Bear checks" }).getByRole("listitem")).toHaveCount(6);
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });

    test("Sessions", async ({ page }) => {
      await page.goto("/sessions/");
      await expect(page.getByRole("list", { name: "Runs, newest first" })).toBeVisible();
      await checkSurface(page);
    });

    test("System", async ({ page }) => {
      await page.goto("/system/");
      await expect(page.getByRole("list", { name: "System" })).toBeVisible();
      await checkSurface(page);
    });

    test("Decide", async ({ page }) => {
      await page.goto("/decide/");
      await expect(page.getByRole("heading", { level: 2, name: "With the lead" })).toBeVisible();
      await checkSurface(page);
    });
  });
}

test.describe("the Hypothesis page", () => {
  test.use({ baseURL: process.env.ATLAS_E2E_HYPOTHESIS_BASE_URL });

  for (const width of WIDTHS) {
    test(`at ${width.name}`, async ({ page }) => {
      test.skip(!process.env.ATLAS_E2E_HYPOTHESIS_BASE_URL, "run through scripts/e2e.py");
      await page.setViewportSize(width.viewport);
      await page.goto("/hypotheses/");
      await page.getByRole("link", { name: /Coherent may control the supply/ }).click();
      await expect(page.getByRole("region", { name: "The argument" })).toBeVisible();
      await checkSurface(page);
      await expect(page.locator("details.reader-records")).toHaveCount(1);
    });
  }
});
