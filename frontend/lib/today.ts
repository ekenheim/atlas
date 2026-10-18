// What Today and Themes show for a theme, put together from reads that each load on their own: the
// theme, its Hypotheses, its active Beliefs, what changed. Pure, so each rule is tested.
import type {
  BeliefSummary,
  Call,
  Hypothesis,
  HypothesisVersion,
  Prediction,
  SessionSummary,
  ThemeChange,
  ThemeSummary,
} from "./api/client";
import { type StepArgument, type Weakest, argumentOf, weakestStep } from "./argument";
import { dueRows } from "./due";
import { isoDay, plainDay } from "./format";
import { COMPANY_LAYERS } from "./relationships";
import { isUnseen, windowStart } from "./seen";
import { type ThesisCheckWord, publishedVersion, thesisCheckWord } from "./status";
import { themeHypotheses } from "./themes";
import { draftedProposition, proposition } from "./thesis";

export interface CardModel {
  themeId: string;
  title: string;
  /** No active Belief yet: the card says so in one line. */
  starting: boolean;
  hypothesis: Hypothesis | null;
  /** The version the card reads: the latest published one, else the latest draft. */
  version: HypothesisVersion | null;
  published: boolean;
  /** "Published 18 Oct", "Draft", or null for a starting theme. */
  lifecycle: { text: string; tone: "ok" | "muted" } | null;
  check: ThesisCheckWord | null;
  /** The thesis's proposition; null when there is no thesis. */
  proposition: string | null;
  steps: StepArgument<BeliefSummary>[];
  weakest: Weakest | null;
  beliefCount: number;
  provenCount: number;
  /** An investigation-backed Hypothesis has findings instead of steps. */
  findings: number | null;
  /** The theme's other Hypotheses that are drafts (not the one shown). */
  otherDrafts: number;
}

/** The Hypothesis a theme leads with: the published one (newest publication first), else the
 * most recently changed draft that has a version to read. */
export function leadHypothesis(hypotheses: readonly Hypothesis[], theme: string): {
  hypothesis: Hypothesis | null;
  version: HypothesisVersion | null;
  published: boolean;
  otherDrafts: number;
} {
  const mine = themeHypotheses(hypotheses, theme);
  const hypothesis = mine.find((each) => each.versions.length > 0) ?? null;
  if (hypothesis === null) return { hypothesis: null, version: null, published: false, otherDrafts: 0 };
  const published = publishedVersion(hypothesis);
  const version = published ?? hypothesis.versions.at(-1) ?? null;
  const otherDrafts = mine.filter(
    (each) => each.id !== hypothesis.id && !each.versions.some((v) => v.published),
  ).length;
  return { hypothesis, version, published: published !== null, otherDrafts };
}

/** The Beliefs a theme's cards read: its active ones. */
export const themeBeliefs = (beliefs: readonly BeliefSummary[], theme: string) =>
  beliefs.filter((each) => each.theme === theme && each.status === "active");

export function buildCard(
  theme: ThemeSummary,
  hypotheses: readonly Hypothesis[],
  beliefs: readonly BeliefSummary[],
  now: Date = new Date(),
): CardModel {
  const mine = themeBeliefs(beliefs, theme.id);
  const steps = argumentOf(mine);
  const { hypothesis, version, published, otherDrafts } = leadHypothesis(hypotheses, theme.id);
  const starting = mine.length === 0;
  const hasSteps = (version?.content.steps ?? []).length > 0;
  const lifecycle = starting
    ? null
    : published && version
      ? { text: `Published ${plainDay(version.published_at, now)}`, tone: "ok" as const }
      : version
        ? { text: "Draft", tone: "muted" as const }
        : null;
  return {
    themeId: theme.id,
    title: theme.title,
    starting,
    hypothesis,
    version,
    published,
    lifecycle,
    check: version ? thesisCheckWord(version) : null,
    proposition: version
      ? proposition(version.content.thesis_statement, draftedProposition(version.content))
      : null,
    steps,
    weakest: starting ? null : weakestStep(steps),
    beliefCount: mine.length,
    provenCount: mine.filter((each) => each.judgement.judgement === "proven").length,
    findings: version && !hasSteps ? version.content.findings.length : null,
    otherDrafts,
  };
}

