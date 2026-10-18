// The Watch's board in the owner's words (spec §10.3): the groups, the badges, the step strip,
// what a chokepoint still needs, its history as sentences and who holds it. Pure, so each rule is
// tested. The board's own state is the API's fold; nothing here re-derives the gate. The board's
// counts are the API's (`BoardCounts`: a theme summary's `board`, `/chokepoints/counts`); the
// detail resolves its evidence (`facts`, `leads`, `issues`), its holders' companies and when the
// status was set.
import type {
  BoardCounts,
  Chokepoint,
  ChokepointDetail,
  ChokepointEvent,
  CompanyLayer,
  EvidenceFact,
  Holder,
  StepState,
} from "./api/client";
import { ARGUMENT_ORDER, STEP_LABELS, type StepName, isAgainst } from "./argument";
import { STEPS } from "./beliefs";
import { COMPANY_LAYERS } from "./relationships";
import {
  BELOW_THE_BAR,
  CHOKEPOINT_WORDS,
  CROWDING_WORDS,
  NEEDS_QUESTION,
  STEP_MARKS,
  STEP_STATUS_WORDS,
  type StepStatusName,
  type Tone,
  type Word,
  gateMissingText,
  quietWord,
} from "./status";

// --- names ---------------------------------------------------------------------------------

