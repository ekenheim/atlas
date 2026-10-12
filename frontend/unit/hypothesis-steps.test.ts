import { expect, test } from "@playwright/test";

import type { HypothesisVersion, Issue } from "../lib/api/client";
import {
  type Step,
  beliefCount,
  openIssues,
  stepViews,
} from "../lib/hypothesis-steps";

function belief(id: string, confidence: number): Step["beliefs"][number] {
  return { belief_id: id, confidence } as Step["beliefs"][number];
}

function version(steps: Partial<Step>[]): HypothesisVersion {
  return { content: { steps } } as unknown as HypothesisVersion;
}

test("the steps come in the argument's order, with the most confident Belief first", () => {
  const views = stepViews(
    version([
      {
        step: "capture",
        statement: "Capture.",
        judged: true,
        beliefs: [belief("c", 0.7)],
      },
      {
        step: "constraint",
        statement: null,
        beliefs: [belief("a", 0.6), belief("b", 0.9)],
      },
      { step: "something_new", beliefs: [belief("d", 0.5)] },
    ]),
  );

  expect(views.map((each) => each.step)).toEqual([
    "constraint",
    "capture",
    "something_new",
  ]);
  expect(views.map((each) => each.title)).toEqual([
    "Constraint",
    "Capture",
    "Something new",
  ]);
  expect(views[0]?.beliefs.map((each) => each.belief_id)).toEqual(["b", "a"]);
  // A statement the Editor's draft lost shows as none; a judged one says so.
  expect(views.map((each) => [each.statement, each.judged])).toEqual([
    [null, null],
    ["Capture.", true],
    [null, null],
  ]);
});

test("a version of an investigation has no steps", () => {
  expect(stepViews(version([]))).toEqual([]);
  expect(beliefCount(version([]))).toBe(0);
});

test("a Belief resting two steps is counted once", () => {
  const shared = belief("a", 0.8);
  expect(
    beliefCount(
      version([
        { step: "constraint", beliefs: [shared, belief("b", 0.5)] },
        { step: "capture", beliefs: [shared] },
      ]),
    ),
  ).toBe(2);
});

test("open Issues are the theme's active ones, the most pressing first", () => {
  const issue = (
    title: string,
    theme: string,
    status: string,
    priority: number,
    at: string,
  ) => ({ title, theme, status, priority, created_at: at }) as Issue;
  const issues = [
    issue("old", "photonics", "active", 1, "2026-10-01T00:00:00Z"),
    issue("done", "photonics", "complete", 9, "2026-10-01T00:00:00Z"),
    issue("other theme", "memory", "active", 9, "2026-10-01T00:00:00Z"),
    issue("urgent", "photonics", "active", 5, "2026-10-02T00:00:00Z"),
    issue("newer", "photonics", "active", 1, "2026-10-03T00:00:00Z"),
  ];

  expect(openIssues(issues, "photonics").map((each) => each.title)).toEqual([
    "urgent",
    "old",
    "newer",
  ]);
});
