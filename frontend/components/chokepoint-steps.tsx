"use client";

// A chokepoint's argument (spec §10.3.4): the four steps for it, then the two against it, each a
// disclosure whose summary is the step, its status and what it rests on, and, for a thesis step,
// its first Fact's statement. Opening a step shows its Facts as quotes with the way into the
// source at the span, its open questions as rows, and how many leads. On mount only the first
// Fact of each thesis step is read (at most three); a step's other Facts load when it is first
// opened. W8's resolved `facts[]` on the detail replaces these reads (`thesisHeadlineFactIds`).
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  api,
  type ChokepointDetail,
  type CompaniesIndex,
  type FactRecord,
  type Issue,
  type SourceVersionDetail,
} from "../lib/api/client";
import {
  THESIS_STEPS,
  type StepView,
  factIdsOf,
  stepViews,
  thesisHeadlineFactIds,
} from "../lib/chokepoints";
import { plainDay } from "../lib/format";
import { routes } from "../lib/routes";
import { type Loaded, useApi } from "../lib/use-api";
import { Quote } from "./quote";

export interface FactView {
  fact: FactRecord;
  version: SourceVersionDetail | null;
}

// One read per Fact and per Source Version for the page's life, shared by the headlines and the
// opened steps.
const factViews = new Map<string, Promise<FactView>>();
const versions = new Map<string, Promise<SourceVersionDetail | null>>();

function versionOf(id: string): Promise<SourceVersionDetail | null> {
  let pending = versions.get(id);
  if (pending === undefined) {
    pending = api.sourceVersion(id).catch(() => null);
    versions.set(id, pending);
  }
  return pending;
}

export function loadFactView(id: string): Promise<FactView> {
  let pending = factViews.get(id);
  if (pending === undefined) {
    pending = api.fact(id).then(async (fact) => ({
      fact,
      version: await versionOf(fact.assertion.source_version_id),
    }));
    pending.catch(() => factViews.delete(id));
    factViews.set(id, pending);
  }
  return pending;
}

/** Each of `ids` as it loads; a failed one is an error in its place. */
function useFactViews(ids: readonly string[]): Loaded<FactView>[] {
  const key = ids.join(",");
  const [loaded, setLoaded] = useState<Map<string, Loaded<FactView>>>(new Map());
  useEffect(() => {
    let current = true;
    for (const id of key ? key.split(",") : []) {
      loadFactView(id).then(
        (view) => current && setLoaded((before) => new Map(before).set(id, { state: "ready", data: view })),
        (error: unknown) =>
          current &&
          setLoaded((before) =>
            new Map(before).set(id, { state: "error", message: error instanceof Error ? error.message : String(error) }),
          ),
      );
    }
    return () => {
      current = false;
    };
  }, [key]);
  return ids.map((id) => loaded.get(id) ?? { state: "loading" });
}

const loadIssues = async () => (await api.issues()).items;

/** An Issue's title from the cached list, else read on its own. */
function IssueRow({ id, listed }: { id: string; listed: Loaded<Issue[]> }) {
  const known = listed.state === "ready" ? listed.data.find((each) => each.id === id) : undefined;
  const missing = listed.state !== "loading" && known === undefined;
  const single = useApi(missing ? id : null, api.issue);
  const title = known?.title ?? (single.state === "ready" ? single.data.title : null);
  return (
    <li className="reader-row">
      <div className="row-title one-line">
        <Link href={routes.issue(id)}>{title ?? "Open question"}</Link>
      </div>
    </li>
  );
}

export function IssueRows({ ids, label }: { ids: readonly string[]; label: string }) {
  const listed = useApi("issues", loadIssues);
  if (ids.length === 0) return null;
  return (
    <ul className="reader-rows" aria-label={label}>
      {ids.map((id) => (
        <IssueRow key={id} id={id} listed={listed} />
      ))}
    </ul>
  );
}

