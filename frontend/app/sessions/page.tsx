"use client";

import Link from "next/link";

import { Load, Missing } from "../../components/ui";
import { api } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { costText, KINDS, newestFirst } from "../../lib/sessions";
import { useApi } from "../../lib/use-api";

export default function SessionsPage() {
  const sessions = useApi("sessions", api.sessions);
  return (
    <>
      <h1>Sessions</h1>
      <p>Each run of research on a question, as of a date: what it found and what it cost.</p>
      <Load loaded={sessions} what="sessions">
        {(page) =>
          page.items.length === 0 ? (
            <p>No sessions yet.</p>
          ) : (
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
                {newestFirst(page.items).map((session) => (
                  <tr key={session.id}>
                    <td>
                      <Link href={routes.session(session.id)}>{session.question}</Link>
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
          )
        }
      </Load>
    </>
  );
}
