import { expect, test } from "@playwright/test";

// Record and Decide, against the database `scripts/e2e.py` seeds: the proven constraint made one
// call; the unproven relief Belief is flagged, so it waits on the owner. (The unpublished
// version at its gate is read in hypothesis-dossier.spec.ts, before that spec publishes it.)
const FLAGGED = "Lumentum can add laser capacity faster than demand grows.";

test("Record shows the calls open, the first checkpoint and no predictions yet", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Record" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Record" })).toBeVisible();
  const figures = page.getByLabel("The record");
  await expect(figures).toContainText("Calls open");
  await expect(figures).toContainText("Checkpoints recorded");
  await expect(figures).toContainText("Ahead of benchmark at +3 m");
  await expect(page.getByText(/^First checkpoint \d{1,2} \w{3}: \d+ calls? priced against/)).toBeVisible();
  await expect(page.getByRole("list", { name: "By horizon" }).getByRole("listitem")).toHaveText([
    "+1 m: no checkpoint yet",
    "+3 m: no checkpoint yet",
    "+6 m: no checkpoint yet",
  ]);
  await expect(page.getByRole("heading", { level: 2, name: "Calls" })).toBeVisible();
  await expect(page.getByText("No prediction is recorded yet.")).toBeVisible();
});

test("Decide counts what waits on the owner and lists the counts held by the lead", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Decide" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Decide" })).toBeVisible();
  const waiting = page.getByRole("list", { name: "Waiting on you" });
  const row = waiting.getByRole("listitem").filter({ hasText: FLAGGED });
  await expect(row).toContainText("1 flag");
  await expect(page.getByText("Nothing waits on you.")).toHaveCount(0);

  const lead = page.getByRole("list", { name: "With the lead" });
  await expect(lead.getByRole("link", { name: /links in the exceptions queue/ })).toBeVisible();
  await expect(lead.getByRole("link", { name: /candidates$/ })).toBeVisible();
  await expect(lead.getByRole("link", { name: /identity reviews$/ })).toBeVisible();

  // The row opens the Belief, where the controls are.
  await row.getByRole("link", { name: FLAGGED }).click();
  await expect(page.getByRole("heading", { level: 1, name: FLAGGED })).toBeVisible();
});
