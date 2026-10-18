"use client";

// Today: what Atlas believes per theme and how sure it is, what changed since the last visit,
// what is due, what the Watch found, and whether Atlas is working. Every read loads at once and a
// failed one costs only its own slot. Nothing here is a record: those are one click deeper.
import Link from "next/link";
import { useEffect, useState } from "react";

import { ThemeCard } from "../components/theme-card";
import { DueList } from "../components/due-list";
import { WatchSection } from "../components/watch-section";
import {
  api,
  type BeliefSummary,
  type Call,
  type Chokepoint,
  type Prediction,
  type ThemeSummary,
  type WatchRun,
} from "../lib/api/client";
import { activity } from "../lib/format";
import { routes } from "../lib/routes";
import { readMark, startMarking, isUnseen } from "../lib/seen";
import { changeHref, changeLabel } from "../lib/themes";
import {
  agentsLine,
  agentsWeek,
  orderThemes,
  recordLine,
  selectChanges,
  themeBeliefs,
} from "../lib/today";
import { type Loaded, useApi } from "../lib/use-api";
import { useDecideCount } from "../lib/use-decide-count";
import { todayCards, watchRows } from "../lib/watch";

const loadThemes = () => api.themes();
const loadHypotheses = async () => (await api.hypotheses()).items;
const loadBeliefs = async () => (await api.beliefs({ status: "active" })).items;
const loadCalls = async () => (await api.allCalls("open")).items;
const loadPredictions = async () => (await api.predictions("open")).items;
const loadSessions = async () => (await api.sessions()).items;
const loadLeads = async () =>
  (await api.calendarLeads(new Date().toISOString().slice(0, 10))).items;
const loadBoard = async () => (await api.chokepoints({ limit: 500 })).items;
const loadRuns = async () => (await api.watchRuns({ limit: 200 })).items;

export default function TodayPage() {
  const themes = useApi("themes", loadThemes);
  const hypotheses = useApi("hypotheses", loadHypotheses);
  const beliefs = useApi("beliefs", loadBeliefs);
  const calls = useApi("calls", loadCalls);
  const predictions = useApi("predictions", loadPredictions);
  const sessions = useApi("sessions", loadSessions);
  const leads = useApi("leads", loadLeads);
  const board = useApi("board", loadBoard);
  const runs = useApi("watch-runs", loadRuns);
  const decide = useDecideCount();

  // The previous visit's mark is read once, when the page mounts, and drives the dots; this
  // visit is marked when the tab is hidden or after ten seconds visible.
  const [mark] = useState<Date | null>(() => readMark());
  useEffect(() => startMarking(), []);

  return (
    <div className="today">
      <h1 className="sr-only">Today</h1>
      {decide ? (
        <p className="decision-banner">
          <Link href={routes.decide}>
            {decide === 1 ? "1 decision waits on you" : `${decide} decisions wait on you`}{" "}
            <span aria-hidden="true">→</span>
          </Link>
        </p>
      ) : null}

      <Cards
        themes={themes}
        hypotheses={hypotheses}
        beliefs={beliefs}
        calls={calls}
        predictions={predictions}
        leads={leads}
        board={board}
        runs={runs}
        mark={mark}
      />

      <Watch themes={themes} beliefs={beliefs} board={board} runs={runs} mark={mark} />
      <AgentsLine sessions={sessions} />
      <RecordLine calls={calls} predictions={predictions} />
    </div>
  );
}

function Cards({
  themes,
  hypotheses,
  beliefs,
  calls,
  predictions,
  leads,
  board,
  runs,
  mark,
}: {
  themes: Loaded<ThemeSummary[]>;
  hypotheses: Loaded<Awaited<ReturnType<typeof loadHypotheses>>>;
  beliefs: Loaded<BeliefSummary[]>;
  calls: Loaded<Call[]>;
  predictions: Loaded<Prediction[]>;
  leads: Loaded<Awaited<ReturnType<typeof loadLeads>>>;
  board: Loaded<Chokepoint[]>;
  runs: Loaded<WatchRun[]>;
  mark: Date | null;
}) {
  if (themes.state === "loading") {
    return (
      <div className="cards" aria-busy="true">
        <div className="theme-card theme-card-skeleton">
          <span className="sk sk-title" />
          <span className="sk sk-thesis" />
          <span className="sk sk-line" />
          <span className="sk sk-strip" />
        </div>
      </div>
    );
  }
  if (themes.state === "error") return <p role="alert">Could not load the themes.</p>;
  if (themes.data.length === 0) return <p className="muted">No theme yet.</p>;
  const starting = new Set(
    beliefs.state === "ready"
      ? themes.data.filter((each) => themeBeliefs(beliefs.data, each.id).length === 0).map((each) => each.id)
      : [],
  );
  // A theme the Watch has begun on but nothing is believed of yet has its Watch row, not a card;
  // the board and the runs count as empty while they load or when they fail.
  const carded = todayCards(
    orderThemes(themes.data, starting),
    beliefs.state === "ready" ? beliefs.data : null,
    board.state === "ready" ? board.data : [],
    runs.state === "ready" ? runs.data : [],
  );
  return (
    <div className="cards">
      {carded.map((theme) => (
        <TodayCard
          key={theme.id}
          theme={theme}
          hypotheses={hypotheses}
          beliefs={beliefs}
          calls={calls}
          predictions={predictions}
          leads={leads}
          mark={mark}
        />
      ))}
    </div>
  );
}

