// The Watch across themes (spec §10.3.1, §10.3.2): which themes are watched, Today's Watch rows
// and cards, and which layout a theme's page takes. Keyed by theme slug: a watched theme need not
// be one of `/themes`. Pure, so each rule is tested.
import type { BeliefSummary, Chokepoint, ThemeSummary, WatchRun } from "./api/client";
import { type BoardCounts, boardCounts, boardLine, themeTitle } from "./chokepoints";
import { plainDay } from "./format";
import { memoExcerpt } from "./markdown";
import { isUnseen } from "./seen";
import { themeBeliefs } from "./today";

export interface LatestRuns {
  latest: WatchRun;
  /** The run before it, which opens the window "what is new" is read in; null for a first run. */
  previous: WatchRun | null;
}

const newestFirst = (a: WatchRun, b: WatchRun) => b.created_at.localeCompare(a.created_at);

/** Each theme's two newest runs. */
export function latestByTheme(runs: readonly WatchRun[]): Map<string, LatestRuns> {
  const out = new Map<string, LatestRuns>();
  for (const run of [...runs].sort(newestFirst)) {
    const seen = out.get(run.theme);
    if (seen === undefined) out.set(run.theme, { latest: run, previous: null });
    else if (seen.previous === null) seen.previous = run;
  }
  return out;
}

/** A theme is watched when it has a run, or a chokepoint that is not ruled out. */
export function watchedSlugs(
  board: readonly Pick<Chokepoint, "theme" | "status">[],
  runs: readonly Pick<WatchRun, "theme">[],
): Set<string> {
  return new Set([
    ...runs.map((run) => run.theme),
    ...board.filter((each) => each.status !== "killed").map((each) => each.theme),
  ]);
}

/** The Watch has stopped when its latest run is more than nine days old. */
export const STOPPED_AFTER_DAYS = 9;

export function stoppedWatch(run: Pick<WatchRun, "run_date">, now: Date = new Date()): boolean {
  const day = Date.parse(`${run.run_date.slice(0, 10)}T00:00:00Z`);
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return !Number.isNaN(day) && (today - day) / 86_400_000 > STOPPED_AFTER_DAYS;
}

export type NamedLabel = "Thesis-ready" | "New" | "Ruled out";

export interface NamedPart {
  label: NamedLabel;
  chokepoints: Chokepoint[];
}

export interface Named {
  parts: NamedPart[];
  /** The rest that could have been named. */
  more: number;
}

/**
 * What Today names on a theme's Watch row: the chokepoints that became thesis-ready (as their
 * current state, until W8's `status_set_at`), were spotted, or were ruled out since the previous
 * run (a first run has no lower bound), at most `shown`. Each chokepoint is named once, under the
 * first label that applies; within a label the API's order (latest event first) holds.
 */
export function namedOnBoard(
  board: readonly Chokepoint[],
  runs: Pick<LatestRuns, "previous"> | null,
  now: Date = new Date(),
  shown = 2,
): Named {
  const from = runs?.previous ? Date.parse(runs.previous.created_at) : Number.NEGATIVE_INFINITY;
  const to = now.getTime();
  const inside = (at: string) => {
    const time = Date.parse(at);
    return time > from && time <= to;
  };
  const rules: [NamedLabel, (cp: Chokepoint) => boolean][] = [
    ["Thesis-ready", (cp) => cp.status === "thesis_ready" && inside(cp.last_event_at)],
    ["New", (cp) => cp.status !== "killed" && inside(cp.created_at)],
    ["Ruled out", (cp) => cp.status === "killed" && inside(cp.last_event_at)],
  ];
  const taken = new Set<string>();
  const all: { label: NamedLabel; cp: Chokepoint }[] = [];
  for (const [label, applies] of rules) {
    for (const cp of board) {
      if (!taken.has(cp.id) && applies(cp)) {
        taken.add(cp.id);
        all.push({ label, cp });
      }
    }
  }
  const parts: NamedPart[] = [];
  for (const { label, cp } of all.slice(0, shown)) {
    const last = parts.at(-1);
    if (last?.label === label) last.chokepoints.push(cp);
    else parts.push({ label, chokepoints: [cp] });
  }
  return { parts, more: Math.max(0, all.length - shown) };
}

export interface WatchRow {
  slug: string;
  title: string;
  runs: LatestRuns | null;
  counts: BoardCounts;
  named: Named;
  /** The latest memo's first paragraph, plain; "" for none. */
  excerpt: string;
  unseen: boolean;
  stopped: boolean;
}

/** Today's Watch rows: in the cards' theme order, then the watched slugs `/themes` does not
 * list, alphabetically. Only watched themes have a row. */
