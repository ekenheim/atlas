"use client";

// What the Watch's run records hold, shown only inside a Records fold: a run's counts, tool
// calls, cost and tokens, its session and exact time (the memo page), and a theme's runs as rows
// that open their memos (the board-led theme page).
import Link from "next/link";

import type { WatchRun } from "../lib/api/client";
import { humanise } from "../lib/chokepoints";
import { evidenceDay, exactTime } from "../lib/format";
import { routes } from "../lib/routes";
import { WATCH_MODE_WORDS } from "../lib/status";
import { Row } from "./ui";

const money = (usd: number | null) => (usd === null ? null : `$${usd.toFixed(2)}`);

/** One run's record. */
export function WatchRunRecord({ run }: { run: WatchRun }) {
  const counts = Object.entries(run.counts);
  return (
    <>
      <table>
        <caption>The run</caption>
        <tbody>
          <Row name="Tool calls">{run.tool_calls}</Row>
          <Row name="Cost">{money(run.cost_usd) ?? "not recorded"}</Row>
          <Row name="Tokens">{run.tokens === null ? "not recorded" : run.tokens.toLocaleString("en-US")}</Row>
          <Row name="Session">
            {run.session_id ? <Link href={routes.session(run.session_id)}>Open the session</Link> : "none"}
          </Row>
          <Row name="Recorded">
            <time dateTime={run.created_at}>{exactTime(run.created_at)}</time>
          </Row>
        </tbody>
      </table>
      {counts.length > 0 ? (
        <table>
          <caption>Counts</caption>
          <tbody>
            {counts.map(([key, value]) => (
              <Row key={key} name={humanise(key)}>
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </Row>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}

/** A theme's runs, newest first, each opening its memo. */
export function WatchRunRows({ runs }: { runs: readonly WatchRun[] }) {
  if (runs.length === 0) return null;
  return (
    <>
      <h2>Watch runs</h2>
      <ul className="reader-rows" aria-label="Watch runs">
        {runs.map((run) => (
          <li className="reader-row" key={run.id}>
            <div className="row-title">
              <Link href={routes.watchRun(run.id)}>
                {[evidenceDay(run.run_date), WATCH_MODE_WORDS[run.mode], `${run.tool_calls} tool calls`, money(run.cost_usd)]
                  .filter(Boolean)
                  .join(" · ")}
              </Link>
            </div>
            <div className="reader-row-sub row-secondary">{exactTime(run.created_at)}</div>
          </li>
        ))}
      </ul>
    </>
  );
}