/** The day of the newest document any active Belief of the theme cites (ISO), or null. */
export function newestEvidence(
  beliefs: readonly Pick<BeliefSummary, "status" | "newest_evidence_at">[],
): string | null {
  const days = beliefs
    .filter((each) => each.status === "active" && each.newest_evidence_at)
    .map((each) => each.newest_evidence_at as string)
    .sort();
  return days.at(-1) ?? null;
}

/** Themes in the order the API gives them (theme config order), starting themes last. */
export function orderThemes<T extends { id: string }>(
  themes: readonly T[],
  startingIds: ReadonlySet<string>,
): T[] {
  return [...themes.filter((each) => !startingIds.has(each.id)), ...themes.filter((each) => startingIds.has(each.id))];
}

// --- a theme's coverage, in a line --------------------------------------------------------

export function withDocuments(theme: Pick<ThemeSummary, "company_count" | "companies_without_sources">): number {
  return Math.max(0, theme.company_count - theme.companies_without_sources);
}

const layers = (count: number) => `${count} ${count === 1 ? "layer" : "layers"}`;

/** "Starting · 0 of 7 companies have documents · 4 layers without a company". */
export function startingLine(theme: ThemeSummary): string {
  return (
    `Starting · ${withDocuments(theme)} of ${theme.company_count} companies have documents` +
    ` · ${layers(theme.empty_layers.length)} without a company`
  );
}

/** The Theme page's longer form, naming the layers. */
export function startingStatus(theme: ThemeSummary): string {
  const names = theme.empty_layers.map((layer) => COMPANY_LAYERS[layer]).join(", ");
  return (
    `Starting · ${withDocuments(theme)} of ${theme.company_count} companies have documents in the archive` +
    ` · ${layers(theme.empty_layers.length)} without a company${names ? ` (${names})` : ""}`
  );
}

/** "12 companies · 11 with documents · 0 layers empty": the Themes card's extra line. */
export function coverageLine(theme: ThemeSummary): string {
  return (
    `${theme.company_count} ${theme.company_count === 1 ? "company" : "companies"}` +
    ` · ${withDocuments(theme)} with documents · ${theme.empty_layers.length} ${theme.empty_layers.length === 1 ? "layer" : "layers"} empty`
  );
}

// --- what changed ----------------------------------------------------------------------------

/** Changes that matter most are met first: a Belief disproven, superseded or withdrawn, or one
 * flagged. Then the newest. */
export function changeWeight(change: Pick<ThemeChange, "kind" | "text">): 0 | 1 {
  if (change.kind === "flagged") return 0;
  return /^(disproven|superseded|withdrawn)\b/i.test(change.text) ? 0 : 1;
}

/** A theme's changes for its own page: inside the window (since the last visit, or the week)
 * the important ones first and then the newest; what is older follows, newest first. */
export function orderChanges(
  changes: readonly ThemeChange[],
  mark: Date | null,
  now: Date,
): ThemeChange[] {
  const start = windowStart(mark, now).getTime();
  const inside = (change: ThemeChange) => new Date(change.at).getTime() >= start;
  const newest = (a: ThemeChange, b: ThemeChange) => b.at.localeCompare(a.at);
  return [
    ...changes.filter(inside).sort((a, b) => changeWeight(a) - changeWeight(b) || newest(a, b)),
    ...changes.filter((change) => !inside(change)).sort(newest),
  ];
}

export interface ChangeView {
  /** "Since last visit", or "This week" with no mark. */
  label: string;
  shown: ThemeChange[];
  /** How many more fall in the window. */
  more: number;
  /** How many in the window are newer than the mark (none without a mark). */
  unseen: number;
}

/** The changes inside the window (the mark, or seven days back), important ones first, then
 * the newest, at most `limit`. */
export function selectChanges(
  changes: readonly ThemeChange[],
  mark: Date | null,
  now: Date,
  limit: number,
): ChangeView {
  const start = windowStart(mark, now).getTime();
  const inWindow = changes
    .filter((change) => new Date(change.at).getTime() >= start)
    .sort((a, b) => changeWeight(a) - changeWeight(b) || b.at.localeCompare(a.at));
  return {
    label: mark === null ? "This week" : "Since last visit",
    shown: inWindow.slice(0, limit),
    more: Math.max(0, inWindow.length - limit),
    unseen: inWindow.filter((change) => isUnseen(change.at, mark)).length,
  };
}

// --- the lines under the cards ---------------------------------------------------------------

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

