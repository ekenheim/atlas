import { expect, test } from "@playwright/test";

import { openRecords, openSystem } from "./helpers";

// The Beliefs pages, against the database `scripts/e2e.py` seeds (`seed_beliefs`): two
// photonics Beliefs about Lumentum citing the session's two Facts. One is a constraint the
// owner proved (80%); the other is an unproven relief whose second Fact stands against it, so
// code flagged it. Expected values are the seed's.
const PROVEN = "Lumentum's laser demand is outrunning its capacity.";
const FLAGGED = "Lumentum can add laser capacity faster than demand grows.";
// The session seed's second Fact (scripts/e2e.py, SESSION_FACTS): a table row of the March 2026
// 10-Q, whose tabs Playwright's text matching reads as spaces.
const AGAINST_QUOTE = "Net revenue $ 808.4";

test("the Beliefs list reads by step, filters to the flagged and opens a Belief at its span", async ({
  page,
}) => {
  await page.goto("/");
  await openSystem(page, "Beliefs");
  await expect(page.getByRole("heading", { level: 1, name: "Beliefs" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("2 beliefs");

  // The assessment first: each step of the argument, the verdict on each Belief.
  const constraint = page.getByRole("region", { name: "Constraint" });
  const proven = constraint.getByRole("listitem", { name: PROVEN });
  await expect(proven).toContainText("Proven 80%");
  await expect(proven).toContainText("Lumentum");
  await expect(proven).toContainText("as of 30 Sep 2026");
  await expect(proven).toContainText("2 citations");
  const relief = page.getByRole("region", { name: "Relief" });
  const flagged = relief.getByRole("listitem", { name: FLAGGED });
  await expect(flagged).toContainText("Unproven");
  await expect(flagged).toContainText("1 flag");
  await expect(page.getByRole("region", { name: "Control" })).toContainText("Nothing believed yet.");

  // The filters live in the URL.
  await page.getByLabel("Flagged only").check();
  await expect(page).toHaveURL(/flagged=true/);
  await expect(page.getByRole("status")).toContainText("1 belief");
  await expect(page.getByRole("listitem", { name: PROVEN })).toHaveCount(0);
  await expect(page.getByRole("listitem", { name: FLAGGED })).toBeVisible();

  // The Belief: its verdict, then why it needs a second look, then the evidence.
  await flagged.getByRole("link", { name: FLAGGED }).click();
  await expect(page.getByRole("heading", { level: 1, name: FLAGGED })).toBeVisible();
  const doubt = page.getByRole("region", { name: "Needs a second look" });
  await expect(doubt).toContainText("A load-bearing citation against it stands");
  const against = page.getByRole("region", { name: "Evidence against it" });
  await expect(against.getByText(AGAINST_QUOTE)).toBeVisible();
  await expect(against).toContainText("load-bearing");
  await expect(page.getByRole("region", { name: "Evidence for it" })).toContainText("Lumentum");

  // A citation opens the source viewer at its span.
  await against.getByRole("link", { name: "Open in source" }).click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(AGAINST_QUOTE);
  await expect(mark).toBeInViewport();
});

test("a proven Belief shows who judged it and its history", async ({ page }) => {
  await page.goto("/beliefs/?step=constraint");
  await page.getByRole("link", { name: PROVEN }).click();
  await expect(page.getByRole("heading", { level: 1, name: PROVEN })).toBeVisible();
  // The verdict line: the word, the confidence and when it was judged.
  await expect(page.getByLabel("Verdict")).toContainText(/^Proven 80% · judged \d{1,2} \w{3} \d{4}/);
  await expect(page.getByRole("region", { name: "Needs a second look" })).toHaveCount(0);
  await expect(page.getByText("Nothing against it found yet")).toBeVisible();

  // The records are one click deeper: who judged it and why, and the history keeps the first,
  // unproven judgement.
  await openRecords(page);
  await expect(page.getByText("Judged by e2e-owner")).toBeVisible();
  await expect(page.getByText("two quarters agree").first()).toBeVisible();
  await expect(page.getByRole("list", { name: "Judgement history" }).getByRole("listitem")).toHaveCount(2);
});
