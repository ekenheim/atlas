// The pure parts of the Beliefs pages: the vocabulary, the filters kept in the page's query
// string (so a filtered list can be reloaded, bookmarked and linked), the grouping of a theme's
// Beliefs by argument step and the reading of a Belief's citations.
import type { Belief, BeliefSummary } from "./api/client";

export type Step = BeliefSummary["step"];
export type JudgementName = BeliefSummary["judgement"]["judgement"];
export type FlagKind = Belief["flags"][number]["kind"];
export type BeliefStatus = BeliefSummary["status"];
type Citation = Belief["citations"][number];

/** The argument's steps in the order the argument runs. */
export const STEPS: Record<Step, string> = {
  constraint: "Constraint",
  demand_vs_supply: "Demand against supply",
  relief: "Relief",
  control: "Control",
  capture: "Capture",
  invalidation: "What would invalidate it",
};

/** Judgements in the order a reader meets them: what stands first, what fell last. */
export const JUDGEMENTS: Record<JudgementName, string> = {
  proven: "Proven",
  unproven: "Unproven",
  undecidable: "Undecidable",
  disproven: "Disproven",
};

export const STATUSES: Record<BeliefStatus, string> = {
  active: "Active",
  superseded: "Superseded",
  withdrawn: "Withdrawn",
};

export const FLAGS: Record<FlagKind, string> = {
  counterevidence_stands: "A load-bearing citation against it stands",
  source_revised: "A cited document was revised and no longer holds the quote",
  assertion_reviewed: "A cited statement was disputed or rejected",
  fact_superseded: "A cited Fact was superseded",
};

/** The pill's colour class: proven green, disproven amber, the rest grey. */
export function judgementTone(judgement: JudgementName): string {
  switch (judgement) {
    case "proven":
      return "reader-supported";
    case "disproven":
      return "reader-disputed";
    default:
      return "reader-unknown";
  }
}

/** A confidence between 0 and 1 as a whole percentage. */
export function confidenceText(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/** Whether a Belief shows a doubt a reader should see first. */
export function isFlagged(belief: Pick<BeliefSummary, "open_flags">): boolean {
  return belief.open_flags > 0;
}

// --- the list's filters, in the URL ---------------------------------------------------------

export interface ListState {
  theme: string | null;
  step: Step | null;
  judgement: JudgementName | null;
  status: BeliefStatus | null;
  flagged: boolean;
  companyId: string | null;
}

export const DEFAULT_STATE: ListState = {
  theme: null,
  step: null,
  judgement: null,
  status: null,
  flagged: false,
  companyId: null,
};

const oneOf = <T extends string>(
  allowed: Record<T, string>,
  value: string | null,
): T | null =>
  value !== null && Object.hasOwn(allowed, value) ? (value as T) : null;

/** The filters a query string holds; a value the page does not know is ignored. */
export function parseListState(search: URLSearchParams): ListState {
  return {
    theme: search.get("theme") || null,
    step: oneOf(STEPS, search.get("step")),
    judgement: oneOf(JUDGEMENTS, search.get("judgement")),
    status: oneOf(STATUSES, search.get("status")),
    flagged: search.get("flagged") === "true",
    companyId: search.get("company") || null,
  };
}

/** The query string for a state (no leading `?`); defaults are left out. */
export function listSearch(state: ListState): string {
  const params = new URLSearchParams();
  if (state.theme) params.set("theme", state.theme);
  if (state.step) params.set("step", state.step);
  if (state.judgement) params.set("judgement", state.judgement);
  if (state.status) params.set("status", state.status);
  if (state.flagged) params.set("flagged", "true");
  if (state.companyId) params.set("company", state.companyId);
  return params.toString();
}

/** The API's query for a state: a Belief list shows the active ones unless asked otherwise. */
export function apiQuery(state: ListState) {
  return {
    ...(state.theme ? { theme: state.theme } : {}),
    ...(state.step ? { step: state.step } : {}),
    ...(state.judgement ? { judgement: state.judgement } : {}),
    status: state.status ?? ("active" as const),
    ...(state.flagged ? { flagged: true } : {}),
    ...(state.companyId ? { company_id: state.companyId } : {}),
  };
}

/** What the filters leave in, in words (empty when nothing narrows the list). */
export function filterSummary(state: ListState): string {
  const parts: string[] = [];
  if (state.step) parts.push(STEPS[state.step].toLowerCase());
  if (state.judgement) parts.push(JUDGEMENTS[state.judgement].toLowerCase());
  if (state.status) parts.push(STATUSES[state.status].toLowerCase());
  if (state.flagged) parts.push("flagged");
  return parts.length === 0 ? "" : ` (${parts.join(", ")})`;
}

// --- grouping -------------------------------------------------------------------------------

const JUDGEMENT_RANK: Record<JudgementName, number> = {
  proven: 0,
  unproven: 1,
  undecidable: 2,
  disproven: 3,
};

/** Flagged first, then by judgement (proven first), then by confidence, then newest. */
export function byStanding(a: BeliefSummary, b: BeliefSummary): number {
  return (
    Number(isFlagged(b)) - Number(isFlagged(a)) ||
    JUDGEMENT_RANK[a.judgement.judgement] -
      JUDGEMENT_RANK[b.judgement.judgement] ||
    b.judgement.confidence - a.judgement.confidence ||
    b.created_at.localeCompare(a.created_at)
  );
}

export interface StepGroup {
  step: Step;
  title: string;
  beliefs: BeliefSummary[];
}

/** Every step of the argument, in its order, with the Beliefs that answer it (maybe none). */
export function groupBySteps(beliefs: readonly BeliefSummary[]): StepGroup[] {
  return (Object.keys(STEPS) as Step[]).map((step) => ({
    step,
    title: STEPS[step],
    beliefs: beliefs.filter((belief) => belief.step === step).sort(byStanding),
  }));
}

/** "Lumentum, Coherent", or a word for a Belief about no one company. */
export function companyNames(belief: Pick<BeliefSummary, "companies">): string {
  return belief.companies.length === 0
    ? "no one company"
    : belief.companies.map((company) => company.display_name).join(", ");
}

// --- a Belief's citations -------------------------------------------------------------------

/** For, against or neither, from the sign of a citation's valence. */
export function direction(valence: number): "for" | "against" | "neutral" {
  return valence > 0 ? "for" : valence < 0 ? "against" : "neutral";
}

/** "for, load-bearing" or "against (-0.5), context". */
export function valenceText(
  citation: Pick<Citation, "valence" | "weight">,
): string {
  const how = direction(citation.valence);
  const sign = how === "against" ? ` (${citation.valence})` : "";
  return `${how}${sign}, ${citation.weight === "load_bearing" ? "load-bearing" : "context"}`;
}

export interface CompanyCitations {
  company: string;
  citations: Citation[];
}

/** Citations grouped by the company that spoke, each group oldest first, groups by name. */
export function citationsByCompany(
  citations: readonly Citation[],
): CompanyCitations[] {
  const groups = new Map<string, Citation[]>();
  for (const citation of citations) {
    groups.set(citation.company_name, [
      ...(groups.get(citation.company_name) ?? []),
      citation,
    ]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([company, items]) => ({
      company,
      citations: items.sort((a, b) =>
        a.available_at.localeCompare(b.available_at),
      ),
    }));
}

/** The day a timestamp falls on. */
export function day(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** Who set a judgement and when: "owner, 2026-10-12". */
export function judgedBy(judgement: { actor: string; at: string }): string {
  return `${judgement.actor}, ${day(judgement.at)}`;
}
