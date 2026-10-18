"use client";

// A Hypothesis over Beliefs (atlas-beliefs ticket 14). Above the fold: the six steps as rows, each
// with its statement and the Beliefs it rests on (their quotes one toggle deeper), and the
// theme's open Issues. In the Records: the full list of what it rests on, with the quotes.
import Link from "next/link";

import {
  api,
  type BeliefSummary,
  type HypothesisVersion,
} from "../lib/api/client";
import { STEPS } from "../lib/beliefs";
import { evidenceDay } from "../lib/format";
import {
  changedSinceDrafting,
  firstSentence,
} from "../lib/hypothesis-page";
import {
  type Step,
  beliefCount,
  callsFor,
  counterevidenceOf,
  openIssues,
  standingNow,
  stepBeliefIds,
  stepViews,
} from "../lib/hypothesis-steps";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { CitationQuote } from "./beliefs";
import { CallsPanel } from "./calls";
import type { QuoteProps } from "./quote";
import { BeliefVerdict } from "./status";
import { StepRows, type BeliefRowData, type StepRowData } from "./step-rows";
import { Load } from "./ui";
import { Quote } from "./quote";

type StepBelief = Step["beliefs"][number];

const loadIssues = () => api.issues();
const loadBeliefs = (key: string) =>
  api.beliefs({ theme: key.slice("beliefs:".length) });

function useNow(theme: string): Map<string, BeliefSummary> {
  // How each Belief stands now, beside how the version drafted it (a failed read shows none).
  const current = useApi(`beliefs:${theme}`, loadBeliefs);
  return new Map<string, BeliefSummary>(
    current.state === "ready"
      ? current.data.items.map((each: BeliefSummary) => [each.id, each])
      : [],
  );
}

function quotesOf(belief: StepBelief): QuoteProps[] {
  return belief.citations.map((citation) => ({
    statement: citation.statement,
    quote: citation.quote,
    company: citation.company_name,
    document: citation.source_title ?? "source",
    availableAt: citation.available_at,
    href: routes.span(citation.source_version_id, citation.ref_id),
    against: citation.valence < 0,
  }));
}

const GLYPH = {
  checked: { glyph: "✓", name: "checked against its quotes", cls: "status-ok" },
  aside: { glyph: "–", name: "set aside", cls: "status-muted" },
} as const;

/** The version's steps as rows: each step's statement (its first sentence leads), the Beliefs it
 * rests on, and whether any has moved since the version was drafted. */
export function VersionStepRows({
  version,
  theme,
}: {
  version: HypothesisVersion;
  theme: string;
}) {
  const now = useNow(theme);
  const views = stepViews(version);
  if (views.length === 0) return null;
  const rows: StepRowData[] = views.map((view) => {
    const beliefs: BeliefRowData[] = view.beliefs.map((belief) => {
      const current = now.get(belief.belief_id);
      const changed = standingNow(belief, current);
      return {
        id: belief.belief_id,
        statement: belief.statement,
        judgement: (belief.judgement as BeliefRowData["judgement"]) ?? "unproven",
        confidence: belief.confidence,
        status: current?.status ?? "active",
        open_flags: current?.open_flags ?? 0,
        open_notices: current?.open_notices ?? 0,
        companies: belief.companies,
        asOf: belief.as_of,
        note: changed ? <>Since drafted: {changed}</> : undefined,
        quotes: quotesOf(belief),
      };
    });
    const strongest = beliefs.find((each) => each.judgement === "proven") ?? beliefs[0] ?? null;
    const statement = view.statements[0]?.statement ?? null;
    const key = view.step as keyof typeof STEPS;
    return {
      key: view.step,
      title: view.title,
      against: key === "relief" || key === "invalidation",
      count: `${beliefs.length} ${beliefs.length === 1 ? "Belief" : "Beliefs"}`,
      headline: statement ? firstSentence(statement) : (strongest?.statement ?? null),
      strongest,
      changed: changedSinceDrafting(view, now) ? "changed since drafting" : null,
      beliefs,
      lead:
        view.statements.length > 0 ? (
          <ul className="step-statements" aria-label={`${view.title} statements`}>
            {view.statements.map((one) => {
              const mark = one.judged === true ? GLYPH.checked : GLYPH.aside;
              return (
                <li key={one.statement}>
                  <span
                    className={`status ${mark.cls}`}
                    role="img"
                    aria-label={mark.name}
                    title={mark.name}
                  >
                    {mark.glyph}
                  </span>{" "}
                  {one.statement}
                </li>
              );
            })}
          </ul>
        ) : undefined,
    };
  });
  return <StepRows steps={rows} />;
}

/** The steps in full, in the argument's order: what the Records show of what it rests on. */
export function HypothesisSteps({
  version,
  theme,
}: {
  version: HypothesisVersion;
  theme: string;
}) {
  const now = useNow(theme);
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
        <div className="row-title">
          <Link href={routes.belief(belief.belief_id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub row-secondary">
          {belief.companies.join(", ") || "no company"} · as of{" "}
          {evidenceDay(belief.as_of)} · judged by {belief.judged_by}
        </div>
        {changed && (
          <div className="reader-row-sub">
            <strong>Since drafted:</strong> {changed}
          </div>
        )}
      </div>
      <span className="row-verdict">
        <BeliefVerdict
          belief={{
            status: "active",
            open_flags: 0,
            open_notices: 0,
            judgement: {
              judgement: belief.judgement as BeliefRowData["judgement"],
              confidence: belief.confidence,
            },
          }}
        />
      </span>
      <div className="row-quotes">
        {quotesOf(belief).map((quote) => (
          <Quote key={`${quote.href}`} {...quote} />
        ))}
      </div>
    </li>
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
                    <div className="row-title">
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

/** Rows shown before `All`. */
export const ISSUES_SHOWN = 7;

/** The theme's Issues still open: what the Hypothesis does not yet settle. */
export function OpenIssues({ theme, title = "Open Issues" }: { theme: string; title?: string }) {
  const issues = useApi("issues", loadIssues);
  return (
    <section aria-labelledby="open-issues">
      <h2 id="open-issues">{title}</h2>
      <Load loaded={issues} what="the Issues">
        {(page) => {
          const open = openIssues(page.items, theme);
          return open.length === 0 ? (
            <p className="muted">None open on this theme.</p>
          ) : (
            <>
              <ul className="reader-rows" aria-label="Open issues">
                {open.slice(0, ISSUES_SHOWN).map((issue) => (
                  <li className="reader-row" key={issue.id}>
                    <div className="row-title one-line">
                      <Link href={routes.issue(issue.id)} title={issue.title}>
                        {issue.title}
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="card-more">
                <Link href={routes.issues(`theme=${encodeURIComponent(theme)}`)}>
                  {open.length > ISSUES_SHOWN ? `All ${open.length} Issues` : "All Issues"}
                </Link>
              </p>
            </>
          );
        }}
      </Load>
    </section>
  );
}
