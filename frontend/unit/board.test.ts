import { expect, test } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { Board } from "../components/board";
import { Memo } from "../components/memo";
import { StepPips } from "../components/step-pips";
import { WatchSection } from "../components/watch-section";
import type { Chokepoint, StepState } from "../lib/api/client";

// The board's components rendered to markup (no browser): what they render for nothing, the
// strip's accessible names, and the ruled-out fold, which renders its rows only once opened.
const NOW = new Date("2026-10-24T12:00:00Z");
const NAMES = ["constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"];

const steps = (status: Partial<Record<string, StepState["status"]>>): StepState[] =>
  ["a", "b", "c", "d", "e", "f"].map((step, index) => ({
    step: step as StepState["step"],
    name: NAMES[index] ?? "",
    status: status[step] ?? "unexamined",
    evidence: { fact_ids: [], lead_ids: [], issue_ids: [] },
    set_at: null,
  }));

const cp = (over: Partial<Chokepoint>): Chokepoint => ({
  id: "cp",
  theme: "photonics",
  created_at: "2026-10-20T00:00:00Z",
  created_by_session: null,
  created_by_run: null,
  constraint: "Indium phosphide laser capacity",
  layer: "laser",
  holders: [{ name: "Lumentum", slug: "lumentum" }],
  status: "candidate",
  status_reason: null,
  thesis_gate: { holds: false, missing: ["open_issue"] },
  needs_review: false,
  stale: false,
  steps: steps({ a: "primary", d: "lead", f: "contradicted" }),
  kill_criteria: [],
  relief_horizon: null,
  crowding: "early",
  issue_ids: [],
  last_event_at: "2026-10-20T00:00:00Z",
  last_evidence_at: "2026-10-20T00:00:00Z",
  event_count: 3,
  ...over,
});

const html = (element: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(element);

test("an empty board and an empty Watch render nothing", () => {
  expect(html(createElement(Board, { items: [], now: NOW }))).toBe("");
  expect(html(createElement(WatchSection, { rows: [], now: NOW }))).toBe("");
});

test("the strip names each step with its state, four for and two against", () => {
  const markup = html(createElement(StepPips, { steps: steps({ a: "primary", d: "lead", f: "contradicted" }) }));
  const names = [...markup.matchAll(/aria-label="([^"]+)"/g)].map((match) => match[1]);
  expect(names).toEqual([
    "Steps",
    "Constraint: quoted",
    "Demand: not examined",
    "Control: unquoted",
    "Capture: not examined",
    "Relief: not examined",
    "Invalidation: contradicted",
  ]);
  expect(markup).toContain("Against");
});

test("the board's groups carry counts, rows carry no status word, ruled out renders no row closed", () => {
  const markup = html(
    createElement(Board, {
      items: [
        cp({ id: "a", status: "thesis_ready", thesis_gate: { holds: true, missing: [] } }),
        cp({ id: "b", status: "candidate", constraint: "Second" }),
        cp({ id: "k", status: "killed", constraint: "Gone for good", status_reason: "Supply added faster than demand." }),
      ],
      now: NOW,
    }),
  );
  expect(markup).toContain("Thesis-ready (1)");
  expect(markup).toContain("Candidates (1)");
  expect(markup).not.toContain("Spotted (");
  expect(markup).toContain("<summary>Ruled out (1)</summary>");
  expect(markup).not.toContain("Gone for good");
  expect(markup).not.toContain("Supply added");
  // A row's text: the constraint, the holder, the layer, the crowding word, never a status word.
  expect(markup).toContain("Lumentum · Laser · Early");
  expect(markup).not.toMatch(/>Candidate<|thesis_ready|primary/);
});

test("the memo renders elements only: a script stays text, a bad link is text", () => {
  const markup = html(
    createElement(Memo, {
      source: "<script>window.__pwned=1</script>\n\n[ok](https://example.com) [bad](javascript:alert(1))",
    }),
  );
  expect(markup).not.toContain("<script");
  expect(markup).toContain("&lt;script&gt;");
  expect(markup).toContain('href="https://example.com"');
  expect(markup).toContain('rel="noopener noreferrer nofollow"');
  expect(markup).not.toContain("javascript");
});
