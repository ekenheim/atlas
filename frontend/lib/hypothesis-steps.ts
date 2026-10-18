// The pure parts of a Hypothesis over Beliefs (atlas-beliefs ticket 14): the version's steps in
// the argument's order, each with the Beliefs it rests on, and the theme's open Issues.
import type {
  Belief,
  BeliefSummary,
  Call,
  HypothesisVersion,
  Issue,
} from "./api/client";
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
  /** The points kept for the step, each with whether the judge passed it. */
  statements: { statement: string; judged: boolean | null }[];
  beliefs: Step["beliefs"];
}

/** How a Belief stands now when that is not how the version recorded it: another judgement or
 * confidence, no longer active, open flags; null when it is unchanged (or not known). */
export function standingNow(
  drafted: Step["beliefs"][number],
  now: BeliefSummary | undefined,
): string | null {
  if (now === undefined) return null;
  const parts: string[] = [];
  if (now.status !== "active") parts.push(now.status);
  const judgement = now.judgement;
  if (
    judgement.judgement !== drafted.judgement ||
    judgement.confidence !== drafted.confidence
  ) {
    parts.push(
      `now ${judgement.judgement} ${Math.round(judgement.confidence * 100)}%`,
    );
  }
  if (now.open_flags > 0) {
    parts.push(
      `${now.open_flags} open ${now.open_flags === 1 ? "flag" : "flags"}`,
    );
  }
  return parts.length === 0 ? null : parts.join(" · ");
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
      // A version drafted before several points a step have only the single form.
      statements: (each.statements?.length
        ? each.statements
        : each.statement
          ? [{ statement: each.statement, judged: each.judged }]
          : []
      ).map((one) => ({
        statement: one.statement,
        judged: one.judged ?? null,
      })),
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

/** The Beliefs the version rests on, once each, in the order its steps list them. */
export function stepBeliefIds(version: HypothesisVersion): string[] {
  return [
    ...new Set(
      stepViews(version).flatMap((each) =>
        each.beliefs.map((b) => b.belief_id),
      ),
    ),
  ];
}

export type ThesisCheck = {
  /** `supported`: the judge passed it; `misstated`: it says more than its quotes; `unchecked`. */
  state: "supported" | "misstated" | "unchecked";
  text: string;
};

/** Whether the thesis was checked against its Beliefs' quotes, in a line. A version of an
 * investigation has no such check: null. */
export function thesisCheck(version: HypothesisVersion): ThesisCheck | null {
  if (stepsOf(version).length === 0) return null;
  const { thesis_judged: judged, thesis_misstated_reason: reason } =
    version.content;
  if (judged === "supported") {
    return { state: "supported", text: "Checked against its Beliefs' quotes." };
  }
  if (judged === "misstated") {
    return {
      state: "misstated",
      text: `Says more than its quotes: ${reason ?? "see the judge's reason"}`,
    };
  }
  return { state: "unchecked", text: "Not checked against its quotes yet." };
}

type Against = Belief["counterevidence"][number];

/** What stands against the Beliefs a version rests on: each Belief that has counterevidence,
 * with those citations, the most heavily against first. */
export function counterevidenceOf(
  beliefs: readonly Pick<Belief, "id" | "statement" | "counterevidence">[],
): { id: string; statement: string; against: Against[] }[] {
  return beliefs
    .filter((belief) => belief.counterevidence.length > 0)
    .map((belief) => ({
      id: belief.id,
      statement: belief.statement,
      against: [...belief.counterevidence].sort((a, b) => a.valence - b.valence),
    }));
}

/** The calls made for a Hypothesis: those of its versions when they were published, and of the
 * Beliefs it rests on when they were proven. Newest first. */
export function callsFor(
  calls: readonly Call[],
  versionIds: readonly string[],
  beliefIds: readonly string[],
): Call[] {
  const versions = new Set(versionIds);
  const beliefs = new Set(beliefIds);
  return calls
    .filter(
      (call) =>
        (call.origin === "hypothesis" && versions.has(call.origin_id)) ||
        (call.origin === "belief" && beliefs.has(call.origin_id)),
    )
    .sort((a, b) => b.made_at.localeCompare(a.made_at));
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
