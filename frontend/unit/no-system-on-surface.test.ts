import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

// The secondary leak guard (Y10): the surface of a reader page does not mention system fields.
// The main guard is the e2e's rendered-text check with Records closed; this scans the source of
// the files that make the surface, with the Records stripped out. (The Hypothesis page defines
// its Records helpers in the same file, so the e2e guard covers it.)
const ROOT = join(__dirname, "..");
const SURFACE = [
  "app/page.tsx",
  "app/themes/page.tsx",
  "app/decide/page.tsx",
  "app/record/page.tsx",
  "app/belief/page.tsx",
  "components/theme-card.tsx",
  "components/due-list.tsx",
  "components/step-rows.tsx",
  "components/quote.tsx",
  "components/argument-strip.tsx",
  "components/stat-strip.tsx",
  "components/status.tsx",
  "components/confidence.tsx",
];

const FORBIDDEN: [string, RegExp][] = [
  ["source_path", /source_path/],
  ["universe_version", /universe_version/],
  ["char_start", /char_start|span_start|span_end/],
  ["a rendered actor", /\{[^}]*\.(actor|created_by|judged_by)\b[^}]*\}/],
  ["an exact time", /mode="exact"/],
];

/** The source with every `<RecordsFold>` block removed. */
function surfaceOf(file: string): string {
  const source = readFileSync(join(ROOT, file), "utf-8");
  return source.replace(/<RecordsFold[\s\S]*?<\/RecordsFold>/g, "");
}

for (const file of SURFACE) {
  test(`${file} shows no system field outside the Records`, () => {
    const source = surfaceOf(file);
    for (const [name, pattern] of FORBIDDEN) {
      // A field read to build an href or a key is not rendered text.
      const hits = source
        .split("\n")
        .filter((line) => pattern.test(line))
        .filter((line) => !/href=|key=|routes\./.test(line));
      expect(hits, `${file} mentions ${name}`).toEqual([]);
    }
  });
}
