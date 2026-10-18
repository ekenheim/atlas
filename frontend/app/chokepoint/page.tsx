"use client";

// One chokepoint of the Watch's board (spec §10.3.4): what is scarce, who holds it, how far the
// evidence has got, what it still needs, what would falsify it, and where the quotes are. Board
// row → this page → open a step → `Open in source` is the two-click path to a highlighted span.
// The raw history, the holders' CIKs and who wrote what are in the Records.
import Link from "next/link";
import { Fragment, Suspense } from "react";

import { ChokepointRecords } from "../../components/chokepoint-records";
import { ChokepointSteps, IssueRows } from "../../components/chokepoint-steps";
import { RecordsFold } from "../../components/records-fold";
import { Status } from "../../components/status";
import { ApiError, api, type ChokepointDetail, type CompaniesIndex, type Issue } from "../../lib/api/client";
import { badges, barLine, holderView, layerName, statusSince, themeTitle } from "../../lib/chokepoints";
import { plainDay } from "../../lib/format";
import { routes } from "../../lib/routes";
import { CHOKEPOINT_WORDS, CROWDING_NONE, CROWDING_TITLE, CROWDING_WORDS } from "../../lib/status";
import { type Loaded, useApi, useIdParam } from "../../lib/use-api";

export default function ChokepointPage() {
  return (
    <Suspense>
      <ChokepointView />
    </Suspense>
  );
}

/** The chokepoint, or null when there is none by that id. */
const loadDetail = async (id: string): Promise<ChokepointDetail | null> => {
  try {
    return await api.chokepoint(id);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
};
const loadThemes = () => api.themes();
const loadCompanies = () => api.companiesIndex();
const loadIssues = async () => (await api.issues()).items;

function ChokepointView() {
  const id = useIdParam();
  const detail = useApi(id, loadDetail);
  if (detail.state === "loading") {
    return (
      <div className="reader" aria-busy="true">
        <span className="sk sk-line" />
        <span className="sk sk-h1" />
        <div className="steps">
          {Array.from({ length: 6 }, (_, index) => (
            <div className="step step-head" key={index}>
              <span className="sk sk-line" />
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (detail.state === "error") return <p role="alert">Could not load the chokepoint</p>;
  if (detail.data === null) return <p role="alert">This chokepoint does not exist.</p>;
  return <Body chokepoint={detail.data} />;
}

function Holders({ chokepoint, companies }: { chokepoint: ChokepointDetail; companies: Loaded<CompaniesIndex> }) {
  if (chokepoint.holders.length === 0) return <p className="holders muted">Holder not yet named</p>;
  const view = holderView(chokepoint.holders, companies.state === "ready" ? companies.data : null);
  return (
    <p className="holders">
      Held by{" "}
      {view.map((holder, index) => (
        <Fragment key={`${holder.name}-${index}`}>
          {index > 0 ? ", " : null}
          {holder.companyId ? (
            <Link href={routes.company(holder.companyId)}>{holder.name}</Link>
          ) : (
            <>
              {holder.name} <span className="muted">not yet researched</span>
            </>
          )}
        </Fragment>
      ))}
    </p>
  );
}

function Verdict({ chokepoint, now }: { chokepoint: ChokepointDetail; now: Date }) {
  const since = plainDay(statusSince(chokepoint), now);
  return (
    <p className="verdict-line">
      {chokepoint.status === "killed" ? (
        <span className="status status-gap">
          <span className="status-dot" aria-hidden="true" />
          Ruled out {since}
          {chokepoint.status_reason ? `: ${chokepoint.status_reason}` : ""}
        </span>
      ) : (
        <>
          <Status word={CHOKEPOINT_WORDS[chokepoint.status]} />
          <span className="verdict-since">since {since}</span>
        </>
      )}
      {badges(chokepoint, now).map((badge) => (
        <Status key={badge.kind} word={badge.word} />
      ))}
    </p>
  );
}

/** What would falsify it, when supply could catch up, and how widely it is known. */
function Band({ chokepoint }: { chokepoint: ChokepointDetail }) {
  return (
    <div className="band band-3 cp-band">
      <section aria-labelledby="falsify">
        <h2 className="reader-label" id="falsify">
          What would falsify it
        </h2>
        {chokepoint.kill_criteria.length === 0 ? (
          <p className="muted">None written yet</p>
        ) : (
          <ul>
            {chokepoint.kill_criteria.map((each) => (
              <li key={each}>{each}</li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="relief">
        <h2 className="reader-label" id="relief">
          When supply could catch up
        </h2>
        {chokepoint.relief_horizon ? (
          <>
            <p>{chokepoint.relief_horizon.horizon}</p>
            <p className="quote-statement">{chokepoint.relief_horizon.basis}</p>
          </>
        ) : (
          <p className="muted">Not estimated</p>
        )}
      </section>
      <section aria-labelledby="context">
        <h2 className="reader-label" id="context">
          Context, not evidence
        </h2>
        {chokepoint.crowding ? (
          <p title={CROWDING_TITLE}>{CROWDING_WORDS[chokepoint.crowding].word}</p>
        ) : (
          <p className="muted">{CROWDING_NONE}</p>
        )}
      </section>
    </div>
  );
}

/** The linked questions still open; none, and the section is left out (the bar line says so). */
function OpenQuestions({ chokepoint }: { chokepoint: ChokepointDetail }) {
  const issues = useApi("issues", loadIssues);
  if (issues.state !== "ready") return null;
  const open = chokepoint.issue_ids.filter((id) =>
    issues.data.some((each: Issue) => each.id === id && each.status === "active"),
  );
  if (open.length === 0) return null;
  return (
    <section aria-labelledby="open-questions">
      <h2 className="reader-label" id="open-questions">
        Open questions
      </h2>
      <IssueRows ids={open} label="Open questions" />
    </section>
  );
}

function Body({ chokepoint }: { chokepoint: ChokepointDetail }) {
  const themes = useApi("themes", loadThemes);
  const companies = useApi("companies", loadCompanies);
  const now = new Date();
  const title = themeTitle(chokepoint.theme, themes.state === "ready" ? themes.data : []);
  const bar = barLine(chokepoint);
  return (
    <div className="reader chokepoint-page">
      <p className="crumbs">
        <Link href={routes.board(chokepoint.theme)}>{title}</Link>
      </p>
      <header>
        <div className="reader-kicker">Chokepoint · {layerName(chokepoint.layer)}</div>
        <h1 className="reader-headline measure">{chokepoint.constraint}</h1>
      </header>
      <Holders chokepoint={chokepoint} companies={companies} />
      <Verdict chokepoint={chokepoint} now={now} />
      {bar ? <p className={`bar-line status-${bar.tone}`}>{bar.text}</p> : null}

      <section aria-labelledby="argument">
        <h2 className="reader-label" id="argument">
          The argument
        </h2>
        <ChokepointSteps chokepoint={chokepoint} companies={companies.state === "ready" ? companies.data : null} now={now} />
      </section>

      <Band chokepoint={chokepoint} />
      <OpenQuestions chokepoint={chokepoint} />

      <RecordsFold counts={`${chokepoint.event_count} ${chokepoint.event_count === 1 ? "event" : "events"}`}>
        <ChokepointRecords chokepoint={chokepoint} />
      </RecordsFold>
    </div>
  );
}
