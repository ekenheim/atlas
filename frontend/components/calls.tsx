"use client";

// The prospective record on the pages (atlas-beliefs ticket 19): a theme's calls with what
// followed, and a Hypothesis's predictions with their settlements. A record of what Atlas said
// and what came after, in few words; raw rows are one click deeper.
import Link from "next/link";

import { api, type Call } from "../lib/api/client";
import {
  DIRECTIONS,
  HORIZONS,
  ORIGINS,
  SOURCES,
  callsSummary,
  cells,
  companiesLine,
  expectedRange,
  predictionStatus,
  shortDate,
} from "../lib/calls";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { Load, Missing } from "./ui";

const loadCalls = async (theme: string) => (await api.calls(theme)).items;

/** The theme's calls: the date, the claim, the companies, and the change since, relative to the
 * theme's peers, at one, three and six months. */
export function CallsPanel({
  theme,
  select,
  title = "Calls",
}: {
  theme: string;
  /** Narrow the theme's calls (a Hypothesis shows only the calls made for it). */
  select?: (calls: Call[]) => Call[];
  title?: string;
}) {
  const loaded = useApi(theme, loadCalls);
  const calls =
    select && loaded.state === "ready"
      ? { ...loaded, data: select(loaded.data) }
      : loaded;
  return (
    <section aria-labelledby="calls">
      <h2 className="reader-label" id="calls">
        {title}
      </h2>
      <Load loaded={calls} what="the calls">
        {(calls) => (
          <>
            <p className="muted-small">
              What Atlas said, on the date it said it, and what followed: each company&apos;s change
              since, relative to the theme&apos;s companies together. {callsSummary(calls)}
            </p>
            {calls.length > 0 && (
              <table className="calls">
                <caption className="sr-only">Calls and the change since each</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Call</th>
                    <th scope="col">Companies</th>
                    {HORIZONS.map((months) => (
                      <th scope="col" key={months}>
                        +{months}m
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {calls.map((call) => (
                    <tr key={call.id}>
                      <th scope="row">{shortDate(call.made_at)}</th>
                      <td>
                        {call.claim}
                        <br />
                        <span className="muted-small">
                          {ORIGINS[call.origin]}
                          {call.direction && `, ${DIRECTIONS[call.direction]}`}
                        </span>
                      </td>
                      <td>
                        {call.companies.length === 0 ? (
                          <Missing>{companiesLine(call)}</Missing>
                        ) : (
                          call.companies.map((company, index) => (
                            <span key={company.company_id}>
                              {index > 0 && ", "}
                              <Link href={routes.company(company.company_id)}>
                                {company.display_name}
                              </Link>
                            </span>
                          ))
                        )}
                      </td>
                      {cells(call).map((cell) => (
                        <td key={cell.horizon} className={`call-${cell.tone}`} title={cell.detail}>
                          {cell.text}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Load>
    </section>
  );
}

const loadPredictions = async (hypothesisId: string) => (await api.predictions(hypothesisId)).items;

/** The Hypothesis's predictions: the measure, the range expected, the deadline and the source
 * that settles it, then what settled it. */
export function Predictions({ hypothesisId }: { hypothesisId: string }) {
  const predictions = useApi(hypothesisId, loadPredictions);
  return (
    <section aria-labelledby="predictions">
      <h2 id="predictions">Predictions</h2>
      <Load loaded={predictions} what="the predictions">
        {(predictions) =>
          predictions.length === 0 ? (
            <p>No prediction is recorded on this Hypothesis.</p>
          ) : (
            <table>
              <caption className="sr-only">Predictions and how they came out</caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Settled by</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {predictions.map((prediction) => (
                  <tr key={prediction.id}>
                    <th scope="row">
                      {prediction.measure}
                      <br />
                      <span className="muted-small">version {prediction.version}</span>
                    </th>
                    <td>
                      {expectedRange(
                        prediction.expected_low,
                        prediction.expected_high,
                        prediction.unit,
                      )}
                    </td>
                    <td>{SOURCES[prediction.source_kind]}</td>
                    <td className={`prediction-${prediction.state}`}>
                      {predictionStatus(prediction)}
                      {prediction.settlement?.note && (
                        <>
                          <br />
                          <span className="muted-small">{prediction.settlement.note}</span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Load>
    </section>
  );
}
