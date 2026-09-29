import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

// Selection-to-Assertion and review, against the API seeded from the recorded Lumentum
// EDGAR fixtures (scripts/e2e.py). The quotes and their offsets are those of the Q4 FY26
// press release (EX-99.1) as parsed by text-v2 (html-text-v1's HTML rules), the same
// hand-checked values as the API's own tests (tests/integration/test_assertions.py).
// The page's text is first checked
// against the pinned golden parse hash, so the offsets hold for what is shown.
// Offsets are code points of the parsed text. Curly quotes, bullets and a dash come
// before these passages, so their UTF-8 byte offsets differ from the character offsets.
const FIXTURES = path.resolve(__dirname, "../../tests/fixtures");
const golden = JSON.parse(
  readFileSync(path.join(FIXTURES, "parser/golden.json"), "utf8"),
) as Record<string, Record<string, string>>;
const EX991_SHA256 = golden["text-v2"]?.["lite_ex991xq4fy26.htm"];

const ACCESSION_8K = "0001628280-26-055726";
const ACTOR = "e2e-smoke"; // ATLAS_ACTOR in scripts/e2e.py
const REVENUE = {
  quote: "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion",
  start: 1604,
  end: 1676,
};
const NAME = {
  quote: "Lumentum Holdings Inc. (“Lumentum” or the “Company”)",
  start: 546,
  end: 598,
};
const MARGIN = { quote: "GAAP gross margin of 47.4%", start: 186, end: 212 };

function sha256(data: string): string {
  return createHash("sha256").update(data).digest("hex");
}

/** Open version 1 of Lumentum's Q4 FY26 press release by clicking through the viewer. */
async function openPressRelease(page: Page): Promise<Locator> {
  await page.goto("/");
  await page.getByRole("link", { name: "Lumentum" }).click();
  await page
    .getByRole("row")
    .filter({ hasText: ACCESSION_8K })
    .filter({ hasText: "EX-99.1" })
    .getByRole("link")
    .click();
  await page.getByRole("link", { name: "Version 1", exact: true }).click();
  const text = page.getByRole("region", { name: "Parsed text" }).locator("pre");
  await expect(text).toContainText("Lumentum");
  return text;
}

/**
 * Select `quote` in the parsed text with the mouse, as a researcher would: press just
 * inside its first character and release just inside its last.
 */
async function selectWithMouse(page: Page, text: Locator, quote: string): Promise<void> {
  const points = await text.evaluate((element, quote) => {
    const node = element.firstChild;
    if (!(node instanceof Text)) throw new Error("the parsed text is not one text node");
    const start = node.data.indexOf(quote);
    if (start < 0) throw new Error(`${quote} is not in the parsed text`);
    const end = start + quote.length;
    const rect = (from: number) => {
      const range = document.createRange();
      range.setStart(node, from);
      range.setEnd(node, from + 1);
      const first = range.getClientRects()[0];
      if (!first) throw new Error(`no box for character ${from}`);
      return first;
    };
    element.scrollIntoView({ block: "start" });
    element.scrollTop += rect(start).top - element.getBoundingClientRect().top - 24;
    const first = rect(start);
    const last = rect(end - 1);
    return {
      from: { x: first.left + 1, y: first.top + first.height / 2 },
      to: { x: last.right - 1, y: last.top + last.height / 2 },
    };
  }, quote);
  await page.mouse.move(points.from.x, points.from.y);
  await page.mouse.down();
  await page.mouse.move(points.to.x, points.to.y, { steps: 8 });
  await page.mouse.up();
  expect(await page.evaluate(() => document.getSelection()?.toString())).toBe(quote);
}

type Posted = { quote: string; span_start: number; span_end: number } & Record<string, unknown>;

/** Fill the New Assertion form for the current selection, submit it, and return the body. */
async function createAssertion(
  page: Page,
  fields: { predicate: string; value?: string; anchor?: string; epistemicType: string },
): Promise<Posted> {
  const form = page.getByRole("region", { name: "New Assertion" });
  await form.getByLabel("Predicate").fill(fields.predicate);
  if (fields.value) await form.getByLabel(/^Value/).fill(fields.value);
  if (fields.anchor) await form.getByLabel(/^Page or anchor/).fill(fields.anchor);
  await form.getByLabel("Epistemic type").selectOption({ label: fields.epistemicType });
  const [request] = await Promise.all([
    page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/api/v1/assertions"),
    ),
    form.getByRole("button", { name: "Create Assertion" }).click(),
  ]);
  return request.postDataJSON() as Posted;
}

/** The Assertions table row whose quote cell is exactly `quote`. */
function assertionRow(page: Page, quote: string): Locator {
  return page
    .getByRole("region", { name: "Assertions" })
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: quote, exact: true }) });
}

async function expectActions(row: Locator, names: string[]): Promise<void> {
  await expect(row.getByRole("button")).toHaveText(names);
}

