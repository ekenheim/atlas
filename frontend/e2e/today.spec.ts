import { expect, test } from "@playwright/test";

import { DESKTOP } from "./helpers";

// Today, against the database `scripts/e2e.py` seeds: the three themes of the config, photonics
// with a proven constraint (whose judgement made a call) and a flagged, unproven relief, the
// other two with no Belief yet. Expected values are the seed's.
test.use(DESKTOP);

const PHOTONICS = "Photonics for AI data centers";
const MEMORY = "Memory and advanced packaging for AI";

test("one card per theme in config order, the thesis, weakest step and strip in the first screen", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeAttached();
  const cards = page.locator("article.theme-card:not(.theme-card-skeleton)");
  await expect(cards).toHaveCount(4);
  // Photonics has Beliefs; the three themes with none come last, in the config's order.
  await expect(cards.locator("h2")).toHaveText([
    PHOTONICS,
    MEMORY,
    "Robotics manufacturing",
    "Early-call scorecard",
  ]);

  const photonics = page.getByRole("article", { name: PHOTONICS });
  await expect(photonics).toContainText("No thesis yet · 1 proven Belief");
  // No Belief proves the demand step, so it is the weakest of the four that argue for it.
  await expect(photonics).toContainText("Weakest step: Demand · nothing proven");
  const strip = photonics.getByRole("list", { name: "Argument" });
  await expect(strip).toBeInViewport();
  await expect(strip.getByRole("listitem", { name: /^Constraint: 1 proven, strongest 80%/ })).toBeVisible();
  await expect(strip.getByRole("listitem", { name: "Demand: nothing proven" })).toBeVisible();
  await expect(strip.getByRole("listitem", { name: "Relief, against the thesis: nothing proven" })).toBeVisible();
});

test("what is due and what changed, and a theme with no Belief says it is starting", async ({ page }) => {
  await page.goto("/");
  const photonics = page.getByRole("article", { name: PHOTONICS });
  // The proven Belief's judgement made a call: its first checkpoint falls a month on.
  await expect(photonics.getByRole("list", { name: "Due" })).toContainText(
    /first checkpoint · \d+ calls?/,
  );
  await expect(photonics.getByRole("list", { name: "Changes, newest first" })).toContainText(
    "proven 80%",
  );
  const memory = page.getByRole("article", { name: MEMORY });
  await expect(memory).toContainText(/Starting · \d+ of \d+ companies have documents · \d+ layers? without a company/);
  await expect(memory.getByRole("list", { name: "Argument" })).toHaveCount(0);
});

test("the flagged Belief is a decision: the banner says so and links to Decide", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /decisions? waits? on you/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Decide" })).toBeVisible();
});
