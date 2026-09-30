import { expect, test } from "@playwright/test";

// The research workbench, against the second API `scripts/e2e.py` starts
// (`ATLAS_E2E_WORKBENCH_URL`): its database holds two investigations of Coherent and
// Lumentum, each run through the API and worker passes with scripted role answers to an
// answered research card (one accepted Claim quoting the recorded Coherent FY2026 10-K, and
// two open questions). No worker runs while these tests do: a launched round stays queued.
// Expected values are the seed's (`seed_workbench`) and the fixture's.
test.use({ baseURL: process.env.ATLAS_E2E_WORKBENCH_URL });

const QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?";
const HYPOTHESIS_QUESTION = "Which laser makers does NVIDIA depend on?";
const OPEN_QUESTION = "Does NVIDIA qualify a second laser source?";
const CARD_QUESTION = "Is InP substrate capacity a constraint for 2027?";
const QUOTE =
  "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a" +
  " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical" +
  " networking products";

test("an investigation shows its plan, events and Evidence, and launches one follow-up round", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Site" })
    .getByRole("link", { name: "Research workbench" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Research workbench" })).toBeVisible();
  const list = page.getByRole("table", { name: /^Investigations, newest first/ });
  await expect(list.locator("tbody").getByRole("row")).toHaveCount(2);
  await list.getByRole("link", { name: QUESTION }).click();

  await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  const summary = page.getByRole("table", { name: "Status and budget use" });
  await expect(summary.getByRole("row", { name: /^Status/ }).getByRole("cell")).toContainText(
    "stopped: answered",
  );
  await expect(summary.getByRole("row", { name: /^Rounds/ }).getByRole("cell")).toHaveText(
    "1 of 2",
  );

  // The fixed plan, each task with its status.
  const round1 = page.getByRole("table", { name: "Round 1" });
  await expect(round1.getByRole("rowheader")).toHaveText([
    "scout",
    "investigator:coherent",
    "investigator:lumentum",
    "skeptic",
    "financial_analyst",
    "editor",
  ]);
  for (const task of ["scout", "investigator:coherent", "skeptic", "editor"]) {
    await expect(round1.getByRole("row", { name: new RegExp(`^${task} `) })).toContainText(
      "succeeded",
    );
  }

  // The Evidence tray: the accepted Claim and its source span.
  const tray = page.getByRole("table", { name: /^Accepted Claims/ });
  const claim = tray.getByRole("row", { name: /^Coherent supplies NVIDIA/ });
  await expect(claim).toHaveCount(1);
  await expect(claim.locator("blockquote")).toHaveText(QUOTE);
  await expect(claim.getByRole("link", { name: "Open source span" })).toHaveAttribute(
    "href",
    /^\/version\/\?id=.+&assertion=.+/,
  );
  await expect(page.getByText("No accepted counterevidence.")).toBeVisible();

  // The event stream, in order, ends with the stop.
  const events = page.getByRole("table", { name: "What happened, in order" });
  await expect(events.getByRole("row").last()).toContainText("stopped");
  await expect(events.getByRole("rowheader").first()).toHaveText("created");

  // One follow-up round on an open question.
  const card = page.getByRole("region", { name: "Research card" });
  await expect(card.getByRole("list", { name: "Open questions" }).getByRole("listitem")).toHaveText(
    [CARD_QUESTION, OPEN_QUESTION],
  );
  // The card reports what was searched and what each Investigator read.
  await expect(
    card.getByRole("list", { name: "What was searched" }).getByRole("listitem").first(),
  ).toContainText("Round 1: 1 query");
  const read = card.getByRole("table", { name: "What was read" });
  await expect(read.getByRole("rowheader")).toHaveText(["Coherent", "Lumentum"]);
  await expect(read.getByRole("row", { name: /^Coherent/ })).toContainText("1 Claim proposed, 1 accepted");
  await expect(read.getByRole("row", { name: /^Lumentum/ })).toContainText(
    "no parsed Source Version",
  );
  const followUp = page.getByRole("form", { name: "Launch the follow-up round" });
  await followUp.getByRole("radio", { name: OPEN_QUESTION }).check();
  await followUp.getByRole("button", { name: "Launch the follow-up round" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Follow-up round launched" })).toHaveText(
    `Follow-up round launched on: ${OPEN_QUESTION}`,
  );
  await expect(summary.getByRole("row", { name: /^Status/ }).getByRole("cell")).toHaveText(
    "running",
  );
  await expect(summary.getByRole("row", { name: /^Rounds/ }).getByRole("cell")).toHaveText(
    "2 of 2",
  );
  const round2 = page.getByRole("table", { name: "Round 2 (follow-up)" });
  await expect(round2.getByRole("row", { name: /^scout / })).toContainText("queued");
  await expect(round2.getByRole("row", { name: /^editor / })).toContainText("pending");
  await expect(events.getByRole("rowheader")).toContainText(["follow_up_started"]);
  await expect(page.getByText(`Round 2: “${OPEN_QUESTION}”`)).toBeVisible();
  await expect(page.getByText("No follow-up now: The investigation is still running.")).toBeVisible();

  // The Evidence opens its span in the source viewer.
  await claim.getByRole("link", { name: "Open source span" }).click();
  await expect(page.locator("mark.span")).toHaveText(QUOTE);
});

test("a stopped investigation's research card is saved as a Hypothesis", async ({ page }) => {
  await page.goto("/workbench/");
  await page
    .getByRole("table", { name: /^Investigations, newest first/ })
    .getByRole("link", { name: HYPOTHESIS_QUESTION })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: HYPOTHESIS_QUESTION })).toBeVisible();

  await page.getByRole("button", { name: "Save as Hypothesis" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Saved as Hypothesis" })).toContainText(
    "(draft)",
  );
  await expect(page.getByText(/^Saved as Hypothesis [0-9a-f-]{36}\.$/)).toBeVisible();
  await expect(
    page.getByText("No follow-up now: It is saved as a Hypothesis, which is drawn from its research card."),
  ).toBeVisible();

  // The saved Hypothesis opens its dossier.
  await page.getByText(/^Saved as Hypothesis [0-9a-f-]{36}\.$/).getByRole("link").click();
  await expect(page).toHaveURL(/\/hypothesis\/\?id=[0-9a-f-]{36}$/);
});
