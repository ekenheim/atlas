// The research workbench's pure parts: labels, the research card's open questions, why a
// follow-up can't be launched, the reading pointers by query, the companies they name and
// which Investigators were added for them, how passages were selected, the Skeptic's items by
// kind, and a task's output as short text.
import type {
  CardArgumentStep,
  CardFact,
  CardQuestionPart,
  CardReading,
  CardSkepticCompany,
  CardStepStatement,
  Counterevidence,
  EntityHop,
  Investigation,
  InvestigationTask,
  PointedCompany,
  ReadingPointer,
  ResearchCard,
} from "./api/client";

export const ROLES: Record<InvestigationTask["role"], string> = {
  scout: "Scout",
  investigator: "Investigator",
  skeptic: "Skeptic",
  financial_analyst: "Financial Analyst",
  editor: "Editor",
  reader: "Reader",
};

/** The plans an investigation can run (bottleneck-argument ticket 05). */
export const PLANS: Record<Investigation["plan"], string> = {
  default: "Findings (an Investigator per company)",
  argument: "Argument (a Reader per step)",
};

export const STEP_STATUS: Record<CardArgumentStep["status"], string> = {
  supported: "supported",
  disputed: "disputed",
  unknown: "unknown",
  // The invalidation step (pilot-review R2-03): an observation against the argument was
  // found, or its Reader searched and found none.
  found: "found",
  nothing_found: "nothing found",
};

/** What the card says of a part of the question (pilot-review R2-01). */
export const PART_STATUS: Record<CardQuestionPart["status"], string> = {
  answered: "answered",
  facts_only: "Facts, no statement",
  unanswered: "unanswered",
};

/** A part of the question in a line: its words, what the card says of it, and its counts. */
export function partLine(part: CardQuestionPart): string {
  const counts: string[] = [];
  if (part.statements > 0) {
    counts.push(`${part.statements} statement${part.statements === 1 ? "" : "s"}`);
  }
  counts.push(`${part.facts} Fact${part.facts === 1 ? "" : "s"}`);
  return `${part.text}: ${PART_STATUS[part.status]} (${counts.join(", ")})`;
}

/** The question's parts counted by what the card says of them: "1 answered, 1 unanswered". */
export function partTally(parts: CardQuestionPart[]): string {
  const order: CardQuestionPart["status"][] = ["answered", "facts_only", "unanswered"];
  return order
    .map((status) => ({ status, count: parts.filter((part) => part.status === status).length }))
    .filter(({ count }) => count > 0)
    .map(({ status, count }) => `${count} ${PART_STATUS[status]}`)
    .join(", ");
}

/** A Fact in a line: its statement, then its quantity, period, the day its document became
 * available (YYYY-MM-DD) and status as recorded. */
export function factLine(fact: CardFact): string {
  const parts: string[] = [];
  if (fact.quantity) {
    parts.push(`${fact.quantity.value} ${fact.quantity.unit} (${fact.quantity.metric})`);
  }
  if (fact.period) parts.push(fact.period);
  if (fact.evidence_available_at) parts.push(fact.evidence_available_at.slice(0, 10));
  parts.push(fact.status.split("_").join(" "));
  return `${fact.statement} [${parts.join("; ")}]`;
}

/** A step's statements that stood, each with the Facts it cites; a card written before the
 * Editor wrote several per step has its one statement, with the step's Facts. */
export function stepStatements(step: CardArgumentStep): CardStepStatement[] {
  if (step.statements && step.statements.length > 0) return step.statements;
  if (!step.statement) return [];
  return [
    {
      statement: step.statement,
      facts: step.facts,
      counterevidence: step.counterevidence,
      judged: step.judged,
    },
  ];
}

/** Facts and counterevidence in a few words: "2 Facts, 1 against, 3 also found". */
export function citedTally(facts: CardFact[], against: CardFact[], alsoFound = 0): string {
  const parts = [`${facts.length} ${facts.length === 1 ? "Fact" : "Facts"}`];
  if (against.length > 0) parts.push(`${against.length} against`);
  if (alsoFound > 0) parts.push(`${alsoFound} also found`);
  return parts.join(", ");
}

