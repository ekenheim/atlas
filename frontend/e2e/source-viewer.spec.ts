import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator } from "@playwright/test";

// Expected values come from the recorded EDGAR fixtures the API was seeded from
// (scripts/e2e.py ingests tests/fixtures/edgar/lumentum), never from the API itself.
const FIXTURES = path.resolve(__dirname, "../../tests/fixtures");
const LUMENTUM = path.join(FIXTURES, "edgar/lumentum");

type ManifestEntry = { url: string; file: string };
type Submissions = {
  filings: { recent: { accessionNumber: string[]; acceptanceDateTime: string[] } };
};

const manifest = JSON.parse(readFileSync(path.join(LUMENTUM, "manifest.json"), "utf8")) as {
  responses: ManifestEntry[];
};
const submissions = JSON.parse(
  readFileSync(path.join(LUMENTUM, "data.sec.gov/submissions/CIK0001633978.json"), "utf8"),
) as Submissions;
const golden = JSON.parse(
  readFileSync(path.join(FIXTURES, "parser/golden.json"), "utf8"),
) as Record<string, Record<string, string>>;

// The FY2026 10-K: accession 0001628280-26-057358, primary document lite-20260627.htm.
const ACCESSION = "0001628280-26-057358";
const URL_10K =
  "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm";
const entry = manifest.responses.find((response) => response.url === URL_10K);
if (!entry) throw new Error(`${URL_10K} is not in the fixture manifest`);
const rawBytes = readFileSync(path.join(LUMENTUM, entry.file));
const RAW_SHA256 = sha256(rawBytes);
const CONTENT_SHA256 = golden["text-v3"]?.["lite-20260627.htm"];
const recent = submissions.filings.recent;
const ACCEPTED_AT = recent.acceptanceDateTime[recent.accessionNumber.indexOf(ACCESSION)];

function sha256(data: Buffer | string): string {
  return createHash("sha256").update(data).digest("hex");
}

test("a Source Version shows its provenance and parsed text", async ({ page }) => {
  expect(CONTENT_SHA256).toBeDefined();
  expect(ACCEPTED_AT).toBeDefined();

  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Companies" }).click();
  await page.getByRole("link", { name: "Lumentum" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Lumentum" })).toBeVisible();
  await page.locator("summary", { hasText: "Records" }).click();
  const documentRow = page.getByRole("row").filter({ hasText: ACCESSION });
  await documentRow.getByRole("link").click();

  await expect(page.getByRole("heading", { name: "Version history" })).toBeVisible();
  await page.getByRole("link", { name: "Version 1", exact: true }).click();

  const provenance = page.getByRole("region", { name: "Provenance" });
  await expect(provenance).toBeVisible();
  const fields: Record<string, string> = {
    URL: URL_10K,
    Accession: ACCESSION,
    "Raw SHA-256": RAW_SHA256,
    "Content SHA-256": CONTENT_SHA256!,
    "Parser version": "text-v3",
    "Fetch status": "ok",
    Supersedes: "none",
  };
  for (const [name, value] of Object.entries(fields)) {
    await expect(fieldRow(provenance, name).getByRole("cell")).toHaveText(value);
  }

  // Every clock is shown with its basis; SEC's availability is the acceptance time.
  const available = fieldRow(provenance, "available_at");
  await expect(available).toContainText("sec_acceptance");
  const availableAt = await available.locator("time").getAttribute("datetime");
  expect(Date.parse(availableAt ?? "")).toBe(Date.parse(ACCEPTED_AT!));
  await expect(fieldRow(provenance, "published_at")).toContainText("not recorded");
  for (const clock of ["fetched_at", "first_seen_at"]) {
    const time = await fieldRow(provenance, clock).locator("time").getAttribute("datetime");
    expect(Number.isNaN(Date.parse(time ?? ""))).toBe(false);
  }

  // The whole parsed text is on the page: its hash is the pinned golden parse hash.
  const parsed = page.getByRole("region", { name: "Parsed text" });
  await expect(parsed).toContainText("Lumentum");
  const text = await parsed.locator("pre").textContent();
  expect(sha256(text ?? "")).toBe(CONTENT_SHA256);

  // The download link hands back the original bytes exactly.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /Download original bytes/ }).click(),
  ]);
  const downloaded = readFileSync(await download.path());
  expect(sha256(downloaded)).toBe(RAW_SHA256);
});

/** The provenance table row whose header cell is `name`. */
function fieldRow(region: Locator, name: string): Locator {
  return region.getByRole("row").filter({
    has: region.page().getByRole("rowheader", { name, exact: true }),
  });
}
