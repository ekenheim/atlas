// The pure parts of the Issues page: the research frontier in the order the API's
// `GET /issues/next` chooses (an active Issue that is not blocked and has no active Issue
// narrowing it; a `step` with no Belief first, then one flagged or disputed, then priority,
// then oldest), the filters kept in the URL, and the words for the columns.
import type { Issue } from "./api/client";

export type Tier = 0 | 1 | 2;

export const TIER_WORDS: Record<Tier, string> = {
  0: "step with no Belief",
  1: "flagged or disputed",
  2: "priority",
};

export const KINDS: Record<Issue["kind"], string> = {
  question: "Question",
  step: "Step",
  read: "Read",
};

export const STATUSES: Record<Issue["status"], string> = {
  active: "Active",
  complete: "Complete",
  abandoned: "Abandoned",
  invalid: "Invalid",
};

const ATTENTION = ["flagged", "disputed"];

/** Whether the Issue is on the frontier: active, unblocked and with no active Issue under it. */
export function onFrontier(issue: Issue): boolean {
  return issue.status === "active" && !issue.blocked && issue.open_children === 0;
}

/** The rule's tier: 0 a step no Belief was produced for, 1 flagged or disputed, 2 the rest. */
export function tier(issue: Issue): Tier {
  if (issue.kind === "step" && !issue.products.some((product) => product.belief_id !== null)) {
    return 0;
  }
  const body = issue.body.toLowerCase();
  return ATTENTION.some((word) => body.includes(word)) ? 1 : 2;
}

function byRule(a: Issue, b: Issue): number {
  return (
    tier(a) - tier(b) ||
    b.priority - a.priority ||
    a.created_at.localeCompare(b.created_at) ||
    a.id.localeCompare(b.id)
  );
}

/** Frontier Issues first, in the order the next action is chosen; the others after, oldest
 * first (blocked and parent Issues wait for what they need). */
export function orderIssues(issues: Issue[]): Issue[] {
  const frontier = issues.filter(onFrontier).sort(byRule);
  const rest = issues
    .filter((issue) => !onFrontier(issue))
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
  return [...frontier, ...rest];
}

/** The next action among the Issues given, or null when none is on the frontier. */
export function nextAction(issues: Issue[]): Issue | null {
  return issues.filter(onFrontier).sort(byRule)[0] ?? null;
}

export interface IssueFilters {
  theme: string;
  status: Issue["status"] | "all";
}

export const DEFAULT_FILTERS: IssueFilters = { theme: "", status: "active" };

/** The filters in a page's query string; anything unknown falls back to the default. */
export function parseFilters(search: URLSearchParams): IssueFilters {
  const status = search.get("status");
  return {
    theme: search.get("theme") ?? DEFAULT_FILTERS.theme,
    status:
      status === "all" || (status !== null && status in STATUSES)
        ? (status as IssueFilters["status"])
        : DEFAULT_FILTERS.status,
  };
}

/** The filters as a query string, leaving out the defaults. */
export function filterSearch(filters: IssueFilters): string {
  const search = new URLSearchParams();
  if (filters.theme) search.set("theme", filters.theme);
  if (filters.status !== DEFAULT_FILTERS.status) search.set("status", filters.status);
  return search.toString();
}

export function applyFilters(issues: Issue[], filters: IssueFilters): Issue[] {
  return issues.filter(
    (issue) =>
      (filters.theme === "" || issue.theme === filters.theme) &&
      (filters.status === "all" || issue.status === filters.status),
  );
}

/** "1 Belief, 2 Facts", or an empty string when nothing was produced. */
export function producedText(issue: Issue): string {
  const beliefs = issue.products.filter((product) => product.belief_id !== null).length;
  const facts = issue.products.length - beliefs;
  const part = (count: number, noun: string) =>
    count === 0 ? [] : [`${count} ${noun}${count === 1 ? "" : "s"}`];
  return [...part(beliefs, "Belief"), ...part(facts, "Fact")].join(", ");
}
