// The shape of the argument (Y1): four steps argue for the thesis, two against it. Whether a
// step is for or against is structure, not state. For each step: how many Beliefs are proven,
// the strongest proven one, and the Beliefs in the order a reader should meet them.
import type { BeliefSummary } from "./api/client";

export type StepName = BeliefSummary["step"];

/** The Beliefs the argument is read from (a theme's active ones, or a company's). */
export type ArgBelief = Pick<
  BeliefSummary,
  "id" | "step" | "statement" | "as_of" | "status" | "open_flags" | "last_examined_at"
> & { judgement: Pick<BeliefSummary["judgement"], "judgement" | "confidence"> };

/** The four steps that argue for the thesis, then the two that argue against it. */
export const FOR_STEPS: readonly StepName[] = ["constraint", "demand_vs_supply", "control", "capture"];
export const AGAINST_STEPS: readonly StepName[] = ["relief", "invalidation"];

/** The one order of the steps, in the strip and in every list of them. */
export const ARGUMENT_ORDER: readonly StepName[] = [...FOR_STEPS, ...AGAINST_STEPS];

/** A step's short name, for the strip. */
export const STEP_LABELS: Record<StepName, string> = {
  constraint: "Constraint",
  demand_vs_supply: "Demand",
  relief: "Relief",
  control: "Control",
  capture: "Capture",
  invalidation: "Invalidation",
};

export function isAgainst(step: StepName): boolean {
  return AGAINST_STEPS.includes(step);
}

export interface StepArgument<T extends ArgBelief = ArgBelief> {
  step: StepName;
  against: boolean;
  /** Active Beliefs proven now. */
  proven: number;
  /** The strongest proven active Belief, or null. */
  strongest: T | null;
  /** Every active Belief: disproven and flagged first, then proven by confidence, then the rest. */
  beliefs: T[];
  /** The newest time a session examined any of them, or null when none has been. */
  examinedAt: string | null;
}

function rank(belief: ArgBelief): number {
  if (belief.judgement.judgement === "disproven" || belief.open_flags > 0) return 0;
  return belief.judgement.judgement === "proven" ? 1 : 2;
}

function inReadingOrder(a: ArgBelief, b: ArgBelief): number {
  return (
    rank(a) - rank(b) ||
    b.judgement.confidence - a.judgement.confidence ||
    b.as_of.localeCompare(a.as_of) ||
    a.id.localeCompare(b.id)
  );
}

/** Per step of the argument, in its order: what stands, the strongest, and the Beliefs sorted.
 * A Belief that is no longer active is not part of the argument. */
export function argumentOf<T extends ArgBelief>(beliefs: readonly T[]): StepArgument<T>[] {
  return ARGUMENT_ORDER.map((step) => {
    const mine = beliefs.filter((each) => each.step === step && each.status === "active");
    const proven = mine
      .filter((each) => each.judgement.judgement === "proven")
      .sort((a, b) => b.judgement.confidence - a.judgement.confidence || a.id.localeCompare(b.id));
    const examined = mine
      .map((each) => each.last_examined_at)
      .filter((at): at is string => at !== null)
      .sort();
    return {
      step,
      against: isAgainst(step),
      proven: proven.length,
      strongest: proven[0] ?? null,
      beliefs: [...mine].sort(inReadingOrder),
      examinedAt: examined.at(-1) ?? null,
    };
  });
}

/** The strip's cells in its order: for-steps, then against-steps. */
export function stripOrder<T extends ArgBelief>(steps: readonly StepArgument<T>[]): StepArgument<T>[] {
  return [...FOR_STEPS, ...AGAINST_STEPS]
    .map((name) => steps.find((each) => each.step === name))
    .filter((each): each is StepArgument<T> => each !== undefined);
}

export interface Weakest {
  step: StepName;
  /** The strongest proven confidence of that step; null when nothing in it is proven. */
  confidence: number | null;
}

/** The weakest of the four steps that argue for the thesis: an empty step first, else the
 * lowest strongest confidence (ties go to the earlier step). */
export function weakestStep(steps: readonly StepArgument[]): Weakest {
  const candidates = FOR_STEPS.map((name) => {
    const found = steps.find((each) => each.step === name);
    return { step: name, confidence: found?.strongest?.judgement.confidence ?? null };
  });
  return candidates.reduce((weakest, each) => {
    if (weakest.confidence === null) return weakest;
    if (each.confidence === null) return each;
    return each.confidence < weakest.confidence ? each : weakest;
  });
}

/** "Weakest step: Control · 60%", or "Weakest step: Control · nothing proven". */
export function weakestText(weakest: Weakest): string {
  const how =
    weakest.confidence === null ? "nothing proven" : `${Math.round(weakest.confidence * 100)}%`;
  return `Weakest step: ${STEP_LABELS[weakest.step]} · ${how}`;
}

/** A strip cell's accessible name: "Relief, against the thesis: 3 proven, strongest 75%". */
export function cellName(step: StepArgument): string {
  const label = STEP_LABELS[step.step];
  const side = step.against ? ", against the thesis" : "";
  if (step.strongest === null) return `${label}${side}: nothing proven`;
  return `${label}${side}: ${step.proven} proven, strongest ${Math.round(step.strongest.judgement.confidence * 100)}%`;
}
