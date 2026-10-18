import { expect, test } from "@playwright/test";

import type { Call, Prediction } from "../lib/api/client";
import { callCells, callsByTheme, firstCheckpointSentence, horizonHits, recordFigures } from "../lib/record";

const NOW = new Date("2026-10-18T13:00:00Z");

function call(over: Partial<Call> = {}): Call {
  return {
    id: "c",
    origin: "belief",
    origin_id: "b",
    lead_id: null,
    theme: "photonics",
    claim: "x",
    direction: null,
    made_at: "2026-10-18T10:00:00Z",
    state: "open",
    unpriced_reason: null,
    companies: [],
    checkpoints: [],
    next_due: { horizon_months: 1, due_on: "2026-11-18" },
    note: "",
    ...over,
  };
}

const point = (horizon: number, relative: number | null, change = 0.1) =>
  ({
    horizon_months: horizon,
    due_on: "2026-11-18",
    change,
    benchmark_change: 0,
    relative_change: relative,
    benchmark_members: 3,
    companies: [],
    benchmark: [],
    settled_at: "2026-11-18T00:00:00Z",
  }) as Call["checkpoints"][number];

test("with no checkpoint the figures show open calls, a dash and when the +3 m reading comes", () => {
  const figures = recordFigures([call(), call({ made_at: "2026-10-12T10:00:00Z" })], []);
  expect(figures.open).toBe(2);
  expect(figures.checkpoints).toBe(0);
  expect(figures.ahead).toBeNull();
  expect(figures.aheadUntil).toBe("2027-01-12");
});

test("with +3 m checkpoints the figure is how many are ahead of the benchmark", () => {
  const figures = recordFigures(
    [
      call({ checkpoints: [point(3, 0.05)] }),
      call({ checkpoints: [point(3, -0.02)] }),
      call({ checkpoints: [point(1, 0.5)] }),
    ],
    [],
  );
  expect(figures.checkpoints).toBe(3);
  expect(figures.ahead).toEqual({ count: 1, of: 2 });
});

test("predictions are counted open, met and missed", () => {
  const prediction = (state: string, outcome?: string) =>
    ({ state, settlement: outcome ? { outcome } : null }) as unknown as Prediction;
  const figures = recordFigures(
    [],
    [prediction("open"), prediction("open"), prediction("settled", "met"), prediction("settled", "missed")],
  );
  expect(figures.predictions).toEqual({ open: 2, met: 1, missed: 1 });
});

test("while no checkpoint exists one sentence says when the first falls", () => {
  expect(firstCheckpointSentence([call(), call({ next_due: { horizon_months: 1, due_on: "2026-11-12" } })], NOW)).toBe(
    "First checkpoint 12 Nov: 2 calls priced against their theme's companies.",
  );
  expect(firstCheckpointSentence([call({ checkpoints: [point(1, 0.1)] })], NOW)).toBeNull();
  expect(firstCheckpointSentence([], NOW)).toBeNull();
});

test("a call has one cell until a checkpoint, then the change against the benchmark with its arrow", () => {
  expect(callCells(call(), NOW).first).toBe("first checkpoint 18 Nov");
  expect(callCells(call({ state: "unpriced", unpriced_reason: "no_symbol", next_due: null }), NOW).first).toBe(
    "not priced: no price symbol",
  );
  expect(
    callCells(call({ state: "unpriced", unpriced_reason: "tradingview_disabled", next_due: null }), NOW).first,
  ).toBe("not priced: price source off");
  const cells = callCells(call({ checkpoints: [point(1, 0.055), point(3, -0.1)] }), NOW);
  expect(cells.horizons.map((each) => each.text)).toEqual(["↑ +5.5%", "↓ -10.0%", ""]);
  expect(cells.horizons.map((each) => each.tone)).toEqual(["up", "down", "none"]);
});

test("calls group by theme, newest first", () => {
  const groups = callsByTheme([
    call({ id: "a", theme: "memory", made_at: "2026-10-01T00:00:00Z" }),
    call({ id: "b", theme: "photonics", made_at: "2026-10-18T00:00:00Z" }),
    call({ id: "c", theme: "memory", made_at: "2026-10-10T00:00:00Z" }),
  ]);
  expect(groups.map((group) => [group.theme, group.calls.map((each) => each.id)])).toEqual([
    ["photonics", ["b"]],
    ["memory", ["c", "a"]],
  ]);
});

test("each horizon says how many checkpointed calls are ahead of the benchmark, or that there is none yet", () => {
  expect(horizonHits([call(), call()]).map((hit) => hit.text)).toEqual([
    "+1 m: no checkpoint yet",
    "+3 m: no checkpoint yet",
    "+6 m: no checkpoint yet",
  ]);
  const hits = horizonHits([
    call({ checkpoints: [point(1, 0.05), point(3, -0.1)] }),
    call({ checkpoints: [point(1, -0.02)] }),
    call({ checkpoints: [point(1, 0.2)] }),
  ]);
  expect(hits.map((hit) => hit.text)).toEqual([
    "+1 m: 2 of 3 ahead of the benchmark",
    "+3 m: 0 of 1 ahead of the benchmark",
    "+6 m: no checkpoint yet",
  ]);
});
