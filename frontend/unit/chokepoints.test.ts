import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import type { Chokepoint, ChokepointEvent, CompaniesIndex, Company, StepState } from "../lib/api/client";
import {
  badges,
  barLine,
  boardCounts,
  boardGroups,
  boardLine,
  boardParts,
  clampWords,
  historyRows,
  holderNames,
  holderView,
  humanise,
  lapse,
  layerName,
  pipsOf,
  rowSecondary,
  statusSince,
  stepCounts,
  stepViews,
  themeTitle,
  thesisHeadlineFactIds,
} from "../lib/chokepoints";

const NOW = new Date("2026-10-18T12:00:00Z");
const LETTERS = ["a", "b", "c", "d", "e", "f"] as const;
const NAMES = ["constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"];

function steps(over: Partial<Record<(typeof LETTERS)[number], Partial<StepState>>> = {}): StepState[] {
  return LETTERS.map((letter, index) => ({
    step: letter,
    name: NAMES[index] ?? "",
    status: "unexamined",
    evidence: { fact_ids: [], lead_ids: [], issue_ids: [] },
    set_at: null,
    ...over[letter],
  }));
}

const primary = (...facts: string[]): Partial<StepState> => ({
  status: "primary",
  evidence: { fact_ids: facts, lead_ids: [], issue_ids: [] },
  set_at: "2026-10-10T00:00:00Z",
});

function cp(over: Partial<Chokepoint> = {}): Chokepoint {
  return {
    id: "cp-1",
    theme: "photonics",
    created_at: "2026-10-01T00:00:00Z",
    created_by_session: null,
    created_by_run: null,
    constraint: "Indium phosphide substrate capacity",
    layer: "substrate",
    holders: [],
    status: "lead",
    status_reason: null,
    thesis_gate: { holds: false, missing: ["step_a_primary", "step_b_primary", "step_d_primary", "kill_criteria", "open_issue"] },
    needs_review: false,
    stale: false,
    steps: steps(),
    kill_criteria: [],
    relief_horizon: null,
    crowding: null,
    issue_ids: [],
    last_event_at: "2026-10-10T00:00:00Z",
    last_evidence_at: "2026-10-10T00:00:00Z",
    event_count: 1,
    ...over,
  };
}

const READY = cp({ id: "ready", status: "thesis_ready", thesis_gate: { holds: true, missing: [] } });
const BELOW = cp({
  id: "below",
  status: "thesis_ready",
  needs_review: true,
  thesis_gate: { holds: false, missing: ["step_d_primary", "kill_criteria"] },
});
const QUESTION = cp({
  id: "question",
  status: "thesis_ready",
  needs_review: true,
  thesis_gate: { holds: false, missing: ["open_issue"] },
});
const QUIET = cp({ id: "quiet", status: "candidate", stale: true, last_evidence_at: "2026-08-14T00:00:00Z" });
const CANDIDATE = cp({ id: "candidate", status: "candidate" });
const KILLED = cp({ id: "killed", status: "killed", status_reason: "Supply caught up." });

test("a layer is the universe's name, else its slug in words", () => {
  expect(layerName("gating-equipment")).toBe("Gating equipment");
  expect(layerName("magnet-material")).toBe("Magnet material");
  expect(layerName("chip-laser")).toBe("Chip / laser");
  expect(layerName("memory-dram")).toBe("Memory: DRAM and HBM");
  expect(humanise("demand_vs_supply")).toBe("Demand vs supply");
  expect(themeTitle("robotics")).toBe("Robotics");
  expect(themeTitle("photonics", [{ id: "photonics", title: "Photonics for AI data centers" }])).toBe(
    "Photonics for AI data centers",
  );
});

test("a long relief horizon is clamped at a word boundary", () => {
  expect(clampWords("2028")).toBe("2028");
  expect(clampWords("after the second fab in Ohio is qualified, around 2029")).toBe("after the second fab in…");
  expect(clampWords("x".repeat(40))).toBe(`${"x".repeat(28)}…`);
});