function FactQuote({
  view,
  companies,
  against,
}: {
  view: Loaded<FactView>;
  companies: CompaniesIndex | null;
  against: boolean;
}) {
  if (view.state === "loading") return null;
  if (view.state === "error") return <p className="muted">Quote unavailable</p>;
  const { fact, version } = view.data;
  const document = version?.source_document;
  return (
    <Quote
      statement={fact.statement}
      quote={fact.assertion.quote}
      company={companies?.byId.get(fact.assertion.subject_company_id)?.display_name ?? document?.publisher ?? null}
      document={document?.title ?? document?.form_type ?? null}
      availableAt={version?.available_at ?? null}
      href={routes.span(fact.assertion.source_version_id, fact.assertion.id)}
      against={against}
    />
  );
}

/** An open step: its Facts as quotes, its open questions and its leads. */
function StepBody({
  step,
  companies,
}: {
  step: StepView;
  companies: CompaniesIndex | null;
}) {
  const ids = factIdsOf(step.state ?? undefined);
  const views = useFactViews(ids);
  const pending = views.filter((view) => view.state === "loading").length;
  const leads = step.state?.evidence.lead_ids?.length ?? 0;
  return (
    <div className="step-body">
      {views.map((view, index) => (
        <FactQuote
          key={ids[index]}
          view={view}
          companies={companies}
          against={step.state?.status === "contradicted"}
        />
      ))}
      {pending > 0 ? (
        <p className="muted">
          +{pending} {pending === 1 ? "quote" : "quotes"} loading
        </p>
      ) : null}
      <IssueRows ids={step.state?.evidence.issue_ids ?? []} label={`${step.title} open questions`} />
      {leads > 0 ? <p className="muted">{leads === 1 ? "1 lead" : `${leads} leads`}</p> : null}
    </div>
  );
}

/** A thesis step's headline: its first Fact's statement, once read. */
function Headline({ id }: { id: string | null }) {
  const view = useApi(id, loadFactView);
  if (id === null || view.state !== "ready") return <span />;
  return <span className="step-headline">{view.data.fact.statement}</span>;
}

function Step({
  step,
  headlineId,
  companies,
  now,
}: {
  step: StepView;
  headlineId: string | null;
  companies: CompaniesIndex | null;
  now: Date;
}) {
  const [opened, setOpened] = useState(false);
  if (!step.examined) {
    return (
      <section className="step" aria-label={step.title}>
        <div className="step-head">
          <p className="step-name">{step.title}</p>
          <p className="muted step-empty">Not examined</p>
        </div>
      </section>
    );
  }
  const tone = step.word.tone === "gap" ? " status-gap" : "";
  return (
    <section className="step" aria-label={step.title}>
      <details
        className="step-details"
        onToggle={(event) => {
          if (event.currentTarget.open) setOpened(true);
        }}
      >
        <summary>
          <span className="step-name">
            {step.title}
            <span className={`step-word${tone}`}>
              {step.mark ? `${step.mark} ` : ""}
              {step.word.word}
            </span>
          </span>
          <Headline id={headlineId} />
          <span className="step-verdict">
            {step.counts ? <span>{step.counts}</span> : null}
            {step.state?.set_at ? <span className="step-fresh">set {plainDay(step.state.set_at, now)}</span> : null}
          </span>
        </summary>
        {opened ? <StepBody step={step} companies={companies} /> : null}
      </details>
    </section>
  );
}

/** The six steps: the four for the thesis, then `Against the thesis` and the two against it. */
export function ChokepointSteps({
  chokepoint,
  companies,
  now = new Date(),
}: {
  chokepoint: Pick<ChokepointDetail, "steps">;
  companies: CompaniesIndex | null;
  now?: Date;
}) {
  const views = stepViews(chokepoint);
  const headlines = new Set(thesisHeadlineFactIds(chokepoint));
  const headlineOf = (step: StepView) => {
    const first = factIdsOf(step.state ?? undefined)[0];
    return first !== undefined && headlines.has(first) && THESIS_STEPS.includes(step.name) ? first : null;
  };
  const render = (step: StepView) => (
    <Step key={step.name} step={step} headlineId={headlineOf(step)} companies={companies} now={now} />
  );
  return (
    <>
      <div className="steps">{views.filter((step) => !step.against).map(render)}</div>
      <h3 className="reader-label">Against the thesis</h3>
      <div className="steps">{views.filter((step) => step.against).map(render)}</div>
    </>
  );
}
