import Link from "next/link";

import type { Belief, BeliefSummary } from "../lib/api/client";
import {
  type Exposure,
  EXPOSURE,
  FLAGS,
  JUDGEMENTS,
  NOTICES,
  answeredSteps,
  companyNames,
  confidenceText,
  confirmationText,
  direction,
  groupBySteps,
  judgementTone,
  judgedBy,
} from "../lib/beliefs";
import { evidenceDay } from "../lib/format";
import { routes } from "../lib/routes";
import { Quote } from "./quote";

type Citation = Belief["citations"][number];

/** The judgement as a coloured pill, with its confidence when one was formed. */
export function JudgementPill({
  belief,
}: {
  belief: Pick<BeliefSummary, "judgement">;
}) {
  const { judgement, confidence } = belief.judgement;
  return (
    <span className={`reader-pill ${judgementTone(judgement)}`}>
      {JUDGEMENTS[judgement]}
      {judgement !== "unproven" && ` ${confidenceText(confidence)}`}
    </span>
  );
}

/** One Belief as a row: the statement first, then who and what stands behind it. With
 * `exposure`, a company's page says how that company stands to it. */
export function BeliefRow({
  belief,
  exposure,
}: {
  belief: BeliefSummary;
  exposure?: Exposure;
}) {
  return (
    <li className="reader-row" aria-label={belief.statement}>
      <div>
        <div className="reader-row-title">
          <Link href={routes.belief(belief.id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub">
          {exposure && <>{EXPOSURE[exposure]} · </>}
          {companyNames(belief)} · as of {evidenceDay(belief.as_of)} ·{" "}
          {belief.citation_count}{" "}
          {belief.citation_count === 1 ? "citation" : "citations"}
          {belief.open_flags > 0 && (
            <>
              {" · "}
              <strong>
                {belief.open_flags} {belief.open_flags === 1 ? "flag" : "flags"}
              </strong>
            </>
          )}
          {belief.open_notices > 0 && (
            <>
              {" · "}
              <span className="reader-pill reader-supported">
                {confirmationText(belief)}
              </span>
            </>
          )}
        </div>
      </div>
      <JudgementPill belief={belief} />
    </li>
  );
}

/** A citation: the quote, who said it and when, and the link that opens it at its span. */
export function CitationQuote({ citation }: { citation: Citation }) {
  return (
    <Quote
      statement={citation.statement}
      quote={citation.quote}
      company={citation.company_name}
      document={citation.source_title ?? "source"}
      availableAt={citation.available_at}
      href={routes.span(citation.source_version_id, citation.ref_id)}
      loadBearing={citation.weight === "load_bearing"}
      against={direction(citation.valence) === "against"}
      note={citation.note}
      noLongerStands={!citation.stands}
    />
  );
}

/** The open and cleared flags of a Belief, the open ones first. */
export function FlagList({ flags }: { flags: Belief["flags"] }) {
  if (flags.length === 0) return <p className="muted">Nothing flagged.</p>;
  const ordered = [...flags].sort(
    (a, b) => Number(a.cleared_by !== null) - Number(b.cleared_by !== null),
  );
  return (
    <ul aria-label="Flags">
      {ordered.map((flag) => (
        <li key={flag.id}>
          <strong>{flag.cleared_by === null ? "Open" : "Cleared"}</strong>{" "}
          {FLAGS[flag.kind]}
          <br />
          <span className="muted-small">
            {flag.detail} Raised {evidenceDay(flag.raised_at)}.
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What supports a Belief, the open notices first: no doubt, so apart from the flags. */
export function NoticeList({ notices }: { notices: Belief["notices"] }) {
  if (notices.length === 0)
    return <p className="muted">Nothing new supports it.</p>;
  const ordered = [...notices].sort(
    (a, b) => Number(a.cleared_by !== null) - Number(b.cleared_by !== null),
  );
  return (
    <ul aria-label="Notices">
      {ordered.map((notice) => (
        <li key={notice.id}>
          <strong>{notice.cleared_by === null ? "Open" : "Cleared"}</strong>{" "}
          {NOTICES[notice.kind]}
          <br />
          <span className="muted-small">
            {notice.detail} Raised {evidenceDay(notice.raised_at)}.
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A judgement in the history: what, how sure, who, when and why. */
export function JudgementLine({
  judgement,
}: {
  judgement: Belief["judgement"];
}) {
  return (
    <li>
      <strong>{JUDGEMENTS[judgement.judgement]}</strong>{" "}
      {confidenceText(judgement.confidence)} · {judgedBy(judgement)}
      <br />
      <span className="muted-small">{judgement.reason}</span>
    </li>
  );
}

/**
 * Beliefs under the steps of the argument, in its order. `all` lists every step, saying so
 * when nothing is believed of one (a theme's gaps); otherwise only the steps answered. A
 * Belief that carries an `exposure` (a company's page) says how the company stands to it.
 */
export function BeliefSteps<T extends BeliefSummary & { exposure?: Exposure }>({
  beliefs,
  all = false,
}: {
  beliefs: readonly T[];
  all?: boolean;
}) {
  const groups = all ? groupBySteps(beliefs) : answeredSteps(beliefs);
  return (
    <>
      {groups.map((group) => (
        <section key={group.step} aria-label={group.title}>
          <p className="reader-step">
            <strong>{group.title}</strong>
          </p>
          {group.beliefs.length === 0 ? (
            <p className="muted">Nothing believed yet.</p>
          ) : (
            <ul className="reader-rows" aria-label={`${group.title} beliefs`}>
              {group.beliefs.map((belief) => (
                <BeliefRow
                  key={belief.id}
                  belief={belief}
                  exposure={belief.exposure}
                />
              ))}
            </ul>
          )}
        </section>
      ))}
    </>
  );
}
