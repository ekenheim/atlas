import { expect, test } from "@playwright/test";

import { openSystem } from "./helpers";

// The Issues page, against the database `scripts/e2e.py` seeds (`seed_session`): closing the
// session opened the question's Issues (the question, its settled step "The constraint", and
// the card's open question); the seed adds a relief step no Belief was produced for. Expected
// values are the seed's.
const QUESTION = "Is laser capacity the constraint on AI optics?";
const STEP = "Relief: who else can supply the lasers?";
const SETTLED_STEP = `The constraint: ${QUESTION}`;
const OPEN_QUESTION = "Who else makes indium phosphide lasers?";

test("the Issues page leads with the next action, lists rows that open an Issue and filters by status in the URL", async ({
  page,
}) => {
  await page.goto("/");
  await openSystem(page, "Issues");
  await expect(page.getByRole("heading", { level: 1, name: "Issues" })).toBeVisible();

  // The next action first: the step no Belief was produced for.
  const next = page.getByRole("region", { name: "Next action" });
  await expect(next).toContainText(STEP);
  await expect(next).toContainText("step with no Belief");
  await expect(next).toContainText(`Under: ${QUESTION}`);

  const list = page.getByRole("list", { name: "Research frontier, next action first" });
  await expect(list.getByRole("listitem").first()).toContainText(STEP);
  const step = list.getByRole("listitem").filter({ hasText: STEP });
  await expect(step).toContainText(`under ${QUESTION}`);
  await expect(step).toContainText("Step");
  await expect(step).toContainText("Lumentum");
  await expect(step).toContainText("Open");
  await expect(list.getByRole("listitem").filter({ hasText: OPEN_QUESTION })).toContainText("Open");
  // The question itself waits on the Issues narrowing it; the settled step is not active.
  await expect(list.getByRole("listitem").filter({ hasText: "Narrowed" })).toContainText(QUESTION);
  await expect(list.getByRole("listitem").filter({ hasText: SETTLED_STEP })).toHaveCount(0);

  // A step's session opens.
  await step.getByRole("link", { name: "Session" }).click();
  await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  await page.goBack();

  // A row opens its Issue.
  await list.getByRole("link", { name: STEP }).click();
  await expect(page).toHaveURL(/\/issue\/\?id=/);
  await expect(page.getByRole("heading", { level: 1, name: STEP })).toBeVisible();
  await page.goBack();

  // Filters are in the URL: complete Issues show the settled step.
  await page.getByLabel("Status").selectOption("complete");
  await expect(page).toHaveURL(/\/issues\/\?status=complete/);
  await expect(
    page
      .getByRole("list", { name: "Research frontier, next action first" })
      .getByRole("listitem")
      .filter({ hasText: SETTLED_STEP }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Next action" })).toHaveCount(0);
});