test("a lapsed gate is below the bar, or needs a new open question when only that is missing", () => {
  expect(lapse(READY)).toBeNull();
  expect(lapse(BELOW)).toBe("below");
  expect(lapse(QUESTION)).toBe("question");
  expect(badges(BELOW, NOW).map((each) => [each.word.word, each.word.tone])).toEqual([["Below the bar", "warn"]]);
  expect(badges(QUESTION, NOW).map((each) => [each.word.word, each.word.tone])).toEqual([
    ["Needs a new open question", "warn"],
  ]);
  expect(badges(QUIET, NOW).map((each) => [each.word.word, each.word.tone])).toEqual([
    ["Quiet since 14 Aug", "muted"],
  ]);
  expect(badges(cp({ status: "killed", stale: true }), NOW)).toEqual([]);
  expect(badges(CANDIDATE, NOW)).toEqual([]);
});

test("the bar line for each state", () => {
  expect(barLine(cp())).toEqual({
    text:
      "Still needs: a quote for the constraint · a quote for demand against supply · a quote for control" +
      " · a falsifier · an open question",
    tone: "muted",
  });
  expect(barLine(cp({ status: "candidate", thesis_gate: { holds: true, missing: [] } }))).toEqual({
    text: "Meets the bar for a thesis.",
    tone: "ok",
  });
  expect(barLine(READY)).toEqual({ text: "Waiting for proof", tone: "muted" });
  expect(barLine(BELOW)).toEqual({ text: "Below the bar: no quote for control · no falsifier", tone: "warn" });
  expect(barLine(QUESTION)).toEqual({ text: "Needs a new open question", tone: "warn" });
  expect(barLine(KILLED)).toBeNull();
});

test("an unknown gate code reads as needing review, and warns", () => {
  const warned: string[] = [];
  const original = console.warn;
  console.warn = (message: string) => warned.push(message);
  try {
    expect(barLine(cp({ thesis_gate: { holds: false, missing: ["step_z_new"] } }))?.text).toBe(
      "Still needs: something else, needs review",
    );
  } finally {
    console.warn = original;
  }
  expect(warned).toHaveLength(1);
});

test("groups: lapsed thesis-ready first, quiet rows last, ruled out apart", () => {
  const groups = boardGroups([QUIET, READY, CANDIDATE, BELOW, KILLED, QUESTION, cp({ id: "spotted" })]);
  expect(groups.ready.map((each) => each.id)).toEqual(["below", "question", "ready"]);
  expect(groups.candidates.map((each) => each.id)).toEqual(["candidate", "quiet"]);
  expect(groups.spotted.map((each) => each.id)).toEqual(["spotted"]);
  expect(groups.killed.map((each) => each.id)).toEqual(["killed"]);
});

test("the board counts its active chokepoints; below the bar is the step or falsifier lapse", () => {
  const counts = boardCounts([READY, BELOW, QUESTION, CANDIDATE, KILLED]);
  expect(counts).toEqual({ active: 4, ready: 3, below: 1, killed: 1 });
  expect(boardLine(counts)).toBe("4 chokepoints · 3 thesis-ready · 1 below the bar");
  expect(boardParts(counts).map((part) => part.tone)).toEqual(["muted", "muted", "warn"]);
  expect(boardLine(boardCounts([CANDIDATE]))).toBe("1 chokepoint");
  expect(boardLine(boardCounts([KILLED]))).toBe("");
});

test("the pips run four for, then two against, each named with its state", () => {
  const pips = pipsOf(
    cp({
      steps: steps({
        a: primary("f1"),
        d: { status: "lead", evidence: { fact_ids: [], lead_ids: ["l1"], issue_ids: [] } },
        f: { status: "contradicted", evidence: { fact_ids: ["f9"], lead_ids: [], issue_ids: [] } },
      }),
    }),
  );
  expect(pips.map((pip) => pip.accessible)).toEqual([
    "Constraint: quoted",
    "Demand: not examined",
    "Control: unquoted",
    "Capture: not examined",
    "Relief: not examined",
    "Invalidation: contradicted",
  ]);
  expect(pips.map((pip) => pip.mark)).toEqual(["●", "", "○", "", "", "✕"]);
  expect(pips.filter((pip) => pip.against).map((pip) => pip.name)).toEqual(["relief", "invalidation"]);
});

