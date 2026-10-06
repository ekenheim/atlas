import { expect, test } from "@playwright/test";

// The Memory page, against the workbench's API (`ATLAS_E2E_WORKBENCH_URL`): its database has
// Coherent ingested and retained into the recorded Hindsight fake, so it holds facts for one
// company and nothing for the other universe companies. The first database has no Hindsight
// and nothing retained, so every row would tie on facts and the sort could not be seen. The
// assertions are on structure and relations (the first row changes with the sort), not on
// counts the fake derives.
test.use({ baseURL: process.env.ATLAS_E2E_WORKBENCH_URL });

const FIGURES = ["Open", "Versions in memory", "Facts", "Consolidation", "Reconciliation"];

test("the Memory page shows the five figures and companies, expands a row and sorts", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Memory" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Memory" })).toBeVisible();

  await expect(page.locator(".mem-figure .mem-label")).toHaveText(FIGURES);
  await expect(page.locator(".mem-figure .mem-value").first()).not.toHaveText("");

  const rows = page.locator("tr.mem-row");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);

  // The expand control toggles aria-expanded and reveals the details row.
  const toggle = rows.first().getByRole("button");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("tr.mem-expand")).toHaveCount(1);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("tr.mem-expand")).toHaveCount(0);

  // Status puts the gaps first; Facts puts the company holding facts first.
  const names = () => rows.locator("th").allInnerTexts();
  const sort = page.getByRole("group", { name: "Sort companies" });
  await expect(sort.getByRole("button", { name: "Status" })).toHaveAttribute("aria-pressed", "true");
  const byStatus = await names();
  await sort.getByRole("button", { name: "Facts" }).click();
  await expect(sort.getByRole("button", { name: "Facts" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(names).not.toEqual(byStatus);
  expect([...(await names())].sort()).toEqual([...byStatus].sort());
});

test("the Memory page does not scroll sideways at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/memory/");
  await expect(page.locator("tr.mem-row").first()).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
