import { expect, type Page } from "@playwright/test";

/** Desktop and phone, for `test.use`. */
export const DESKTOP = { viewport: { width: 1440, height: 900 } } as const;
export const PHONE = { viewport: { width: 390, height: 844 } } as const;

/** Site → System, then the named link: every route that is not Today, Themes, Record or Decide. */
export async function openSystem(page: Page, name: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Site" });
  await nav.getByRole("link", { name: "System" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "System" })).toBeVisible();
  await page.getByRole("list", { name: "System" }).getByRole("link", { name, exact: true }).click();
}

/** Opens the Records fold: its summary, then it is open. */
export async function openRecords(page: Page): Promise<void> {
  const records = page.locator("details.reader-records");
  const open = await records.evaluate((element) => (element as HTMLDetailsElement).open);
  if (!open) await records.locator("summary").click();
  await expect(records).toHaveAttribute("open", "");
}

/** The Records fold is closed and has rendered nothing. */
export async function expectRecordsClosed(page: Page): Promise<void> {
  const records = page.locator("details.reader-records");
  await expect(records).toHaveCount(1);
  expect(await records.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false);
  expect(await records.locator(".records-body").count()).toBe(0);
}

/** The page does not run past the viewport sideways. */
export async function expectNoOverflow(page: Page): Promise<void> {
  const over = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(over).toBeLessThanOrEqual(0);
}

/** What the surface must never say: system names, config, times of day, offsets, valences. The
 * quotes (verbatim document text) and the Records are taken out first. */
export const LEAKS = new RegExp(
  [
    /atlas-[a-z]+|source path|universe config|Hindsight|mental model|\d{2}:\d{2}(:\d{2})?|characters \d+|valence|-0\.\d+/
      .source,
    // Round 3 (spec §10.5): exact codes, step letters, commands, system words, ISO dates, UUIDs.
    /\bstep [a-f]\b|\bstep_[a-f](_primary)?\b|\bthesis_ready\b|\bdemand_vs_supply\b|\bkill_criteria\b/.source,
    /\bopen_issue\b|\bunexamined\b|\bneeds_review\b|\bshelf_or_atm\b|\bgaap_gross_margin\b/.source,
    /\bcustomer_concentration\b|\bgoing_concern\b|\bnet_cash\b|\buv run\b|\bXBRL\b/.source,
    /\bin the ledger\b|\bas-of time\b|\b\d{4}-\d{2}-\d{2}\b/.source,
    /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/.source,
  ].join("|"),
  "i",
);

export async function expectNoLeaks(page: Page): Promise<void> {
  const text = await page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return "";
    const clone = main.cloneNode(true) as HTMLElement;
    clone
      .querySelectorAll("blockquote, .quote, .quote-card, details.reader-records")
      .forEach((node) => node.remove());
    return clone.textContent ?? "";
  });
  const hit = LEAKS.exec(text);
  const context = hit
    ? `...${text.slice(Math.max(0, hit.index - 60), hit.index + hit[0].length + 60)}...`
    : "";
  expect(hit, `leak "${hit?.[0]}" in: ${context}`).toBeNull();
}