test("an Assertion is created from a real selection, then reviewed", async ({ page }) => {
  expect(EX991_SHA256).toBeDefined();
  const text = await openPressRelease(page);
  expect(sha256((await text.textContent()) ?? "")).toBe(EX991_SHA256);

  // Select the revenue sentence; the form quotes it with its code-point offsets.
  await selectWithMouse(page, text, REVENUE.quote);
  const form = page.getByRole("region", { name: "New Assertion" });
  await expect(form.locator("blockquote")).toHaveText(REVENUE.quote);
  await expect(form).toContainText(`Characters ${REVENUE.start}–${REVENUE.end}`);
  await expect(form).toContainText("Subject: Lumentum");

  const body = await createAssertion(page, {
    predicate: "reported_net_revenue",
    value: '{"amount": 1010000000, "currency": "USD", "period": "Q4 FY2026"}',
    anchor: "Fiscal Fourth Quarter",
    epistemicType: "Company claim",
  });
  expect(body).toMatchObject({
    quote: REVENUE.quote,
    span_start: REVENUE.start,
    span_end: REVENUE.end,
    predicate: "reported_net_revenue",
    value_json: { amount: 1010000000, currency: "USD", period: "Q4 FY2026" },
    page_or_anchor: "Fiscal Fourth Quarter",
    epistemic_type: "company_claim",
  });
  await expect(page.getByRole("status").filter({ hasText: "Recorded Assertion" })).toBeVisible();

  const revenue = assertionRow(page, REVENUE.quote);
  await expect(revenue).toContainText(`${REVENUE.start}–${REVENUE.end} (Fiscal Fourth Quarter)`);
  await expect(revenue).toContainText("reported_net_revenue");
  await expect(revenue).toContainText("unreviewed");
  await expect(revenue).toContainText(`by ${ACTOR}`);
  // A new Assertion may become anything but unreviewed again.
  await expectActions(revenue, ["Corroborate", "Dispute", "Reject"]);

  await revenue.getByRole("button", { name: "Dispute" }).click();
  await expect(revenue).toContainText("disputed");
  await expect(revenue).toContainText(`reviewed by ${ACTOR}`);
  await expectActions(revenue, ["Corroborate", "Reject"]);

  await revenue.getByRole("button", { name: "Corroborate" }).click();
  await expect(revenue).toContainText("corroborated");
  await expectActions(revenue, ["Dispute", "Reject"]);

  // A second Assertion, with curly quotes inside its span, supersedes the first.
  await selectWithMouse(page, text, NAME.quote);
  await expect(form).toContainText(`Characters ${NAME.start}–${NAME.end}`);
  const named = await createAssertion(page, {
    predicate: "legal_name",
    epistemicType: "Direct source statement",
  });
  expect(named).toMatchObject({ quote: NAME.quote, span_start: NAME.start, span_end: NAME.end });
  expect(named.value_json ?? null).toBeNull();
  expect(named.page_or_anchor ?? null).toBeNull();
  const name = assertionRow(page, NAME.quote);
  await expect(name).toContainText("unreviewed");
  // Only an open Assertion may be the successor; the first may name the second.
  await expectActions(revenue, ["Dispute", "Reject", "Supersede"]);

  await revenue.getByLabel("Successor").selectOption({ label: `legal_name: ${NAME.quote}` });
  await revenue.getByRole("button", { name: "Supersede" }).click();
  await expect(revenue).toContainText("superseded");
  await expect(revenue).toContainText("by legal_name");
  await expectActions(revenue, []); // superseded is final

  await name.getByRole("button", { name: "Reject" }).click();
  await expect(name).toContainText("rejected");
  await expectActions(name, []); // rejected is final

  // The states are the API's, not just the page's: they survive a reload.
  await page.reload();
  await expect(assertionRow(page, REVENUE.quote)).toContainText("superseded");
  await expect(assertionRow(page, NAME.quote)).toContainText("rejected");
  await expectActions(assertionRow(page, REVENUE.quote), []);
});

test("offsets are code points even after an astral character, and a refusal shows why", async ({
  page,
}) => {
  // Serve the parsed text with "😀 " before it: 😀 (U+1F600) is two UTF-16 units in the DOM
  // but one character to the API, so the revenue sentence is now at 1604 + 2. The real
  // archived parse doesn't have the prefix, so the API refuses the span and says where
  // the quote really is.
  const parsedContent = (url: URL) =>
    url.pathname.endsWith("/content") && url.searchParams.get("kind") === "parsed";
  await page.route(parsedContent, async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      status: response.status(),
      contentType: response.headers()["content-type"],
      body: `😀 ${await response.text()}`,
    });
  });
  const text = await openPressRelease(page);
  const assertions = page.getByRole("region", { name: "Assertions" });
  await expect(assertions).toBeVisible();
  const before = await assertions.getByRole("row").count();

  await selectWithMouse(page, text, MARGIN.quote);
  const form = page.getByRole("region", { name: "New Assertion" });
  await expect(form).toContainText(`Characters ${MARGIN.start + 2}–${MARGIN.end + 2}`);
  const body = await createAssertion(page, {
    predicate: "gaap_gross_margin",
    epistemicType: "Company claim",
  });
  expect(body).toMatchObject({
    quote: MARGIN.quote,
    span_start: MARGIN.start + 2,
    span_end: MARGIN.end + 2,
  });

  const refusal = form.getByRole("alert");
  await expect(refusal).toContainText("quote_mismatch");
  await expect(refusal).toContainText(
    `does not occur exactly at characters [${MARGIN.start + 2}, ${MARGIN.end + 2})`,
  );
  await expect(refusal).toContainText(`it occurs at [${MARGIN.start}, ${MARGIN.end})`);
  // Nothing was recorded, and the form keeps the selection to correct or retry.
  await expect(assertions.getByRole("row")).toHaveCount(before);
  await expect(form.locator("blockquote")).toHaveText(MARGIN.quote);
});
