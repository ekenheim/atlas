"use client";

// The six steps of the argument as rows (spec §3.5). Each step is a region named by the step
// (the e2e regions `Constraint`, `Relief`, ...). Its summary is the step's name, how many Beliefs
// are proven, the strongest Belief's statement (two lines), its status and confidence, how
// freshly it was examined and `+N more`. Opening it lists the step's Beliefs, each a row-link to
// the Belief. Opening a step is a disclosure, not a navigation.
import Link from "next/link";
import { type ReactNode, useState } from "react";

import type { BeliefSummary } from "../lib/api/client";
import type { StepArgument } from "../lib/argument";
import { STEPS } from "../lib/beliefs";
import { activity, evidenceDay } from "../lib/format";
import { routes } from "../lib/routes";
import { BeliefVerdict } from "./status";

/** A Belief as a row needs it, whether it comes from a theme's list or from a version's record. */
export interface BeliefRowData {
  id: string;
  statement: string;
  judgement: BeliefSummary["judgement"]["judgement"];
  confidence: number;
  status: BeliefSummary["status"];
  open_flags: number;
  open_notices: number;
  companies: string[];
  asOf: string;
  /** A line under the row (what changed since a version drafted it). */
  note?: ReactNode;
}

export interface StepRowData {
  key: string;
  /** The region's name: the step's title. */
  title: string;
  against: boolean;
  /** "3 proven", "5 Beliefs", or none. */
  count: string | null;
  /** The strongest Belief's statement, clamped to two lines. */
  headline: string | null;
  strongest: BeliefRowData | null;
  /** "examined 12 d ago" or "never re-examined"; none: nothing is said. */
  freshness?: string | null;
  /** "changed since drafting", in warn. */
  changed?: string | null;
  beliefs: BeliefRowData[];
  /** Shown above the Beliefs when the step is open (a version's statements). */
  lead?: ReactNode;
  empty?: string;
}

/** Beyond this many Beliefs a step opens to seven and a `Show all`. */
export const MANY = 30;
export const FIRST = 7;

export function beliefRowOf(belief: BeliefSummary, names?: (b: BeliefSummary) => string[]): BeliefRowData {
  return {
    id: belief.id,
    statement: belief.statement,
    judgement: belief.judgement.judgement,
    confidence: belief.judgement.confidence,
    status: belief.status,
    open_flags: belief.open_flags,
    open_notices: belief.open_notices,
    companies: names ? names(belief) : belief.companies.map((each) => each.display_name),
    asOf: belief.as_of,
  };
}

/** The rows of a theme's (or company's) argument, from `argumentOf`. */
export function stepRowsOf(steps: readonly StepArgument<BeliefSummary>[], now?: Date): StepRowData[] {
  return steps.map((step) => {
    const rows = step.beliefs.map((each) => beliefRowOf(each));
    const strongest = step.strongest ? beliefRowOf(step.strongest) : null;
    return {
      key: step.step,
      title: STEPS[step.step],
      against: step.against,
      count: rows.length === 0 ? null : `${step.proven} proven`,
      headline: strongest?.statement ?? rows[0]?.statement ?? null,
      strongest,
      freshness:
        rows.length === 0
          ? null
          : step.examinedAt
            ? `examined ${activity(step.examinedAt, now)}`
            : "never re-examined",
      beliefs: rows,
    };
  });
}

function verdictOf(belief: BeliefRowData) {
  return {
    status: belief.status,
    open_flags: belief.open_flags,
    open_notices: belief.open_notices,
    judgement: { judgement: belief.judgement, confidence: belief.confidence },
  };
}

export function BeliefRow({ belief }: { belief: BeliefRowData }) {
  return (
    <li className="reader-row" aria-label={belief.statement}>
      <div>
        <div className="row-title">
          <Link href={routes.belief(belief.id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub row-secondary">
          {belief.companies.length > 0 ? `${belief.companies.join(", ")} · ` : ""}as of{" "}
          {evidenceDay(belief.asOf)}
        </div>
        {belief.note ? <div className="reader-row-sub row-secondary">{belief.note}</div> : null}
      </div>
      <span className="row-verdict">
        <BeliefVerdict belief={verdictOf(belief)} />
      </span>
    </li>
  );
}

function Rows({ step }: { step: StepRowData }) {
  const [all, setAll] = useState(false);
  const clipped = step.beliefs.length > MANY && !all;
  const shown = clipped ? step.beliefs.slice(0, FIRST) : step.beliefs;
  return (
    <>
      {step.lead}
      <ul className="reader-rows" aria-label={`${step.title} beliefs`}>
        {shown.map((belief) => (
          <BeliefRow key={belief.id} belief={belief} />
        ))}
      </ul>
      {clipped ? (
        <button type="button" className="show-all" onClick={() => setAll(true)}>
          Show all {step.beliefs.length}
        </button>
      ) : null}
    </>
  );
}

export function StepRow({ step }: { step: StepRowData }) {
  const more = Math.max(0, step.beliefs.length - 1);
  return (
    <section className="step" aria-label={step.title}>
      {step.beliefs.length === 0 && !step.lead ? (
        <div className="step-head">
          <p className="step-name">{step.title}</p>
          <p className="muted step-empty">{step.empty ?? "Nothing believed yet."}</p>
        </div>
      ) : (
        <details className="step-details">
          <summary>
            <span className="step-name">
              {step.title}
              {step.against ? <span className="step-side">Against the thesis</span> : null}
              {step.count ? <span className="step-count">{step.count}</span> : null}
            </span>
            {step.headline ? <span className="step-headline">{step.headline}</span> : <span />}
            <span className="step-verdict">
              {step.strongest ? <BeliefVerdict belief={verdictOf(step.strongest)} /> : null}
              {step.changed ? <span className="status status-warn">{step.changed}</span> : null}
              {step.freshness ? <span className="step-fresh">{step.freshness}</span> : null}
              {more > 0 ? <span className="step-more">+{more} more</span> : null}
            </span>
          </summary>
          <Rows step={step} />
        </details>
      )}
    </section>
  );
}

export function StepRows({ steps }: { steps: readonly StepRowData[] }) {
  return (
    <div className="steps">
      {steps.map((step) => (
        <StepRow key={step.key} step={step} />
      ))}
    </div>
  );
}
