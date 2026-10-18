"use client";

// The claim, how sure Atlas is, and the quote in its document, one click away. The judgement's
// reason, its history, flags, examinations and the session are in the Records.
import Link from "next/link";
import { Suspense, useState } from "react";

import {
  CitationQuote,
  FlagList,
  JudgementLine,
  NoticeList,
} from "../../components/beliefs";
import { RecordsFold } from "../../components/records-fold";
import { BeliefVerdict } from "../../components/status";
import { Load, Row, Timestamp } from "../../components/ui";
import { ApiError, api, type Belief } from "../../lib/api/client";
import {
  FLAGS,
  JUDGEMENTS,
  OUTCOMES,
  STEPS,
  judgedBy,
  testedText,
  type JudgementName,
} from "../../lib/beliefs";
import { evidenceDay } from "../../lib/format";
import { routes } from "../../lib/routes";
import { forgetDecideCount } from "../../lib/decide";
import { useApi, useIdParam, usePolled } from "../../lib/use-api";

export default function BeliefPage() {
  return (
    <Suspense>
      <BeliefDetail />
    </Suspense>
  );
}

const never = () => false;
const loadThemes = () => api.themes();

function BeliefDetail() {
  const id = useIdParam();
  const [loaded, reload] = usePolled(id, api.belief, 0, never);
  return (
    <>
      <Load loaded={loaded} what="the belief">
        {(belief) => <Body belief={belief} reload={reload} />}
      </Load>
    </>
  );
}

/** Citations shown before `+N`. */
const SHOWN = 7;

function Group({ citations }: { citations: Belief["citations"] }) {
  const [all, setAll] = useState(false);
  const shown = all ? citations : citations.slice(0, SHOWN);
  return (
    <>
      {shown.map((citation) => (
        <CitationQuote key={citation.id} citation={citation} />
      ))}
      {!all && citations.length > SHOWN ? (
        <button type="button" className="show-all show-all-flush" onClick={() => setAll(true)}>
          +{citations.length - SHOWN}
        </button>
      ) : null}
    </>
  );
}

function Body({ belief, reload }: { belief: Belief; reload: () => void }) {
  const themes = useApi("themes", loadThemes);
  const themeTitle =
    themes.state === "ready"
      ? (themes.data.find((each) => each.id === belief.theme)?.title ?? belief.theme)
      : belief.theme;
  const supporting = belief.citations.filter((citation) => citation.valence >= 0);
  const against = belief.counterevidence.filter((citation) => citation.weight === "load_bearing");
  const context = belief.counterevidence.filter((citation) => citation.weight !== "load_bearing");
  const openFlag = belief.flags.find((flag) => flag.cleared_by === null);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.theme(belief.theme)}>{themeTitle}</Link>
      </p>
      <h1 className="measure">{belief.statement}</h1>
      <p className="verdict-line" aria-label="Verdict">
        <BeliefVerdict belief={belief} />{" "}
        <span className="verdict-rest">
          · judged {evidenceDay(belief.judgement.at)} · {STEPS[belief.step]} · as of{" "}
          {evidenceDay(belief.as_of)}
        </span>
      </p>
      {openFlag ? <p className="verdict-reason">{FLAGS[openFlag.kind]}</p> : null}

      {belief.superseded_by.length > 0 && (
        <section aria-labelledby="superseded-by">
          <h2 className="reader-label" id="superseded-by">
            Superseded by
          </h2>
          <ul className="reader-rows">
            {belief.superseded_by.map((link) => (
              <li className="reader-row" key={link.id}>
                <div className="row-title">
                  <Link href={routes.belief(link.id)}>{link.statement}</Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {belief.open_flags > 0 && (
        <section aria-labelledby="flags">
          <h2 className="reader-label" id="flags">
            Needs a second look
          </h2>
          <FlagList flags={belief.flags} />
        </section>
      )}

      {belief.open_notices > 0 && (
        <section aria-labelledby="notices">
          <h2 className="reader-label" id="notices">
            Newer evidence supports it
          </h2>
          <NoticeList notices={belief.notices} />
        </section>
      )}

      <section aria-labelledby="evidence">
        <h2 className="reader-label" id="evidence">
          Evidence for it
        </h2>
        {supporting.length === 0 ? (
          <p className="muted">No citation supports it.</p>
        ) : (
          <Group citations={supporting} />
        )}
      </section>

      {against.length > 0 ? (
        <section aria-labelledby="against">
          <h2 className="reader-label" id="against">
            Evidence against it
          </h2>
          <Group citations={against} />
        </section>
      ) : (
        <p className="muted">Nothing against it found yet</p>
      )}

      {context.length > 0 && (
        <section aria-labelledby="context">
          <h2 className="reader-label" id="context">
            Context
          </h2>
          <Group citations={context} />
        </section>
      )}

      {belief.supersedes.length > 0 && (
        <section aria-labelledby="supersedes">
          <h2 className="reader-label" id="supersedes">
            It replaces
          </h2>
          <ul className="reader-rows">
            {belief.supersedes.map((link) => (
              <li className="reader-row" key={link.id}>
                <div className="row-title">
                  <Link href={routes.belief(link.id)}>{link.statement}</Link>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <RecordsFold>
        <p className="measure">
          <strong>Judged by {judgedBy(belief.judgement)}:</strong> {belief.judgement.reason}
        </p>
        <h3>Judgements</h3>
        <ol aria-label="Judgement history">
          {belief.history.map((judgement) => (
            <JudgementLine key={judgement.id} judgement={judgement} />
          ))}
        </ol>
        <h3>Flags</h3>
        <FlagList flags={belief.flags} />
        <h3>Notices</h3>
        <NoticeList notices={belief.notices} />
        <h3>Examinations</h3>
        {belief.examinations.length === 0 ? (
          <p className="muted">Not tested since it was proposed.</p>
        ) : (
          <ul aria-label="Examinations">
            {belief.examinations.map((each) => (
              <li key={each.id}>
                {OUTCOMES[each.outcome]} · <Timestamp value={each.at} mode="exact" /> · as of{" "}
                <Timestamp value={each.as_of} mode="exact" /> · {each.actor}
                {each.note ? <> · {each.note}</> : null}
              </li>
            ))}
          </ul>
        )}
        <table>
          <caption>The Belief</caption>
          <tbody>
            <Row name="Session">
              {belief.session ? (
                <Link href={routes.session(belief.session.id)}>{belief.session.question}</Link>
              ) : (
                <span className="muted">none</span>
              )}
            </Row>
            <Row name="Proposed by">
              {belief.created_by}, <Timestamp value={belief.created_at} mode="exact" />
            </Row>
            <Row name="Citations">{belief.citation_count}</Row>
            <Row name="Tested">{testedText(belief)}</Row>
          </tbody>
        </table>
        {belief.status === "active" && <JudgeForm belief={belief} reload={reload} />}
      </RecordsFold>
    </>
  );
}

function JudgeForm({ belief, reload }: { belief: Belief; reload: () => void }) {
  const [judgement, setJudgement] = useState<JudgementName>(belief.judgement.judgement);
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
            forgetDecideCount();
            reload();
          })
          .catch((error: unknown) =>
            setFailure(error instanceof ApiError ? error.message : String(error)),
          );
      }}
    >
      <h3>Set the judgement</h3>
      <div className="field">
        <label htmlFor="judge-judgement">Judgement</label>
        <select
          id="judge-judgement"
          value={judgement}
          onChange={(event) => setJudgement(event.target.value as JudgementName)}
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
