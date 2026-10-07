import { expect, test } from "@playwright/test";

import type { InvestigationSummary } from "../lib/api/client";
import type { Hypothesis } from "../lib/api/client";
import {
  companyQuestions,
  dayOf,
  hypothesisByInvestigation,
  hypothesisWords,
  questionKey,
  researchIndex,
  rowResult,
  runsLabel,
  statusTone,
  statusWords,
} from "../lib/research-index";

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
    plan: "default",
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

test("a company's questions are its seeded runs, the same question collapsed", () => {
  const seeded = (id: string, at: string, seeds: string[]) => ({
    ...run(id, "t", "Is InP short?", at),
    seed_company_ids: seeds,
  });
  const rows = companyQuestions(
    [
      seeded("old", "2026-10-01T00:00:00Z", ["lite"]),
      seeded("new", "2026-10-03T00:00:00Z", ["lite", "coht"]),
      seeded("other", "2026-10-02T00:00:00Z", ["coht"]),
    ],
    "lite",
  );
  expect(rows).toHaveLength(1);
  expect(rows[0]?.latest.id).toBe("new");
  expect(rows[0]?.runs).toBe(2);
});

test("no runs and no themes is an empty index; a listed theme with no runs is one empty theme", () => {
  expect(researchIndex([], [])).toEqual([]);
  expect(researchIndex([], ["photonics"])).toEqual([{ theme: "photonics", rows: [] }]);
});

test("five wordings of one question collapse to one row with the newest wording", () => {
  const rows = researchIndex(
    [
      run("1", "t", "Is InP short?", "2026-10-01T00:00:00Z"),
      run("2", "t", "is inp short", "2026-10-02T00:00:00Z"),
      run("3", "t", "Is  InP short.", "2026-10-03T00:00:00Z"),
      run("4", "t", "IS INP SHORT???", "2026-10-04T00:00:00Z"),
      run("5", "t", "Is InP short?!", "2026-10-05T00:00:00Z"),
    ],
    ["t"],
  )[0]!.rows;
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({ runs: 5, question: "Is InP short?!" });
  expect(rows[0]!.runIds).toHaveLength(5);
});

test("a company's questions are newest first across themes", () => {
  const seeded = (id: string, theme: string, q: string, at: string) => ({
    ...run(id, theme, q, at),
    seed_company_ids: ["lite"],
  });
  const rows = companyQuestions(
    [
      seeded("a", "photonics", "First?", "2026-10-01T00:00:00Z"),
      seeded("b", "robotics", "Second?", "2026-10-03T00:00:00Z"),
      seeded("c", "photonics", "Third?", "2026-10-02T00:00:00Z"),
    ],
    "lite",
  );
  expect(rows.map((r) => r.latest.id)).toEqual(["b", "c", "a"]);
});

test("a pill is quiet unless a run needs a look", () => {
  const tone = (reason: InvestigationSummary["stop_reason"]) =>
    statusTone(run("a", "t", "q", "2026-10-01T00:00:00Z", reason));
  expect(tone("answered")).toBe("reader-supported");
  expect(tone(null)).toBe("reader-unknown");
  expect(tone("needs_review")).toBe("reader-review");
  expect(tone("budget_exhausted")).toBe("reader-review");
  expect(tone("no_new_independent_evidence")).toBe("reader-review");
  expect(tone("premise_disproven")).toBe("reader-unknown");
});

function hypothesis(
  id: string,
  investigation: string,
  updated: string,
  thesis: string,
  latest: number | null = 2,
): Hypothesis {
  return {
    id,
    investigation_id: investigation,
    status: "draft",
    updated_at: updated,
    latest_version: latest,
    versions: [
      { version: 1, content: { thesis_statement: "old " + thesis } },
      { version: 2, content: { thesis_statement: thesis } },
    ],
  } as unknown as Hypothesis;
}

test("a question with a Hypothesis shows its thesis; without one it is a draft", () => {
  const rows = researchIndex(
    [run("1", "t", "Q?", "2026-10-01T00:00:00Z"), run("2", "t", "Other?", "2026-10-02T00:00:00Z")],
    ["t"],
  )[0]!.rows;
  const byRun = hypothesisByInvestigation([hypothesis("h1", "1", "2026-10-03T00:00:00Z", "InP is short")]);
  const withThesis = rowResult(rows.find((r) => r.latest.id === "1")!, byRun);
  expect(withThesis).toMatchObject({ kind: "hypothesis", id: "h1", thesis: "InP is short" });
  expect(rowResult(rows.find((r) => r.latest.id === "2")!, byRun)).toEqual({
    kind: "draft",
    words: "Draft",
  });
});

test("a Hypothesis of an older run still leads its collapsed question", () => {
  const rows = researchIndex(
    [run("old", "t", "Q?", "2026-10-01T00:00:00Z"), run("new", "t", "q", "2026-10-05T00:00:00Z", null)],
    [],
  )[0]!.rows;
  const byRun = hypothesisByInvestigation([hypothesis("h", "old", "2026-10-02T00:00:00Z", "Thesis")]);
  expect(rowResult(rows[0]!, byRun)).toMatchObject({ kind: "hypothesis", id: "h" });
  expect(rowResult(rows[0]!, new Map())).toEqual({ kind: "draft", words: "Running" });
});

test("of two Hypotheses of one run the latest updated wins; no versions means none", () => {
  const byRun = hypothesisByInvestigation([
    hypothesis("a", "1", "2026-10-01T00:00:00Z", "A"),
    hypothesis("b", "1", "2026-10-02T00:00:00Z", "B"),
    { ...hypothesis("c", "2", "2026-10-02T00:00:00Z", "C"), versions: [] } as Hypothesis,
  ]);
  expect(byRun.get("1")?.id).toBe("b");
  expect(byRun.has("2")).toBe(false);
  expect(hypothesisWords("paper_tracking")).toBe("Paper tracking");
});
