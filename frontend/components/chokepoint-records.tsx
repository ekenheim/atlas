"use client";

// What a chokepoint's Records hold (spec §10.3.4, item 8), and nothing above them: its history as
// sentences with who wrote each and when exactly, the holders' CIKs linked to EDGAR, the closed
// questions it linked, and the session or run that created it. Rendered only inside the fold.
import Link from "next/link";

import { api, type ChokepointDetail, cikKey, type Issue } from "../lib/api/client";
import { historyRows } from "../lib/chokepoints";
import { evidenceDay, exactTime } from "../lib/format";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";

const loadIssues = async () => (await api.issues()).items;

/** A filer's page on EDGAR. */
export const edgarFiler = (cik: string) =>
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${encodeURIComponent(cikKey(cik))}`;

export function ChokepointRecords({ chokepoint }: { chokepoint: ChokepointDetail }) {
  const rows = historyRows(chokepoint.history);
  const issues = useApi("issues", loadIssues);
  const closed: Issue[] =
    issues.state === "ready"
      ? issues.data.filter((each) => chokepoint.issue_ids.includes(each.id) && each.status !== "active")
      : [];
  const withCik = chokepoint.holders.filter((holder) => holder.cik);
  return (
    <>
      <h2>History</h2>
      <ul className="reader-rows" aria-label="History, oldest first">
        {rows.map((row) => (
          <li className="reader-row" key={row.eventId}>
            <div>
              <div>
                {evidenceDay(row.at)} · {row.text}
              </div>
              <div className="reader-row-sub">
                by {row.actor}
                {row.sessionId ? (
                  <>
                    {" · "}
                    <Link href={routes.session(row.sessionId)}>session</Link>
                  </>
                ) : null}
                {" · "}
                <time dateTime={row.at}>{exactTime(row.at)}</time>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {withCik.length > 0 ? (
        <>
          <h2>Holders on EDGAR</h2>
          <ul>
            {withCik.map((holder) => (
              <li key={`${holder.name}-${holder.cik}`}>
                <a href={edgarFiler(holder.cik ?? "")} target="_blank" rel="noopener noreferrer">
                  {holder.name} · CIK {holder.cik}
                </a>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {closed.length > 0 ? (
        <>
          <h2>Answered questions</h2>
          <ul>
            {closed.map((issue) => (
              <li key={issue.id}>
                <Link href={routes.issue(issue.id)}>{issue.title}</Link>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h2>Created</h2>
      <p>
        {exactTime(chokepoint.created_at)}
        {chokepoint.created_by_session ? (
          <>
            {" · "}
            <Link href={routes.session(chokepoint.created_by_session)}>by a research session</Link>
          </>
        ) : chokepoint.created_by_run ? (
          <> · by a pipeline run</>
        ) : null}
      </p>
    </>
  );
}
