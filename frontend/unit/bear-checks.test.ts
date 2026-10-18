import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import type { BearCheck, BearChecks } from "../lib/api/client";
import {
  BEAR_ORDER,
  bearConcepts,
  bearFigures,
  bearFilings,
  bearLabel,
  bearQuotes,
  bearSummary,
  bearValue,
  bearWord,
  money,
  orderedChecks,
  unknownText,
} from "../lib/bear-checks";

// Real answers of `GET /companies/{id}/bear-checks` (0.6.18), computed over the e2e seed:
// Lumentum from the recorded EDGAR fixtures, and a company Atlas holds nothing of.
const read = (name: string) =>
  JSON.parse(readFileSync(join(__dirname, "fixtures", name), "utf-8")) as BearChecks;
const LUMENTUM = read("bear-checks-lumentum.json");
const EMPTY = read("bear-checks-empty.json");
const NOW = new Date("2026-10-18T12:00:00Z");

const byKey = (answer: BearChecks, key: BearCheck["key"]) => {
  const found = answer.checks.find((each) => each.key === key);
  if (!found) throw new Error(`no ${key}`);
  return found;
};

test("Lumentum: six rows in the fixed order, the counts adding up to six", () => {
  expect(orderedChecks([...LUMENTUM.checks].reverse()).map((each) => each.key)).toEqual([...BEAR_ORDER]);
  expect(orderedChecks(LUMENTUM.checks).map(bearLabel)).toEqual([
    "Share count growth",
    "Shelf or offering filings",
    "Gross margin, last four quarters",
    "Largest customer",
    "Going-concern warning",
    "Net cash or debt",
  ]);
  expect(bearSummary(LUMENTUM)).toBe("2 flags · 2 clear · 2 unknown");
  expect(bearSummary(EMPTY)).toBe("6 unknown");
});

test("each row's value reads from its own typed value", () => {
  expect(bearValue(byKey(LUMENTUM, "dilution"), NOW)).toBe("+28% in a year");
  expect(bearValue(byKey(LUMENTUM, "customer_concentration"), NOW)).toBe("26.6% of revenue");
  expect(bearValue(byKey(LUMENTUM, "going_concern"), NOW)).toBe("none in the 10-K");
  expect(bearValue(byKey(LUMENTUM, "net_cash"), NOW)).toBe("net cash $406.1M");
  expect(bearValue(byKey(LUMENTUM, "shelf_or_atm"), NOW)).toBe("");
  expect(bearWord(byKey(LUMENTUM, "dilution"))).toEqual({ word: "Flag", tone: "warn" });
  expect(bearWord(byKey(LUMENTUM, "net_cash"))).toBeNull();
  expect(bearWord(byKey(LUMENTUM, "shelf_or_atm"))).toEqual({ word: "Unknown", tone: "muted" });
});

test("an unknown check says why in the owner's words", () => {
  expect(unknownText(byKey(LUMENTUM, "shelf_or_atm"))).toBe("not in the filings Atlas collects");
  expect(unknownText(byKey(LUMENTUM, "gaap_gross_margin"))).toBe("nothing a year earlier to compare");
  expect(unknownText(byKey(EMPTY, "net_cash"))).toBe("not in the company's financial data");
});

