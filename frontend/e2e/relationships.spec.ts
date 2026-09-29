import { expect, test, type Locator, type Page } from "@playwright/test";

// The edge table, an edge's Evidence and source span, and the exceptions queue, against
// the Relationships `scripts/e2e.py` builds from hedged sentences of Lumentum's FY2026 10-K
// (the recorded EDGAR fixture), through the Assertions service and a `review_relationships`
// job. Machine review sent all three edges to the exceptions queue (`hedged_language`);
// the seed's owner approved the `manufactures` edge. The quotes are the seed's.
const ACTOR = "e2e-smoke"; // ATLAS_ACTOR in scripts/e2e.py
const DEPENDS = {
  name: "Lumentum depends_on Fabrinet",
  quote:
    "For many products, a particular contract manufacturer may be the sole source of the" +
    " finished good products.",
};
const COMPETES = "Lumentum competes_with Coherent";
const MANUFACTURES = "Lumentum manufactures optical and photonic products";

/** The edge table's body rows, by their accessible names (the edge read in its direction). */
async function edgeNames(table: Locator): Promise<string[]> {
  const rows = table.locator("tbody").getByRole("row");
  return rows.evaluateAll((elements) =>
    elements.map((row) => row.getAttribute("aria-label") ?? ""),
  );
}

function edgeTable(page: Page): Locator {
  return page.getByRole("table", { name: /^Relationships/ });
}