function TodayCard({
  theme,
  hypotheses,
  beliefs,
  calls,
  predictions,
  leads,
  mark,
}: {
  theme: ThemeSummary;
  hypotheses: Loaded<Awaited<ReturnType<typeof loadHypotheses>>>;
  beliefs: Loaded<BeliefSummary[]>;
  calls: Loaded<Call[]>;
  predictions: Loaded<Prediction[]>;
  leads: Loaded<Awaited<ReturnType<typeof loadLeads>>>;
  mark: Date | null;
}) {
  const changes = useApi(theme.id, api.themeChanges);
  const now = new Date();
  const view = changes.state === "ready" ? selectChanges(changes.data, mark, now, 3) : null;
  const starting = beliefs.state === "ready" && themeBeliefs(beliefs.data, theme.id).length === 0;
  const statements = new Map(beliefs.state === "ready" ? beliefs.data.map((each) => [each.id, each.statement]) : []);
  const statementOf = (id: string) => statements.get(id);
  return (
    <ThemeCard
      theme={theme}
      hypotheses={hypotheses}
      beliefs={beliefs}
      unseen={view?.unseen ?? 0}
      extra={
        starting ? null : (
          <div className="card-columns">
            <section aria-label="Changes">
              <h3 className="reader-label">{view?.label ?? "This week"}</h3>
              {changes.state === "error" ? (
                <p className="muted">Changes unavailable</p>
              ) : view === null ? (
                <span className="sk sk-line" />
              ) : view.shown.length === 0 ? (
                <p className="muted">Nothing changed.</p>
              ) : (
                <>
                  <ul className="reader-rows change-rows" aria-label="Changes, newest first">
                    {view.shown.map((change, index) => {
                      const href = changeHref(change);
                      const unseen = isUnseen(change.at, mark);
                      const label = changeLabel(change, statementOf);
                      return (
                        <li className="reader-row change-row" key={`${change.at}-${index}`}>
                          <div>
                            <div className="row-title">
                              {unseen ? <span className="unseen-dot" aria-label="new" /> : null}
                              {href ? <Link href={href}>{label}</Link> : label}
                            </div>
                            <div className="reader-row-sub">{activity(change.at, now)}</div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                  {view.more > 0 ? (
                    <p className="card-more">
                      <Link href={routes.theme(theme.id)}>+{view.more} more</Link>
                    </p>
                  ) : null}
                </>
              )}
            </section>
            <section aria-label="Due">
              <h3 className="reader-label">Due</h3>
              {calls.state === "error" || predictions.state === "error" ? (
                <p className="muted">Due unavailable</p>
              ) : calls.state === "loading" || predictions.state === "loading" ? (
                <span className="sk sk-line" />
              ) : (
                <DueList
                  calls={calls.data.filter((call) => call.theme === theme.id)}
                  predictions={predictions.data.filter((each) => each.theme === theme.id)}
                  leads={leads.state === "ready" ? leads.data : undefined}
                  theme={theme.id}
                  limit={3}
                  now={now}
                />
              )}
            </section>
          </div>
        )
      }
    />
  );
}

/** The Watch's rows, once the board and the runs have answered; nothing while they load, when
 * both fail, or when no theme is watched (the shipping state). */
function Watch({
  themes,
  beliefs,
  board,
  runs,
  mark,
}: {
  themes: Loaded<ThemeSummary[]>;
  beliefs: Loaded<BeliefSummary[]>;
  board: Loaded<Chokepoint[]>;
  runs: Loaded<WatchRun[]>;
  mark: Date | null;
}) {
  if (board.state === "loading" || runs.state === "loading") return null;
  const listed = themes.state === "ready" ? themes.data : [];
  const starting = new Set(
    beliefs.state === "ready"
      ? listed.filter((each) => themeBeliefs(beliefs.data, each.id).length === 0).map((each) => each.id)
      : [],
  );
  const now = new Date();
  const rows = watchRows(
    orderThemes(listed, starting),
    board.state === "ready" ? board.data : [],
    runs.state === "ready" ? runs.data : [],
    mark,
    now,
  );
  return <WatchSection rows={rows} now={now} />;
}

function AgentsLine({ sessions }: { sessions: Loaded<Awaited<ReturnType<typeof loadSessions>>> }) {
  if (sessions.state !== "ready") return null;
  const week = agentsWeek(sessions.data, new Date());
  if (week.length === 0) return null;
  return (
    <p className="today-line">
      <Link href={routes.sessions}>
        {agentsLine(week)} <span aria-hidden="true">→</span>
      </Link>
    </p>
  );
}

function RecordLine({ calls, predictions }: { calls: Loaded<Call[]>; predictions: Loaded<Prediction[]> }) {
  if (calls.state !== "ready" || predictions.state !== "ready") return null;
  const line = recordLine(calls.data, predictions.data, new Date());
  if (line === null) return null;
  return (
    <p className="today-line">
      <Link href={routes.record}>
        {line} <span aria-hidden="true">→</span>
      </Link>
    </p>
  );
}
