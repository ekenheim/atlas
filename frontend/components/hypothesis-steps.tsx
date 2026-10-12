"use client";

// A Hypothesis over Beliefs, as the dossier leads with it (atlas-beliefs ticket 14): the steps of
// the argument, each with its statement and the Beliefs it rests on, every Belief with its
// judgement and the Facts' quotes at their spans; and the theme's open Issues.
import Link from "next/link";

import { api, type HypothesisVersion } from "../lib/api/client";
import {
  JUDGEMENTS,
  type JudgementName,
  confidenceText,
  day,
  judgementTone,
} from "../lib/beliefs";
import {
  type Step,
  beliefCount,
  openIssues,
  stepViews,
} from "../lib/hypothesis-steps";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { Load } from "./ui";

type StepBelief = Step["beliefs"][number];

const loadIssues = () => api.issues();

/** The steps, in the argument's order. Nothing for a version of an investigation. */
export function HypothesisSteps({ version }: { version: HypothesisVersion }) {
  const steps = stepViews(version);
  if (steps.length === 0) return null;
  const count = beliefCount(version);
  return (
    <section aria-labelledby="steps">
      <h2 id="steps">What it rests on</h2>
      <p className="muted">
        {count} {count === 1 ? "Belief" : "Beliefs"}, proven when this version
        was drafted. Each links to its record; the quotes are the evidence.
      </p>
      {steps.map((step) => (
        <section key={step.step} aria-label={step.title}>
          <p className="reader-step">
            <strong>{step.title}</strong>
          </p>
          {step.statement ? (
            <p>
              {step.statement}
              {step.judged === true && (
                <span className="muted-small">
                  {" "}
                  · checked against its quotes
                </span>
              )}
            </p>
          ) : (
            <p className="muted">No statement of its own: read the Beliefs.</p>
          )}
          <ul className="reader-rows" aria-label={`${step.title} beliefs`}>
            {step.beliefs.map((belief) => (
              <StepBeliefRow key={belief.belief_id} belief={belief} />
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

function pill(belief: StepBelief) {
  const judgement = belief.judgement as JudgementName;
  return (
    <span className={`reader-pill ${judgementTone(judgement)}`}>
      {JUDGEMENTS[judgement] ?? belief.judgement}
      {judgement !== "unproven" && ` ${confidenceText(belief.confidence)}`}
    </span>
  );
}

function StepBeliefRow({ belief }: { belief: StepBelief }) {
  return (
    <li className="reader-row" aria-label={belief.statement}>
      <div>
        <div className="reader-row-title">
          <Link href={routes.belief(belief.belief_id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub">
          {belief.companies.join(", ") || "no company"} · as of{" "}
          {day(belief.as_of)} · judged by {belief.judged_by}
        </div>
        {belief.citations.map((citation) => (
          <figure key={citation.ref_id} className="reader-quote">
            {citation.statement && <p>{citation.statement}</p>}
            <blockquote>{citation.quote}</blockquote>
            <figcaption>
              {citation.company_name} · {citation.source_title ?? "source"} ·
              available {day(citation.available_at)} ·{" "}
              <Link
                href={routes.span(citation.source_version_id, citation.ref_id)}
              >
                Source
              </Link>
            </figcaption>
          </figure>
        ))}
      </div>
      {pill(belief)}
    </li>
  );
}

/** The theme's Issues still open: what the Hypothesis does not yet settle. */
export function OpenIssues({ theme }: { theme: string }) {
  const issues = useApi("issues", loadIssues);
  return (
    <section aria-labelledby="open-issues">
      <h2 id="open-issues">Open Issues</h2>
      <Load loaded={issues} what="the Issues">
        {(page) => {
          const open = openIssues(page.items, theme);
          return open.length === 0 ? (
            <p className="muted">None open on this theme.</p>
          ) : (
            <>
              <ul aria-label="Open issues">
                {open.map((issue) => (
                  <li key={issue.id}>{issue.title}</li>
                ))}
              </ul>
              <p>
                <Link href={routes.issues()}>All Issues</Link>
              </p>
            </>
          );
        }}
      </Load>
    </section>
  );
}
