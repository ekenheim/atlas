"use client";

// The agents: what each did this week, and each run as a sentence about what it came to. The
// held-out runs of the scorecard are left out of the counts and the list. The table of every run,
// with model, cost and exact times, is in the Records.
import Link from "next/link";

import { RecordsFold } from "../../components/records-fold";
import { Load, Missing } from "../../components/ui";
import { api, type SessionSummary } from "../../lib/api/client";
import { activity } from "../../lib/format";
import { routes } from "../../lib/routes";
import { collapseRuns, costText, KINDS, newestFirst, outcomeText } from "../../lib/sessions";
import { AGENTS, agentOf, agentParts, agentsWeek } from "../../lib/today";
import { useApi } from "../../lib/use-api";

export default function SessionsPage() {
  const sessions = useApi("sessions", api.sessions);
  return (
    <>
      <h1>Sessions</h1>
      <Load loaded={sessions} what="sessions">
        {(page) => <Agents sessions={page.items} />}
      </Load>
    </>
  );
}

function Agents({ sessions }: { sessions: SessionSummary[] }) {
  const now = new Date();
  const week = agentsWeek(sessions, now);
  const runs = collapseRuns(sessions.filter((each) => !each.isolated));
  return (
    <>
      {sessions.length === 0 ? <p>No sessions yet.</p> : null}
      {week.length > 0 ? (
        <ul className="agent-strip" aria-label="This week">
          {week.map((each) => (
            <li key={each.agent} className="strip-cell">
              <span className="strip-step">{AGENTS[each.agent]}</span>
              <span className="strip-count">{agentParts(each).join(" · ")}</span>
            </li>
          ))}
        </ul>
      ) : sessions.length > 0 ? (
        <p className="muted">No run this week.</p>
      ) : null}

      {runs.length > 0 ? (
        <ul className="reader-rows agent-rows" aria-label="Runs, newest first">
          {runs.map((group) => (
            <li className="reader-row" key={group.session.id}>
              <div>
                <div className="row-title">
                  <Link href={routes.session(group.session.id)}>
                    {AGENTS[agentOf(group.session)]} · {outcomeText(group.session)} ·{" "}
                    {activity(group.session.started_at, now)}
                    {group.runs > 1 ? ` · ×${group.runs}` : ""}
                  </Link>
                </div>
                <div className="reader-row-sub issue-parent" title={group.session.question}>
                  {group.session.question}
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <RecordsFold>
        {sessions.length === 0 ? null : (
          <table>
            <caption>Research sessions, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col">Kind</th>
                <th scope="col">Model</th>
                <th scope="col">As of</th>
                <th scope="col">Facts</th>
                <th scope="col">Cost</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {newestFirst(sessions).map((session) => (
                <tr key={session.id}>
                  <td>
                    <Link href={routes.session(session.id)}>{session.question}</Link>
                    {session.isolated ? <span className="muted-small"> · held out</span> : null}
                  </td>
                  <td>{KINDS[session.kind]}</td>
                  <td>{session.model ?? <Missing />}</td>
                  <td>{session.as_of.slice(0, 10)}</td>
                  <td>{session.facts}</td>
                  <td>{costText(session.usage)}</td>
                  <td>
                    <time dateTime={session.started_at}>{session.started_at.slice(0, 10)}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </RecordsFold>
    </>
  );
}
