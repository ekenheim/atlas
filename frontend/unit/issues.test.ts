import { expect, test } from "@playwright/test";

import type { Issue } from "../lib/api/client";
import {
  applyFilters,
  filterSearch,
  nextAction,
  orderIssues,
  parseFilters,
  producedText,
  tier,
} from "../lib/issues";

let counter = 0;
function issue(over: Partial<Issue> & Pick<Issue, "title">): Issue {
  counter += 1;
  return {
    id: `i-${String(counter).padStart(3, "0")}`,
    body: "",
    theme: "photonics",
    kind: "read",
    priority: 0,
    status: "active",
    produced_by: null,
    company_ids: [],
    created_by: "test",
    created_at: `2026-10-01T00:00:${String(counter).padStart(2, "0")}Z`,
    closed_at: null,
    parent_id: null,
    parent_title: null,
    requires: [],
    blocked: false,
    open_children: 0,
    products: [],
    ...over,
  };
}

const belief = { belief_id: "b-1", fact_id: null, actor: "t", created_at: "2026-10-02T00:00:00Z" };
const fact = { belief_id: null, fact_id: "f-1", actor: "t", created_at: "2026-10-02T00:00:00Z" };

test("the next action is a step with no Belief, then flagged or disputed, then priority, then age", () => {
  const old = issue({ title: "old", priority: 1 });
  const urgent = issue({ title: "urgent", priority: 5 });
  const disputed = issue({ title: "disputed", body: "Step disputed", priority: 0 });
  const step = issue({ title: "step", kind: "step", priority: 0 });
  const stepWithBelief = issue({ title: "done step", kind: "step", products: [belief] });
  const stepWithFact = issue({ title: "fact step", kind: "step", products: [fact] });
  const ordered = orderIssues([old, urgent, disputed, stepWithBelief, step, stepWithFact]);
  // A Fact alone is not a Belief, so the step it came from is still first (the older first).
  expect(ordered.map((each) => each.title)).toEqual([
    "step",
    "fact step",
    "disputed",
    "urgent",
    "old",
    "done step",
  ]);
  expect(nextAction([old, urgent, disputed])?.title).toBe("disputed");
  expect(nextAction([old, urgent])?.title).toBe("urgent");
  expect(tier(stepWithBelief)).toBe(2);
});

test("blocked Issues, parents with active children and closed ones wait after the frontier", () => {
  const blocked = issue({ title: "blocked", priority: 9, blocked: true });
  const parent = issue({ title: "parent", kind: "question", priority: 9, open_children: 2 });
  const closed = issue({ title: "closed", priority: 9, status: "complete" });
  const ready = issue({ title: "ready", priority: 0 });
  const ordered = orderIssues([blocked, parent, closed, ready]);
  expect(ordered.map((each) => each.title)).toEqual(["ready", "blocked", "parent", "closed"]);
  expect(nextAction([blocked, parent, closed])).toBeNull();
});

test("equal rank goes to the oldest", () => {
  const first = issue({ title: "first", priority: 1 });
  const second = issue({ title: "second", priority: 1 });
  expect(orderIssues([second, first]).map((each) => each.title)).toEqual(["first", "second"]);
});

test("filters live in the URL, default to active, and leave out defaults", () => {
  expect(parseFilters(new URLSearchParams(""))).toEqual({ theme: "", status: "active" });
  expect(parseFilters(new URLSearchParams("theme=photonics&status=all"))).toEqual({
    theme: "photonics",
    status: "all",
  });
  expect(parseFilters(new URLSearchParams("status=nonsense")).status).toBe("active");
  expect(filterSearch({ theme: "", status: "active" })).toBe("");
  expect(filterSearch({ theme: "photonics", status: "complete" })).toBe(
    "theme=photonics&status=complete",
  );
  const a = issue({ title: "a" });
  const b = issue({ title: "b", theme: "robotics" });
  const c = issue({ title: "c", status: "complete" });
  expect(applyFilters([a, b, c], { theme: "photonics", status: "active" })).toEqual([a]);
  expect(applyFilters([a, b, c], { theme: "", status: "all" })).toHaveLength(3);
});

test("what an Issue produced reads as counts", () => {
  expect(producedText(issue({ title: "x" }))).toBe("");
  expect(producedText(issue({ title: "x", products: [belief, fact, fact] }))).toBe(
    "1 Belief, 2 Facts",
  );
});
