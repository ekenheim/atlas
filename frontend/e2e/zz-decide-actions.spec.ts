import { expect, test } from "@playwright/test";

// Decide's inline actions, against the database `scripts/e2e.py` seeds. Named to run after the
// specs that read the seed: judging the flagged relief Belief clears its flag and changes what
// they read.
const FLAGGED = "Lumentum can add laser capacity faster than demand grows.";

test("judging a Belief on Decide leaves the queue, with a message, and the nav count drops", async ({
  page,
}) => {
  await page.goto("/decide/");
  const waiting = page.getByRole("list", { name: "Waiting on you" });
  const row = waiting.getByRole("listitem").filter({ hasText: FLAGGED });
  // The row carries the load-bearing quote to judge it on.
  await expect(row.locator("blockquote")).toBeVisible();

  await row.getByRole("button", { name: "Judge" }).click();
  const form = row.getByRole("form", { name: /^Judge:/ });
  // A reason is required, and the error is a sentence if the API refuses.
  await form.getByLabel("Judgement").selectOption("disproven");
  await form.getByLabel(/^Confidence/).fill("70");
  await expect(form.getByRole("button", { name: "Save judgement" })).toBeDisabled();
  await form.getByLabel("Reason").fill("The second quarter's revenue stands against it.");
  await form.getByRole("button", { name: "Save judgement" }).click();

  await expect(page.getByRole("status")).toContainText("Judged disproven");
  await expect(row).toHaveCount(0);
  await expect(page.getByText("Nothing waits on you.")).toBeVisible();
});