/** A Skeptic Fact as a step or a statement shows it, with what it does to the Facts there. */
export interface CounterLine {
  fact: CardFact;
  relation: string; // "contradicts", "qualifies, supports", "": none recorded (an older card)
}

/** A step's (or a statement's) counterevidence split by the counter-judge's labels (pilot-review
 * T3): "Against", the Skeptic Facts that contradict, limit or date one of `factIds` (or could
 * not be judged against one), with that relation; "Also found", the rest, with what they do
 * (to these Facts, or to another step's). A card written before the labels has none: a Fact
 * against one of `factIds` is against, with no relation shown. */
export function splitCounterevidence(
  counter: CardFact[],
  factIds: string[],
): { against: CounterLine[]; alsoFound: CounterLine[] } {
  const here = new Set(factIds);
  const against: CounterLine[] = [];
  const alsoFound: CounterLine[] = [];
  for (const fact of counter) {
    const relations = fact.relations ?? [];
    const named = (fact.against ?? []).filter((id) => here.has(id));
    if (named.length > 0) {
      const labels = relations.filter((each) => named.includes(each.fact_id));
      against.push({ fact, relation: unique(labels.map((each) => each.relation)) });
      continue;
    }
    const onHere = relations.filter((each) => here.has(each.fact_id));
    const relation =
      onHere.length > 0
        ? unique(onHere.map((each) => each.relation))
        : relations.length > 0
          ? `${unique(relations.map((each) => each.relation))} another step's Fact`
          : "names no Fact";
    alsoFound.push({ fact, relation });
  }
  return { against, alsoFound };
}

function unique(values: string[]): string {
  return [...new Set(values)].join(", ");
}

/** The argument's steps counted by status: "4 supported, 1 nothing found, 1 unknown". */
export function stepTally(steps: CardArgumentStep[]): string {
  const order: CardArgumentStep["status"][] = [
    "supported",
    "found",
    "disputed",
    "nothing_found",
    "unknown",
  ];
  return order
    .map((status) => ({ status, count: steps.filter((step) => step.status === status).length }))
    .filter(({ count }) => count > 0)
    .map(({ status, count }) => `${count} ${STEP_STATUS[status]}`)
    .join(", ");
}

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
 * or its documents (for the Skeptic, how many code chose because Memory pointed at nothing
 * of a company the Claims name), passages and proposals (Claims, or counterevidence items),
 * with the rejected ones by reason.
 */