export type AgentName = SessionSummary["agent"];

/** The agents in the order the line reads them. */
export const AGENTS: Record<AgentName, string> = {
  scout: "Scout",
  researcher: "Researcher",
  skeptic: "Skeptic",
  editor: "Editor",
  lead: "Lead",
};

export interface AgentWeek {
  agent: AgentName;
  runs: number;
  facts: number;
  beliefsProposed: number;
  /** Beliefs the runs examined, whatever they found. */
  examined: number;
  issuesOpened: number;
  /** Runs that added nothing: no Fact, Belief or Issue, and no examination that found anything. */
  nothingNew: number;
}

const examinedTotal = (session: SessionSummary) => {
  const each = session.beliefs_examined;
  return each.confirmed + each.qualified + each.contradicted + each.nothing_new;
};

const addedSomething = (session: SessionSummary) =>
  session.facts > 0 ||
  session.beliefs_proposed > 0 ||
  (session.issues_opened ?? 0) > 0 ||
  session.beliefs_examined.confirmed +
    session.beliefs_examined.qualified +
    session.beliefs_examined.contradicted >
    0;

/** The week's runs by agent, in the line's order, leaving out the held-out runs of the
 * scorecard and any agent with no run. */
export function agentsWeek(sessions: readonly SessionSummary[], now: Date): AgentWeek[] {
  const since = now.getTime() - 7 * 86_400_000;
  const week = sessions.filter(
    (session) => !session.isolated && new Date(session.started_at).getTime() >= since,
  );
  return (Object.keys(AGENTS) as AgentName[])
    .map((agent) => {
      const mine = week.filter((session) => session.agent === agent);
      return {
        agent,
        runs: mine.length,
        facts: mine.reduce((sum, session) => sum + session.facts, 0),
        beliefsProposed: mine.reduce((sum, session) => sum + session.beliefs_proposed, 0),
        examined: mine.reduce((sum, session) => sum + examinedTotal(session), 0),
        issuesOpened: mine.reduce((sum, session) => sum + (session.issues_opened ?? 0), 0),
        nothingNew: mine.filter((session) => !addedSomething(session)).length,
      };
    })
    .filter((each) => each.runs > 0);
}

/** "This week: Scout 3 runs · 7 Facts · Skeptic 4 runs · examined 6 Beliefs · 3 found nothing new". */
export function agentsLine(weeks: readonly AgentWeek[]): string {
  const parts = weeks.flatMap((week) => [`${AGENTS[week.agent]} ${agentParts(week).join(" · ")}`]);
  return `This week: ${parts.join(" · ")}`;
}

/** One agent's week in parts: "3 runs", "7 Facts", "1 found nothing new". */
export function agentParts(week: AgentWeek): string[] {
  return [
    plural(week.runs, "run"),
    ...(week.facts > 0 ? [plural(week.facts, "Fact")] : []),
    ...(week.beliefsProposed > 0 ? [`${plural(week.beliefsProposed, "Belief", "Beliefs")} proposed`] : []),
    ...(week.examined > 0 ? [`examined ${plural(week.examined, "Belief", "Beliefs")}`] : []),
    ...(week.issuesOpened > 0 ? [`${plural(week.issuesOpened, "Issue")} opened`] : []),
    ...(week.nothingNew > 0 ? [`${week.nothingNew} found nothing new`] : []),
  ];
}

/** "22 calls open · first checkpoint 18 Nov · 4 predictions due 30 Nov"; null when empty. */
export function recordLine(
  calls: readonly Call[],
  predictions: readonly Prediction[],
  now: Date,
): string | null {
  const open = calls.filter((call) => call.state !== "settled");
  const rows = dueRows({ calls: open, predictions, today: isoDay(now.toISOString()) });
  const checkpoint = rows.find((row) => row.kind === "calls");
  const deadline = rows.find((row) => row.kind === "predictions");
  const parts: string[] = [];
  if (open.length > 0) parts.push(`${plural(open.length, "call")} open`);
  if (checkpoint) parts.push(`first checkpoint ${plainDay(checkpoint.date, now)}`);
  const openPredictions = predictions.filter((each) => each.state === "open");
  if (openPredictions.length > 0 && deadline) {
    parts.push(`${plural(openPredictions.length, "prediction")} due ${plainDay(deadline.date, now)}`);
  }
  return parts.length === 0 ? null : parts.join(" · ");
}
