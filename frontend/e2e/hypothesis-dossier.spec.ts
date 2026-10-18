import { expect, test } from "@playwright/test";

import { expectRecordsClosed, openRecords, openSystem } from "./helpers";

// The Hypothesis dossier, against the database `scripts/e2e_hypothesis.py` seeds through the
// real services (the LLM's answers scripted): Coherent's recorded EDGAR filings, an
// investigation whose Skeptic quoted a later statement limiting the supply agreement as a
// contradiction (a hand-shaped document the seed imports), version 1
// (the supply finding) published with its snapshot and a researcher's scenario, and version 2,
// a correction adding NVIDIA's investment, held by the publish gate until the owner approves
// its edge. Expected values are the seed's and the fixtures'.
const baseURL = process.env.ATLAS_E2E_HYPOTHESIS_BASE_URL;
if (!baseURL) {
  throw new Error("ATLAS_E2E_HYPOTHESIS_BASE_URL is not set: run `uv run python scripts/e2e.py`");
}
test.use({ baseURL });

const THESIS = {
  1:
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring" +
    " suppliers with long-term agreements such as Coherent.",
  2:
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring" +
    " Coherent, whose largest customer is also an investor.",
};
const SUPPLY = {
  finding: "Coherent supplies NVIDIA with advanced lasers under a multi-year agreement.",
  quote:
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a" +
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical" +
    " networking products",
};
const INVESTMENT = "NVIDIA has invested $2 billion in Coherent.";
const BELIEF = "Coherent holds a multi-year supply agreement with NVIDIA for advanced lasers.";
const BELIEF_STEP =
  "Coherent entered into a strategic multi-year supply agreement with NVIDIA for advanced lasers.";
const BELIEF_THESIS =
  "Coherent may control the supply of advanced lasers through its multi-year supply agreement" +
  " with NVIDIA.";
const LIMIT =
  "the agreement no longer commits NVIDIA to purchase from Coherent after December 31, 2027";
const OWNS = "NVIDIA owns Coherent";

// Before the next test publishes version 2: Decide lists the version at its gate, and the row
// opens the Hypothesis.
test("Decide lists the unpublished version at its gate and opens it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Decide" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Decide" })).toBeVisible();
  const row = page
    .getByRole("list", { name: "Waiting on you" })
    .getByRole("listitem")
    .filter({ hasText: THESIS[2] });
  await expect(row).toContainText("Version 2");
  await expect(row).toContainText("1 link not yet approved");
  await row.getByRole("link", { name: THESIS[2] }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(THESIS[2]);
});

