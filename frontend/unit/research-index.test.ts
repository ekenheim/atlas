import { expect, test } from "@playwright/test";

import type { InvestigationSummary } from "../lib/api/client";
import { dayOf, questionKey, researchIndex, runsLabel, statusWords } from "../lib/research-index";

function run(
  id: string,
  theme: string,
  question: string,
  created_at: string,
  stop_reason: InvestigationSummary["stop_reason"] = "answered",
): InvestigationSummary {
  return {
    id,
    theme,
    question,
    seed_company_ids: [],
    round: 1,
    status: stop_reason === null ? "running" : "stopped",
    stop_reason,
    created_by: "owner",
    created_at,
    stopped_at: null,
  };
}

test("status words", () => {
  expect(statusWords(run("a", "t", "q", "2026-10-01T00:00:00Z", null))).toBe("Running");
  expect(statusWords(run("a", "t", "q", "2026-10-01T00:00:00Z", "answered"))).toBe("Answered");
  expect(statusWords(run("a", "t", "q", "2026-10-01T00:00:00Z", "needs_review"))).toBe(
    "Draft · needs review",
  );
  expect(statusWords(run("a", "t", "q", "2026-10-01T00:00:00Z", "budget_exhausted"))).toBe(
    "Stopped early",
  );
});

test("the same question asked again collapses to the latest run", () => {
  const index = researchIndex(
    [
      run("1", "photonics", "Who is short of lasers?", "2026-10-01T10:00:00Z"),
      run("3", "photonics", "who is short of  lasers", "2026-10-03T10:00:00Z", "needs_review"),
      run("2", "photonics", "Who is short of lasers?", "2026-10-02T10:00:00Z"),
      run("4", "photonics", "What limits InP supply?", "2026-10-04T10:00:00Z"),
    ],
    ["photonics"],
  );
  expect(index).toHaveLength(1);
  const rows = index[0]!.rows;
  expect(rows.map((r) => [r.latest.id, r.runs])).toEqual([
    ["4", 1],
    ["3", 3],
  ]);
});

test("listed themes come first, even empty; unlisted ones follow", () => {
  const index = researchIndex([run("1", "robotics", "q", "2026-10-01T00:00:00Z")], ["photonics"]);
  expect(index.map((t) => [t.theme, t.rows.length])).toEqual([
    ["photonics", 0],
    ["robotics", 1],
  ]);
});

test("small helpers", () => {
  expect(questionKey("  A  b? ")).toBe("a b");
  expect(runsLabel(1)).toBeNull();
  expect(runsLabel(3)).toBe("3 runs");
  expect(dayOf("2026-10-06T12:00:00Z")).toBe("2026-10-06");
});
