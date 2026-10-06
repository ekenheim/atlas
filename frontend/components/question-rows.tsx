import Link from "next/link";
import type { ReactNode } from "react";

import {
  dayOf,
  hypothesisWords,
  rowResult,
  runsLabel,
  statusTone,
  type HypothesisLine,
  type QuestionRow,
} from "../lib/research-index";
import { routes } from "../lib/routes";

/**
 * The reader's question rows. A question with a Hypothesis leads with its thesis and the
 * question under it; one without leads with the question and a Draft pill.
 */
export function QuestionRows({
  rows,
  hypotheses,
  seeds,
}: {
  rows: QuestionRow[];
  hypotheses: ReadonlyMap<string, HypothesisLine>;
  /** The companies to name under a row (the index shows its seeds; a dossier needs none). */
  seeds?: (row: QuestionRow) => ReactNode;
}) {
  return (
    <ul className="reader-rows">
      {rows.map((row) => {
        const result = rowResult(row, hypotheses);
        const sub = (
          <div className="reader-row-sub">
            {result.kind === "hypothesis" && (
              <>
                <Link href={routes.investigation(row.latest.id)}>{row.question}</Link>
                {" · "}
              </>
            )}
            {dayOf(row.latest.created_at)}
            {runsLabel(row.runs) ? ` · ${runsLabel(row.runs)}` : ""}
            {seeds?.(row)}
          </div>
        );
        return (
          <li key={row.latest.id}>
            <div className="reader-row">
              <div>
                {result.kind === "hypothesis" ? (
                  <Link className="reader-row-title" href={routes.hypothesis(result.id)}>
                    {result.thesis}
                  </Link>
                ) : (
                  <Link className="reader-row-title" href={routes.investigation(row.latest.id)}>
                    {row.question}
                  </Link>
                )}
                {sub}
              </div>
              <span
                className={`reader-pill ${
                  result.kind === "hypothesis" ? "reader-supported" : statusTone(row.latest)
                }`}
              >
                {result.kind === "hypothesis" ? hypothesisWords(result.status) : result.words}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
