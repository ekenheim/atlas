// The prospective record's pure parts (atlas-beliefs ticket 19): how a call's checkpoints and a
// prediction's range read on the theme page and the Hypothesis dossier. A record of what Atlas
// said and what followed, in few words; nothing here advises.
import type { Call, Prediction } from "./api/client";
import { evidenceDay } from "./format";

export const HORIZONS = [1, 3, 6] as const;
export type Horizon = (typeof HORIZONS)[number];

export const ORIGINS: Record<Call["origin"], string> = {
  belief: "Belief",
  hypothesis: "Hypothesis",
  signal: "Archive lead",
};

export const DIRECTIONS: Record<NonNullable<Call["direction"]>, string> = {
  tightening: "tightening",
  easing: "easing",
};

/** "+5.5%" / "-10.0%" / "0.0%": a fraction as the signed percent it is, one decimal. */
export function percent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return "";
  const value = Math.round(fraction * 1000) / 10;
  if (value === 0) return "0.0%";
  return `${value > 0 ? "+" : "-"}${Math.abs(value).toFixed(1)}%`;
}

export type Tone = "up" | "down" | "flat" | "due" | "none";

/** One horizon's cell of the calls table. */
export type Cell = {
  horizon: Horizon;
  /** What the cell says: the change relative to peers, "due <date>", "unpriced" or empty. */
  text: string;
  tone: Tone;
  /** The longer reading, for a tooltip: the call's companies' change and the peers'. */
  detail: string;
};

/**
 * The cells of a call, +1, +3 and +6 months. A reached checkpoint shows the call companies'
 * change relative to the theme's equal-weighted universe (without peers, their own change); a
 * horizon not reached shows when it falls due, or that the call is unpriced.
 */
export function cells(call: Pick<Call, "checkpoints" | "state" | "made_at">): Cell[] {
  return HORIZONS.map((horizon): Cell => {
    const checkpoint = call.checkpoints.find((each) => each.horizon_months === horizon);
    if (checkpoint) {
      const relative = checkpoint.relative_change;
      const shown = relative ?? checkpoint.change;
      const detail =
        relative === null
          ? `Own change ${percent(checkpoint.change)}; no peers priced.`
          : `Own change ${percent(checkpoint.change)}, peers ${percent(checkpoint.benchmark_change)}` +
            ` (${checkpoint.benchmark_members} companies).`;
      return {
        horizon,
        text: percent(shown),
        tone: shown > 0 ? "up" : shown < 0 ? "down" : "flat",
        detail,
      };
    }
    if (call.state === "unpriced") {
      return { horizon, text: "unpriced", tone: "none", detail: "No closes to read this against." };
    }
    return { horizon, text: `due ${evidenceDay(dueDate(call.made_at, horizon))}`, tone: "due", detail: "" };
  });
}

/** The day a horizon falls due: the call's UTC date plus whole calendar months (a day the month
 * lacks becomes its last), as the server does. */
export function dueDate(madeAt: string, months: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(madeAt);
  if (!match) return madeAt;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  const index = year * 12 + month + months;
  const dueYear = Math.floor(index / 12);
  const dueMonth = index % 12;
  const last = new Date(Date.UTC(dueYear, dueMonth + 1, 0)).getUTCDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${dueYear}-${pad(dueMonth + 1)}-${pad(Math.min(day, last))}`;
}

/** The companies of a call, by name, with their symbol when they have one. */
export function companiesLine(call: Pick<Call, "companies">): string {
  return call.companies.length === 0
    ? "no company named"
    : call.companies.map((each) => each.display_name).join(", ");
}

/** The counts the panel opens with: calls made, and how many have all three checkpoints. */
export function callsSummary(calls: readonly Pick<Call, "state">[]): string {
  if (calls.length === 0) return "No calls yet.";
  const settled = calls.filter((each) => each.state === "settled").length;
  const open = calls.length - settled;
  return `${calls.length} ${calls.length === 1 ? "call" : "calls"}: ${settled} read at all three dates, ${open} still open.`;
}

// --- predictions ---------------------------------------------------------------------------

export const SOURCES: Record<Prediction["source_kind"], string> = {
  fact: "a Fact",
  financial_observation: "an XBRL figure",
  price: "a close",
};

function number(value: number): string {
  return String(value);
}

/** The range a prediction expects: "100 to 120", "at least 100", "at most 120", with its unit. */
export function expectedRange(
  low: number | null | undefined,
  high: number | null | undefined,
  unit?: string | null,
): string {
  const suffix = unit ? ` ${unit}` : "";
  if (low !== null && low !== undefined && high !== null && high !== undefined) {
    return `${number(low)} to ${number(high)}${suffix}`;
  }
  if (low !== null && low !== undefined) return `at least ${number(low)}${suffix}`;
  if (high !== null && high !== undefined) return `at most ${number(high)}${suffix}`;
  return "";
}

/** What a prediction's state and settlement say, in few words. */
export function predictionStatus(
  prediction: Pick<Prediction, "state" | "settlement" | "deadline">,
): string {
  const settlement = prediction.settlement;
  if (settlement) {
    const outcome = settlement.outcome === "met" ? "Met" : "Missed";
    return `${outcome} at ${number(settlement.value)}${settlement.late ? " (settled late)" : ""}`;
  }
  return prediction.state === "lapsed"
    ? `Lapsed, due ${evidenceDay(prediction.deadline)}`
    : `Open, due ${evidenceDay(prediction.deadline)}`;
}
