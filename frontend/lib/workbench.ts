// The research workbench's pure parts: labels, the research card's open questions, why a
// follow-up can't be launched, and a task's output as short text.
import type { Investigation, InvestigationTask, ResearchCard } from "./api/client";

export const ROLES: Record<InvestigationTask["role"], string> = {
  scout: "Scout",
  investigator: "Investigator",
  skeptic: "Skeptic",
  financial_analyst: "Financial Analyst",
  editor: "Editor",
};

export const STOP_REASONS: Record<NonNullable<Investigation["stop_reason"]>, string> = {
  answered: "answered",
  no_new_independent_evidence: "no new independent Evidence",
  budget_exhausted: "budget exhausted",
  needs_review: "needs review",
  premise_disproven: "premise disproven",
};

/** The investigation's state in words: running (or paused by the queue), or why it stopped. */
export function statusText(investigation: Investigation): string {
  if (investigation.status === "running") {
    return investigation.paused ? "paused (LLM quota or outage; it resumes)" : "running";
  }
  const reason = investigation.stop_reason;
  return `stopped: ${reason ? STOP_REASONS[reason] : "unknown"}`;
}

/** A research card's open questions: the card's own, then its findings', each once. */
export function openQuestions(card: ResearchCard | null | undefined): string[] {
  if (!card) return [];
  const questions = [
    ...card.open_questions,
    ...card.findings.flatMap((finding) => finding.open_questions),
  ];
  return [...new Set(questions)];
}

/**
 * Why no follow-up round can be launched now, or null when one can. The API decides; this
 * only keeps the page from offering what it would refuse.
 */
export function followUpBlocked(investigation: Investigation): string | null {
  if (investigation.status === "running") return "The investigation is still running.";
  if (investigation.stop_reason === "budget_exhausted") {
    return "It stopped on its token budget: resume it instead.";
  }
  if (investigation.stop_reason === "premise_disproven") {
    return "It stopped on a disproven premise.";
  }
  if (investigation.usage.rounds >= investigation.budgets.max_rounds) {
    return `Its ${investigation.budgets.max_rounds} round${
      investigation.budgets.max_rounds === 1 ? " is" : "s are"
    } spent: one follow-up round at most.`;
  }
  if (investigation.request.hypothesis_id) {
    return "It is saved as a Hypothesis, which is drawn from its research card.";
  }
  if (openQuestions(investigation.research_card).length === 0) {
    return "Its research card has no open question to pursue.";
  }
  return null;
}

/** Whether the research card can be saved as a Hypothesis now. */
export function canSaveHypothesis(investigation: Investigation): boolean {
  return (
    investigation.status === "stopped" &&
    investigation.research_card !== null &&
    !investigation.request.hypothesis_id
  );
}

/** The investigation's tasks by round, rounds in order. */
export function byRound(tasks: InvestigationTask[]): [number, InvestigationTask[]][] {
  const rounds = new Map<number, InvestigationTask[]>();
  for (const task of tasks) rounds.set(task.round, [...(rounds.get(task.round) ?? []), task]);
  return [...rounds.entries()].sort(([a], [b]) => a - b);
}

/**
 * A task's output as short "name: value" parts, from whatever its role recorded (so a role
 * built later shows its output without changes here): scalars as they are, lists by length,
 * objects by their number of entries.
 */
export function outputParts(artifacts: InvestigationTask["artifacts"]): string[] {
  return Object.entries(artifacts).map(([name, value]) => {
    const label = name.replaceAll("_", " ");
    if (value === null) return `${label}: none`;
    if (Array.isArray(value)) return `${label}: ${value.length}`;
    if (typeof value === "object") return `${label}: ${Object.keys(value).length} entries`;
    return `${label}: ${String(value)}`;
  });
}

/** The tokens the investigation's run used, against its budget. */
export function tokenUse(investigation: Investigation): string {
  const used = investigation.usage.tokens_in + investigation.usage.tokens_out;
  return `${used} of ${investigation.budgets.token_budget}`;
}
