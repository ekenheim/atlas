import Link from "next/link";

import type { Belief, BeliefSummary } from "../lib/api/client";
import {
  FLAGS,
  JUDGEMENTS,
  companyNames,
  confidenceText,
  day,
  direction,
  judgementTone,
  judgedBy,
  valenceText,
} from "../lib/beliefs";
import { routes } from "../lib/routes";

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

/** One Belief as a row: the statement first, then who and what stands behind it. */
export function BeliefRow({ belief }: { belief: BeliefSummary }) {
  return (
    <li className="reader-row" aria-label={belief.statement}>
      <div>
        <div className="reader-row-title">
          <Link href={routes.belief(belief.id)}>{belief.statement}</Link>
        </div>
        <div className="reader-row-sub">
          {companyNames(belief)} · as of {day(belief.as_of)} ·{" "}
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
        </div>
      </div>
      <JudgementPill belief={belief} />
    </li>
  );
}

/** A citation: the quote, who said it and when, and the link that opens it at its span. */
export function CitationQuote({ citation }: { citation: Citation }) {
  const against = direction(citation.valence) === "against";
  return (
    <figure className={`reader-quote${against ? " reader-against" : ""}`}>
      {citation.statement && <p>{citation.statement}</p>}
      <blockquote>{citation.quote}</blockquote>
      <figcaption>
        {citation.company_name} · {citation.source_title ?? "source"} ·
        available {day(citation.available_at)} · {valenceText(citation)}
        {!citation.stands && " · no longer stands"}
        {" · "}
        <Link href={routes.span(citation.source_version_id, citation.ref_id)}>
          Source
        </Link>
        {citation.note && <> · {citation.note}</>}
      </figcaption>
    </figure>
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
            {flag.detail} Raised {day(flag.raised_at)}.
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
