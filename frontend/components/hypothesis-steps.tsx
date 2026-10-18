"use client";

// A Hypothesis over Beliefs, as the dossier leads with it (atlas-beliefs ticket 14): the steps of
// the argument, each with its statement and the Beliefs it rests on, every Belief with its
// judgement and the Facts' quotes at their spans; and the theme's open Issues.
import Link from "next/link";

import {
  api,
  type BeliefSummary,
  type HypothesisVersion,
} from "../lib/api/client";
import {
  JUDGEMENTS,
  type JudgementName,
  confidenceText,
  judgementTone,
} from "../lib/beliefs";
import {
  type Step,
  beliefCount,
  callsFor,
  counterevidenceOf,
  openIssues,
  standingNow,
  stepBeliefIds,
  stepViews,
  thesisCheck,
} from "../lib/hypothesis-steps";
import { evidenceDay } from "../lib/format";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { CitationQuote } from "./beliefs";
import { CallsPanel } from "./calls";
import { Load } from "./ui";

type StepBelief = Step["beliefs"][number];

const loadIssues = () => api.issues();
const loadBeliefs = (key: string) =>
  api.beliefs({ theme: key.slice("beliefs:".length) });

/** The steps, in the argument's order. Nothing for a version of an investigation. */
export function HypothesisSteps({
  version,
  theme,
}: {
  version: HypothesisVersion;
  theme: string;
}) {
  // How each Belief stands now, beside how the version drafted it (a failed read shows none).
  const current = useApi(`beliefs:${theme}`, loadBeliefs);
  const now = new Map<string, BeliefSummary>(
    current.state === "ready"
      ? current.data.items.map((each: BeliefSummary) => [each.id, each])
      : [],
  );
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
          {step.statements.length > 0 ? (
            <ul aria-label={`${step.title} statements`}>
              {step.statements.map((one) => (
                <li key={one.statement}>
                  {one.statement}
                  {one.judged === true && (
                    <span className="muted-small">
                      {" "}
                      · checked against its quotes
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No statement of its own: read the Beliefs.</p>
          )}
          <ul className="reader-rows" aria-label={`${step.title} beliefs`}>
            {step.beliefs.map((belief) => (
              <StepBeliefRow
                key={belief.belief_id}
                belief={belief}
                now={now.get(belief.belief_id)}
              />
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

function StepBeliefRow({
  belief,
  now,
}: {
  belief: StepBelief;
  now: BeliefSummary | undefined;
}) {
  const changed = standingNow(belief, now);
  return (
    <li className="reader-row" aria-label={belief.statement}>
      <div>
        <div className="reader-row-title">
          <Link href={routes.belief(belief.belief_id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub">
          {belief.companies.join(", ") || "no company"} · as of{" "}
          {evidenceDay(belief.as_of)} · judged by {belief.judged_by}
        </div>
        {changed && (
          <div className="reader-row-sub">
            <strong>Since drafted:</strong> {changed}
          </div>
        )}
        {belief.citations.map((citation) => (
          <figure key={citation.ref_id} className="reader-quote">
            {citation.statement && <p>{citation.statement}</p>}
            <blockquote>{citation.quote}</blockquote>
            <figcaption>
              {citation.company_name} · {citation.source_title ?? "source"} ·
              available {evidenceDay(citation.available_at)} ·{" "}
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

/** Whether the thesis was checked against its Beliefs' quotes (a version of an investigation
 * has no such check and says nothing). */
export function ThesisLine({ version }: { version: HypothesisVersion }) {
  const check = thesisCheck(version);
  if (check === null) return null;
  return (
    <p className="reader-meta" aria-label="Thesis check">
      <span
        className={`reader-pill ${
          check.state === "supported"
            ? "reader-supported"
            : check.state === "misstated"
              ? "reader-disputed"
              : "reader-unknown"
        }`}
      >
        {check.state === "supported"
          ? "Checked"
          : check.state === "misstated"
            ? "Overreaches"
            : "Unchecked"}
      </span>{" "}
      {check.text}
    </p>
  );
}

const loadAgainst = async (key: string) =>
  counterevidenceOf(
    await Promise.all(key.split(",").map((id) => api.belief(id))),
  );

/** What stands against the Beliefs the version rests on: each citation against, its quote
 * opening the source at its span. */
export function Counterevidence({ version }: { version: HypothesisVersion }) {
  const ids = stepBeliefIds(version).join(",");
  const against = useApi(ids === "" ? null : ids, loadAgainst);
  if (ids === "") return null;
  return (
    <section aria-labelledby="counterevidence">
      <h2 id="counterevidence">Against it</h2>
      <Load loaded={against} what="the counterevidence">
        {(groups) =>
          groups.length === 0 ? (
            <p className="muted">Nothing recorded against its Beliefs.</p>
          ) : (
            <ul className="reader-rows" aria-label="Counterevidence">
              {groups.map((group) => (
                <li className="reader-row" key={group.id}>
                  <div>
                    <div className="reader-row-title">
                      <Link href={routes.belief(group.id)}>
                        {group.statement}
                      </Link>
                    </div>
                    {group.against.map((citation) => (
                      <CitationQuote key={citation.ref_id} citation={citation} />
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </Load>
    </section>
  );
}

/** The calls made for this Hypothesis: its published versions and the Beliefs it rests on. */
export function HypothesisCalls({
  theme,
  versionIds,
  beliefIds,
}: {
  theme: string;
  versionIds: readonly string[];
  beliefIds: readonly string[];
}) {
  return (
    <CallsPanel
      theme={theme}
      title="Calls made for it"
      select={(calls) => callsFor(calls, versionIds, beliefIds)}
    />
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
