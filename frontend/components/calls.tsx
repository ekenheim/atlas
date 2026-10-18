"use client";

// The prospective record on the pages (atlas-beliefs ticket 19): calls with what followed, and a
// Hypothesis's predictions with their settlements. A record of what Atlas said and what came
// after, in few words. A call has one cell until its first checkpoint; after, the change at
// +1, +3 and +6 months relative to the benchmark, with the sign in the text.
import Link from "next/link";

import { api, type Call } from "../lib/api/client";
import { DIRECTIONS, ORIGINS, SOURCES, companiesLine, expectedRange } from "../lib/calls";
import { evidenceDay } from "../lib/format";
import { callCells } from "../lib/record";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { PredictionStatus } from "./status";
import { Load, Missing } from "./ui";

const loadCalls = async (theme: string) => (await api.calls(theme)).items;

/** Calls as a table: the date, the claim, the companies, and the cells. */
export function CallsTable({ calls, now = new Date() }: { calls: readonly Call[]; now?: Date }) {
  const checkpointed = calls.some((call) => call.checkpoints.length > 0);
  return (
    <table className="calls">
      <caption className="sr-only">Calls and the change since each</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th scope="col">Call</th>
          <th scope="col">Companies</th>
          {checkpointed ? (
            <>
              <th scope="col">+1 m</th>
              <th scope="col">+3 m</th>
              <th scope="col">+6 m</th>
            </>
          ) : (
            <th scope="col">Next</th>
          )}
        </tr>
      </thead>
      <tbody>
        {calls.map((call) => {
          const cells = callCells(call, now);
          return (
            <tr key={call.id}>
              <th scope="row">{evidenceDay(call.made_at)}</th>
              <td className="call-claim">
                {call.claim}
                <br />
                <span className="muted-small">
                  {ORIGINS[call.origin]}
                  {call.direction && `, ${DIRECTIONS[call.direction]}`}
                </span>
              </td>
              <td className="call-companies">
                {call.companies.length === 0 ? (
                  <Missing>{companiesLine(call)}</Missing>
                ) : (
                  call.companies.map((company, index) => (
                    <span key={company.company_id}>
                      {index > 0 && ", "}
                      <Link href={routes.company(company.company_id)}>{company.display_name}</Link>
                    </span>
                  ))
                )}
              </td>
              {checkpointed ? (
                cells.horizons.map((cell) => (
                  <td key={cell.horizon} className={`call-${cell.tone}`}>
                    {cell.text}
                  </td>
                ))
              ) : (
                <td className="call-due">{cells.first}</td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** The theme's calls (narrowed by `select`), in the Records of a Hypothesis. */
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
    select && loaded.state === "ready" ? { ...loaded, data: select(loaded.data) } : loaded;
  return (
    <section aria-labelledby="calls">
      <h2 id="calls">{title}</h2>
      <Load loaded={calls} what="the calls">
        {(calls) =>
          calls.length === 0 ? (
            <p className="muted">No calls yet.</p>
          ) : (
            <CallsTable calls={calls} />
          )
        }
      </Load>
    </section>
  );
}

const loadPredictions = async (hypothesisId: string) => (await api.hypothesisPredictions(hypothesisId)).items;

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
                    <th scope="row" className="th-wrap">
                      {prediction.measure}
                      <br />
                      <span className="muted-small">version {prediction.version}</span>
                    </th>
                    <td>
                      {expectedRange(prediction.expected_low, prediction.expected_high, prediction.unit)}
                    </td>
                    <td>{SOURCES[prediction.source_kind]}</td>
                    <td>
                      <PredictionStatus prediction={prediction} />
                      <span className="muted-small">due {evidenceDay(prediction.deadline)}</span>
                      {prediction.settlement && (
                        <>
                          <br />
                          <span className="muted-small">
                            at {prediction.settlement.value}
                            {prediction.settlement.note ? ` · ${prediction.settlement.note}` : ""}
                          </span>
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
