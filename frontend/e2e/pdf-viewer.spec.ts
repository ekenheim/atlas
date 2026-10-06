import { expect, test, type Locator } from "@playwright/test";

// A PDF Source Version in the viewer: its language, page count and page anchors.
// scripts/e2e.py records tests/fixtures/pdf/annual-report-en.pdf (written by
// scripts/make_pdf_fixtures.py) for Lumentum; the expected values are that script's pages:
// labels i, 1, 2 (a roman cover), the second page opening with "Chair's statement".
const TITLE = "Synthetic annual report (PDF)";

test("a PDF version shows its page anchors and jumps to a page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Companies" }).click();
  await page.getByRole("link", { name: "Lumentum" }).click();
  await page.locator("summary", { hasText: "Records" }).click();
  await page.getByRole("link", { name: TITLE }).click();
  await page.getByRole("link", { name: "Version 1", exact: true }).click();

  const provenance = page.getByRole("region", { name: "Provenance" });
  await expect(fieldRow(provenance, "Parse status").getByRole("cell")).toHaveText("parsed");
  await expect(fieldRow(provenance, "Language").getByRole("cell")).toHaveText("en");
  await expect(fieldRow(provenance, "Pages").getByRole("cell")).toHaveText("3");

  const pages = page.getByRole("navigation", { name: "Pages" });
  await expect(pages.getByRole("button")).toHaveText([
    "Page i (PDF page 1)",
    "Page 1 (PDF page 2)",
    "Page 2 (PDF page 3)",
  ]);
  // The cover page is 54 characters: two lines of 22 and 32 (newlines included).
  await expect(pages.getByRole("listitem").first()).toContainText("characters 0–54");

  const text = page.getByRole("region", { name: "Parsed text" }).locator("pre");
  await expect(text).toContainText("Chair's statement");
  await text.evaluate((element) => {
    element.style.maxHeight = "3em"; // so a page's text is out of view until jumped to
  });
  const scrolledBefore = await text.evaluate((element) => element.scrollTop);
  await pages.getByRole("button", { name: "Page 2 (PDF page 3)" }).click();
  await expect.poll(() => text.evaluate((element) => element.scrollTop)).toBeGreaterThan(
    scrolledBefore,
  );
});

/** The provenance table row whose header cell is `name`. */
function fieldRow(region: Locator, name: string): Locator {
  return region.getByRole("row").filter({
    has: region.page().getByRole("rowheader", { name, exact: true }),
  });
}
