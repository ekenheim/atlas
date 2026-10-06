// The reader's theme index: each theme's research questions, the same question asked
// several times collapsed into one row that shows the latest run.
import type { Hypothesis, InvestigationSummary } from "./api/client";

/** A run's state in the reader's words. */
export function statusWords(run: Pick<InvestigationSummary, "status" | "stop_reason">): string {
  if (run.status === "running") return "Running";
  switch (run.stop_reason) {
    case "answered":
      return "Answered";
    case "needs_review":
      return "Draft · needs review";
    case "budget_exhausted":
      return "Stopped early";
    case "no_new_independent_evidence":
      return "No new evidence";
    case "premise_disproven":
      return "Premise disproven";
    default:
      return "Stopped";
  }
}

/** One question of a theme: its latest run and how many times it was asked. */
export type QuestionRow = {
  question: string;
  latest: InvestigationSummary;
  runs: number;
  /** Every run of the question, so a Hypothesis of an older run is still found. */
  runIds: string[];
};

/** A theme id with its questions, the most recently asked first. */
export type ThemeQuestions = { theme: string; rows: QuestionRow[] };

/** Case, spacing and a closing full stop or question mark do not make a different question. */
export function questionKey(question: string): string {
  return question.trim().replace(/\s+/g, " ").replace(/[.?!]+$/, "").toLowerCase();
}

/**
 * The runs grouped by theme, then by question. Every theme in `themeIds` comes first in that
 * order, even with no runs; a run's theme not listed there follows. Rows are newest-first by
 * their latest run.
 */
export function researchIndex(
  runs: readonly InvestigationSummary[],
  themeIds: readonly string[],
): ThemeQuestions[] {
  const byTheme = new Map<string, Map<string, QuestionRow>>();
  for (const id of themeIds) byTheme.set(id, new Map());
  for (const run of runs) {
    const rows = byTheme.get(run.theme) ?? new Map<string, QuestionRow>();
    byTheme.set(run.theme, rows);
    const key = questionKey(run.question);
    const row = rows.get(key);
    if (!row) rows.set(key, { question: run.question.trim(), latest: run, runs: 1, runIds: [run.id] });
    else {
      row.runs += 1;
      row.runIds.push(run.id);
      if (Date.parse(run.created_at) > Date.parse(row.latest.created_at)) {
        row.latest = run;
        row.question = run.question.trim();
      }
    }
  }
  return [...byTheme].map(([theme, rows]) => ({
    theme,
    rows: [...rows.values()].sort(
      (a, b) => Date.parse(b.latest.created_at) - Date.parse(a.latest.created_at),
    ),
  }));
}

/** "2 runs" for a question asked more than once; nothing for one. */
export function runsLabel(runs: number): string | null {
  return runs > 1 ? `${runs} runs` : null;
}

/** The date of a timestamp (UTC), as `2026-10-06`. */
export function dayOf(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** The questions a company was a seed of, the same question collapsed to its latest run. */
export function companyQuestions(
  runs: readonly InvestigationSummary[],
  companyId: string,
): QuestionRow[] {
  const seeded = runs.filter((run) => run.seed_company_ids.includes(companyId));
  return researchIndex(seeded, [])
    .flatMap((entry) => entry.rows)
    .sort((a, b) => Date.parse(b.latest.created_at) - Date.parse(a.latest.created_at));
}

/** A pill's colour class: colour only for what needs a look; a running run is quiet. */
export function statusTone(
  run: Pick<InvestigationSummary, "status" | "stop_reason">,
): "reader-supported" | "reader-unknown" | "reader-review" {
  if (run.status === "running") return "reader-unknown";
  switch (run.stop_reason) {
    case "answered":
      return "reader-supported";
    case "needs_review":
    case "budget_exhausted":
    case "no_new_independent_evidence":
      return "reader-review";
    default:
      return "reader-unknown";
  }
}

/** A Hypothesis of a question: its id, status and the latest version's thesis. */
export type HypothesisLine = { id: string; status: Hypothesis["status"]; thesis: string; updatedAt: string };

/** The Hypotheses by the investigation they came from; the most recently updated one wins. */
export function hypothesisByInvestigation(
  hypotheses: readonly Hypothesis[],
): Map<string, HypothesisLine> {
  const map = new Map<string, HypothesisLine>();
  for (const h of hypotheses) {
    const version =
      h.versions.find((v) => v.version === h.latest_version) ??
      [...h.versions].sort((a, b) => b.version - a.version)[0];
    const thesis = version?.content.thesis_statement.trim();
    if (!thesis) continue;
    const held = map.get(h.investigation_id);
    if (held && Date.parse(held.updatedAt) >= Date.parse(h.updated_at)) continue;
    map.set(h.investigation_id, { id: h.id, status: h.status, thesis, updatedAt: h.updated_at });
  }
  return map;
}

/** A question's latest result: the Hypothesis's thesis once one exists, else a draft. */
export type RowResult =
  | { kind: "hypothesis"; thesis: string; id: string; status: Hypothesis["status"] }
  | { kind: "draft"; words: string };

/** A Hypothesis's status in the reader's words: "paper_tracking" is "Paper tracking". */
export function hypothesisWords(status: Hypothesis["status"]): string {
  const words = status.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function rowResult(row: QuestionRow, byRun: ReadonlyMap<string, HypothesisLine>): RowResult {
  let best: HypothesisLine | undefined;
  for (const runId of row.runIds) {
    const line = byRun.get(runId);
    if (line && (!best || Date.parse(line.updatedAt) > Date.parse(best.updatedAt))) best = line;
  }
  if (best) return { kind: "hypothesis", thesis: best.thesis, id: best.id, status: best.status };
  const words = statusWords(row.latest);
  return { kind: "draft", words: words === "Answered" ? "Draft" : words };
}
