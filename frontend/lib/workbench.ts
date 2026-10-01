// The research workbench's pure parts: labels, the research card's open questions, why a
// follow-up can't be launched, the reading pointers by query, how passages were selected, the
// Skeptic's items by kind, and a task's output as short text.
import type {
  CardReading,
  Counterevidence,
  Investigation,
  InvestigationTask,
  ReadingPointer,
  ResearchCard,
} from "./api/client";

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

/**
 * Whether the research card can be saved as a Hypothesis now: a card with no finding (no
 * Claim was accepted) reports what was searched and read, and has nothing to save.
 */
export function canSaveHypothesis(investigation: Investigation): boolean {
  return (
    investigation.status === "stopped" &&
    (investigation.research_card?.findings.length ?? 0) > 0 &&
    !investigation.request.hypothesis_id
  );
}

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

/** Who a row of the card's "What was read" is: the Investigator's company, or the Skeptic. */
export function readerName(reading: CardReading): string {
  if (reading.role === "skeptic") return ROLES.skeptic;
  return reading.company_name ?? reading.task_key;
}

/**
 * What one Investigator's or the Skeptic's reading came to, in words: why it read nothing,
 * or its documents (for the Skeptic, how many code chose because its plan chose none for a
 * seed company), passages and proposals (Claims, or counterevidence items), with the
 * rejected ones by reason.
 */
export function readingOutcome(reading: CardReading): string {
  if (reading.documents.length === 0) return reading.detail ?? "Read nothing.";
  const skeptic = reading.role === "skeptic";
  const chosenByCode = reading.documents.filter((d) => d.selected_by === "fallback").length;
  const parts = [
    `${plural(reading.documents.length, "document")} read`,
    ...(chosenByCode > 0
      ? [`${chosenByCode} chosen by code (its plan chose none for a seed company)`]
      : []),
    ...(reading.documents_dropped > 0
      ? [`${reading.documents_dropped} left out by the document budget`]
      : []),
    plural(reading.passages, "passage"),
    `${plural(
      reading.claims_proposed,
      skeptic ? "counterevidence item" : "Claim",
    )} proposed, ${reading.claims_accepted} accepted`,
  ];
  const rejected = Object.entries(reading.rejected)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([reason, count]) => `${reason.replaceAll("_", " ")} ×${count}`);
  if (rejected.length > 0) parts.push(`rejected: ${rejected.join(", ")}`);
  if (reading.passages === 0 && reading.detail) parts.push(reading.detail);
  return `${parts.join("; ")}.`;
}

/**
 * The kinds of passage selection, best first: a reading pointer's window (Memory as an
 * index), the term search, an entity tag, a lead window.
 */
const SELECTIONS = ["pointer", "search", "entity", "lead"];

const selectionOrder = (kind: string) =>
  SELECTIONS.includes(kind) ? SELECTIONS.indexOf(kind) : SELECTIONS.length;

/**
 * How a document's passages were selected, in words ("pointer 2, search 5"): its passages
 * per kind of selection, a passage counting under each kind that chose it. Null when the
 * card records none (a document with no passage sent, the Skeptic's, an older card).
 */
export function selectionSummary(selections: Record<string, number> | undefined): string | null {
  const kinds = Object.entries(selections ?? {}).sort(
    ([a], [b]) => selectionOrder(a) - selectionOrder(b) || a.localeCompare(b),
  );
  if (kinds.length === 0) return null;
  return kinds.map(([kind, count]) => `${kind} ${count}`).join(", ");
}

/**
 * Which selections chose the passage a Claim quotes, in words ("pointer, search"): the kinds
 * of its `selected_by` tags, each once. Null when none is recorded.
 */
export function foundBy(selectedBy: string[] | undefined): string | null {
  const kinds = [...new Set((selectedBy ?? []).map((tag) => tag.split(":")[0] ?? tag))].sort(
    (a, b) => selectionOrder(a) - selectionOrder(b) || a.localeCompare(b),
  );
  return kinds.length > 0 ? kinds.join(", ") : null;
}

