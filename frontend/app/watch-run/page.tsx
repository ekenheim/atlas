"use client";

// One run of the Watch: its memo, read as the Watch wrote it (spec §10.3.5). The memo is not
// evidence and says so; its links to the board open chokepoints, and only links to the web leave
// Atlas. The theme's earlier runs follow, and the run's own record is in the Records.
import Link from "next/link";
import { Suspense } from "react";

import { Memo } from "../../components/memo";
import { RecordsFold } from "../../components/records-fold";
import { WatchRunRecord } from "../../components/watch-run-records";
import { ApiError, api, type WatchRun } from "../../lib/api/client";
import { themeTitle } from "../../lib/chokepoints";
import { plainDay } from "../../lib/format";
import { memoExcerpt } from "../../lib/markdown";
import { routes } from "../../lib/routes";
import { WATCH_MODE_WORDS } from "../../lib/status";
import { useApi, useIdParam } from "../../lib/use-api";

export default function WatchRunPage() {
  return (
    <Suspense>
      <WatchRunView />
    </Suspense>
  );
}

/** The run, or null when there is none by that id. */
const loadRun = async (id: string): Promise<WatchRun | null> => {
  try {
    return await api.watchRun(id);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
};
const loadThemes = () => api.themes();
const loadEarlier = async (theme: string) => (await api.watchRuns({ theme, limit: 8 })).items;

/** Earlier runs shown under the memo. */
export const EARLIER_SHOWN = 7;

function WatchRunView() {
  const id = useIdParam();
  const run = useApi(id, loadRun);
  if (run.state === "loading") {
    return (
      <div className="reader" aria-busy="true">
        <span className="sk sk-line" />
        <span className="sk sk-h1" />
        <span className="sk sk-thesis" />
        <span className="sk sk-strip" />
      </div>
    );
  }
  if (run.state === "error") return <p role="alert">Could not load the memo</p>;
  if (run.data === null) return <p role="alert">This memo does not exist.</p>;
  return <Body run={run.data} />;
}

function Earlier({ run }: { run: WatchRun }) {
  const runs = useApi(run.theme, loadEarlier);
  if (runs.state !== "ready") return null;
  const earlier = runs.data.filter((each) => each.id !== run.id).slice(0, EARLIER_SHOWN);
  if (earlier.length === 0) return null;
  const now = new Date();
  return (
    <section aria-labelledby="earlier">
      <h2 className="reader-label" id="earlier">
        Earlier runs
      </h2>
      <ul className="reader-rows" aria-label="Earlier runs">
        {earlier.map((each) => {
          const excerpt = memoExcerpt(each.memo);
          return (
            <li className="reader-row" key={each.id}>
              <div className="row-title one-line">
                <Link href={routes.watchRun(each.id)}>
                  {plainDay(each.run_date, now)}
                  {excerpt ? ` · ${excerpt}` : ""}
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Body({ run }: { run: WatchRun }) {
  const themes = useApi("themes", loadThemes);
  const title = themeTitle(run.theme, themes.state === "ready" ? themes.data : []);
  const mode = WATCH_MODE_WORDS[run.mode];
  return (
    <div className="reader watch-run-page">
      <p className="crumbs">
        <Link href={routes.theme(run.theme)}>{title}</Link>
      </p>
      <header>
        {mode ? <div className="reader-kicker">{mode}</div> : null}
        <h1 className="reader-headline">
          {title} · {plainDay(run.run_date)}
        </h1>
      </header>
      <p className="memo-note">The Watch&apos;s memo · not evidence</p>
      <Memo source={run.memo} />
      <Earlier run={run} />
      <RecordsFold>
        <WatchRunRecord run={run} />
      </RecordsFold>
    </div>
  );
}
