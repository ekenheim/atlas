// What is coming due (Today, Theme, Hypothesis, Record): calls grouped by the day their next
// checkpoint falls, predictions by deadline, and, when TradingView's calendar gave any, the
// reporting dates. One row per day and kind, soonest first; each row says what falls due.
import type { Call, Lead, Prediction } from "./api/client";
import { isoDay } from "./format";
import { routes } from "./routes";

export type DueKind = "calls" | "predictions" | "earnings";

export interface DueRow {
  key: string;
  /** The day it falls due, ISO. */
  date: string;
  kind: DueKind;
  /** What falls due, after the date: "first checkpoint · 22 calls". */
  label: string;
  /** The longer reading, for a tooltip (a prediction's whole measure). */
  title?: string;
  href: string | null;
}

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

const CHECKPOINT: Record<number, string> = {
  1: "first checkpoint",
  3: "3-month checkpoint",
  6: "6-month checkpoint",
};

/** The first clause of a measure: up to the first comma, semicolon, bracket or full stop, kept
 * to `max` characters at a word. "AXT total revenue for Q3 2026 (quarter ended ...), from..." →
 * "AXT total revenue for Q3 2026". */
export function firstClause(measure: string, max = 64): string {
  const cut = measure.search(/\s\(|[,;]|\.\s|\.$/);
  const clause = (cut > 0 ? measure.slice(0, cut) : measure).trim();
  if (clause.length <= max) return clause;
  const short = clause.slice(0, max);
  const space = short.lastIndexOf(" ");
  return `${(space > max / 2 ? short.slice(0, space) : short).trimEnd()}…`;
}

const SCALES: readonly [number, string][] = [
  [1e9, "B"],
  [1e6, "M"],
];

function trim(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/** USD amounts in millions or billions; null for any other unit. */
function dollars(value: number, unit: string): { amount: number; suffix: string } | null {
  const lower = unit.toLowerCase();
  if (lower === "usd") {
    for (const [scale, suffix] of SCALES) {
      if (Math.abs(value) >= scale) return { amount: value / scale, suffix };
    }
    return { amount: value, suffix: "" };
  }
  if (lower === "usd million") return { amount: value, suffix: "M" };
  if (lower === "usd billion") return { amount: value, suffix: "B" };
  return null;
}

/** The range a prediction expects, short: "$66–70M", "≥ $66M", "≤ 120", "100–120 units". */
export function rangeText(
  low: number | null | undefined,
  high: number | null | undefined,
  unit?: string | null,
): string {
  const lo = low ?? null;
  const hi = high ?? null;
  if (lo === null && hi === null) return "";
  const a = unit && lo !== null ? dollars(lo, unit) : null;
  const b = unit && hi !== null ? dollars(hi, unit) : null;
  if ((lo === null || a !== null) && (hi === null || b !== null)) {
    if (a && b) {
      // A shared suffix once: $66–70M. Different suffixes keep their own.
      return a.suffix === b.suffix
        ? `$${trim(a.amount)}–${trim(b.amount)}${a.suffix}`
        : `$${trim(a.amount)}${a.suffix}–$${trim(b.amount)}${b.suffix}`;
    }
    if (a) return `≥ $${trim(a.amount)}${a.suffix}`;
    if (b) return `≤ $${trim(b.amount)}${b.suffix}`;
  }
  const tail = unit ? ` ${unit}` : "";
  if (lo !== null && hi !== null) return `${trim(lo)}–${trim(hi)}${tail}`;
  return lo !== null ? `≥ ${trim(lo)}${tail}` : `≤ ${trim(hi as number)}${tail}`;
}

/** The open calls grouped by the day (and horizon) of their next checkpoint. */
function callRows(calls: readonly Call[], theme: string | null): DueRow[] {
  const groups = new Map<string, { date: string; horizon: number; count: number }>();
  for (const call of calls) {
    if (call.state === "settled" || call.next_due === null) continue;
    const date = isoDay(call.next_due.due_on);
    const key = `${date}:${call.next_due.horizon_months}`;
    const found = groups.get(key);
    if (found) found.count += 1;
    else groups.set(key, { date, horizon: call.next_due.horizon_months, count: 1 });
  }
  return [...groups.entries()].map(([key, group]) => ({
    key: `calls:${key}`,
    date: group.date,
    kind: "calls" as const,
    label: `${CHECKPOINT[group.horizon] ?? `${group.horizon}-month checkpoint`} · ${plural(group.count, "call")}`,
    href: theme ? routes.recordFor(theme) : routes.record,
  }));
}

/** Predictions that have not been settled, grouped by deadline; the first one's measure and range. */
function predictionRows(predictions: readonly Prediction[]): DueRow[] {
  const groups = new Map<string, Prediction[]>();
  for (const prediction of predictions) {
    if (prediction.state !== "open") continue;
    const date = isoDay(prediction.deadline);
    groups.set(date, [...(groups.get(date) ?? []), prediction]);
  }
  return [...groups.entries()].map(([date, mine]) => {
    const first = mine[0] as Prediction;
    const range = rangeText(first.expected_low, first.expected_high, first.unit);
    return {
      key: `predictions:${date}`,
      date,
      kind: "predictions" as const,
      label: [plural(mine.length, "prediction"), firstClause(first.measure), range]
        .filter((part) => part !== "")
        .join(" · "),
      title: first.measure,
      href: routes.hypothesis(first.hypothesis_id),
    };
  });
}

/** Reporting dates still to come, from the calendar's leads (none: no rows). */
function earningsRows(leads: readonly Lead[], today: string): DueRow[] {
  return leads
    .filter((lead) => lead.calendar && isoDay(lead.calendar.event_at) >= today)
    .map((lead) => {
      const calendar = lead.calendar as NonNullable<Lead["calendar"]>;
      const date = isoDay(calendar.event_at);
      return {
        key: `earnings:${calendar.event_key}`,
        date,
        kind: "earnings" as const,
        label: `${calendar.symbol} reports${calendar.status === "confirmed" ? "" : " (expected)"}`,
        href: null,
      };
    });
}

const KIND_ORDER: Record<DueKind, number> = { earnings: 0, calls: 1, predictions: 2 };

/** The rows, soonest first, at most `limit` (all when it is 0). */
export function dueRows(input: {
  calls?: readonly Call[];
  predictions?: readonly Prediction[];
  leads?: readonly Lead[];
  theme?: string | null;
  today: string;
}): DueRow[] {
  return [
    ...callRows(input.calls ?? [], input.theme ?? null),
    ...predictionRows(input.predictions ?? []),
    ...earningsRows(input.leads ?? [], input.today),
  ].sort((a, b) => a.date.localeCompare(b.date) || KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
}