test("the hand-made values: shelf filings, margin moves, a lower bound, none above, net debt, a flag", () => {
  const shelf = {
    key: "shelf_or_atm",
    status: "flag",
    unknown_reason: null,
    summary: "",
    basis: "",
    sources: [],
    value: {
      filings: [
        { form: "S-3", available_at: "2026-01-10T12:00:00Z", source_version_id: "a", title: "S-3" },
        { form: "424B5", available_at: "2026-03-04T12:00:00Z", source_version_id: "b", title: "424B5" },
      ],
    },
  } as BearCheck;
  expect(bearValue(shelf, NOW)).toBe("2 filings · S-3, 424B5 · latest 4 Mar");
  expect(bearFigures(shelf).map((each) => [each.label, each.href])).toEqual([
    ["S-3 · 10 Jan 2026", "/version/?id=a"],
    ["424B5 · 4 Mar 2026", "/version/?id=b"],
  ]);
  const margin = (change: number | null) =>
    ({
      key: "gaap_gross_margin",
      status: change === null ? "flag" : "clear",
      unknown_reason: null,
      summary: "",
      basis: "",
      sources: [],
      value: { unit: "USD", ttm_margin_pct: 41.2, prior_ttm_margin_pct: 47.3, change_points: change, quarters: [] },
    }) as BearCheck;
  expect(bearValue(margin(-6.1), NOW)).toBe("41% · down 6 pts");
  expect(bearValue(margin(2.2), NOW)).toBe("41% · up 2 pts");
  expect(bearValue(margin(0.2), NOW)).toBe("41% · flat");
  expect(bearValue(margin(null), NOW)).toBe("41%");
  const concentration = (current: number | null, lower: boolean, none: number[]) =>
    ({
      key: "customer_concentration",
      status: "clear",
      unknown_reason: null,
      summary: "",
      basis: "",
      sources: [],
      value: {
        document: { source_version_id: "d", form: "10-K" },
        current_percent: current,
        matches:
          current === null
            ? []
            : [{ percents: [current], current_percent: current, lower_bound: lower, char_start: 1, char_end: 9, quote: "q" }],
        top_customers_share: [],
        no_customer_above: none,
      },
    }) as BearCheck;
  expect(bearValue(concentration(38, true, []), NOW)).toBe("more than 38%");
  expect(bearValue(concentration(null, false, [10]), NOW)).toBe("none above 10%");
  const debt = {
    key: "net_cash",
    status: "flag",
    unknown_reason: null,
    summary: "",
    basis: "",
    sources: [],
    value: {
      unit: "EUR",
      as_of_balance_sheet: "2026-06-30",
      net_cash: -1_200_000_000,
      cash: 300_000_000,
      short_term_investments: 50_000_000,
      debt: 1_550_000_000,
      debt_concepts: ["Borrowings"],
    },
  } as BearCheck;
  expect(bearValue(debt, NOW)).toBe("net debt €1.2B");
  expect(bearFigures(debt)).toEqual([
    { label: "Cash, 30 Jun 2026", value: "€300M" },
    { label: "Short-term investments", value: "€50M" },
    { label: "Debt", value: "€1.6B" },
  ]);
  expect(bearConcepts(debt)).toEqual(["Borrowings"]);
  const flagged = { ...byKey(LUMENTUM, "going_concern"), status: "flag" } as BearCheck;
  expect(bearValue(flagged, NOW)).toBe("in the 10-K");
  expect(bearValue({ ...byKey(LUMENTUM, "net_cash"), value: null } as BearCheck, NOW)).toBe("—");
});

test("money: currency symbols, other units after the number, B/M/K", () => {
  expect(money(412_000_000, "USD")).toBe("$412M");
  expect(money(1_234_000_000, "GBP")).toBe("£1.2B");
  expect(money(412_000_000, "CHF")).toBe("412M CHF");
  expect(money(5_500, "JPY")).toBe("¥5.5K");
  expect(money(950, "USD")).toBe("$950");
  expect(money(-3_000_000, "USD")).toBe("−$3M");
});

test("the open row: figures with days, the quoted row at its span, the filing a clear check read", () => {
  expect(bearFigures(byKey(LUMENTUM, "dilution"))).toEqual([
    { label: "Shares, 14 Aug 2026", value: "89,700,000" },
    { label: "A year earlier, 12 Aug 2025", value: "69,900,000" },
  ]);
  const quotes = bearQuotes(byKey(LUMENTUM, "customer_concentration"));
  expect(quotes).toHaveLength(1);
  expect(quotes[0]?.href).toMatch(/^\/version\/\?id=[0-9a-f-]+&from=27835&to=27866&parse=text-v3$/);
  expect(quotes[0]?.form).toBe("10-K");
  expect(bearFilings(byKey(LUMENTUM, "customer_concentration"))).toEqual([]);
  expect(bearFilings(byKey(LUMENTUM, "going_concern"))).toEqual([
    { href: "/version/?id=ff625442-57a2-4c86-8c30-73cad5de112f", form: "10-K" },
  ]);
  // Observations render nothing in the open row: the figures show them.
  expect(bearFilings(byKey(LUMENTUM, "net_cash"))).toEqual([]);
  expect(bearConcepts(byKey(LUMENTUM, "net_cash"))).toContain("us-gaap:CashAndCashEquivalentsAtCarryingValue");
});

test("no row's surface text carries an ISO date, a concept name or a code", () => {
  for (const check of [...LUMENTUM.checks, ...EMPTY.checks]) {
    const surface = [
      bearLabel(check),
      bearValue(check, NOW),
      check.status === "unknown" ? unknownText(check) : "",
      check.summary,
      ...bearFigures(check).map((each) => `${each.label} ${each.value}`),
    ].join(" ");
    expect(surface).not.toMatch(/\d{4}-\d{2}-\d{2}|us-gaap|dei:|_/);
  }
});

test("a key this page does not know is its slug in words, with a warning", () => {
  const warned: string[] = [];
  const original = console.warn;
  console.warn = (message: string) => warned.push(message);
  try {
    expect(bearLabel({ key: "insider_selling" as BearCheck["key"] })).toBe("Insider selling");
  } finally {
    console.warn = original;
  }
  expect(warned).toHaveLength(1);
});
