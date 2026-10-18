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
export const LEAKS =
  /atlas-[a-z]+|source path|universe config|Hindsight|mental model|\d{2}:\d{2}(:\d{2})?|characters \d+|valence|-0\.\d+/i;

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
  expect(text).not.toMatch(LEAKS);
}
