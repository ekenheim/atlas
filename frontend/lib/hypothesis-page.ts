// The Hypothesis page's pure parts (spec §5.4): the argument of a version as it recorded it, a
// step statement's first sentence, the thesis's mechanism as one paragraph, and what changed
// since drafting. The thesis proposition itself is in `lib/thesis.ts`.
import type { BeliefSummary, HypothesisVersion } from "./api/client";
import { type ArgBelief, type StepArgument, argumentOf } from "./argument";
import { standingNow, stepViews, type StepView } from "./hypothesis-steps";
import type { JudgementName } from "./status";

/** The first sentence of a statement: up to the first full stop followed by a capital. A figure
 * ("$22.5 million") has no space after its point and is not split. */
export function firstSentence(text: string): string {
  const match = /^(.+?[.!?])(\s+(?=[A-Z"“‘])|$)/s.exec(text.trim());
  return match?.[1] ?? text.trim();
}

/** The mechanism's parts as one paragraph, the ones the draft established. */
export function mechanismText(mechanism: HypothesisVersion["content"]["mechanism"] | undefined): string {
  if (!mechanism) return "";
  return [mechanism.demand_driver, mechanism.possible_constraint, mechanism.economic_capture_question]
    .filter((part): part is string => typeof part === "string" && part.trim() !== "")
    .join(" ");
}

const JUDGEMENTS = new Set(["proven", "unproven", "disproven", "undecidable"]);

/** The version's Beliefs as the argument reads them: what each was when the version drafted it. */
export function versionArgument(version: HypothesisVersion): StepArgument<ArgBelief>[] {
  const beliefs: ArgBelief[] = stepViews(version).flatMap((view) =>
    view.beliefs.map((belief) => ({
      id: belief.belief_id,
      step: view.step as ArgBelief["step"],
      statement: belief.statement,
      as_of: belief.as_of,
      status: "active" as const,
      open_flags: 0,
      last_examined_at: null,
      judgement: {
        judgement: (JUDGEMENTS.has(belief.judgement) ? belief.judgement : "unproven") as JudgementName,
        confidence: belief.confidence,
      },
    })),
  );
  return argumentOf(beliefs);
}

/** Whether any of a step's Beliefs stands differently now from how the version recorded it. */
export function changedSinceDrafting(
  view: StepView,
  now: ReadonlyMap<string, BeliefSummary>,
): boolean {
  return view.beliefs.some((belief) => standingNow(belief, now.get(belief.belief_id)) !== null);
}
