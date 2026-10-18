import { expect, test } from "@playwright/test";

import type { BeliefSummary, Chokepoint, ThemeSummary, WatchRun } from "../lib/api/client";
import {
  countsFor,
  latestByTheme,
  namedOnBoard,
  stoppedWatch,
  themeLayout,
  themesCards,
  todayCards,
  watchRows,
  watchedSlugs,
} from "../lib/watch";

const NOW = new Date("2026-10-24T18:00:00Z");

function run(over: Partial<WatchRun> = {}): WatchRun {
  return {
    id: "run-1",
    theme: "robotics",
    run_date: "2026-10-24",
    mode: "architect",
    memo: "Two makers hold most precision reducer capacity.\n\n## Discoveries\n\n- One",
    counts: {},
    tool_calls: 212,
    cost_usd: 3.1,
    tokens: 1000,
    session_id: null,
    created_at: "2026-10-24T08:00:00Z",
    ...over,
  };
}

function cp(over: Partial<Chokepoint> = {}): Chokepoint {
  return {
    id: "cp",
    theme: "robotics",
    created_at: "2026-10-24T08:10:00Z",
    created_by_session: null,
    created_by_run: null,
    constraint: "Precision reducer capacity",
    layer: "reducer",
    holders: [],
    status: "lead",
    status_reason: null,
    status_set_at: "2026-10-24T08:10:00Z",
    thesis_gate: { holds: false, missing: ["open_issue"] },
    needs_review: false,
    stale: false,
    steps: [],
    kill_criteria: [],
    relief_horizon: null,
    crowding: null,
    issue_ids: [],
    last_event_at: "2026-10-24T08:10:00Z",
    last_evidence_at: "2026-10-24T08:10:00Z",
    event_count: 1,
    ...over,
  };
}

const theme = (id: string, company_count = 12): ThemeSummary => ({
  id,
  title: id === "photonics" ? "Photonics for AI data centers" : id,
  description: "",
  universe_version: 9,
  company_count,
  companies_without_sources: 0,
  empty_layers: [],
  relationship_count: 0,
  open_candidate_count: 0,
  board: { lead: 0, candidate: 0, thesis_ready: 0, killed: 0, stale: 0, needs_review: 0 },
});

const belief = (theme: string) =>
  ({ id: `b-${theme}`, theme, status: "active", step: "constraint" }) as unknown as BeliefSummary;

test("each theme's latest run and the one before it", () => {
  const runs = [
    run({ id: "r1", created_at: "2026-10-10T08:00:00Z" }),
    run({ id: "r3", created_at: "2026-10-24T08:00:00Z" }),
    run({ id: "r2", created_at: "2026-10-17T08:00:00Z" }),
    run({ id: "p1", theme: "photonics" }),
  ];
  const latest = latestByTheme(runs);
  expect(latest.get("robotics")?.latest.id).toBe("r3");
  expect(latest.get("robotics")?.previous?.id).toBe("r2");
  expect(latest.get("photonics")?.previous).toBeNull();
});

test("a theme is watched by a run or a chokepoint not ruled out", () => {
  expect([...watchedSlugs([cp({ theme: "a" }), cp({ theme: "b", status: "killed" })], [run({ theme: "c" })])].sort()).toEqual([
    "a",
    "c",
  ]);
  expect(watchedSlugs([], []).size).toBe(0);
});

test("the watch has stopped after nine days", () => {
  expect(stoppedWatch(run({ run_date: "2026-10-15" }), NOW)).toBe(false);
  expect(stoppedWatch(run({ run_date: "2026-10-14" }), NOW)).toBe(true);
});

test("a first run names what was spotted, at most two, then counts the rest", () => {
  const board = [
    cp({ id: "x", constraint: "X" }),
    cp({ id: "y", constraint: "Y", status: "thesis_ready" }),
    cp({ id: "z", constraint: "Z" }),
    cp({ id: "k", constraint: "K", status: "killed" }),
  ];
  const named = namedOnBoard(board, { previous: null });
  expect(named.parts.map((part) => [part.label, part.chokepoints.map((each) => each.id)])).toEqual([
    ["Thesis-ready", ["y"]],
    ["New", ["x"]],
  ]);
  expect(named.more).toBe(2);
});

test("a later run names only what changed since the previous run", () => {
  const previous = run({ id: "r1", created_at: "2026-10-17T08:00:00Z" });
  const board = [
    cp({ id: "old", created_at: "2026-10-10T00:00:00Z", last_event_at: "2026-10-12T00:00:00Z" }),
    cp({ id: "new1", created_at: "2026-10-23T00:00:00Z" }),
    cp({ id: "new2", created_at: "2026-10-22T00:00:00Z" }),
    cp({ id: "gone", status: "killed", created_at: "2026-10-01T00:00:00Z", last_event_at: "2026-10-20T00:00:00Z" }),
  ];
  const named = namedOnBoard(board, { previous });
  expect(named.parts).toEqual([{ label: "New", chokepoints: [board[1], board[2]] }]);
  expect(named.more).toBe(1);
  expect(namedOnBoard([board[0] as Chokepoint], { previous })).toEqual({ parts: [], more: 0 });
});

