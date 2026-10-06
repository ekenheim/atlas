import { expect, test, type Page } from "@playwright/test";

// The reader's way in: the research index, the nav's two groups and the company dossier
// (findings first, records folded away). The index is read from the workbench's API
// (`ATLAS_E2E_WORKBENCH_URL`), whose database holds two investigations; the dossier from the
// first database, where Lumentum has three Relationships (scripts/e2e.py).
const WORKBENCH = process.env.ATLAS_E2E_WORKBENCH_URL;
const QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?";

/** How far the page runs past the viewport sideways, in pixels. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

test.describe("the research index", () => {
  test.use({ baseURL: WORKBENCH });

  test("lists a question with its status and opens its investigation; the nav has two groups", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Research" })).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Site" });
    await expect(nav.locator("ul.nav-reader").getByRole("link")).toHaveText([
      "Research",
      "Hypotheses",
      "Companies",
    ]);
    await expect(nav.getByRole("list", { name: "Operations" }).getByRole("link")).toHaveText([
      "Memory",
      "Relationships",
      "Exceptions queue",
      "Research workbench",
      "Themes",
    ]);

    const row = page.locator(".reader-row").filter({ hasText: QUESTION });
    await expect(row).toBeVisible();
    await expect(row.locator(".reader-pill")).toHaveText("Answered");
    await row.getByRole("link", { name: QUESTION }).click();
    await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  });

  test("does not scroll sideways at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator(".reader-row").first()).toBeVisible();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });
});

test.describe("the company dossier", () => {
  test("shows what Atlas found, expands a sentence to its quote, and opens the records", async ({
    page,
  }) => {
    await page.goto("/");
    await page
      .getByRole("navigation", { name: "Site" })
      .getByRole("link", { name: "Companies" })
      .click();
    await page.getByRole("link", { name: "Lumentum" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "What Atlas found" })).toBeVisible();

    const finding = page.locator("button.finding-line").first();
    await expect(finding).toHaveAttribute("aria-expanded", "false");
    await finding.click();
    await expect(finding).toHaveAttribute("aria-expanded", "true");
    const quote = page.locator(".reader-quote blockquote").first();
    await expect(quote).toBeVisible();
    await expect(quote).not.toHaveText("");
    await expect(page.locator(".reader-quote").getByRole("link", { name: "Source" })).toBeVisible();

    // The records are folded away until opened.
    const identity = page.getByRole("table", { name: "Identity" });
    await expect(identity).toBeHidden();
    await page.locator("summary", { hasText: "Records" }).click();
    await expect(identity.getByRole("row", { name: /^CIK/ }).getByRole("cell")).toHaveText(
      "0001633978",
    );
  });

  test("does not scroll sideways at phone width, records open", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/companies/");
    await page.getByRole("link", { name: "Lumentum" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
    await page.locator("summary", { hasText: "Records" }).click();
    await expect(page.getByRole("table", { name: "Identity" })).toBeVisible();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });
});