test("a Hypothesis's versions, diff, gate, snapshots and scenarios, and a citation's span", async ({
  page,
}) => {
  await page.goto("/");
  await openSystem(page, "Hypotheses");
  await expect(page.getByRole("heading", { level: 1, name: "Hypotheses" })).toBeVisible();
  const list = page.getByRole("table", { name: "Hypotheses, newest first" });
  // The seed holds a second Hypothesis, over Beliefs (the next test); this one's row is read.
  await expect(
    list.locator("tbody").getByRole("row").filter({ hasText: THESIS[2] }).getByRole("cell"),
  ).toHaveText([
    THESIS[2],
    "Reviewed",
    "photonics",
    "2",
    "version 1",
    /^\d{1,2} \w{3}( \d{4})?$/,
  ]);
  await list.getByRole("link", { name: THESIS[2] }).click();

  // The latest version: its thesis, findings with citations, and the Skeptic's contradiction.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(THESIS[2]);
  const version = page.getByLabel("Version", { exact: true });
  const findings = page.getByRole("list", { name: "Findings" });
  await expect(findings.getByRole("listitem")).toHaveCount(2);
  await expect(findings.getByRole("listitem").first()).toContainText(SUPPLY.finding);
  await expect(findings.getByRole("listitem").last()).toContainText(INVESTMENT);
  await expect(findings.getByRole("link", { name: /^Citation \d+:/ })).toHaveText(["[1]", "[2]"]);
  await expect(page.getByRole("list", { name: "What would falsify it" })).toHaveText(
    "Verified laser capacity exceeds plausible demand",
  );
  await expect(page.getByRole("list", { name: "Contradictions" })).toContainText(LIMIT);
  // The assessment leads; the raw records are one click deeper.
  await expect(page.getByRole("region", { name: "Changes between versions" })).toHaveCount(0);
  await expectRecordsClosed(page);
  await openRecords(page);
  await expect(version).toHaveValue("2");
  await expect(version.locator("option")).toHaveText([
    "Version 1: the Editor's draft, published",
    "Version 2: correction, not published",
  ]);
  await expect(page.getByRole("list", { name: "Falsifiers" })).toHaveText(
    "Verified laser capacity exceeds plausible demand",
  );

  // The diff from version 1: the investment is new, the supply finding unchanged.
  const diff = page.getByRole("region", { name: "Changes between versions" });
  await expect(diff.getByRole("status")).toHaveText(
    "Version 1 → 2: 1 new, 0 contradicted, 1 unchanged, 0 removed. Also changed: Thesis" +
      " statement.",
  );
  await expect(diff.getByRole("list", { name: "New claims" })).toHaveText(INVESTMENT);
  await expect(diff.getByRole("list", { name: "Unchanged claims" })).toHaveText(SUPPLY.finding);

  // The gate holds version 2 until the owner approves the investment's edge: the banner at the
  // top says so in plain words.
  const publish = page.getByRole("region", { name: "Lifecycle and publication" });
  const failed = publish.getByRole("list", { name: "Failed checks" });
  await expect(failed.getByRole("listitem").first()).toContainText("1 link not yet approved");
  await failed.getByRole("link", { name: OWNS }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(OWNS);
  const review = page.getByRole("region", { name: "Owner review" });
  await review.getByRole("button", { name: "Approve" }).click();
  await expect(review.getByRole("status")).toHaveText(/^Recorded: approved/);
  await page.goBack();
  await expect(
    publish.getByText("Every check passes: the version can be published."),
  ).toBeVisible();
  await publish.getByRole("button", { name: "Publish version 2" }).click();
  await expect(page.getByRole("status").first()).toHaveText("Published version 2.");
  // The banner is gone once the latest version is published; the Records say so.
  await expect(publish).toHaveCount(0);

  // Coming back from the edge's page remounted the dossier with its records folded again.
  await openRecords(page);
  await expect(version.locator("option")).toHaveText([
    "Version 1: the Editor's draft, published",
    "Version 2: correction, published",
  ]);
  await expect(
    page.getByText("The latest version is published.", { exact: false }),
  ).toBeVisible();

  // Both publications froze a snapshot, each verified when it is read.
  // Version 1 rests on the supply edge and carries the scenario; version 2 adds the owns edge.
  for (const [number, contents] of [
    [1, "1 Relationship, 1 scenario"],
    [2, "2 Relationships, 0 scenarios"],
  ] as const) {
    const snapshot = page.getByRole("table", { name: `Snapshot of version ${number}` });
    await expect(snapshot.getByRole("row", { name: /^Integrity/ })).toContainText(
      "Verified: the archived snapshot hashes to its recorded SHA-256.",
    );
    await expect(snapshot.getByRole("row", { name: /^SHA-256/ })).toContainText(/[0-9a-f]{64}/);
    await expect(snapshot.getByRole("row", { name: /^Contents/ })).toContainText(contents);
  }

  // Version 1: its scenario, sourced and estimated inputs, outputs and sensitivity.
  await version.selectOption("1");
  await expect(page).toHaveURL(/version=1/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(THESIS[1]);
  const inputs = page.getByRole("table", {
    name: "Scenario 1: advanced lasers: inputs, sourced or estimated",
  });
  await expect(inputs.getByRole("row", { name: /^Reported revenue/ })).toContainText(
    "sourced from XBRL: RevenueFromContractWithCustomerExcludingAssessedTax",
  );
  await expect(
    inputs.getByRole("link", { name: "Open the XBRL source of reported revenue" }),
  ).toBeVisible();
  await expect(inputs.getByRole("row", { name: /^Company share/ })).toContainText(SUPPLY.quote);
  await expect(inputs.getByRole("row", { name: /^Operating margin/ })).toContainText(
    "estimated: a guess",
  );
  // 10,000,000 units × 0.25 share × (1,000 × 0.2) component price, in the base case.
  const outputs = page.getByRole("table", { name: "Scenario 1: advanced lasers: outputs by case" });
  await expect(
    outputs
      .getByRole("row", { name: /^Incremental revenue/ })
      .getByRole("cell")
      .nth(1),
  ).toHaveText(/^500,000,000(\.0+)?$/);
  const sensitivity = page.getByRole("table", {
    name: /^Scenario 1: advanced lasers: sensitivity/,
  });
  await expect(sensitivity.getByRole("row", { name: /^Addressable units/ })).toHaveCount(2);

  // The export links: version 1's dossier as JSON and as Markdown.
  const json = await page.request.get(
    (await page.getByRole("link", { name: "JSON" }).getAttribute("href")) ?? "",
  );
  expect(json.ok()).toBe(true);
  const exported = (await json.json()) as { version: { version: number }; citations: unknown[] };
  expect(exported.version.version).toBe(1);
  expect(exported.citations).toHaveLength(1);
  const markdown = await page.request.get(
    (await page.getByRole("link", { name: "Markdown" }).getAttribute("href")) ?? "",
  );
  expect(await markdown.text()).toContain(`# Hypothesis: ${THESIS[1]}`);

  // A finding's citation opens its span, highlighted in the Source Version.
  await page
    .getByRole("list", { name: "Findings" })
    .getByRole("link", { name: /^Citation 1:/ })
    .click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(SUPPLY.quote);
  await expect(mark).toBeInViewport();
});

// The seed's second Hypothesis, drafted from a proven Belief: it leads with the thesis and the
// steps, each Belief with its judgement and the Fact's quote, then the falsifiers.
test("a Hypothesis over Beliefs leads with its thesis and steps, each Belief with its quote", async ({
  page,
}) => {
  await page.goto("/hypotheses/");
  await page.getByRole("link", { name: BELIEF_THESIS }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(BELIEF_THESIS);
  // Above the fold: the six steps as rows, the falsifiers and the Issues; the full list of what
  // it rests on is in the Records.
  await expect(page.getByRole("region", { name: "The argument" })).toBeVisible();
  await expect(
    page.getByRole("list", { name: "What would falsify it" }).getByRole("listitem"),
  ).toHaveText(["A qualified second laser source ships to NVIDIA"]);
  await expect(page.getByRole("heading", { level: 2, name: "Open Issues" })).toBeVisible();
  // Whether the thesis was checked against its Beliefs' quotes is said in the kicker.
  await expect(page.getByLabel("Thesis check", { exact: true })).toContainText(/checked/i);
  await expectRecordsClosed(page);
  await openRecords(page);
  const rests = page.getByRole("region", { name: "What it rests on" });
  await expect(rests.getByRole("region", { name: "Control" })).toContainText(BELIEF_STEP);
  const beliefs = rests.getByRole("list", { name: "Control beliefs" });
  await expect(beliefs.getByRole("listitem", { name: BELIEF })).toContainText("Proven 85%");
  await expect(beliefs.getByRole("link", { name: BELIEF })).toBeVisible();
  await expect(beliefs.locator("blockquote")).toHaveText(SUPPLY.quote);
  await expect(page.getByRole("region", { name: "Against it" })).toContainText(
    "Nothing recorded against its Beliefs.",
  );
  // It has no investigation: the summary gives its question instead.
  await expect(page.getByRole("row", { name: /^Investigation/ })).toHaveCount(0);

  // The Belief's record, and the quote opened at its span.
  await beliefs.getByRole("link", { name: "Open in source" }).click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(SUPPLY.quote);
});

// The theme page leads with its Hypotheses (the published one first), then its Beliefs, then
// what changed: the seed's judgement of the Belief and the Fact it cites.
test("the theme page leads with its Hypotheses and shows what changed", async ({ page }) => {
  await page.goto("/theme/?id=photonics");
  // The thesis block leads with the published Hypothesis's thesis and counts the draft.
  const thesis = page.getByLabel("Thesis", { exact: true });
  await expect(thesis).toContainText(THESIS[2]);
  await expect(thesis).toContainText("1 draft");

  // The Hypotheses themselves are in the Records, the published one first.
  await openRecords(page);
  const hypotheses = page.getByRole("list", { name: "Hypotheses" });
  await expect(hypotheses.getByRole("listitem")).toHaveCount(2);
  await expect(hypotheses.getByRole("listitem").first()).toContainText(THESIS[2]);
  await expect(hypotheses.getByRole("listitem").first()).toContainText(/Published \d{1,2} \w{3}/);
  await expect(hypotheses.getByRole("listitem").last()).toContainText("not published");
  await expect(hypotheses.getByRole("listitem", { name: BELIEF_THESIS })).toBeVisible();

  // What Atlas believes, by step, then what changed, newest first.
  const believed = page.getByRole("region", { name: "What Atlas believes" });
  await believed.getByRole("region", { name: "Control" }).locator("summary").click();
  await expect(believed.getByRole("listitem", { name: BELIEF })).toContainText("Proven 85%");
  const changes = page.getByRole("list", { name: "Changes, newest first" });
  await expect(changes.getByRole("link", { name: `proven 85%: ${BELIEF}` })).toBeVisible();
  await expect(changes.getByRole("link", { name: `Coherent: ${BELIEF_STEP}` })).toBeVisible();

  // A change opens its record: the Belief, and a Fact at its span.
  await changes.getByRole("link", { name: `proven 85%: ${BELIEF}` }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(BELIEF);
  await page.goBack();
  await changes.getByRole("link", { name: `Coherent: ${BELIEF_STEP}` }).click();
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toHaveText(SUPPLY.quote);
});
