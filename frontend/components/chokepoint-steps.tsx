"use client";

// A chokepoint's argument (spec §10.3.4): the four steps for it, then the two against it, each a
// disclosure whose summary is the step, its status and what it rests on, and, for a thesis step,
// its first Fact's statement. Opening a step shows its Facts as quotes with the way into the
// source at the span, its open questions as rows, and its leads, which link out to the web. The
// detail resolves every Fact, lead and Issue it cites, so the page reads nothing more.
import Link from "next/link";

import type { ChokepointDetail, EvidenceIssue, EvidenceLead } from "../lib/api/client";
import { type StepView, headlineOf, leadHref, stepFacts, stepViews } from "../lib/chokepoints";
import { plainDay } from "../lib/format";
import { routes } from "../lib/routes";
import { Quote } from "./quote";

type Evidence = Pick<ChokepointDetail, "facts" | "leads" | "issues">;

/** Questions as rows that open their Issue, in the order given. */
export function IssueRows({ issues, label }: { issues: readonly EvidenceIssue[]; label: string }) {
  if (issues.length === 0) return null;
  return (
    <ul className="reader-rows" aria-label={label}>
      {issues.map((issue) => (
        <li className="reader-row" key={issue.id}>
          <div className="row-title one-line">
            <Link href={routes.issue(issue.id)}>{issue.title}</Link>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Leads (records, never evidence): their title, out to the web when the link is http(s). */
function LeadRows({ leads, label }: { leads: readonly EvidenceLead[]; label: string }) {
  if (leads.length === 0) return null;
  return (
    <ul className="lead-rows" aria-label={label}>
      {leads.map((lead) => {
        const href = leadHref(lead.url);
        return (
          <li key={lead.id}>
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                {lead.title}
              </a>
            ) : (
              lead.title
            )}
            {lead.published_at ? <span className="muted-small"> · {plainDay(lead.published_at)}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

/** An open step: its Facts as quotes, its open questions and its leads. */
function StepBody({ step, evidence }: { step: StepView; evidence: Evidence }) {
  const facts = stepFacts(evidence, step.state);
  const cited = step.state?.evidence;
  const issues = evidence.issues.filter((issue) => (cited?.issue_ids ?? []).includes(issue.id));
  const leads = evidence.leads.filter((lead) => (cited?.lead_ids ?? []).includes(lead.id));
  return (
    <div className="step-body">
      {facts.map((fact) => (
        <Quote
          key={fact.id}
          statement={fact.statement}
          quote={fact.quote}
          company={fact.company_name}
          document={fact.document_title}
          availableAt={fact.available_at}
          href={routes.span(fact.source_version_id, fact.assertion_id)}
          against={step.state?.status === "contradicted"}
        />
      ))}
      <IssueRows issues={issues} label={`${step.title} open questions`} />
      <LeadRows leads={leads} label={`${step.title} leads`} />
    </div>
  );
}

function Step({ step, evidence, now }: { step: StepView; evidence: Evidence; now: Date }) {
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
  const headline = headlineOf(evidence, step.name, step.state);
  return (
    <section className="step" aria-label={step.title}>
      <details className="step-details">
        <summary>
          <span className="step-name">
            {step.title}
            <span className={`step-word${tone}`}>
              {step.mark ? `${step.mark} ` : ""}
              {step.word.word}
            </span>
          </span>
          {headline ? <span className="step-headline">{headline}</span> : <span />}
          <span className="step-verdict">
            {step.counts ? <span>{step.counts}</span> : null}
            {step.state?.set_at ? <span className="step-fresh">set {plainDay(step.state.set_at, now)}</span> : null}
          </span>
        </summary>
        <StepBody step={step} evidence={evidence} />
      </details>
    </section>
  );
}

/** The six steps: the four for the thesis, then `Against the thesis` and the two against it. */
export function ChokepointSteps({
  chokepoint,
  now = new Date(),
}: {
  chokepoint: Pick<ChokepointDetail, "steps" | "facts" | "leads" | "issues">;
  now?: Date;
}) {
  const views = stepViews(chokepoint);
  const render = (step: StepView) => <Step key={step.name} step={step} evidence={chokepoint} now={now} />;
  return (
    <>
      <div className="steps">{views.filter((step) => !step.against).map(render)}</div>
      <h3 className="reader-label">Against the thesis</h3>
      <div className="steps">{views.filter((step) => step.against).map(render)}</div>
    </>
  );
}