test("a step's counts and the page's step sections", () => {
  expect(stepCounts({ evidence: { fact_ids: ["a", "b"], lead_ids: ["l"], issue_ids: ["i"] } })).toBe(
    "2 quotes · 1 lead · 1 open question",
  );
  expect(stepCounts({ evidence: { fact_ids: [], lead_ids: [], issue_ids: [] } })).toBe("");
  const views = stepViews(cp({ steps: steps({ b: primary("x") }) }));
  expect(views.map((view) => view.title)).toEqual([
    "Constraint",
    "Demand against supply",
    "Control",
    "Capture",
    "Relief",
    "What would invalidate it",
  ]);
  expect(views[1]?.word.word).toBe("Quoted");
  expect(views[1]?.examined).toBe(true);
  expect(views[0]?.examined).toBe(false);
});

test("on mount the page reads at most the first Fact of each thesis step", () => {
  const ids = thesisHeadlineFactIds(
    cp({ steps: steps({ a: primary("f1", "f2"), b: primary("f1"), c: primary("f7"), d: primary("f3", "f4") }) }),
  );
  expect(ids).toEqual(["f1", "f3"]);
  expect(thesisHeadlineFactIds(cp({ steps: steps({ a: primary("f1"), b: primary("f2"), d: primary("f3") }) }))).toEqual([
    "f1",
    "f2",
    "f3",
  ]);
  expect(thesisHeadlineFactIds(cp())).toEqual([]);
});

const COMPANIES: Company[] = [
  { id: "c-lumentum", slug: "lumentum", cik: "0001633978", display_name: "Lumentum", legal_name: "Lumentum Holdings Inc." },
  { id: "c-axt", slug: "axt", cik: "1051627", display_name: "AXT", legal_name: "AXT, Inc." },
].map((each) => each as unknown as Company);

const INDEX: CompaniesIndex = {
  byId: new Map(COMPANIES.map((each) => [each.id, each])),
  bySlug: new Map(COMPANIES.map((each) => [each.slug, each])),
  byCik: new Map(COMPANIES.map((each) => [(each.cik ?? "").replace(/^0+/, ""), each])),
  byName: new Map(
    COMPANIES.flatMap((each) => [
      [each.display_name.toLowerCase(), each],
      [each.legal_name.toLowerCase(), each],
    ]),
  ),
};

test("a holder is matched by slug, else CIK, else exact name", () => {
  const view = holderView(
    [
      { name: "Lumentum Holdings", slug: "lumentum" },
      { name: "Somebody", cik: "0001051627" },
      { name: "  axt, inc. " },
      { name: "Outside Holder Co" },
    ],
    INDEX,
  );
  expect(view.map((each) => each.companyId)).toEqual(["c-lumentum", "c-axt", "c-axt", null]);
  expect(holderView([{ name: "Lumentum" }], null)[0]?.companyId).toBeNull();
  expect(holderNames([{ name: "A" }, { name: "B" }, { name: "C" }])).toBe("A, B +1");
  expect(holderNames([])).toBeNull();
});

test("a row's second line: holders, layer, crowding, relief", () => {
  expect(
    rowSecondary({
      holders: [{ name: "AXT" }, { name: "Sumitomo Electric" }, { name: "JX" }],
      layer: "substrate",
      crowding: "early",
      relief_horizon: { horizon: "2028, once the new crystal growers are qualified", basis: "x" },
    }),
  ).toEqual(["AXT, Sumitomo Electric +1", "Substrate", "Early", "relief 2028, once the new crystal…"]);
  expect(rowSecondary({ holders: [], layer: "gating-equipment", crowding: null, relief_horizon: null })).toEqual([
    "Gating equipment",
  ]);
});

