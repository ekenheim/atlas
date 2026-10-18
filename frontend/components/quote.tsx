"use client";

// The evidence block, in four lines (spec §3.5): Atlas's statement of the Fact, the document's own
// words, who said it and where and when, and the way into the source at that span. The words are
// selectable and no link overlays them (Y8): the path from a claim to its highlighted span stays
// two clicks, and "Open in source" is that second click.
import Link from "next/link";
import { useState } from "react";

import { evidenceDay } from "../lib/format";

/** A quote longer than this is clamped, with a toggle for the whole of it. */
export const CLAMP_AT = 600;

export interface QuoteProps {
  /** Atlas's own statement of the Fact (line 1); absent for a bare Assertion. */
  statement?: string | null;
  /** The document's words, verbatim (line 2). */
  quote: string;
  company?: string | null;
  document?: string | null;
  /** When the document became public (ISO); shown as an absolute day with its year. */
  availableAt?: string | null;
  /** Where the span opens in the source (`routes.span`); none: no link. */
  href?: string | null;
  loadBearing?: boolean;
  /** Evidence that counts against what it is cited for. */
  against?: boolean;
  note?: string | null;
  /** The cited statement no longer stands (a superseded Fact, a disputed Assertion). */
  noLongerStands?: boolean;
}

export function Quote({
  statement,
  quote,
  company,
  document,
  availableAt,
  href,
  loadBearing = false,
  against = false,
  note,
  noLongerStands = false,
}: QuoteProps) {
  const long = quote.length > CLAMP_AT;
  const [whole, setWhole] = useState(false);
  const caption = [company, document, availableAt ? evidenceDay(availableAt) : null].filter(
    (part): part is string => Boolean(part),
  );
  return (
    <figure className={`quote-card${against ? " quote-against" : ""}`}>
      {statement ? <p className="quote-statement">{statement}</p> : null}
      <blockquote className={`quote quote-text${long && !whole ? " quote-clamped" : ""}`}>{quote}</blockquote>
      {long ? (
        <button
          type="button"
          className="quote-toggle"
          aria-expanded={whole}
          onClick={() => setWhole((each) => !each)}
        >
          {whole ? "Clamp the quote" : "Whole quote"}
        </button>
      ) : null}
      <figcaption className="quote-caption">
        {caption.join(" · ")}
        {loadBearing ? <span className="quote-tag">load-bearing</span> : null}
        {noLongerStands ? <span className="quote-tag quote-tag-gap">no longer stands</span> : null}
        {note ? <> · {note}</> : null}
      </figcaption>
      {href ? (
        <Link className="quote-open" href={href}>
          Open in source <span aria-hidden="true">→</span>
        </Link>
      ) : null}
    </figure>
  );
}
