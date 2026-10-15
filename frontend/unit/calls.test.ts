import { expect, test } from "@playwright/test";

import type { Call, Prediction } from "../lib/api/client";
import {
  callsSummary,
  cells,
  companiesLine,
  dueDate,
  expectedRange,
  percent,
  predictionStatus,
  shortDate,
} from "../lib/calls";

type Checkpoints = Call["checkpoints"];

function checkpoint(
  horizon: number,
  change: number,
  benchmark: number | null,
  relative: number | null,
): Checkpoints[number] {
  return {
    horizon_months: horizon,
    due_on: "2026-11-16",
    change,
    benchmark_change: benchmark,
    relative_change: relative,
    benchmark_members: benchmark === null ? 0 : 2,
    companies: [],
    benchmark: [],
    settled_at: "2026-11-16T12:00:00Z",
  } as Checkpoints[number];
}

const MADE = "2026-10-16T03:30:00Z";

test("a change reads as a signed percent with one decimal", () => {
  expect(percent(0.055)).toBe("+5.5%");
  expect(percent(-0.1)).toBe("-10.0%");
  expect(percent(0)).toBe("0.0%");
  expect(percent(0.0004)).toBe("0.0%");
  expect(percent(0.016667)).toBe("+1.7%");
  expect(percent(null)).toBe("");
});

test("dates read as day, month and year, from the UTC date", () => {
  expect(shortDate("2026-11-16T03:30:00Z")).toBe("16 Nov 2026");
  expect(shortDate("2027-01-03")).toBe("3 Jan 2027");
  expect(shortDate("not a date")).toBe("not a date");
});

test("a horizon falls due that many calendar months on, a missing day becoming the last", () => {
  expect(dueDate(MADE, 1)).toBe("2026-11-16");
  expect(dueDate(MADE, 3)).toBe("2027-01-16");
  expect(dueDate(MADE, 6)).toBe("2027-04-16");
  expect(dueDate("2026-08-31T10:00:00Z", 1)).toBe("2026-09-30");
  expect(dueDate("2027-11-30T10:00:00Z", 3)).toBe("2028-02-29");
});

test("a call shows its change relative to peers where a checkpoint is reached, else when it is due", () => {
  const call = {
    made_at: MADE,
    state: "open",
    checkpoints: [checkpoint(1, 0.1, 0.05, 0.05)],
  } as Pick<Call, "checkpoints" | "state" | "made_at">;

  expect(cells(call).map((cell) => [cell.horizon, cell.text, cell.tone])).toEqual([
    [1, "+5.0%", "up"],
    [3, "due 16 Jan 2027", "due"],
    [6, "due 16 Apr 2027", "due"],
  ]);
  expect(cells(call)[0]?.detail).toBe("Own change +10.0%, peers +5.0% (2 companies).");
});

test("a call that did worse than its peers, or the same, or has none to compare, reads so", () => {
  const call = {
    made_at: MADE,
    state: "settled",
    checkpoints: [
      checkpoint(1, 0.02, 0.1, -0.08),
      checkpoint(3, 0.1, 0.1, 0),
      checkpoint(6, -0.1, null, null),
    ],
  } as Pick<Call, "checkpoints" | "state" | "made_at">;

  expect(cells(call).map((cell) => [cell.text, cell.tone])).toEqual([
    ["-8.0%", "down"],
    ["0.0%", "flat"],
    ["-10.0%", "down"],
  ]);
  expect(cells(call)[2]?.detail).toBe("Own change -10.0%; no peers priced.");
});

test("a call with no prices says it is unpriced in the places a checkpoint would be", () => {
  const call = { made_at: MADE, state: "unpriced", checkpoints: [] } as Pick<
    Call,
    "checkpoints" | "state" | "made_at"
  >;

  expect(cells(call).map((cell) => [cell.text, cell.tone])).toEqual([
    ["unpriced", "none"],
    ["unpriced", "none"],
    ["unpriced", "none"],
  ]);
});

test("the companies of a call, and the panel's opening line", () => {
  expect(
    companiesLine({
      companies: [{ display_name: "Lumentum" }, { display_name: "Coherent" }],
    } as Pick<Call, "companies">),
  ).toBe("Lumentum, Coherent");
  expect(companiesLine({ companies: [] })).toBe("no company named");
  expect(callsSummary([])).toBe("No calls yet.");
  expect(callsSummary([{ state: "settled" }, { state: "open" }, { state: "unpriced" }])).toBe(
    "3 calls: 1 read at all three dates, 2 still open.",
  );
  expect(callsSummary([{ state: "open" }])).toBe("1 call: 0 read at all three dates, 1 still open.");
});

test("a prediction's range, in the words of its bounds", () => {
  expect(expectedRange(100, 120)).toBe("100 to 120");
  expect(expectedRange(100, 120, "USD billion")).toBe("100 to 120 USD billion");
  expect(expectedRange(1.5, null)).toBe("at least 1.5");
  expect(expectedRange(null, 90, "weeks")).toBe("at most 90 weeks");
  expect(expectedRange(null, null)).toBe("");
});

test("a prediction is open or lapsed with its deadline, or settled with its value", () => {
  const base = { deadline: "2026-11-15" } as Pick<Prediction, "deadline">;
  expect(predictionStatus({ ...base, state: "open", settlement: null })).toBe(
    "Open, due 15 Nov 2026",
  );
  expect(predictionStatus({ ...base, state: "lapsed", settlement: null })).toBe(
    "Lapsed, due 15 Nov 2026",
  );
  const settlement = (outcome: "met" | "missed", late: boolean) =>
    ({ outcome, value: 110, late }) as NonNullable<Prediction["settlement"]>;
  expect(
    predictionStatus({ ...base, state: "settled", settlement: settlement("met", false) }),
  ).toBe("Met at 110");
  expect(
    predictionStatus({ ...base, state: "settled", settlement: settlement("missed", true) }),
  ).toBe("Missed at 110 (settled late)");
});
