import { expect, test } from "@playwright/test";

import type { Call, Lead, Prediction } from "../lib/api/client";
import { dueRows, firstClause, rangeText } from "../lib/due";

const TODAY = "2026-10-18";

function call(over: Partial<Call>): Call {
  return {
    id: "c",
    origin: "belief",
    origin_id: "b",
    lead_id: null,
    theme: "photonics",
    claim: "x",
    direction: null,
    made_at: "2026-10-18T10:44:08Z",
    state: "open",
    unpriced_reason: null,
    companies: [],
    checkpoints: [],
    next_due: { horizon_months: 1, due_on: "2026-11-18" },
    note: "",
    ...over,
  };
}

function prediction(over: Partial<Prediction>): Prediction {
  return {
    id: "p",
    hypothesis_id: "h1",
    hypothesis_status: "reviewed",
    theme: "photonics",
    version: 2,
    version_published_at: "2026-10-18T10:44:08Z",
    prediction_index: null,
    measure:
      "AXT total revenue for Q3 2026 (quarter ended 2026-09-30), from its 10-Q. AXT guided about $66 million.",
    unit: "USD",
    expected_low: 66_000_000,
    expected_high: null,
    deadline: "2026-11-30",
    source_kind: "financial_observation",
    company_id: null,
    state: "open",
    settlement: null,
    actor: "owner",
    recorded_at: "2026-10-18T11:04:17Z",
    ...over,
  };
}

test("calls fall due together: one row for the day and the horizon, with their count", () => {
  const calls = [call({ id: "1" }), call({ id: "2" }), call({ id: "3" })];
  expect(dueRows({ calls, today: TODAY })).toEqual([
    {
      key: "calls:2026-11-18:1",
      date: "2026-11-18",
      kind: "calls",
      label: "first checkpoint · 3 calls",
      href: "/record/",
    },
  ]);
});

test("a theme's rows link to that theme's record, and a settled call is not due", () => {
  const rows = dueRows({
    calls: [call({}), call({ state: "settled", next_due: null })],
    theme: "photonics",
    today: TODAY,
  });
  expect(rows).toHaveLength(1);
  expect(rows[0]?.label).toBe("first checkpoint · 1 call");
  expect(rows[0]?.href).toBe("/record/?theme=photonics");
});

test("predictions are grouped by deadline with the first one's measure and range", () => {
  const rows = dueRows({
    predictions: [
      prediction({ id: "a" }),
      prediction({ id: "b", measure: "Another measure, longer" }),
      prediction({ id: "c", state: "settled" }),
      prediction({ id: "d", deadline: "2026-12-31" }),
    ],
    today: TODAY,
  });
  expect(rows.map((row) => [row.date, row.label])).toEqual([
    ["2026-11-30", "2 predictions · AXT total revenue for Q3 2026 · ≥ $66M"],
    ["2026-12-31", "1 prediction · AXT total revenue for Q3 2026 · ≥ $66M"],
  ]);
  expect(rows[0]?.title).toContain("AXT guided");
  expect(rows[0]?.href).toBe("/hypothesis/?id=h1");
});

test("rows are soonest first, whatever their kind", () => {
  const rows = dueRows({
    calls: [call({})],
    predictions: [prediction({ deadline: "2026-11-10" })],
    today: TODAY,
  });
  expect(rows.map((row) => row.kind)).toEqual(["predictions", "calls"]);
});

test("earnings rows appear only when the calendar gave any, and not for a past date", () => {
  const lead = (event_at: string, status: string) =>
    ({
      calendar: { symbol: "NASDAQ:LITE", event_key: `k${event_at}`, event_at, status },
    }) as unknown as Lead;
  expect(dueRows({ today: TODAY })).toEqual([]);
  const rows = dueRows({
    leads: [lead("2026-11-04T21:00:00Z", "confirmed"), lead("2026-09-01T21:00:00Z", "reported")],
    today: TODAY,
  });
  expect(rows).toHaveLength(1);
  expect(rows[0]?.label).toBe("NASDAQ:LITE reports");
});

test("a measure is shown to its first clause", () => {
  expect(firstClause("AXT total revenue for Q3 2026 (quarter ended 2026-09-30), from its 10-Q.")).toBe(
    "AXT total revenue for Q3 2026",
  );
  expect(firstClause("Revenue of $22.5 million, as reported")).toBe("Revenue of $22.5 million");
  expect(firstClause("Short")).toBe("Short");
  const long = `${"word ".repeat(40)}end`;
  const clause = firstClause(long, 30);
  expect(clause.length).toBeLessThanOrEqual(31);
  expect(clause.endsWith("…")).toBe(true);
});

test("a range reads as money when the unit is dollars, else as numbers with the unit", () => {
  expect(rangeText(66_000_000, 70_000_000, "USD")).toBe("$66–70M");
  expect(rangeText(66_000_000, null, "USD")).toBe("≥ $66M");
  expect(rangeText(null, 1_200_000_000, "USD")).toBe("≤ $1.2B");
  expect(rangeText(30.7, null, "USD million")).toBe("≥ $30.7M");
  expect(rangeText(100, 120, "units")).toBe("100–120 units");
  expect(rangeText(100, null, null)).toBe("≥ 100");
  expect(rangeText(null, null, "USD")).toBe("");
});
