// The prospective record (Record page): what Atlas said, dated, and what followed. Figures, the
// sentence that explains an empty scoreboard, and a call's cells. Closes score a call after the
// fact; they are never evidence.
import type { Call, Prediction } from "./api/client";
import { dueDate, percent } from "./calls";
import { evidenceDay, plainDay } from "./format";
import { UNPRICED_REASONS } from "./status";

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

export interface RecordFigures {
  open: number;
  checkpoints: number;
  /** At +3 months: how many calls with a checkpoint are ahead of the benchmark, of how many. */
  ahead: { count: number; of: number } | null;
  /** The day the first +3 month checkpoint falls, while none has. */
  aheadUntil: string | null;
  predictions: { open: number; met: number; missed: number };
}

export function recordFigures(
  calls: readonly Call[],
  predictions: readonly Prediction[],
): RecordFigures {
  const checkpoints = calls.reduce((sum, call) => sum + call.checkpoints.length, 0);
  const atThree = calls.flatMap((call) =>
    call.checkpoints.filter((each) => each.horizon_months === 3),
  );
  const measured = atThree.filter((each) => (each.relative_change ?? each.change) !== null);
  const dueThree = calls
    .filter((call) => !call.checkpoints.some((each) => each.horizon_months === 3))
    .map((call) => dueDate(call.made_at, 3))
    .sort();
  return {
    open: calls.filter((call) => call.state === "open").length,
    checkpoints,
    ahead:
      measured.length > 0
        ? {
            count: measured.filter((each) => (each.relative_change ?? each.change) > 0).length,
            of: measured.length,
          }
        : null,
    aheadUntil: dueThree[0] ?? null,
    predictions: {
      open: predictions.filter((each) => each.state === "open").length,
      met: predictions.filter((each) => each.settlement?.outcome === "met").length,
      missed: predictions.filter((each) => each.settlement?.outcome === "missed").length,
    },
  };
}

export interface HorizonHit {
  horizon: 1 | 3 | 6;
  /** Calls with a checkpoint at this horizon. */
  checkpointed: number;
  /** Of those, the calls ahead of the benchmark. */
  ahead: number;
  text: string;
}

/** Per horizon: how many of the calls checkpointed there are ahead of the benchmark ("+1 m: 14 of
 * 22 ahead of the benchmark"), or "no checkpoint yet". A call with no peers priced is read by its
 * own change. */
export function horizonHits(calls: readonly Call[]): HorizonHit[] {
  return ([1, 3, 6] as const).map((horizon) => {
    const points = calls.flatMap((call) =>
      call.checkpoints.filter((each) => each.horizon_months === horizon),
    );
    const ahead = points.filter((each) => (each.relative_change ?? each.change) > 0).length;
    return {
      horizon,
      checkpointed: points.length,
      ahead,
      text:
        points.length === 0
          ? `+${horizon} m: no checkpoint yet`
          : `+${horizon} m: ${ahead} of ${points.length} ahead of the benchmark`,
    };
  });
}

/** While no checkpoint exists: the day the first falls and what it will do. */
export function firstCheckpointSentence(
  calls: readonly Call[],
  now: Date,
): string | null {
  if (calls.some((call) => call.checkpoints.length > 0)) return null;
  const pending = calls.filter((call) => call.state === "open" && call.next_due !== null);
  if (pending.length === 0) return null;
  const first = pending
    .map((call) => (call.next_due?.due_on ?? "").slice(0, 10))
    .sort()[0] as string;
  return `First checkpoint ${plainDay(first, now)}: ${plural(pending.length, "call")} priced against their theme's companies.`;
}

export interface CallCells {
  /** One cell until the call has a checkpoint: when the first falls, or why it is not priced. */
  first: string;
  /** After: the change relative to the benchmark at +1, +3 and +6 months. */
  horizons: { horizon: 1 | 3 | 6; text: string; tone: "up" | "down" | "flat" | "none" }[];
}

/** A call's cells: "first checkpoint 18 Nov" until it has one; after, each horizon's change
 * relative to the benchmark with ↑ or ↓. */
export function callCells(call: Call, now: Date): CallCells {
  const first =
    call.state === "unpriced"
      ? `not priced: ${call.unpriced_reason ? UNPRICED_REASONS[call.unpriced_reason] : "no price"}`
      : call.next_due
        ? `first checkpoint ${plainDay(call.next_due.due_on, now)}`
        : "";
  return {
    first,
    horizons: ([1, 3, 6] as const).map((horizon) => {
      const point = call.checkpoints.find((each) => each.horizon_months === horizon);
      if (!point) return { horizon, text: "", tone: "none" as const };
      const shown = point.relative_change ?? point.change;
      const arrow = shown > 0 ? "↑ " : shown < 0 ? "↓ " : "";
      return {
        horizon,
        text: `${arrow}${percent(shown)}`,
        tone: shown > 0 ? ("up" as const) : shown < 0 ? ("down" as const) : ("flat" as const),
      };
    }),
  };
}

/** The calls grouped by theme, in the order the themes are first met (newest call first). */
export function callsByTheme(calls: readonly Call[]): { theme: string; calls: Call[] }[] {
  const groups = new Map<string, Call[]>();
  for (const call of [...calls].sort((a, b) => b.made_at.localeCompare(a.made_at))) {
    groups.set(call.theme, [...(groups.get(call.theme) ?? []), call]);
  }
  return [...groups.entries()].map(([theme, mine]) => ({ theme, calls: mine }));
}

/** A call dated by when Atlas said it. */
export const calledOn = (call: Pick<Call, "made_at">) => evidenceDay(call.made_at);
