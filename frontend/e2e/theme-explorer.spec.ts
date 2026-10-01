import { expect, test } from "@playwright/test";

// The Theme explorer and the Company dossier, against the database `scripts/e2e.py` seeds:
// the photonics universe (configs/themes/ai-infrastructure.yaml), Lumentum ingested from the
// recorded EDGAR fixtures (its companyfacts normalized into as-of financials), and three
// Relationships built from hedged sentences of its FY2026 10-K. Expected values are the
// theme config's, the fixtures' and the seed's.
const THEME = "Photonics for AI data centers";
const DEPENDS = {
  name: "Lumentum depends_on Fabrinet",
  quote:
    "For many products, a particular contract manufacturer may be the sole source of the" +
    " finished good products.",
};
const COMPETES = "Lumentum competes_with Coherent";
const MANUFACTURES = "Lumentum manufactures optical and photonic products";

test("a theme opens by layer, a company's dossier, and an edge's source span", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Site" })
    .getByRole("link", { name: "Themes" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Themes" })).toBeVisible();
  const themes = page.getByRole("table", { name: "Themes and their coverage" });
  // Twelve companies, eleven without sources (only Lumentum is ingested), three edges.
  await expect(themes.getByRole("row", { name: new RegExp(THEME) }).getByRole("cell")).toHaveText([
    new RegExp(`^${THEME}`),
    "12",
    "11",
    "none",
    "3",
    "0",
  ]);
  await themes.getByRole("link", { name: THEME }).click();

  // The map: companies by layer, upstream to downstream.
  await expect(page.getByRole("heading", { level: 1, name: THEME })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3 })).toHaveText([
    "Substrate",
    "Epi",
    "Chip / laser",
    "DSP",
    "Module",
    "Contract manufacturing",
    "System",
  ]);
  const chips = page.getByRole("table", { name: "Chip / laser companies" });
  await expect(chips.getByRole("rowheader")).toHaveText([
    "Coherent",
    "Lumentum",
    "MACOM",
    "STMicroelectronics",
  ]);
  await expect(chips.getByRole("row", { name: /^Coherent/ }).getByRole("cell").last()).toHaveText(
    "no sources",
  );
  await expect(chips.getByRole("row", { name: /^Lumentum/ }).getByRole("cell").last()).toHaveText(
    "none",
  );
  // Only the sole-source sentence names a layer ("a particular contract manufacturer"); the
  // other two edges' Evidence names none, so they are listed under their companies.
  const edges = page.getByRole("table", { name: "Relationships between the theme's companies" });
  await expect(edges.locator("tbody").getByRole("row")).toHaveCount(1);
  await expect(edges.getByRole("row", { name: DEPENDS.name })).toBeVisible();
  const lumentumEdges = page.getByRole("table", { name: "Relationships with no layer: Lumentum" });
  await expect(lumentumEdges.locator("tbody").getByRole("row")).toHaveCount(2);
  await expect(lumentumEdges.getByRole("row", { name: COMPETES })).toBeVisible();
  await expect(lumentumEdges.getByRole("row", { name: MANUFACTURES })).toBeVisible();
  const coherentEdges = page.getByRole("table", { name: "Relationships with no layer: Coherent" });
  await expect(coherentEdges.locator("tbody").getByRole("row")).toHaveCount(1);
  await expect(coherentEdges.getByRole("row", { name: COMPETES })).toBeVisible();
  await expect(page.getByText("Hindsight is not configured")).toBeVisible();

  // The dossier: identity, listings, Relationships, financials, sources.
  await chips.getByRole("link", { name: "Lumentum" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
  const identity = page.getByRole("table", { name: "Identity" });
  await expect(identity.getByRole("row", { name: /^CIK/ }).getByRole("cell")).toHaveText(
    "0001633978",
  );
  await expect(identity.getByRole("row", { name: /^Themes/ }).getByRole("link")).toHaveText(THEME);
  const listings = page.getByRole("table", { name: "Listings (securities)" });
  await expect(listings.getByRole("rowheader")).toHaveText(["LITE"]);
  const out = page.getByRole("table", { name: "Relationships out (Lumentum as subject)" });
  await expect(out.locator("tbody").getByRole("row")).toHaveCount(3);
  await expect(out.getByRole("row", { name: COMPETES })).toBeVisible();
  await expect(out.getByRole("row", { name: MANUFACTURES })).toBeVisible();
  // FY2026 net revenue, $3,014.0M, from the FY2026 10-K (0001628280-26-057358).
  const financials = page.getByRole("table", { name: /^Financials as of/ });
  const fy2026 = financials
    .getByRole("row")
    .filter({ hasText: "2025-06-29 – 2026-06-27" })
    .filter({ hasText: "3,014,000,000" });
  await expect(fy2026).toHaveCount(1);
  await expect(fy2026).toContainText("0001628280-26-057358");
  await expect(page.getByRole("table", { name: /^Source Documents/ })).toBeVisible();

  // An edge opens its Evidence, and that its highlighted source span.
  await out.getByRole("link", { name: `Open ${DEPENDS.name}` }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(DEPENDS.name);
  await page.getByRole("link", { name: "Open source span" }).click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(DEPENDS.quote);
  await expect(mark).toBeInViewport();
});
