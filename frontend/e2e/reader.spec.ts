import { expect, test, type Page } from "@playwright/test";

import { expectNoOverflow, openRecords, openSystem } from "./helpers";

// The reader's way in: the nav (five items, the current one marked), the research index on the
// workbench's page, and the company dossier (findings first, records folded away). The index is
// read from the workbench's API (`ATLAS_E2E_WORKBENCH_URL`), whose database holds two
// investigations; the dossier from the first database, where Lumentum has three Relationships
// (scripts/e2e.py).
const WORKBENCH = process.env.ATLAS_E2E_WORKBENCH_URL;
const QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?";

/** The nav's current item: the link marked `aria-current="page"`. */
async function current(page: Page): Promise<string[]> {
  return page
    .getByRole("navigation", { name: "Site" })
    .locator('a[aria-current="page"]')
    .allTextContents();
}

test.describe("the nav and the research index", () => {
  test.use({ baseURL: WORKBENCH });

  test("the nav has five items and marks the section the page belongs to", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Site" });
    await expect(nav.getByRole("link")).toHaveText(["Today", "Themes", "Record", "Decide", "System"]);
    expect(await current(page)).toEqual(["Today"]);

    await page.goto("/theme/?id=photonics");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await current(page)).toEqual(["Themes"]);

    await page.goto("/memory/");
    await expect(page.getByRole("heading", { level: 1, name: "Memory" })).toBeVisible();
    expect(await current(page)).toEqual(["System"]);
  });

  test("lists a question with its status on the workbench and opens its investigation", async ({
    page,
  }) => {
    await page.goto("/workbench/");
    await expect(page.getByRole("heading", { level: 1, name: "Research workbench" })).toBeVisible();
    const list = page.getByRole("table", { name: /^Investigations, newest first/ });
    await expect(list.getByRole("row").filter({ hasText: QUESTION })).toBeVisible();
    await list.getByRole("link", { name: QUESTION }).click();
    await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  });

  test("does not scroll sideways at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator("article.theme-card:not(.theme-card-skeleton)").first()).toBeVisible();
    await expectNoOverflow(page);
  });
});

test.describe("the company dossier", () => {
  test("shows what Atlas found, expands a sentence to its quote, and opens the records", async ({
    page,
  }) => {
    await page.goto("/");
    await openSystem(page, "Companies");
    await page.getByRole("link", { name: "Lumentum" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
    // The assessment leads: the company's Beliefs (seeded) come before what was found.
    await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("What Atlas believes");
    await expect(page.getByRole("region", { name: "What Atlas believes" })).toContainText(
      "Lumentum's laser demand is outrunning its capacity.",
    );
    // What Atlas found is a record: folded away until opened.
    await expect(page.getByRole("heading", { level: 2, name: "What Atlas found" })).toHaveCount(0);
    await openRecords(page);
    await expect(page.getByRole("heading", { level: 2, name: "What Atlas found" })).toBeVisible();

    const finding = page.locator("button.finding-line").first();
    await expect(finding).toHaveAttribute("aria-expanded", "false");
    await finding.click();
    await expect(finding).toHaveAttribute("aria-expanded", "true");
    const quote = page.locator(".quote-card blockquote").first();
    await expect(quote).toBeVisible();
    await expect(quote).not.toHaveText("");
    await expect(page.locator(".quote-card").getByRole("link", { name: "Open in source" })).toBeVisible();

    const identity = page.getByRole("table", { name: "Identity" });
    await expect(identity.getByRole("row", { name: /^CIK/ }).getByRole("cell")).toHaveText(
      "0001633978",
    );
  });

  test("does not scroll sideways at phone width, records open", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/companies/");
    await page.getByRole("link", { name: "Lumentum" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
    await openRecords(page);
    await expect(page.getByRole("table", { name: "Identity" })).toBeVisible();
    await expectNoOverflow(page);
  });
});
