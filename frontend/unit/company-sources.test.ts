import { expect, test } from "@playwright/test";

import type { SourceDocument } from "../lib/api/client";
import { SOURCE_ROWS, filterByType, typeChips, typeName } from "../lib/company-sources";

const doc = (id: string, source_type: string) => ({ id, source_type }) as SourceDocument;

test("type names are the reader's, with a fallback", () => {
  expect(typeName("filing")).toBe("Filings");
  expect(typeName("xbrl_companyfacts")).toBe("XBRL facts");
  expect(typeName("press_release")).toBe("press release");
});

test("chips count each type, most first, after All", () => {
  const docs = [doc("1", "filing"), doc("2", "transcript"), doc("3", "filing")];
  expect(typeChips(docs)).toEqual([
    { type: null, name: "All", count: 3 },
    { type: "filing", name: "Filings", count: 2 },
    { type: "transcript", name: "Transcripts", count: 1 },
  ]);
});

test("filtering by type, and by none", () => {
  const docs = [doc("1", "filing"), doc("2", "transcript")];
  expect(filterByType(docs, "transcript").map((d) => d.id)).toEqual(["2"]);
  expect(filterByType(docs, null)).toHaveLength(2);
  expect(SOURCE_ROWS).toBe(25);
});