export function watchRows(
  themes: readonly Pick<ThemeSummary, "id" | "title">[],
  board: readonly Chokepoint[],
  runs: readonly WatchRun[],
  mark: Date | null,
  now: Date = new Date(),
): WatchRow[] {
  const watched = watchedSlugs(board, runs);
  const latest = latestByTheme(runs);
  const listed = themes.map((each) => each.id).filter((slug) => watched.has(slug));
  const others = [...watched].filter((slug) => !themes.some((each) => each.id === slug)).sort();
  return [...listed, ...others].map((slug) => {
    const mine = board.filter((each) => each.theme === slug);
    const theirs = latest.get(slug) ?? null;
    return {
      slug,
      title: themeTitle(slug, themes),
      runs: theirs,
      counts: boardCounts(mine),
      named: namedOnBoard(mine, theirs, now),
      excerpt: theirs ? memoExcerpt(theirs.latest.memo) : "",
      unseen: theirs ? isUnseen(theirs.latest.created_at, mark) : false,
      stopped: theirs ? stoppedWatch(theirs.latest, now) : false,
    };
  });
}

/**
 * The themes Today gives a card (Z6): one with active Beliefs (its round-2 card); one with no
 * Belief, no chokepoint, no run and companies (the Starting card). A theme the Watch has begun
 * on but no Belief yet has only its Watch row. While the Beliefs are unknown (loading or failed)
 * a theme with companies keeps its card, as before.
 */
export function todayCards<T extends Pick<ThemeSummary, "id" | "company_count">>(
  themes: readonly T[],
  beliefs: readonly BeliefSummary[] | null,
  board: readonly Pick<Chokepoint, "theme">[],
  runs: readonly Pick<WatchRun, "theme">[],
): T[] {
  return themes.filter((theme) => {
    if (beliefs === null) return theme.company_count > 0;
    if (themeBeliefs(beliefs, theme.id).length > 0) return true;
    const onBoard = board.some((each) => each.theme === theme.id) || runs.some((run) => run.theme === theme.id);
    return !onBoard && theme.company_count > 0;
  });
}

export type ThemeLayout = "thesis" | "board" | "starting" | "missing";

/**
 * Which layout a theme's page takes, the first rule that applies: active Beliefs → the thesis;
 * any chokepoint (ruled out too) or a run → the board-led page; one of `/themes` → Starting;
 * otherwise it is not a theme. A failed read counts as empty (`null` Beliefs too).
 */
export function themeLayout(
  summary: Pick<ThemeSummary, "id"> | undefined,
  beliefs: readonly Pick<BeliefSummary, "theme" | "status">[] | null,
  board: readonly unknown[],
  runs: readonly unknown[],
): ThemeLayout {
  const active = summary && beliefs ? beliefs.filter((each) => each.theme === summary.id && each.status === "active") : [];
  if (active.length > 0) return "thesis";
  if (board.length > 0 || runs.length > 0) return "board";
  if (summary) return "starting";
  return "missing";
}

export interface ThemesCard<T> {
  slug: string;
  title: string;
  /** One of `/themes`, for its round-2 card; null for a watched slug `/themes` does not list. */
  theme: T | null;
  /** `Watching` or `Not started` instead of the round-2 card; null keeps that card. */
  watch: { watching: boolean; line: string } | null;
}

/**
 * The Themes page's cards: every theme of `/themes` keeps one, then the watched slugs it does not
 * list, alphabetically. A theme with no active Belief that the Watch is on reads `Watching` with
 * its last watch and board; one with no company and nothing watched reads `Not started`.
 */
export function themesCards<T extends Pick<ThemeSummary, "id" | "title" | "company_count">>(
  themes: readonly T[],
  beliefs: readonly BeliefSummary[] | null,
  board: readonly Chokepoint[],
  runs: readonly WatchRun[],
  now: Date = new Date(),
): ThemesCard<T>[] {
  const watched = watchedSlugs(board, runs);
  const latest = latestByTheme(runs);
  const watchLine = (slug: string) => {
    const run = latest.get(slug)?.latest;
    const parts = [
      run ? `last watch ${plainDay(run.run_date, now)}` : null,
      boardLine(boardCounts(board.filter((each) => each.theme === slug))) || null,
    ].filter((part): part is string => part !== null);
    return parts.join(" · ");
  };
  const listed = themes.map((theme): ThemesCard<T> => {
    const believed = beliefs !== null && themeBeliefs(beliefs, theme.id).length > 0;
    const watch =
      beliefs === null || believed
        ? null
        : watched.has(theme.id)
          ? { watching: true, line: watchLine(theme.id) }
          : theme.company_count === 0
            ? { watching: false, line: "The first watch has not run." }
            : null;
    return { slug: theme.id, title: theme.title, theme, watch };
  });
  const others = [...watched]
    .filter((slug) => !themes.some((each) => each.id === slug))
    .sort()
    .map((slug): ThemesCard<T> => ({
      slug,
      title: themeTitle(slug, themes),
      theme: null,
      watch: { watching: true, line: watchLine(slug) },
    }));
  return [...listed, ...others];
}