export function readingOutcome(reading: CardReading): string {
  if (reading.documents.length === 0) return reading.detail ?? "Read nothing.";
  const skeptic = reading.role === "skeptic";
  const chosenByCode = reading.documents.filter((d) => d.selected_by === "fallback").length;
  const parts = [
    `${plural(reading.documents.length, "document")} read`,
    ...(chosenByCode > 0
      ? [`${chosenByCode} chosen by code (Memory pointed at nothing of the company's)`]
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
 * index), an entity pointer's (the entity hop), the term search, an entity tag, a lead window.
 */
const SELECTIONS = ["pointer", "entity_pointer", "search", "entity", "lead"];

const selectionOrder = (kind: string) =>
  SELECTIONS.includes(kind) ? SELECTIONS.indexOf(kind) : SELECTIONS.length;

/**
 * How a document's passages were selected, in words ("pointer 2, search 5"): its passages
 * per kind of selection, a passage counting under each kind that chose it. Null when the
 * card records none (a document with no passage sent, an older card).
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

/**
 * Who says a Claim's quoted words, in a call or conference transcript ("said by Alex Example
 * (CEO, Example Photonics)"): the paragraph's speaker label. Null for any other document.
 */
export function saidBy(speaker: string | null | undefined): string | null {
  const label = speaker?.trim();
  return label ? `said by ${label}` : null;
}

/** One query asked of Memory, and the reading pointers its recall gave. */
export type PointerGroup = {
  round: number;
  /** Who asked: the Scout (its pointers direct the Investigators) or the Skeptic. */
  kind: ReadingPointer["query_kind"];
  /**
   * The Scout's: 0 for the round's question, n for its nth query. The Skeptic's: the
   * query's position among its own, from 1.
   */
  queryIndex: number;
  query: string;
  /** A Skeptic's query: its bear-checklist item and the company it asks about. */
  checklistItem: string | null;
  queryCompany: string | null;
  /** Best rank first. */
  pointers: ReadingPointer[];
  /** The companies pointed at, most pointers first. */
  companies: { name: string; pointers: number }[];
};

/**
 * An investigation's reading pointers by the query that recalled them: rounds in order, in
 * each the Scout's (the question before its queries) before the Skeptic's (its
 * bear-checklist queries, in the order asked), each group's pointers by rank. A query whose
 * recall gave no pointer has no group.
 */
export function pointerGroups(pointers: ReadingPointer[]): PointerGroup[] {
  const groups = new Map<string, PointerGroup>();
  for (const pointer of pointers) {
    const key = `${pointer.round}:${pointer.query_kind}:${pointer.query_index}`;
    const group = groups.get(key) ?? {
      round: pointer.round,
      kind: pointer.query_kind,
      queryIndex: pointer.query_index,
      query: pointer.query,
      checklistItem: pointer.checklist_item,
      queryCompany: pointer.query_company_name,
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
  const ASKERS = { scout: 0, entity: 1, bear_checklist: 2 };
  const asker = (group: PointerGroup) => ASKERS[group.kind];
  return [...groups.values()].sort(
    (a, b) => a.round - b.round || asker(a) - asker(b) || a.queryIndex - b.queryIndex,
  );
}

/**
 * Which query a group is: the round's question or one of the Scout's, by number; or the
 * Skeptic's, by its bear-checklist item and the company it asks about.
 */
export function pointerQueryLabel(group: PointerGroup): string {
  const which =
    group.kind === "bear_checklist"
      ? `${checklistLabel(group.checklistItem ?? "")} of ${group.queryCompany ?? "a company"}`
      : group.kind === "entity"
        ? `Other companies' documents naming ${group.queryCompany ?? "a company"}`
        : group.queryIndex === 0
          ? "The question"
          : `Query ${group.queryIndex}`;
  return group.round > 1 ? `${which} (follow-up round ${group.round})` : which;
}

/**
 * Which recall made a pointer, in words (memory-quality ticket 13): a Scout query that carries
 * a layer is asked across the theme and again among the facts labelled with that layer.
 */
export function pointerScope(pointer: Pick<ReadingPointer, "scope" | "layer">): string {
  return pointer.scope === "theme_layer"
    ? `the theme's facts labelled ${pointer.layer ?? "with a layer"}`
    : "the theme";
}

/** A group's pointers in words: how many, and how many name each company. */
export function pointerSummary(group: PointerGroup): string {
  const companies = group.companies.map((each) => `${each.name} ${each.pointers}`).join(", ");
  return `${plural(group.pointers.length, "pointer")}: ${companies}`;
}

/**
 * How strongly a round's reading pointers name a company, in words: how many recall pointers,
 * the best rank among them, how many entity pointers (the entity hop's), and their weight
 * (a recall pointer weighs 1 / its rank in its recall, an entity pointer its own share).
 */
export function pointerWeight(company: {
  pointers: number;
  best_rank: number | null;
  score: number;
  entity_pointers?: number;
}): string {
  const weight = Number(company.score.toFixed(2));
  const parts = [plural(company.pointers, "pointer")];
  if (company.best_rank !== null) parts.push(`best rank ${company.best_rank}`);
  if (company.entity_pointers) parts.push(plural(company.entity_pointers, "entity pointer"));
  parts.push(`weight ${weight}`);
  return parts.join(", ");
}

/** The channels that reached a company no Investigator read, in words. */
export function channelsLabel(channels: string[] | undefined): string | null {
  const names: Record<string, string> = { recall: "recall", entity: "the entity hop" };
  const named = (channels ?? []).map((channel) => names[channel] ?? channel);
  return named.length > 0 ? `reached by ${named.join(" and ")}` : null;
}

/**
 * What the Skeptic did across the companies the accepted Claims name: how many it checked
 * and which it did not. "Not checked" is never read as "no contradiction found".
 */
export function skepticCoverageSummary(rows: CardSkepticCompany[] | undefined): string | null {
  if (!rows || rows.length === 0) return null;
  const missed = rows.filter((row) => row.outcome === "not_checked");
  const checked = rows.length - missed.length;
  const head = `The Skeptic checked ${checked} of ${rows.length} companies the accepted Claims name`;
  return missed.length === 0
    ? `${head}.`
    : `${head}. Not checked: ${missed.map((row) => row.company_name).join(", ")}. For these, no contradiction was looked for.`;
}

/** One company's row of the Skeptic's coverage: what it read and found, or why it did not check. */
export function skepticCompanyLine(row: CardSkepticCompany): string {
  if (row.outcome === "not_checked") {
    return `not checked: ${row.reason ?? "no reason recorded"}`;
  }
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  return [
    `checked: ${plural(row.documents.length, "document")}`,
    plural(row.passages, "passage"),
    plural(row.contradictions, "contradiction"),
    `${row.bear_context} bear context`,
  ].join(", ");
}

/**
 * What the entity hop did for one company, in words: the entity it found by the company's
 * canonical name and the pointers its facts made, or why there are none.
 */
export function entityHopSummary(hop: EntityHop): string {
  switch (hop.outcome) {
    case "no_entity":
      return `no entity named "${hop.entity_name}" in Memory`;
    case "listing_failed":
      return `listing the facts of "${hop.entity_name}" failed (see the events)`;
    case "entities_unavailable":
      return "the entity listing failed, so no company was hopped (see the events)";
    case "listed": {
      const skipped = [
        hop.own_documents > 0 && `${hop.own_documents} from its own documents`,
        hop.after_as_of > 0 && `${hop.after_as_of} after the as-of time`,
        hop.already_pointed > 0 && `${hop.already_pointed} already pointed at by recall`,
        hop.unresolved > 0 && `${hop.unresolved} not resolved to a section`,
        hop.beyond_limit > 0 && `${hop.beyond_limit} beyond the bound`,
      ].filter((part): part is string => typeof part === "string");
      const facts = `${plural(hop.facts_listed, "fact")} carry "${hop.entity_name}"`;
      const made = `${plural(hop.pointers, "entity pointer")}`;
      return skipped.length > 0
        ? `${facts}: ${made}; ${skipped.join(", ")}`
        : `${facts}: ${made}`;
    }
  }
}

/**
 * What became of a company the pointers name: a seed is read whatever its rank; another got
 * an Investigator while the company budget had room; the rest were not read.
 */
export function pointedOutcome(company: PointedCompany, maxCompanies: number): string {
  switch (company.outcome) {
    case "seed":
      return "a seed: read whatever its rank";
    case "added":
      return "Investigator added";
    case "no_room":
      return `not read: the company budget (${maxCompanies} Investigators a round) had no room`;
    case "premise_disproven":
      return "not read: its premise was disproven";
  }
}

/**
 * Why an Investigator task is in the plan when its company is no seed: the pointers it was
 * added for. Null for every other task.
 */
export function addedInvestigator(
  task: Pick<InvestigationTask, "round" | "key">,
  pointed: PointedCompany[],
): string | null {
  const company = pointed.find(
    (each) => each.outcome === "added" && each.round === task.round && each.task_key === task.key,
  );
  if (!company) return null;
  return `Added after the Scout: Memory points to ${company.company_name} (${pointerWeight(
    company,
  )}).`;
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
