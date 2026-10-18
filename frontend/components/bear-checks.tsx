"use client";

// A company's bear checks (spec §10.6): six rows in a fixed order, each its label, a short value
// and a word only for a flag or an unknown; opening a row gives the check's sentence, its figures,
// the sentences it quotes (each opening the filing at the span) and the filings it read. An
// unknown check is always shown, with why. An older backend (404) or a failed read hides the
// section. How each was read is in the Records (`BearChecksRecords`).
import Link from "next/link";

import { api, type BearCheck } from "../lib/api/client";
import {
  bearFigures,
  bearFilings,
  bearLabel,
  bearQuotes,
  bearSummary,
  bearValue,
  bearWord,
  orderedChecks,
  unknownText,
} from "../lib/bear-checks";
import { useApi } from "../lib/use-api";
import { Quote } from "./quote";

function BearRow({ check, now }: { check: BearCheck; now: Date }) {
  const word = bearWord(check);
  const figures = bearFigures(check);
  const quotes = bearQuotes(check);
  const filings = bearFilings(check);
  const label = bearLabel(check);
  return (
    <li>
      <details className="bear-row">
        <summary>
          <span className="bear-label">{label}</span>
          {check.status === "unknown" ? (
            <span className="bear-unknown">Unknown · {unknownText(check)}</span>
          ) : (
            <>
              <span className="bear-value">{bearValue(check, now)}</span>
              {word ? <span className={`bear-word status-${word.tone}`}>{word.word}</span> : null}
            </>
          )}
        </summary>
        <div className="bear-body">
          {check.summary ? <p>{check.summary}</p> : null}
          {figures.length > 0 ? (
            <dl className="bear-figures">
              {figures.map((figure) => (
                <div key={figure.label}>
                  <dt>{figure.label}</dt>
                  <dd>
                    {figure.href ? (
                      <Link href={figure.href}>
                        Open the filing <span aria-hidden="true">→</span>
                      </Link>
                    ) : (
                      figure.value
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {quotes.map((quote) => (
            <Quote
              key={quote.href}
              quote={quote.quote}
              document={quote.form}
              availableAt={quote.availableAt}
              href={quote.href}
            />
          ))}
          {filings.map((filing) => (
            <p key={filing.href}>
              <Link href={filing.href}>
                Open the filing <span aria-hidden="true">→</span>
              </Link>{" "}
              <span className="muted-small">{filing.form}</span>
            </p>
          ))}
        </div>
      </details>
    </li>
  );
}

export function BearChecks({ companyId }: { companyId: string }) {
  const loaded = useApi(companyId, api.bearChecks);
  if (loaded.state !== "ready" || loaded.data === null) return null;
  const now = new Date();
  return (
    <section id="bear" className="bear" aria-labelledby="bear-title">
      <h2 className="reader-label" id="bear-title">
        Bear checks
      </h2>
      <p className="bear-summary">{bearSummary(loaded.data)}</p>
      <ul className="bear-rows" aria-label="Bear checks">
        {orderedChecks(loaded.data.checks).map((check) => (
          <BearRow key={check.key} check={check} now={now} />
        ))}
      </ul>
    </section>
  );
}