/** A slug in words: "gating-equipment" → "Gating equipment". */
export function humanise(slug: string): string {
  const words = slug.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A layer's name: the universe's own, else the humanised slug (a new theme's layers, such as
 * robotics', are not in `COMPANY_LAYERS`). */
export function layerName(layer: string): string {
  return (COMPANY_LAYERS as Record<string, string | undefined>)[layer as CompanyLayer] ?? humanise(layer);
}

/** A theme's title from `/themes`, else its humanised slug. */
export function themeTitle(slug: string, themes: readonly { id: string; title: string }[] = []): string {
  return themes.find((each) => each.id === slug)?.title ?? humanise(slug);
}

/** A text cut at a word boundary to about `max` characters, with an ellipsis. */
export function clampWords(text: string, max = 28): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  const cut = trimmed.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return `${(space > max / 3 ? cut.slice(0, space) : cut).replace(/[\s,;:.]+$/, "")}…`;
}

// --- the gate and the badges ---------------------------------------------------------------

type Gated = Pick<Chokepoint, "status" | "needs_review" | "thesis_gate">;

/** Why a thesis-ready chokepoint's gate lapsed: `below` when a thesis step lost its quote or
 * the falsifiers were cleared, `question` when only the open question is missing. */
export function lapse(cp: Gated): "below" | "question" | null {
  if (!cp.needs_review) return null;
  const missing = cp.thesis_gate.missing;
  return missing.length > 0 && missing.every((each) => each === "open_issue") ? "question" : "below";
}

export type BadgeKind = "below" | "question" | "quiet";

export interface Badge {
  kind: BadgeKind;
  word: Word;
}

/** The badges a row and the page carry beside the status: a lapsed gate, and quiet. */
export function badges(
  cp: Gated & Pick<Chokepoint, "stale" | "last_evidence_at">,
  now: Date = new Date(),
): Badge[] {
  const out: Badge[] = [];
  const lapsed = lapse(cp);
  if (lapsed === "below") out.push({ kind: "below", word: BELOW_THE_BAR });
  if (lapsed === "question") out.push({ kind: "question", word: NEEDS_QUESTION });
  if (cp.stale && cp.status !== "killed") out.push({ kind: "quiet", word: quietWord(cp.last_evidence_at, now) });
  return out;
}

/** The gate's words without their article: "a quote for control" → "quote for control". */
const bare = (text: string) => text.replace(/^(a|an) /, "");

export interface Line {
  text: string;
  tone: Tone;
}

/** What the chokepoint still needs, or that it meets the bar, or that its gate lapsed. A ruled
 * out one has no line. */
export function barLine(cp: Gated): Line | null {
  if (cp.status === "killed") return null;
  const missing = cp.thesis_gate.missing;
  if (cp.status === "thesis_ready") {
    const lapsed = lapse(cp);
    if (lapsed === "question") return { text: NEEDS_QUESTION.word, tone: "warn" };
    if (lapsed === "below") {
      return {
        text: `${BELOW_THE_BAR.word}: ${missing.map((each) => `no ${bare(gateMissingText(each))}`).join(" · ")}`,
        tone: "warn",
      };
    }
    return { text: "Waiting for proof", tone: "muted" };
  }
  if (cp.thesis_gate.holds) return { text: "Meets the bar for a thesis.", tone: "ok" };
  return { text: `Still needs: ${missing.map(gateMissingText).join(" · ")}`, tone: "muted" };
}

// --- the board -----------------------------------------------------------------------------

export interface BoardGroups<T extends Chokepoint = Chokepoint> {
  ready: T[];
  candidates: T[];
  spotted: T[];
  killed: T[];
}

/** Quiet rows move to the end of their group; the API's order (latest event first) holds
 * otherwise. */
const quietLast = <T extends Chokepoint>(rows: T[]) => [
  ...rows.filter((each) => !each.stale),
  ...rows.filter((each) => each.stale),
];

/** The board's groups. Thesis-ready leads with the lapsed ones. */
export function boardGroups<T extends Chokepoint>(items: readonly T[]): BoardGroups<T> {
  const of = (status: Chokepoint["status"]) => items.filter((each) => each.status === status);
  const ready = quietLast(of("thesis_ready"));
  return {
    ready: [...ready.filter((each) => lapse(each) !== null), ...ready.filter((each) => lapse(each) === null)],
    candidates: quietLast(of("candidate")),
    spotted: quietLast(of("lead")),
    killed: of("killed"),
  };
}

/** A board counted as the API counts it, for a slug no theme summary carries (a watched theme
 * that `/themes` does not list): the same object as `/chokepoints/counts`. */
export function boardCounts(
  items: readonly Pick<Chokepoint, "status" | "stale" | "needs_review">[],
): BoardCounts {
  const of = (status: Chokepoint["status"]) => items.filter((each) => each.status === status).length;
  return {
    lead: of("lead"),
    candidate: of("candidate"),
    thesis_ready: of("thesis_ready"),
    killed: of("killed"),
    stale: items.filter((each) => each.stale && each.status !== "killed").length,
    needs_review: items.filter((each) => each.needs_review).length,
  };
}

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/** The chokepoints not ruled out. */
export const activeCount = (counts: BoardCounts) => counts.lead + counts.candidate + counts.thesis_ready;

/** "4 chokepoints · 1 thesis-ready · 1 below the bar", in parts with their tones: active ones
 * only, and below the bar is every thesis-ready one whose gate lapsed (the API's `needs_review`;
 * its row and page say which). Zero parts drop out; none at all is an empty list. */
export function boardParts(counts: BoardCounts): Line[] {
  const parts: Line[] = [];
  const active = activeCount(counts);
  if (active > 0) parts.push({ text: plural(active, "chokepoint"), tone: "muted" });
  if (counts.thesis_ready > 0) parts.push({ text: `${counts.thesis_ready} thesis-ready`, tone: "muted" });
  if (counts.needs_review > 0) parts.push({ text: `${counts.needs_review} below the bar`, tone: "warn" });
  return parts;
}

export const boardLine = (counts: BoardCounts) => boardParts(counts).map((part) => part.text).join(" · ");

// --- the steps -----------------------------------------------------------------------------

export interface Pip {
  name: StepName;
  label: string;
  status: StepStatusName;
  mark: string;
  word: Word;
  against: boolean;
  /** "Control: unquoted": the item's accessible name. */
  accessible: string;
}

/** A chokepoint's steps by name (the API answers them a to f, each with its name). */
export function stepsByName(steps: readonly StepState[]): Map<StepName, StepState> {
  return new Map(steps.map((each) => [each.name as StepName, each]));
}

/** The strip: the steps in the argument's order, four for and two against. */
export function pipsOf(cp: Pick<Chokepoint, "steps">): Pip[] {
  const byName = stepsByName(cp.steps);
  return ARGUMENT_ORDER.map((name) => {
    const status = byName.get(name)?.status ?? "unexamined";
    const word = STEP_STATUS_WORDS[status];
    return {
      name,
      label: STEP_LABELS[name],
      status,
      mark: STEP_MARKS[status],
      word,
      against: isAgainst(name),
      accessible: `${STEP_LABELS[name]}: ${word.word.toLowerCase()}`,
    };
  });
}

/** "2 quotes · 1 lead · 1 open question", zero parts dropped. */
export function stepCounts(step: Pick<StepState, "evidence">): string {
  const evidence = step.evidence;
  const facts = evidence.fact_ids?.length ?? 0;
  const leads = evidence.lead_ids?.length ?? 0;
  const issues = evidence.issue_ids?.length ?? 0;
  return [
    facts > 0 ? plural(facts, "quote") : null,
    leads > 0 ? plural(leads, "lead") : null,
    issues > 0 ? plural(issues, "open question") : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

/** The steps a thesis rests on: constraint, demand against supply, control. */
export const THESIS_STEPS: readonly StepName[] = ["constraint", "demand_vs_supply", "control"];

/** A step's Facts, in the order the step cites them, from the detail's resolved `facts` (a step
 * cites a Fact by its id). A Fact the detail did not resolve is left out. */
export function stepFacts(
  cp: Pick<ChokepointDetail, "facts">,
  step: Pick<StepState, "evidence"> | null | undefined,
): EvidenceFact[] {
  const byId = new Map(cp.facts.flatMap((fact) => [[fact.id, fact] as const, [fact.assertion_id, fact] as const]));
  return (step?.evidence.fact_ids ?? [])
    .map((id) => byId.get(id))
    .filter((fact): fact is EvidenceFact => fact !== undefined);
}

/** A thesis step's headline: its first Fact's statement; none for the other steps. */
export function headlineOf(
  cp: Pick<ChokepointDetail, "facts">,
  name: StepName,
  step: Pick<StepState, "evidence"> | null | undefined,
): string | null {
  return THESIS_STEPS.includes(name) ? (stepFacts(cp, step)[0]?.statement ?? null) : null;
}

/** A lead's link, only to the web (http or https); anything else is its title alone. */
export function leadHref(url: string): string | null {
  return /^https?:\/\/\S+$/i.test(url) ? url : null;
}

// --- the page ------------------------------------------------------------------------------

/** When the status was last set. */
export const statusSince = (cp: Pick<Chokepoint, "status_set_at">): string => cp.status_set_at;

export interface HolderView {
  name: string;
  /** The universe company it is, or null: "not yet researched". */
  companyId: string | null;
}

/** Each holder with the universe company the API resolved it to, if any. */
export function holderView(holders: readonly Pick<Holder, "name" | "company_id">[]): HolderView[] {
  return holders.map((holder) => ({ name: holder.name, companyId: holder.company_id }));
}

/** "AXT, Sumitomo Electric +1": up to two names, then the rest counted. */
export function holderNames(holders: readonly Pick<Holder, "name">[], shown = 2): string | null {
  if (holders.length === 0) return null;
  const names = holders.slice(0, shown).map((each) => each.name).join(", ");
  return holders.length > shown ? `${names} +${holders.length - shown}` : names;
}

/** A board row's second line, left: holders, layer, crowding, relief, each omitted when absent. */
export function rowSecondary(
  cp: Pick<Chokepoint, "holders" | "layer" | "crowding" | "relief_horizon">,
): string[] {
  return [
    holderNames(cp.holders),
    cp.layer ? layerName(cp.layer) : null,
    cp.crowding ? CROWDING_WORDS[cp.crowding].word : null,
    cp.relief_horizon ? `relief ${clampWords(cp.relief_horizon.horizon)}` : null,
  ].filter((part): part is string => part !== null);
}

// --- the history, as sentences ---------------------------------------------------------------

const STEP_OF_LETTER: Record<string, StepName> = {
  a: "constraint",
  b: "demand_vs_supply",
  c: "relief",
  d: "control",
  e: "capture",
  f: "invalidation",
};

/** A payload's step, by letter or name, as a step name. */
function stepNameOf(value: unknown): StepName | null {
  if (typeof value !== "string") return null;
  if (value in STEP_OF_LETTER) return STEP_OF_LETTER[value] ?? null;
  return (ARGUMENT_ORDER as readonly string[]).includes(value) ? (value as StepName) : null;
}

const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);

const statusWord = (value: unknown) =>
  typeof value === "string" && value in CHOKEPOINT_WORDS
    ? CHOKEPOINT_WORDS[value as keyof typeof CHOKEPOINT_WORDS].word
    : humanise(String(value));

const stepWord = (value: unknown) =>
  typeof value === "string" && value in STEP_STATUS_WORDS
    ? STEP_STATUS_WORDS[value as StepStatusName].word.toLowerCase()
    : humanise(String(value)).toLowerCase();

function fieldSentences(payload: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (key === "constraint") out.push(`Renamed: ${String(value)}`);
    else if (key === "layer") out.push(`Layer: ${layerName(String(value))}`);
    else if (key === "holders") out.push(`Holders set (${count(value)})`);
    else if (key === "kill_criteria") out.push(`Falsifiers rewritten (${count(value)})`);
    else if (key === "issue_ids") out.push(`Open questions set (${count(value)})`);
    else if (key === "add_issue_ids") out.push(`Open questions added (${count(value)})`);
    else if (key === "relief_horizon") {
      const horizon = (value as { horizon?: unknown } | null)?.horizon;
      out.push(typeof horizon === "string" ? `Relief: ${horizon}` : "Relief horizon cleared");
    } else if (key === "crowding") {
      out.push(
        typeof value === "string" && value in CROWDING_WORDS
          ? `Crowding: ${CROWDING_WORDS[value as keyof typeof CROWDING_WORDS].word}`
          : "Crowding cleared",
      );
    } else out.push(`${humanise(key)} set`);
  }
  return out;
}

export interface HistoryRow {
  at: string;
  text: string;
  actor: string;
  sessionId: string | null;
  eventId: string;
}

/** The events, oldest first, each as a sentence that knows the value before it: the replay
 * keeps each step's and the status's previous value. */
export function historyRows(events: readonly ChokepointEvent[]): HistoryRow[] {
  const steps = new Map<StepName, unknown>();
  let status: unknown = "lead";
  return events.map((event) => {
    const payload = event.payload as Record<string, unknown>;
    let text: string;
    if (event.kind === "created") {
      const holders = count(payload.holders);
      const layer = typeof payload.layer === "string" ? layerName(payload.layer) : null;
      text = [`Created${layer ? ` at ${layer}` : ""}`, holders > 0 ? `held by ${holders}` : null]
        .filter(Boolean)
        .join(", ");
    } else if (event.kind === "step_set") {
      const name = stepNameOf(payload.step);
      const before = name ? (steps.get(name) ?? "unexamined") : "unexamined";
      if (name) steps.set(name, payload.status);
      text = `${name ? STEP_LABELS[name] : "A step"}: ${stepWord(before)} → ${stepWord(payload.status)}`;
    } else if (event.kind === "status_set") {
      const before = status;
      status = payload.status;
      text = `Status: ${statusWord(before)} → ${statusWord(payload.status)}`;
    } else if (event.kind === "field_set") {
      text = fieldSentences(payload).join("; ");
    } else {
      text = `Note: ${typeof payload.text === "string" ? payload.text : ""}`;
    }
    if (event.reason) text = `${text} · why: ${event.reason}`;
    return { at: event.at, text, actor: event.actor, sessionId: event.session_id, eventId: event.id };
  });
}

// --- a step on the page --------------------------------------------------------------------

export interface StepView {
  name: StepName;
  /** The section's name: `STEPS` (step f is "What would invalidate it"). */
  title: string;
  state: StepState | null;
  word: Word;
  mark: string;
  against: boolean;
  counts: string;
  examined: boolean;
}

/** The page's six steps, four for the thesis then the two against it. */
export function stepViews(cp: Pick<Chokepoint, "steps">): StepView[] {
  const byName = stepsByName(cp.steps);
  return ARGUMENT_ORDER.map((name) => {
    const state = byName.get(name) ?? null;
    const status = state?.status ?? "unexamined";
    return {
      name,
      title: STEPS[name],
      state,
      word: STEP_STATUS_WORDS[status],
      mark: STEP_MARKS[status],
      against: isAgainst(name),
      counts: state ? stepCounts(state) : "",
      examined: status !== "unexamined",
    };
  });
}
