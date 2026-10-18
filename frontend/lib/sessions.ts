// The pure parts of the research sessions pages: reading a session's card (the argument
// plan's shape, written by the pipeline's Editor or by a Claude session) without trusting it,
// and the words for the list's columns.
import type { ResearchSession, SessionSummary } from "./api/client";
import { agentOf, examinedOf } from "./today";

export const KINDS: Record<SessionSummary["kind"], string> = {
  claude: "Claude",
  pipeline: "Pipeline",
};

/** What a step's status means in a card, as the investigation page words it. */
export const STEP_STATUS: Record<string, string> = {
  supported: "supported",
  disputed: "disputed",
  unknown: "unknown",
  found: "found",
  nothing_found: "nothing found",
};

export interface CardFactRef {
  id: string | null;
  statement: string;
  detail: string;
}

export interface CardStatement {
  statement: string;
  facts: CardFactRef[];
  counterevidence: CardFactRef[];
}

export interface CardStep {
  key: string;
  title: string;
  status: string;
  statements: CardStatement[];
  unchecked: string[];
}

export interface CardPart {
  key: string;
  text: string;
  status: string;
}

export interface CardView {
  steps: CardStep[];
  parts: CardPart[];
  openQuestions: string[];
}

type Obj = Record<string, unknown>;

function obj(value: unknown): Obj | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Obj)
    : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? (value as unknown[]) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strings(value: unknown): string[] {
  return list(value).filter((each): each is string => typeof each === "string" && each !== "");
}

/** A Fact as a card cites it: its ID when it has one, its statement and a short detail
 * (period, the day its document became available, status). */
export function factRef(value: unknown): CardFactRef | null {
  const fact = obj(value);
  if (!fact) return null;
  const statement = text(fact.statement);
  if (!statement) return null;
  const id = text(fact.fact_id) || text(fact.id) || null;
  const detail = [
    text(fact.period),
    text(fact.evidence_available_at).slice(0, 10),
    text(fact.status).split("_").join(" "),
  ]
    .filter(Boolean)
    .join("; ");
  return { id, statement, detail };
}

function factRefs(value: unknown): CardFactRef[] {
  return list(value).flatMap((each) => {
    const ref = factRef(each);
    return ref ? [ref] : [];
  });
}

function statements(step: Obj): CardStatement[] {
  const written = list(step.statements).flatMap((each) => {
    const statement = obj(each);
    if (!statement || !text(statement.statement)) return [];
    return [
      {
        statement: text(statement.statement),
        facts: factRefs(statement.facts),
        counterevidence: factRefs(statement.counterevidence),
      },
    ];
  });
  if (written.length > 0) return written;
  // A card with one statement per step and the step's Facts beside it.
  const single = text(step.statement);
  return single
    ? [{ statement: single, facts: factRefs(step.facts), counterevidence: factRefs(step.counterevidence) }]
    : [];
}

/** A session's card as the page shows it; anything it does not understand is left out. */
export function cardView(card: ResearchSession["card"] | null | undefined): CardView {
  const root = obj(card);
  if (!root) return { steps: [], parts: [], openQuestions: [] };
  const steps = list(root.steps).flatMap((each) => {
    const step = obj(each);
    if (!step) return [];
    const key = text(step.step);
    return [
      {
        key,
        title: text(step.title) || key.split("_").join(" "),
        status: text(step.status),
        statements: statements(step),
        unchecked: strings(step.unchecked),
      },
    ];
  });
  const parts = list(root.question_parts).flatMap((each) => {
    const part = obj(each);
    return part
      ? [{ key: text(part.key), text: text(part.text), status: text(part.status) }]
      : [];
  });
  return { steps, parts, openQuestions: strings(root.open_questions) };
}

export function statusLabel(status: string): string {
  return STEP_STATUS[status] ?? (status.split("_").join(" ") || "unknown");
}

/** Tokens a session spent, from its usage (`tokens`, else `tokens_in` + `tokens_out`), or null
 * when it recorded none. */
