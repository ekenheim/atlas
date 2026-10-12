"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import {
  CitationQuote,
  FlagList,
  JudgementLine,
  JudgementPill,
} from "../../components/beliefs";
import { Load, Row } from "../../components/ui";
import { ApiError, api, type Belief } from "../../lib/api/client";
import {
  JUDGEMENTS,
  STATUSES,
  STEPS,
  citationsByCompany,
  companyNames,
  day,
  judgedBy,
  type JudgementName,
} from "../../lib/beliefs";
import { routes } from "../../lib/routes";
import { useIdParam, usePolled } from "../../lib/use-api";

export default function BeliefPage() {
  return (
    <Suspense>
      <BeliefDetail />
    </Suspense>
  );
}

const never = () => false;

function BeliefDetail() {
  const id = useIdParam();
  const [loaded, reload] = usePolled(id, api.belief, 0, never);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.beliefs()}>Beliefs</Link>
      </p>
      <Load loaded={loaded} what="the belief">
        {(belief) => <Body belief={belief} reload={reload} />}
      </Load>
    </>
  );
}

function Body({ belief, reload }: { belief: Belief; reload: () => void }) {
  const against = belief.counterevidence;
  const supporting = belief.citations.filter(
    (citation) => citation.valence >= 0,
  );
  return (
    <>
      <h1>{belief.statement}</h1>
      <p>
        <JudgementPill belief={belief} />{" "}
        <span className="muted">{STEPS[belief.step]}</span>
        {belief.status !== "active" && (
          <strong> {STATUSES[belief.status]}</strong>
        )}
      </p>
      <p className="muted-small">
        Judged by {judgedBy(belief.judgement)}: {belief.judgement.reason}.
        Evidence as of {day(belief.as_of)}. About {companyNames(belief)}.
      </p>

      {belief.superseded_by.length > 0 && (
        <section aria-labelledby="superseded-by">
          <h2 id="superseded-by">Superseded by</h2>
          <ul>
            {belief.superseded_by.map((link) => (
              <li key={link.id}>
                <Link href={routes.belief(link.id)}>{link.statement}</Link>
                <br />
                <span className="muted-small">
                  {link.reason} ({judgedBy(link)})
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {belief.open_flags > 0 && (
        <section aria-labelledby="flags">
          <h2 id="flags">Needs a second look</h2>
          <FlagList flags={belief.flags} />
        </section>
      )}

      <section aria-labelledby="evidence">
        <h2 id="evidence">Evidence for it</h2>
        {supporting.length === 0 ? (
          <p className="muted">No citation supports it.</p>
        ) : (
          citationsByCompany(supporting).map((group) => (
            <div key={group.company}>
              <h3>{group.company}</h3>
              {group.citations.map((citation) => (
                <CitationQuote key={citation.id} citation={citation} />
              ))}
            </div>
          ))
        )}
      </section>

      <section aria-labelledby="against">
        <h2 id="against">Evidence against it</h2>
        {against.length === 0 ? (
          <p className="muted">Nothing cited against it.</p>
        ) : (
          against.map((citation) => (
            <CitationQuote key={citation.id} citation={citation} />
          ))
        )}
      </section>

      {belief.supersedes.length > 0 && (
        <section aria-labelledby="supersedes">
          <h2 id="supersedes">It replaces</h2>
          <ul>
            {belief.supersedes.map((link) => (
              <li key={link.id}>
                <Link href={routes.belief(link.id)}>{link.statement}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <details className="reader-records">
        <summary>
          <h2 className="records-title">Records</h2>
          <span>judgement history, flags, session</span>
        </summary>
        <h3>Judgements</h3>
        <ol aria-label="Judgement history">
          {belief.history.map((judgement) => (
            <JudgementLine key={judgement.id} judgement={judgement} />
          ))}
        </ol>
        <h3>Flags</h3>
        <FlagList flags={belief.flags} />
        <table>
          <caption>The Belief</caption>
          <tbody>
            <Row name="Session">
              {belief.session ? (
                <Link href={routes.session(belief.session.id)}>
                  {belief.session.question}
                </Link>
              ) : (
                <span className="muted">none</span>
              )}
            </Row>
            <Row name="Proposed by">
              {belief.created_by}, {day(belief.created_at)}
            </Row>
            <Row name="Citations">{belief.citation_count}</Row>
          </tbody>
        </table>
        {belief.status === "active" && (
          <JudgeForm belief={belief} reload={reload} />
        )}
      </details>
    </>
  );
}

function JudgeForm({ belief, reload }: { belief: Belief; reload: () => void }) {
  const [judgement, setJudgement] = useState<JudgementName>(
    belief.judgement.judgement,
  );
  const [confidence, setConfidence] = useState(belief.judgement.confidence);
  const [reason, setReason] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  return (
    <form
      aria-label="Set the judgement"
      onSubmit={(event) => {
        event.preventDefault();
        setFailure(null);
        api
          .judgeBelief(belief.id, {
            actor: "owner",
            judgement,
            confidence,
            reason,
          })
          .then(() => {
            setReason("");
            reload();
          })
          .catch((error: unknown) =>
            setFailure(
              error instanceof ApiError ? error.message : String(error),
            ),
          );
      }}
    >
      <h3>Set the judgement</h3>
      <div className="field">
        <label htmlFor="judge-judgement">Judgement</label>
        <select
          id="judge-judgement"
          value={judgement}
          onChange={(event) =>
            setJudgement(event.target.value as JudgementName)
          }
        >
          {Object.entries(JUDGEMENTS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="judge-confidence">Confidence (0 to 1)</label>
        <input
          id="judge-confidence"
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={confidence}
          onChange={(event) => setConfidence(Number(event.target.value))}
        />
      </div>
      <div className="field">
        <label htmlFor="judge-reason">Reason</label>
        <input
          id="judge-reason"
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <button type="submit">Set judgement</button>
      {failure && <p role="alert">Could not set it: {failure}</p>}
    </form>
  );
}
