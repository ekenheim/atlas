import { expect, test } from "@playwright/test";

import { expectRecordsClosed, openRecords, openSystem } from "./helpers";

// The sessions pages, against the database `scripts/e2e.py` seeds (`seed_session`): one
// Claude session on Lumentum with two Facts quoted from its March 2026 10-Q and a small card
// citing them. Expected values are the seed's.
const QUESTION = "Is laser capacity the constraint on AI optics?";
const STATEMENT = "Lumentum reported quarterly net revenue and its shares outstanding.";
const FIRST_QUOTE =
  "As of April 30, 2026, the Registrant had 77.8 million shares of common stock outstanding.";
const SECOND_FACT =
  "Lumentum's net revenue for the three months ended March 28, 2026 was $808.4 million.";

test("the sessions list opens a session's card, its Facts and a Fact's source span", async ({
  page,
}) => {
  await page.goto("/");
  await openSystem(page, "Sessions");
  await expect(page.getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
  // Each run is a sentence: the agent, what it came to and when; the question is its second line.
  const runs = page.getByRole("list", { name: "Runs, newest first" });
  await expect(runs.getByRole("listitem").filter({ hasText: QUESTION })).toContainText("recorded 2 Facts");
  await expect(page.getByRole("list", { name: "This week" })).toContainText("2 Facts");
  // The table of every run, with its model and cost, is in the Records.
  await expectRecordsClosed(page);
  await openRecords(page);
  const list = page.getByRole("table", { name: "Research sessions, newest first" });
  await expect(list.getByRole("row", { name: new RegExp(QUESTION) }).getByRole("cell")).toHaveText([
    QUESTION,
    "Claude",
    "claude-e2e",
    "2026-09-30",
    "2",
    "12,345 tokens",
    /^\d{4}-\d{2}-\d{2}$/,
  ]);

  await runs.getByRole("link", { name: /recorded 2 Facts/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();

  // The assessment first: the card's step, its statement and the Facts it cites.
  await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("Card");
  const step = page.getByRole("region", { name: /The constraint/ });
  await expect(step).toContainText("supported");
  await expect(step.getByText(STATEMENT)).toBeVisible();
  await expect(step.getByText(SECOND_FACT)).toBeVisible();
  await expect(page.getByText("Who else makes indium phosphide lasers?")).toBeVisible();

  // Then the records: the Facts table and the session's record.
  await openRecords(page);
  const facts = page.getByRole("table", { name: "Facts recorded in the session" });
  await expect(facts.getByRole("row")).toHaveCount(3); // header and two Facts
  await expect(page.getByRole("row", { name: /Researcher/ })).toContainText("e2e-researcher");

  // A Fact's quote opens the source viewer at its span.
  await facts.getByRole("link", { name: FIRST_QUOTE }).click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(FIRST_QUOTE);
  await expect(mark).toBeInViewport();
});