test("the edge table sorts and filters, and an edge opens its highlighted source span", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Site" })
    .getByRole("link", { name: "Relationships" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Relationships" })).toBeVisible();
  const table = edgeTable(page);
  await expect(page.getByRole("status")).toHaveText("3 relationships.");
  // Oldest first by default: the order the seed's Assertions were reviewed in.
  await expect.poll(() => edgeNames(table)).toEqual([DEPENDS.name, COMPETES, MANUFACTURES]);
  const depends = table.getByRole("row", { name: DEPENDS.name });
  await expect(depends.getByRole("cell")).toHaveText([
    "Lumentum",
    "depends_on",
    "Fabrinet",
    "Contract manufacturing",
    /^Needs human review\s*reasons: hedged_language$/,
    "1",
    "1",
    "Open",
  ]);
  await expect(table.getByRole("row", { name: MANUFACTURES })).toContainText(
    `approved by ${ACTOR}`,
  );

  // Sort by object: a header click sorts ascending, a second descending.
  const object = table.getByRole("columnheader", { name: "Object" });
  await object.getByRole("button").click();
  await expect(object).toHaveAttribute("aria-sort", "ascending");
  await expect.poll(() => edgeNames(table)).toEqual([COMPETES, DEPENDS.name, MANUFACTURES]);
  await object.getByRole("button").click();
  await expect(object).toHaveAttribute("aria-sort", "descending");
  await expect.poll(() => edgeNames(table)).toEqual([MANUFACTURES, DEPENDS.name, COMPETES]);
  // Sorting by layer is upstream to downstream, not alphabetical.
  await table.getByRole("button", { name: "Layer" }).click();
  await expect.poll(async () => (await edgeNames(table))[2]).toBe(DEPENDS.name);

  // Filter by review state, then by layer; the filters live in the URL.
  const filters = page.getByRole("form", { name: "Filter relationships" });
  await filters.getByLabel("Review state").selectOption({ label: "Approved" });
  await expect(page.getByRole("status")).toHaveText("1 relationship, approved.");
  await expect.poll(() => edgeNames(table)).toEqual([MANUFACTURES]);
  await filters.getByLabel("Review state").selectOption({ label: "Needs human review" });
  await filters.getByLabel("Layer").selectOption({ label: "Contract manufacturing" });
  await expect(page.getByRole("status")).toHaveText(
    "1 relationship in layer Contract manufacturing, needs human review.",
  );
  await expect.poll(() => edgeNames(table)).toEqual([DEPENDS.name]);
  await expect(page).toHaveURL(/layer=contract-manufacturing/);
  await page.reload();
  await expect(page.getByRole("status")).toHaveText(
    "1 relationship in layer Contract manufacturing, needs human review.",
  );

  // Open the edge: its Evidence is the one hedged Assertion.
  await table.getByRole("link", { name: `Open ${DEPENDS.name}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: DEPENDS.name })).toBeVisible();
  const evidence = page.getByRole("table", { name: /^Supporting Assertions/ });
  await expect(evidence.locator("blockquote")).toHaveText(DEPENDS.quote);
  await expect(evidence).toContainText("needs_human_review: hedged_language");
  await expect(evidence).toContainText("Tier A");
  await expect(evidence).toContainText("(hedge “may”)");

  // ... and its source span, highlighted in the Source Version's parsed text.
  await evidence.getByRole("link", { name: "Open source span" }).click();
  const text = page.getByRole("region", { name: "Parsed text" }).locator("pre");
  const mark = text.locator("mark");
  await expect(mark).toHaveText(DEPENDS.quote);
  await expect(mark).toBeInViewport();
  await expect(page.getByText(/^Highlighted: the span of the depends_on Assertion/)).toBeVisible();
  // The highlight is only presentation: the offsets still index the verbatim text.
  const [before, span] = await text.evaluate((element) => {
    const marked = element.querySelector("mark");
    const whole = element.textContent ?? "";
    const prefix = whole.slice(0, whole.indexOf(marked?.textContent ?? "\u0000"));
    return [[...prefix].length, marked?.textContent ?? ""];
  });
  expect(span).toBe(DEPENDS.quote);
  const end = before + [...DEPENDS.quote].length;
  await expect(page.getByText(`characters ${before}–${end}`)).toBeVisible();
});

test("the owner approves and rejects edges in the exceptions queue", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Site" })
    .getByRole("link", { name: "Exceptions queue" })
    .click();
  const queue = page.getByRole("table", { name: /waiting for the owner/ });
  await expect(queue.locator("caption")).toHaveText(
    "2 relationships waiting for the owner, oldest first",
  );
  const depends = queue.getByRole("row", { name: DEPENDS.name });
  const competes = queue.getByRole("row", { name: COMPETES });
  await expect(depends).toContainText("reasons: hedged_language");
  await expect(competes).toContainText("reasons: hedged_language");
  await expect(queue.getByRole("row", { name: MANUFACTURES })).toHaveCount(0);

  // A customer building its own products is no evidence Coherent competes: reject it.
  await competes.getByLabel("Note (optional)").fill("customers, not Coherent");
  await competes.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByRole("status")).toHaveText(/^Lumentum competes_with Coherent: rejected/);
  await expect(competes).toHaveCount(0);

  await depends.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("status")).toHaveText(/^Lumentum depends_on Fabrinet: approved/);
  await expect(page.getByText("No relationships need review.")).toBeVisible();

  // The decisions are the API's: the queue stays empty on reload, and the table shows them.
  await page.reload();
  await expect(page.getByText("No relationships need review.")).toBeVisible();
  await page.goto("/relationships/?review_state=rejected");
  const table = edgeTable(page);
  await expect.poll(() => edgeNames(table)).toEqual([COMPETES]);
  await expect(table.getByRole("row", { name: COMPETES })).toContainText(
    `rejected by ${ACTOR}`,
  );
  await expect(table.getByRole("row", { name: COMPETES })).toContainText(
    "customers, not Coherent",
  );

  // On the edge's page, the owner can change their mind; the decision is audited.
  await table.getByRole("link", { name: `Open ${COMPETES}` }).click();
  const review = page.getByRole("region", { name: "Owner review" });
  await expect(review.getByRole("button")).toHaveText(["Approve"]);
  await review.getByRole("button", { name: "Approve" }).click();
  await expect(review.getByRole("status")).toHaveText(/^Recorded: approved \(audit event \d+\)\.$/);
  await expect(review.getByRole("button")).toHaveText(["Reject"]);
  await expect(page.getByRole("table", { name: "The edge" })).toContainText(`approved by ${ACTOR}`);
});