/** One query asked of Memory, and the reading pointers its recall gave. */
export type PointerGroup = {
  round: number;
  /** 0: the round's question; n: the Scout's nth query. */
  queryIndex: number;
  query: string;
  /** Best rank first. */
  pointers: ReadingPointer[];
  /** The companies pointed at, most pointers first. */
  companies: { name: string; pointers: number }[];
};

/**
 * An investigation's reading pointers by the query that recalled them: rounds in order, the
 * question before the Scout's queries, each group's pointers by rank. A query whose recall
 * gave no pointer has no group.
 */
export function pointerGroups(pointers: ReadingPointer[]): PointerGroup[] {
  const groups = new Map<string, PointerGroup>();
  for (const pointer of pointers) {
    const key = `${pointer.round}:${pointer.query_index}`;
    const group = groups.get(key) ?? {
      round: pointer.round,
      queryIndex: pointer.query_index,
      query: pointer.query,
      pointers: [],
      companies: [],
    };
    group.pointers.push(pointer);
    groups.set(key, group);
  }
  for (const group of groups.values()) {
    group.pointers.sort(
      (a, b) =>
        a.rank - b.rank ||
        a.source_version_id.localeCompare(b.source_version_id) ||
        a.section_char_start - b.section_char_start,
    );
    const counts = new Map<string, number>();
    for (const pointer of group.pointers) {
      const name = pointer.company_name ?? "no company";
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    group.companies = [...counts.entries()]
      .map(([name, count]) => ({ name, pointers: count }))
      .sort((a, b) => b.pointers - a.pointers || a.name.localeCompare(b.name));
  }
  return [...groups.values()].sort((a, b) => a.round - b.round || a.queryIndex - b.queryIndex);
}

/** Which query a group is: the round's question or one of the Scout's, by number. */
export function pointerQueryLabel(group: PointerGroup): string {
  const which = group.queryIndex === 0 ? "The question" : `Query ${group.queryIndex}`;
  return group.round > 1 ? `${which} (follow-up round ${group.round})` : which;
}

/** A group's pointers in words: how many, and how many name each company. */
export function pointerSummary(group: PointerGroup): string {
  const companies = group.companies.map((each) => `${each.name} ${each.pointers}`).join(", ");
  return `${plural(group.pointers.length, "pointer")}: ${companies}`;
}

/** The bear checklist's items, in words. */
const CHECKLIST: Record<string, string> = {
  substitutes: "Substitutes",
  second_sources: "Second sources",
  capacity_additions: "Capacity additions",
  inventory_cycle: "Inventory cycle",
  dilution_financing: "Dilution and financing",
  customer_concentration: "Customer concentration",
};

/** A bear-checklist item in words (an item added later shows as its name, spaced). */
export function checklistLabel(item: string): string {
  return CHECKLIST[item] ?? item.replaceAll("_", " ");
}

/** The figure a quoted table row states, with its period; null for any other quote. */
export function figureLabel(item: {
  figure_name: string | null;
  figure_period: string | null;
}): string | null {
  const parts = [item.figure_name, item.figure_period].filter((part) => part);
  return parts.length > 0 ? parts.join(", ") : null;
}

/**
 * What the Skeptic's items came to, by kind: contradictions of a Claim, bear context (which
 * contradicts none), and how many proposed items were rejected.
 */
export function counterevidenceSummary(items: Counterevidence[]): string {
  const accepted = items.filter((item) => item.outcome === "accepted");
  const contradictions = accepted.filter((item) => item.kind === "contradiction").length;
  const rejected = items.length - accepted.length;
  const parts = [
    accepted.length === 0
      ? "No accepted counterevidence."
      : `${plural(contradictions, "contradiction")} of a Claim and ${plural(
          accepted.length - contradictions,
          "bear-context item",
        )} accepted${rejected > 0 ? ";" : "."}`,
    ...(rejected > 0 ? [`${plural(rejected, "proposed item")} rejected.`] : []),
  ];
  return parts.join(" ");
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