test("Today's rows follow the cards' theme order, then the slugs /themes does not list", () => {
  const rows = watchRows(
    [theme("photonics"), theme("memory-packaging")],
    [cp({ theme: "zeta" }), cp({ theme: "photonics" })],
    [run(), run({ id: "p", theme: "photonics", mode: "delta" })],
    new Date("2026-10-20T00:00:00Z"),
    NOW,
  );
  expect(rows.map((row) => [row.slug, row.title])).toEqual([
    ["photonics", "Photonics for AI data centers"],
    ["robotics", "Robotics"],
    ["zeta", "Zeta"],
  ]);
  expect(rows[0]?.unseen).toBe(true);
  expect(rows[0]?.excerpt).toBe("Two makers hold most precision reducer capacity.");
  expect(rows[2]?.runs).toBeNull();
  expect(rows[2]?.excerpt).toBe("");
});

test("cards: Beliefs give a card, the untouched Starting theme keeps one, the watched one has a row only", () => {
  const themes = [theme("photonics"), theme("memory-packaging", 7), theme("robotics", 0), theme("scorecard", 5)];
  const beliefs = [belief("photonics")];
  // The shipping state: no board, no run.
  expect(todayCards(themes, beliefs, [], []).map((each) => each.id)).toEqual([
    "photonics",
    "memory-packaging",
    "scorecard",
  ]);
  // Robotics after its first run, and memory-packaging with a board: rows only.
  expect(
    todayCards(themes, beliefs, [cp({ theme: "memory-packaging" })], [run()]).map((each) => each.id),
  ).toEqual(["photonics", "scorecard"]);
  // A board does not take a card from a theme with Beliefs.
  expect(todayCards(themes, beliefs, [cp({ theme: "photonics" })], []).map((each) => each.id)).toContain("photonics");
  // While the Beliefs are unknown, a theme with companies keeps its card.
  expect(todayCards(themes, null, [], []).map((each) => each.id)).toEqual(["photonics", "memory-packaging", "scorecard"]);
});

test("the theme page's layout, every rule, robotics in and out of /themes", () => {
  const photonics = theme("photonics");
  const robotics = theme("robotics", 0);
  expect(themeLayout(photonics, [belief("photonics")], [], [])).toBe("thesis");
  expect(themeLayout(photonics, [belief("photonics")], [cp()], [run()])).toBe("thesis");
  expect(themeLayout(robotics, [], [], [run()])).toBe("board");
  expect(themeLayout(undefined, null, [], [run()])).toBe("board");
  expect(themeLayout(undefined, [], [cp({ status: "killed" })], [])).toBe("board");
  expect(themeLayout(theme("memory-packaging", 7), [], [cp({ theme: "memory-packaging" })], [])).toBe("board");
  expect(themeLayout(robotics, [], [], [])).toBe("starting");
  expect(themeLayout(theme("memory-packaging", 7), null, [], [])).toBe("starting");
  expect(themeLayout(undefined, [], [], [])).toBe("missing");
});

test("Themes keeps every card: Watching for a watched theme with no Belief, Not started for an empty one", () => {
  const themes = [theme("photonics"), theme("memory-packaging", 7), theme("robotics", 0)];
  const beliefs = [belief("photonics")];
  // The shipping state: robotics is Not started, the others keep their round-2 cards.
  expect(themesCards(themes, beliefs, [], [], NOW).map((card) => [card.slug, card.watch])).toEqual([
    ["photonics", null],
    ["memory-packaging", null],
    ["robotics", { watching: false, line: "The first watch has not run." }],
  ]);
  // After the first survey, and with a watched slug that /themes does not list. A theme of
  // /themes is counted by its summary's `board`; the other slug, from the board read.
  const counted = { lead: 1, candidate: 0, thesis_ready: 1, killed: 0, stale: 0, needs_review: 0 };
  const cards = themesCards(
    [themes[0] as ThemeSummary, themes[1] as ThemeSummary, { ...theme("robotics", 0), board: counted }],
    beliefs,
    [cp(), cp({ id: "2", status: "thesis_ready" }), cp({ theme: "zeta" })],
    [run()],
    NOW,
  );
  expect(cards.map((card) => [card.slug, card.watch?.line ?? null])).toEqual([
    ["photonics", null],
    ["memory-packaging", null],
    ["robotics", "last watch 24 Oct · 2 chokepoints · 1 thesis-ready"],
    ["zeta", "1 chokepoint"],
  ]);
  expect(cards[3]?.theme).toBeNull();
  expect(cards[3]?.title).toBe("Zeta");
  // While the Beliefs are unknown no card is replaced.
  expect(themesCards(themes, null, [], [run()], NOW).map((card) => card.watch)).toEqual([null, null, null]);
});

test("a theme's counts are its summary's; without one (an older server, an unlisted slug) the board read's", () => {
  const counted = { lead: 2, candidate: 1, thesis_ready: 0, killed: 0, stale: 0, needs_review: 0 };
  const listed = [{ id: "robotics", title: "Robotics manufacturing", board: counted }];
  expect(countsFor("robotics", listed, [cp()])).toBe(counted);
  expect(countsFor("robotics", [{ id: "robotics", title: "Robotics" }], [cp(), cp({ id: "k", status: "killed" })])).toEqual({
    lead: 1,
    candidate: 0,
    thesis_ready: 0,
    killed: 1,
    stale: 0,
    needs_review: 0,
  });
  // Today names what became thesis-ready by when its status was set, not its latest event.
  const previous = run({ created_at: "2026-10-20T00:00:00Z" });
  const old = cp({ id: "old", status: "thesis_ready", status_set_at: "2026-10-10T00:00:00Z", created_at: "2026-10-01T00:00:00Z", last_event_at: "2026-10-23T00:00:00Z" });
  expect(namedOnBoard([old], { previous })).toEqual({ parts: [], more: 0 });
});
