"use client";

// Whether Atlas is working: what it said, dated, and what followed. Calls are priced against
// their theme's companies at one, three and six months; predictions settle against a figure.
// Closes score a call after the fact and are never evidence.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { CallsTable } from "../../components/calls";
import { StatStrip } from "../../components/stat-strip";
import { PredictionStatus } from "../../components/status";
import { Load } from "../../components/ui";
import { api } from "../../lib/api/client";
import { evidenceDay, plainDay } from "../../lib/format";
import { firstClause, rangeText } from "../../lib/due";
import {
  callsByTheme,
  firstCheckpointSentence,
  recordFigures,
} from "../../lib/record";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

export default function RecordPage() {
  return (
    <Suspense>
      <Record />
    </Suspense>
  );
}

const loadCalls = async () => (await api.allCalls()).items;
const loadPredictions = async () => (await api.predictions()).items;
const loadThemes = () => api.themes();

function Record() {
  const theme = useSearchParams().get("theme");
  const calls = useApi("calls", loadCalls);
  const predictions = useApi("predictions", loadPredictions);
  const themes = useApi("themes", loadThemes);
  const titles = new Map(
    themes.state === "ready" ? themes.data.map((each) => [each.id, each.title]) : [],
  );
  const now = new Date();
  return (
    <div className="record-page">
      <h1>Record</h1>
      <Load loaded={calls} what="the calls">
        {(allCalls) => {
          const mine = theme ? allCalls.filter((call) => call.theme === theme) : allCalls;
          const given = predictions.state === "ready" ? predictions.data : [];
          const shownPredictions = theme ? given.filter((each) => each.theme === theme) : given;
          const figures = recordFigures(mine, shownPredictions);
          const sentence = firstCheckpointSentence(mine, now);
          return (
            <>
              <StatStrip
                label="The record"
                stats={[
                  { label: "Calls open", value: figures.open },
                  { label: "Checkpoints recorded", value: figures.checkpoints },
                  {
                    label: "Ahead of benchmark at +3 m",
                    value: figures.ahead ? `${figures.ahead.count} of ${figures.ahead.of}` : "—",
                    sub: figures.ahead
                      ? undefined
                      : figures.aheadUntil
                        ? `until ${plainDay(figures.aheadUntil, now)}`
                        : undefined,
                  },
                  {
                    label: "Predictions open · met · missed",
                    value: `${figures.predictions.open} · ${figures.predictions.met} · ${figures.predictions.missed}`,
                  },
                ]}
              />
              {theme ? (
                <p className="muted-small">
                  {titles.get(theme) ?? theme} ·{" "}
                  <Link href={routes.record}>All themes</Link>
                </p>
              ) : null}
              {sentence ? <p className="measure">{sentence}</p> : null}

              <section aria-labelledby="calls">
                <h2 className="reader-label" id="calls">
                  Calls
                </h2>
                {mine.length === 0 ? (
                  <p className="muted">
                    No calls yet: a call is made when a Belief is judged proven or a thesis is
                    published.
                  </p>
                ) : (
                  callsByTheme(mine).map((group) => (
                    <div key={group.theme} className="record-theme">
                      <h3 className="record-theme-title">{titles.get(group.theme) ?? group.theme}</h3>
                      <div className="records-body">
                        <CallsTable calls={group.calls} now={now} />
                      </div>
                    </div>
                  ))
                )}
              </section>

              <section aria-labelledby="predictions">
                <h2 className="reader-label" id="predictions">
                  Predictions
                </h2>
                {predictions.state === "loading" ? (
                  <span className="sk sk-line" />
                ) : predictions.state === "error" ? (
                  <p className="muted">Predictions unavailable</p>
                ) : shownPredictions.length === 0 ? (
                  <p className="muted">No prediction is recorded yet.</p>
                ) : (
                  <ul className="reader-rows" aria-label="Predictions">
                    {shownPredictions.map((prediction) => (
                      <li className="reader-row" key={prediction.id}>
                        <div>
                          <div className="row-title" title={prediction.measure}>
                            <Link href={routes.hypothesis(prediction.hypothesis_id)}>
                              {evidenceDay(prediction.deadline)} · {firstClause(prediction.measure)}
                            </Link>
                          </div>
                          <div className="reader-row-sub">
                            {rangeText(prediction.expected_low, prediction.expected_high, prediction.unit)}
                          </div>
                        </div>
                        <span className="row-verdict">
                          <PredictionStatus prediction={prediction} />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          );
        }}
      </Load>
    </div>
  );
}
