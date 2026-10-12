// The pure parts of a Hypothesis over Beliefs (atlas-beliefs ticket 14): the version's steps in
// the argument's order, each with the Beliefs it rests on, and the theme's open Issues.
import type { HypothesisVersion, Issue } from "./api/client";
import { STEPS } from "./beliefs";
import { words } from "./hypotheses";

export type Step = NonNullable<HypothesisVersion["content"]["steps"]>[number];

/** The version's steps (none for a version of an investigation, and for one stored before
 * ticket 14). */
export function stepsOf(version: HypothesisVersion): Step[] {
  return version.content.steps ?? [];
}

/** A step of the argument as the dossier shows it: its title, its statement (none when the
 * Editor's was set aside), whether the judge passed the statement, and the Beliefs it rests on
 * (the most confident first). */
export interface StepView {
  step: string;
  title: string;
  statement: string | null;
  judged: boolean | null;
  beliefs: Step["beliefs"];
}

/** The version's steps in the argument's order (a version of an investigation has none). */
export function stepViews(version: HypothesisVersion): StepView[] {
  const order = Object.keys(STEPS);
  const rank = (step: string) => {
    const at = order.indexOf(step);
    return at < 0 ? order.length : at;
  };
  return [...stepsOf(version)]
    .sort((a, b) => rank(a.step) - rank(b.step))
    .map((each) => ({
      step: each.step,
      title: STEPS[each.step as keyof typeof STEPS] ?? words(each.step),
      statement: each.statement ?? null,
      judged: each.judged ?? null,
      beliefs: [...each.beliefs].sort((a, b) => b.confidence - a.confidence),
    }));
}

/** How many Beliefs the version's steps rest on, once each. */
export function beliefCount(version: HypothesisVersion): number {
  const ids = stepsOf(version).flatMap((each) =>
    each.beliefs.map((b) => b.belief_id),
  );
  return new Set(ids).size;
}

/** The Issues still open on a theme, the most pressing first. */
export function openIssues(issues: readonly Issue[], theme: string): Issue[] {
  return issues
    .filter((each) => each.theme === theme && each.status === "active")
    .sort(
      (a, b) =>
        b.priority - a.priority || a.created_at.localeCompare(b.created_at),
    );
}
