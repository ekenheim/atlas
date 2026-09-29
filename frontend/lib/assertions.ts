import type { EpistemicType, ReviewState } from "./api/client";

/** The epistemic types (build plan §5.4), as the create form offers them. */
export const EPISTEMIC_TYPES: readonly { value: EpistemicType; label: string }[] = [
  { value: "direct_source_statement", label: "Direct source statement" },
  { value: "company_claim", label: "Company claim" },
  { value: "third_party_report", label: "Third-party report" },
  { value: "agent_inference", label: "Agent inference" },
  { value: "quantitative_derived", label: "Quantitative (derived)" },
];

/** A review action: the state it moves an Assertion to, and its button's label. */
export type ReviewAction = { state: Exclude<ReviewState, "unreviewed">; label: string };

const ACTIONS: readonly ReviewAction[] = [
  { state: "corroborated", label: "Corroborate" },
  { state: "disputed", label: "Dispute" },
  { state: "rejected", label: "Reject" },
  { state: "superseded", label: "Supersede" },
];

const OPEN: readonly ReviewState[] = ["unreviewed", "corroborated", "disputed"];

/**
 * The review actions an Assertion in `state` offers. This mirrors the API's transition
 * rules (docs/decisions.md, ticket 08), which stay authoritative: an open state
 * (unreviewed, corroborated, disputed) may move to any other state except back to
 * unreviewed, and rejected and superseded are final.
 */
export function reviewActions(state: ReviewState): ReviewAction[] {
  return OPEN.includes(state) ? ACTIONS.filter((action) => action.state !== state) : [];
}

/** Whether an Assertion in `state` may be named as another's successor. */
export function canSucceed(state: ReviewState): boolean {
  return OPEN.includes(state);
}
