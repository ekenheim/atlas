import { expect, test } from "@playwright/test";

import { DESKTOP } from "./helpers";

// A company's bear checks, against the database `scripts/e2e.py` seeds: Lumentum from the
// recorded EDGAR fixtures (its companyfacts, 10-K and 10-Qs; no S-3, so the shelf check is
// unknown). Expected values are the seed's, as `unit/fixtures/bear-checks-lumentum.json` holds.
test.use(DESKTOP);

const ORDER = [
  "Share count growth",
  "Shelf or offering filings",
  "Gross margin, last four quarters",
  "Largest customer",
  "Going-concern warning",
  "Net cash or debt",
];

async function openLumentum(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/companies/");
  await page.getByRole("link", { name: "Lumentum" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
}

test("Lumentum's six checks in order, the counts adding to six, the shelf row unknown with why", async ({ page }) => {
  await openLumentum(page);
  const bear = page.getByRole("region", { name: "Bear checks" });
  const rows = bear.getByRole("list", { name: "Bear checks" }).getByRole("listitem");
  await expect(rows).toHaveCount(6);
  for (const [index, label] of ORDER.entries()) await expect(rows.nth(index)).toContainText(label);
  await expect(bear.locator(".bear-summary")).toHaveText("2 flags · 2 clear · 2 unknown");
  await expect(rows.nth(1)).toContainText("Unknown · not in the filings Atlas collects");
  await expect(rows.nth(0)).toContainText("+28% in a year");
  await expect(rows.nth(0)).toContainText("Flag");
  // Bear checks sit after what Atlas believes and before what is on this company.
  const order = await page.locator("h2").evaluateAll((headings) => headings.map((each) => each.textContent?.trim() ?? ""));
  expect(order.indexOf("Bear checks")).toBeGreaterThan(order.indexOf("What Atlas believes"));
  expect(order.indexOf("On this company")).toBeGreaterThan(order.indexOf("Bear checks"));
});

test("a quoted check opens its filing at the span: the row, then Open in source", async ({ page }) => {
  await openLumentum(page);
  const row = page.getByRole("region", { name: "Bear checks" }).getByRole("listitem").filter({ hasText: "Largest customer" });
  await row.locator("summary").click(); // a disclosure, not a navigation
  await row.getByRole("link", { name: "Open in source" }).click();
  await expect(page).toHaveURL(/\/version\/\?id=[^&]+&from=\d+&to=\d+&parse=/);
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toContainText("Customer A");
  await expect(page.getByText(/^Quoted passage · 10-K · filed /)).toBeVisible();
});

test("an older backend's 404 hides the section", async ({ page }) => {
  await page.route("**/api/v1/companies/*/bear-checks*", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: '{"error":{"code":"not_found","message":"no"}}' }),
  );
  await openLumentum(page);
  await expect(page.getByRole("region", { name: "What Atlas believes" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Bear checks" })).toHaveCount(0);
});
