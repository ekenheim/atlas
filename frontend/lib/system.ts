// The System index (spec §5.9): every route that is not Today, Themes, Record or Decide, each with
// one state line built from a read Atlas already makes. The link names are the old nav labels, so
// the e2e's second click needs no other change.
import type { MemoryHealth, SessionSummary } from "./api/client";
import { figures } from "./memory";
import { routes } from "./routes";

export interface SystemItem {
  key: string;
  /** The link's name. */
  label: string;
  href: string;
}

export const SYSTEM_ITEMS: readonly SystemItem[] = [
  { key: "memory", label: "Memory", href: routes.memory },
  { key: "sessions", label: "Sessions", href: routes.sessions },
  { key: "issues", label: "Issues", href: routes.issues() },
  { key: "relationships", label: "Relationships", href: routes.relationships() },
  { key: "exceptions", label: "Exceptions queue", href: routes.exceptions },
  { key: "workbench", label: "Research workbench", href: routes.workbench },
  { key: "beliefs", label: "Beliefs", href: routes.beliefs() },
  { key: "hypotheses", label: "Hypotheses", href: routes.hypotheses },
  { key: "companies", label: "Companies", href: routes.companies },
];

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count.toLocaleString("en")} ${count === 1 ? one : many}`;

/** "clean · 69% in memory": nothing open on the bank, and how much of what belongs there is. */
export function memoryState(health: MemoryHealth, now: number): string {
  const found = figures(health, now);
  const state = found.open.count === 0 ? "clean" : `${plural(found.open.count, "item")} open`;
  return found.inMemory.percent === null
    ? state
    : `${state} · ${found.inMemory.percent}% in memory`;
}

/** Runs started in the last seven days, leaving out the held-out runs of the scorecard. */
export function runsThisWeek(sessions: readonly SessionSummary[], now: Date): number {
  const since = now.getTime() - 7 * 86_400_000;
  return sessions.filter(
    (session) => !session.isolated && new Date(session.started_at).getTime() >= since,
  ).length;
}

export const runsState = (count: number) => `${plural(count, "run")} this week`;
export const openState = (count: number) => `${count.toLocaleString("en")} open`;
export const countState = (count: number) => count.toLocaleString("en");
export const inQueueState = (count: number) => `${count.toLocaleString("en")} waiting`;
