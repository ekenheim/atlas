import { expect, test } from "@playwright/test";

import { DESKTOP } from "./helpers";

// The Chokepoint Watch's pages, against the board `scripts/e2e_board.py` seeds through the
// public routes: photonics with A thesis-ready, B below the bar, F needing a new open question,
// C a candidate, D ruled out and E spotted, and a weekly run whose memo carries hostile text;
// robotics, not one of the themes, with a first survey and one chokepoint; memory-packaging
// with nothing. Expected values are the seed's.
test.use(DESKTOP);

const A = "Indium phosphide laser capacity";
const B = "EML supply for 800G transceivers";
const F = "Indium phosphide substrate export permits";
const C = "CW lasers for silicon photonics";
const D = "Pump laser capacity";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

async function openChokepoint(page: import("@playwright/test").Page, name: string): Promise<void> {
  await page.goto("/theme/?id=photonics");
  await page.getByRole("region", { name: "Chokepoints" }).getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(/\/chokepoint\/\?id=/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("Today: a Watch row per watched theme, naming what became thesis-ready", async ({ page }) => {
  await page.goto("/");
  const watch = page.getByRole("region", { name: "Watch" });
  const rows = watch.getByRole("listitem");
  const robotics = rows.filter({ hasText: "Robotics" });
  await expect(robotics).toContainText("First survey");
  const photonics = rows.filter({ hasText: "Photonics for AI data centers" });
  await expect(photonics).not.toContainText("First survey");
  await expect(photonics).toContainText("3 thesis-ready");
  await expect(photonics.locator(".watch-named")).toHaveText(/^Thesis-ready: /);
  await expect(rows.filter({ hasText: "Memory and advanced packaging" })).toHaveCount(0);
  // Robotics has a Watch row only, no card.
  await expect(page.getByRole("article", { name: "Robotics" })).toHaveCount(0);

  const named = photonics.locator(".watch-named").getByRole("link").first();
  const name = (await named.textContent()) ?? "";
  expect([A, B, F]).toContain(name);
  await named.click();
  await expect(page).toHaveURL(/\/chokepoint\/\?id=/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  await page.goBack();
  await page.getByRole("region", { name: "Watch" }).getByRole("listitem").filter({ hasText: "Photonics" }).getByRole("link", { name: "Memo" }).click();
  await expect(page).toHaveURL(/\/watch-run\/\?id=/);
});

test("the memo page renders the memo safely, in the owner's words", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("region", { name: "Watch" }).getByRole("listitem").filter({ hasText: "Photonics" }).getByRole("link", { name: "Memo" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Photonics for AI data centers ·");
  await expect(page.getByText("The Watch's memo · not evidence")).toBeVisible();
  const main = page.locator("main");
  expect(await page.evaluate(() => (window as unknown as { __pwned?: unknown }).__pwned)).toBeUndefined();
  await expect(main.locator("script")).toHaveCount(0);
  await expect(main).toContainText("<script>window.__pwned=1</script>");
  await expect(main.getByRole("link", { name: "bad" })).toHaveCount(0);
  await expect(main).toContainText("bad");
  const ok = main.getByRole("link", { name: "ok" });
  await expect(ok).toHaveAttribute("rel", /noopener/);
  await expect(ok).toHaveAttribute("href", "https://example.com");
  await expect(main.getByRole("link", { name: "A", exact: true })).toHaveAttribute("href", /\/chokepoint\/\?id=/);
  const text = (await main.textContent()) ?? "";
  expect(text).not.toContain("uv run");
  expect(text).not.toMatch(UUID);
  expect(text).toContain("thesis-ready");
  expect(text).toContain("Control");
  expect(text).not.toContain("thesis_ready");
  expect(text).not.toContain("step d");
  expect(text).not.toMatch(/Fact {2}|holds: {2}/);
  await expect(main).toContainText("Fact shows it.");
  // The theme's other runs: photonics has only this one.
  await expect(page.getByRole("region", { name: "Earlier runs" })).toHaveCount(0);
});

test("the photonics board: after Changed, before Companies, grouped, with badges and named steps", async ({ page }) => {
  await page.goto("/theme/?id=photonics");
  const board = page.getByRole("region", { name: "Chokepoints" });
  await expect(board).toBeVisible();
  const order = await page
    .locator("h2")
    .evaluateAll((headings) => headings.map((each) => each.textContent?.trim() ?? ""));
  const changed = order.findIndex((each) => /^(Since last visit|This week|Changed)/.test(each));
  expect(changed).toBeGreaterThanOrEqual(0);
  expect(order.indexOf("Chokepoints")).toBeGreaterThan(changed);
  expect(order.indexOf("Companies")).toBeGreaterThan(order.indexOf("Chokepoints"));

  await expect(board.getByRole("heading", { level: 3 })).toHaveText([
    "Thesis-ready (3)",
    "Candidates (1)",
    "Spotted (1)",
  ]);
  const ready = board.getByRole("list", { name: "Thesis-ready" });
  await expect(ready.getByRole("listitem").filter({ hasText: B }).first()).toContainText("Below the bar");
  await expect(ready.getByRole("listitem").filter({ hasText: F }).first()).toContainText("Needs a new open question");
  // Rows carry badges only: no status word.
  await expect(ready.getByRole("listitem").filter({ hasText: A }).first()).not.toContainText("Thesis-ready");

  const killed = board.locator("details.board-killed");
  await expect(killed.locator("summary")).toHaveText("Ruled out (1)");
  expect(await killed.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false);
  await expect(killed.getByRole("listitem")).toHaveCount(0);
  await killed.locator("summary").click();
  await expect(killed.getByRole("listitem")).toContainText(`${D} · ruled out`);

  const steps = ready.getByRole("listitem").filter({ hasText: A }).first().getByRole("list", { name: "Steps" });
  await expect(steps.getByRole("listitem")).toHaveText([
    "●Constraint",
    "●Demand",
    "●Control",
    "○Capture",
    "Relief",
    "Invalidation",
  ]);
  for (const name of [
    "Constraint: quoted",
    "Demand: quoted",
    "Control: quoted",
    "Capture: unquoted",
    "Relief: not examined",
    "Invalidation: not examined",
  ]) {
    await expect(steps.getByRole("listitem", { name, exact: true })).toBeVisible();
  }
});

test("robotics, not one of the themes, leads with its board; memory-packaging has none", async ({ page }) => {
  await page.goto("/theme/?id=robotics");
  await expect(page.getByRole("heading", { level: 1, name: "Robotics" })).toBeVisible();
  await expect(page.locator(".thesis-status").first()).toHaveText(/^Watching/);
  await expect(page.getByRole("region", { name: "Chokepoints" })).toContainText("Precision strain-wave reducer capacity");
  await expect(page.locator("main")).not.toContainText("not one of the themes");

  await page.goto("/theme/?id=memory-packaging");
  await expect(page.getByRole("heading", { level: 1, name: "Memory and advanced packaging for AI" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Chokepoints" })).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("Watch");
});

test("A: waiting for proof, its holders, and the quote in two clicks from the board", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/v1\/facts\/[0-9a-f-]+/.test(request.url())) reads.push(request.url());
  });
  await page.goto("/theme/?id=photonics");
  const board = page.getByRole("region", { name: "Chokepoints" });
  await board.getByRole("link", { name: A, exact: true }).click(); // click 1
  await expect(page.getByRole("heading", { level: 1, name: A })).toBeVisible();
  await expect(page.getByText("Waiting for proof")).toBeVisible();
  await expect(page.getByText("Still needs")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Lumentum", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Outside Holder Co" })).toHaveCount(0);
  await expect(page.locator(".holders")).toContainText("Outside Holder Co not yet researched");
  await expect(page.locator(".step-headline").first()).toBeVisible();
  expect(reads.length).toBeLessThanOrEqual(3);

  const constraint = page.getByRole("region", { name: "Constraint" });
  await constraint.locator("summary").click(); // a disclosure, not a navigation
  const open = constraint.getByRole("link", { name: "Open in source" }).first();
  await open.click(); // click 2
  await expect(page).toHaveURL(/\/version\/\?id=[^&]+&assertion=[0-9a-f-]+/);
  const mark = page.getByRole("region", { name: "Parsed text" }).locator("mark");
  await expect(mark).toBeVisible();
});

test("B is below the bar, F needs a new open question, C's relief is unquoted, D is ruled out", async ({ page }) => {
  await openChokepoint(page, B);
  await expect(page.locator(".bar-line")).toHaveText("Below the bar: no falsifier");
  await expect(page.locator(".verdict-line")).toContainText("Thesis-ready");

  await openChokepoint(page, F);
  await expect(page.locator(".bar-line")).toHaveText("Needs a new open question");
  await expect(page.locator(".bar-line")).toHaveClass(/status-warn/);

  await openChokepoint(page, C);
  await expect(page.getByRole("region", { name: "Relief" })).toContainText("Unquoted");
  await expect(page.getByRole("region", { name: "What would invalidate it" })).toContainText("Contradicted");

  await page.goto("/theme/?id=photonics");
  const killed = page.locator("details.board-killed");
  await killed.locator("summary").click();
  await killed.getByRole("link", { name: D }).click();
  await expect(page.locator(".verdict-line")).toHaveText(/Ruled out \d{1,2} [A-Z][a-z]{2}( \d{4})?: Supply added faster than demand\./);
});
