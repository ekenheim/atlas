import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import type { MemoryHealth, SessionSummary } from "../lib/api/client";
import { SYSTEM_ITEMS, memoryState, runsState, runsThisWeek } from "../lib/system";

const NOW = Date.parse("2026-10-06T13:12:40Z");
const sample = JSON.parse(
  readFileSync(path.join(__dirname, "fixtures", "memory-health.json"), "utf8"),
) as MemoryHealth;

test("the System index keeps every old nav label as a link name", () => {
  expect(SYSTEM_ITEMS.map((item) => item.label)).toEqual([
    "Memory",
    "Sessions",
    "Issues",
    "Relationships",
    "Exceptions queue",
    "Research workbench",
    "Beliefs",
    "Hypotheses",
    "Companies",
  ]);
  for (const item of SYSTEM_ITEMS) expect(item.href.startsWith("/")).toBe(true);
});

test("the memory line says whether anything is open and how much is in memory", () => {
  const line = memoryState(sample, NOW);
  expect(line).toMatch(/^(clean|\d+ items? open)( · \d+% in memory)?$/);
});

const run = (over: Partial<SessionSummary>): SessionSummary =>
  ({
    id: "s",
    started_at: "2026-10-17T10:00:00Z",
    isolated: false,
    ...over,
  }) as SessionSummary;

test("runs this week leave out the held-out runs and anything older than seven days", () => {
  const now = new Date("2026-10-18T12:00:00Z");
  const sessions = [
    run({}),
    run({ started_at: "2026-10-12T10:00:00Z" }),
    run({ started_at: "2026-10-01T10:00:00Z" }),
    run({ isolated: true }),
  ];
  expect(runsThisWeek(sessions, now)).toBe(2);
  expect(runsState(2)).toBe("2 runs this week");
  expect(runsState(1)).toBe("1 run this week");
});
