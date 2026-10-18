"use client";

// The theme page's lists: its Hypotheses (in the Records) and what changed (above them). Both in
// few words; each row opens the record it is about.
import Link from "next/link";
import { useState } from "react";

import { type Hypothesis, type ThemeChange, api } from "../lib/api/client";
import { activity, plainDay } from "../lib/format";
import { routes } from "../lib/routes";
import { isUnseen } from "../lib/seen";
import { lifecycleWord, publishedVersion } from "../lib/status";
import { changeHref, changeLabel, hypothesisThesis, themeHypotheses } from "../lib/themes";
import { orderChanges } from "../lib/today";
import { useApi } from "../lib/use-api";
import { Status } from "./status";
import { Load } from "./ui";

const loadHypotheses = async (theme: string) => (await api.hypothesesFor(theme)).items;

/** The theme's Hypotheses, the published first: the thesis, its status and when it last changed. */
export function ThemeHypotheses({ theme }: { theme: string }) {
  const loaded = useApi(theme, loadHypotheses);
  return (
    <section aria-labelledby="hypotheses">
      <h2 className="reader-label" id="hypotheses">
        Hypotheses
      </h2>
      <Load loaded={loaded} what="the Hypotheses">
        {(all: Hypothesis[]) => {
          const mine = themeHypotheses(all, theme);
          return mine.length === 0 ? (
            <p className="muted">No Hypothesis on this theme yet.</p>
          ) : (
            <ul className="reader-rows" aria-label="Hypotheses">
              {mine.map((hypothesis) => {
                const published = publishedVersion(hypothesis);
                const thesis = hypothesisThesis(hypothesis);
                return (
                  <li className="reader-row" key={hypothesis.id} aria-label={thesis}>
                    <div>
                      <div className="row-title">
                        <Link href={routes.hypothesis(hypothesis.id)}>{thesis}</Link>
                      </div>
                      <div className="reader-row-sub row-secondary">
                        {published === null
                          ? "not published"
                          : `Published ${plainDay(hypothesis.first_published_at ?? published.published_at)}`}
                        {" · "}
                        {hypothesis.versions.length}{" "}
                        {hypothesis.versions.length === 1 ? "version" : "versions"}
                        {hypothesis.open_proposed_updates > 0 && (
                          <>
                            {" · "}
                            <strong>
                              {hypothesis.open_proposed_updates} proposed{" "}
                              {hypothesis.open_proposed_updates === 1 ? "update" : "updates"}
                            </strong>
                          </>
                        )}
                      </div>
                    </div>
                    <span className="row-verdict">
                      <Status word={lifecycleWord(hypothesis.status)} />
                    </span>
                  </li>
                );
              })}
            </ul>
          );
        }}
      </Load>
    </section>
  );
}

/** Rows shown before `All N`. */
export const CHANGES_SHOWN = 7;

const loadChanges = (theme: string) => api.themeChanges(theme);

/** What changed on the theme: the window's important changes first, then the newest. A dot marks
 * what is newer than the last visit. */
export function ChangedList({ theme, mark }: { theme: string; mark: Date | null }) {
  const loaded = useApi(theme, loadChanges);
  const [all, setAll] = useState(false);
  return (
    <section aria-labelledby="changed">
      <h2 className="reader-label" id="changed">
        Changed
      </h2>
      <Load loaded={loaded} what="the changes">
        {(changes: ThemeChange[]) => {
          if (changes.length === 0) return <p className="muted">Nothing has changed yet.</p>;
          const now = new Date();
          const ordered = orderChanges(changes, mark, now);
          const shown = all ? ordered : ordered.slice(0, CHANGES_SHOWN);
          return (
            <>
              <ul className="reader-rows change-rows change-compact" aria-label="Changes, newest first">
                {shown.map((change, index) => {
                  const href = changeHref(change);
                  return (
                    <li className="reader-row change-row" key={`${change.at}-${index}`}>
                      <div>
                        <div className="row-title">
                          {isUnseen(change.at, mark) ? <span className="unseen-dot" aria-label="new" /> : null}
                          {href ? (
                            <Link href={href} title={changeLabel(change)}>
                              {changeLabel(change)}
                            </Link>
                          ) : (
                            changeLabel(change)
                          )}
                        </div>
                        <div className="reader-row-sub">{activity(change.at, now)}</div>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {!all && ordered.length > CHANGES_SHOWN ? (
                <button type="button" className="show-all show-all-flush" onClick={() => setAll(true)}>
                  All {ordered.length}
                </button>
              ) : null}
            </>
          );
        }}
      </Load>
    </section>
  );
}