export function tokensSpent(usage: SessionSummary["usage"]): number | null {
  const number = (value: unknown) => (typeof value === "number" ? value : null);
  const total = number(usage.tokens);
  if (total !== null) return total;
  const parts = [number(usage.tokens_in), number(usage.tokens_out)];
  return parts.every((each) => each === null) ? null : parts.reduce<number>((sum, each) => sum + (each ?? 0), 0);
}

/** "1,234 tokens", or "none recorded". */
export function costText(usage: SessionSummary["usage"]): string {
  const tokens = tokensSpent(usage);
  return tokens === null ? "none recorded" : `${tokens.toLocaleString("en-US")} tokens`;
}

/** The usage's other figures as "name: value" parts, the tokens aside (calls, records, refusals). */
export function usageParts(usage: SessionSummary["usage"]): string[] {
  return Object.entries(usage)
    .filter(([name, value]) => !name.startsWith("tokens") && typeof value === "number")
    .map(([name, value]) => `${name.split("_").join(" ")}: ${String(value)}`);
}

/** The session's seeds' names where known, else how many there are. */
export function seedsText(session: SessionSummary, names: Map<string, string>): string {
  if (session.seed_company_ids.length === 0) return "none";
  return session.seed_company_ids.map((id) => names.get(id) ?? "a company").join(", ");
}

/** Newest first, then the question: the list's order whatever the API sent. */
export function newestFirst<T extends Pick<SessionSummary, "started_at" | "question">>(
  sessions: T[],
): T[] {
  return [...sessions].sort(
    (a, b) => b.started_at.localeCompare(a.started_at) || a.question.localeCompare(b.question),
  );
}

/** One session's Facts by ID, to link a card's citations to their spans. */
export function factsById<T extends { id: string }>(facts: T[]): Map<string, T> {
  return new Map(facts.map((fact) => [fact.id, fact]));
}

// --- the Agents page: runs as outcome sentences ----------------------------------------------

const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What a run came to, in a few words: what it recorded, proposed, examined or opened, or that
 * it found nothing new. A Skeptic's examination reads as its outcomes ("1 confirmed, 1 nothing
 * new"). */
export function outcomeText(
  session: Pick<SessionSummary, "facts"> &
    Partial<Pick<SessionSummary, "beliefs_proposed" | "beliefs_examined" | "issues_opened">>,
): string {
  const { confirmed, qualified, contradicted, nothing_new } = examinedOf(session);
  const examined = confirmed + qualified + contradicted + nothing_new;
  const parts: string[] = [];
  if (session.facts > 0) parts.push(`recorded ${count(session.facts, "Fact")}`);
  const proposed = session.beliefs_proposed ?? 0;
  if (proposed > 0) parts.push(`proposed ${count(proposed, "Belief", "Beliefs")}`);
  if (examined > 0) {
    const found = [
      confirmed > 0 ? `${confirmed} confirmed` : "",
      qualified > 0 ? `${qualified} qualified` : "",
      contradicted > 0 ? `${contradicted} contradicted` : "",
    ].filter((each) => each !== "");
    parts.push(
      `examined ${count(examined, "Belief", "Beliefs")}: ${found.length > 0 ? found.join(", ") : "nothing new"}`,
    );
  }
  if ((session.issues_opened ?? 0) > 0) parts.push(`opened ${count(session.issues_opened ?? 0, "Issue")}`);
  return parts.length > 0 ? parts.join(", ") : "found nothing new";
}

export interface RunGroup {
  /** The newest run of the group. */
  session: SessionSummary;
  /** How many runs asked the same question as the same agent. */
  runs: number;
}

/** Runs newest first, the same agent's repeats of one question collapsed into the newest, with
 * their count. */
export function collapseRuns(sessions: readonly SessionSummary[]): RunGroup[] {
  const groups = new Map<string, RunGroup>();
  for (const session of newestFirst([...sessions])) {
    const key = `${agentOf(session)}|${session.question}`;
    const found = groups.get(key);
    if (found) found.runs += 1;
    else groups.set(key, { session, runs: 1 });
  }
  return [...groups.values()];
}
