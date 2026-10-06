// The reader's theme index: each theme's research questions, the same question asked
// several times collapsed into one row that shows the latest run.
import type { InvestigationSummary } from "./api/client";

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
    if (!row) rows.set(key, { question: run.question.trim(), latest: run, runs: 1 });
    else {
      row.runs += 1;
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
  return researchIndex(seeded, []).flatMap((entry) => entry.rows);
}