const event = (kind: ChokepointEvent["kind"], payload: Record<string, unknown>, over: Partial<ChokepointEvent> = {}) =>
  ({
    id: `e-${kind}-${JSON.stringify(payload).length}`,
    chokepoint_id: "cp-1",
    at: "2026-10-12T09:00:00Z",
    actor: "watch",
    session_id: null,
    run_id: null,
    kind,
    payload,
    reason: null,
    ...over,
  }) as ChokepointEvent;

test("the history replays the events into sentences that know the value before", () => {
  const rows = historyRows([
    event("created", { constraint: "X", layer: "gating-equipment", holders: [{ name: "a" }, { name: "b" }, { name: "c" }] }),
    event("step_set", { step: "d", status: "lead", evidence: {} }, { reason: "a lead names it" }),
    event("step_set", { step: "d", status: "primary", evidence: {} }),
    event("status_set", { status: "candidate" }),
    event("status_set", { status: "thesis_ready" }),
    event("field_set", { kill_criteria: ["a", "b"] }),
    event("field_set", { crowding: "consensus", relief_horizon: null }),
    event("note", { text: "Checked the call." }),
    event("status_set", { status: "killed" }, { reason: "Supply caught up." }),
  ]);
  expect(rows.map((row) => row.text)).toEqual([
    "Created at Gating equipment, held by 3",
    "Control: not examined → unquoted · why: a lead names it",
    "Control: unquoted → quoted",
    "Status: Spotted → Candidate",
    "Status: Candidate → Thesis-ready",
    "Falsifiers rewritten (2)",
    "Crowding: Crowded; Relief horizon cleared",
    "Note: Checked the call.",
    "Status: Thesis-ready → Ruled out · why: Supply caught up.",
  ]);
  for (const row of rows) expect(row.text).not.toMatch(/thesis_ready|unexamined|step d|kill_criteria/);
});

test("the status was set at its last status event, else at creation", () => {
  expect(statusSince({ created_at: "2026-10-01T00:00:00Z", history: [] })).toBe("2026-10-01T00:00:00Z");
  expect(
    statusSince({
      created_at: "2026-10-01T00:00:00Z",
      history: [
        event("status_set", { status: "candidate" }, { at: "2026-10-03T00:00:00Z" }),
        event("note", { text: "x" }, { at: "2026-10-05T00:00:00Z" }),
        event("status_set", { status: "thesis_ready" }, { at: "2026-10-04T00:00:00Z" }),
      ],
    }),
  ).toBe("2026-10-04T00:00:00Z");
});

test("a real board answer: groups, counts and quiet read from it", () => {
  const board = JSON.parse(readFileSync(join(__dirname, "fixtures", "board.json"), "utf-8")) as {
    items: Chokepoint[];
  };
  const groups = boardGroups(board.items);
  expect(groups.ready.length + groups.candidates.length + groups.spotted.length + groups.killed.length).toBe(
    board.items.length,
  );
  const photonics = boardGroups(board.items.filter((each) => each.theme === "photonics"));
  // The e2e seed's board (`scripts/e2e_board.py`): the lapsed thesis-ready ones lead their group.
  expect(photonics.ready.map((each) => barLine(each)?.text)).toEqual([
    "Needs a new open question",
    "Below the bar: no falsifier",
    "Waiting for proof",
  ]);
  expect(photonics.candidates).toHaveLength(1);
  expect(photonics.spotted).toHaveLength(1);
  expect(photonics.killed[0]?.status_reason).toBe("Supply added faster than demand.");
  const counts = boardCounts(board.items);
  expect(counts.active).toBe(board.items.filter((each) => each.status !== "killed").length);
  expect(boardLine(boardCounts(board.items.filter((each) => each.theme === "photonics")))).toBe(
    "5 chokepoints · 3 thesis-ready · 1 below the bar",
  );
  // Quiet is clock-derived: the API's `stale` against a fixed now.
  for (const each of board.items) {
    const quiet = badges(each, NOW).some((badge) => badge.kind === "quiet");
    expect(quiet).toBe(each.stale && each.status !== "killed");
  }
});
