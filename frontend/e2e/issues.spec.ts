import { expect, test } from "@playwright/test";

// The Issues page, against the database `scripts/e2e.py` seeds (`seed_session`): closing the
// session opened the question's Issues (the question, its settled step "The constraint", and
// the card's open question); the seed adds a relief step no Belief was produced for. Expected
// values are the seed's.
const QUESTION = "Is laser capacity the constraint on AI optics?";
const STEP = "Relief: who else can supply the lasers?";
const SETTLED_STEP = `The constraint: ${QUESTION}`;
const OPEN_QUESTION = "Who else makes indium phosphide lasers?";

test("the Issues page leads with the next action and filters by status in the URL", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Issues" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Issues" })).toBeVisible();

  // The next action first: the step no Belief was produced for.
  const next = page.getByRole("region", { name: "Next action" });
  await expect(next).toContainText(STEP);
  await expect(next).toContainText("step with no Belief");
  await expect(next).toContainText(`Under: ${QUESTION}`);

  const table = page.getByRole("table", { name: "Research frontier, next action first" });
  await expect(table.getByRole("row").nth(1)).toContainText(STEP);
  const step = table.getByRole("row", { name: new RegExp(STEP) });
  await expect(step.getByRole("cell")).toHaveText([QUESTION, "Step", "Lumentum", "open", "none", "Session"]);
  await expect(table.getByRole("row", { name: new RegExp(OPEN_QUESTION) })).toContainText("open");
  // The question itself waits on the Issues narrowing it; the settled step is not active.
  await expect(table.getByRole("row", { name: new RegExp(`^${QUESTION}`) })).toContainText("narrowed");
  await expect(table.getByRole("row", { name: new RegExp(SETTLED_STEP) })).toHaveCount(0);

  // A step's session opens.
  await step.getByRole("link", { name: "Session" }).click();
  await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  await page.goBack();

  // Filters are in the URL: complete Issues show the settled step.
  await page.getByLabel("Status").selectOption("complete");
  await expect(page).toHaveURL(/\/issues\/\?status=complete/);
  await expect(
    page
      .getByRole("table", { name: "Research frontier, next action first" })
      .getByRole("row", { name: new RegExp(SETTLED_STEP) }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Next action" })).toHaveCount(0);
});
