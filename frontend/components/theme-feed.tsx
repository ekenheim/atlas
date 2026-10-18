"use client";

// The theme page's lead (atlas-beliefs ticket 21): the theme's Hypotheses, then, after its
// Beliefs, what changed. Both in few words; each row opens the record it is about.
import Link from "next/link";

import { api } from "../lib/api/client";
import { evidenceDay } from "../lib/format";
import { words } from "../lib/hypotheses";
import { routes } from "../lib/routes";
import { CHANGE_KINDS, changeHref, hypothesisThesis, themeHypotheses } from "../lib/themes";
import { useApi } from "../lib/use-api";
import { Load } from "./ui";

const loadHypotheses = async () => (await api.hypotheses()).items;

/** The theme's Hypotheses, the published first: the thesis, its status and when it last changed. */
export function ThemeHypotheses({ theme }: { theme: string }) {
  const loaded = useApi("hypotheses", loadHypotheses);
  return (
    <section aria-labelledby="hypotheses">
      <h2 className="reader-label" id="hypotheses">
        Hypotheses
      </h2>
      <Load loaded={loaded} what="the Hypotheses">
        {(all) => {
          const mine = themeHypotheses(all, theme);
          return mine.length === 0 ? (
            <p className="muted">No Hypothesis on this theme yet.</p>
          ) : (
            <ul className="reader-rows" aria-label="Hypotheses">
              {mine.map((hypothesis) => {
                const published = hypothesis.versions.filter((each) => each.published);
                const thesis = hypothesisThesis(hypothesis);
                return (
                  <li className="reader-row" key={hypothesis.id} aria-label={thesis}>
                    <div>
                      <div className="reader-row-title">
                        <Link href={routes.hypothesis(hypothesis.id)}>{thesis}</Link>
                      </div>
                      <div className="reader-row-sub">
                        {published.length === 0
                          ? "not published"
                          : `published ${evidenceDay(hypothesis.first_published_at ?? "")}`}
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
                    <span className="reader-pill reader-unknown">{words(hypothesis.status)}</span>
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

const loadChanges = (theme: string) => api.themeChanges(theme);

/** What changed on the theme, newest first. */
export function ThemeChanges({ theme }: { theme: string }) {
  const loaded = useApi(theme, loadChanges);
  return (
    <section aria-labelledby="changed">
      <h2 className="reader-label" id="changed">
        What changed
      </h2>
      <Load loaded={loaded} what="the changes">
        {(changes) =>
          changes.length === 0 ? (
            <p className="muted">Nothing has changed yet.</p>
          ) : (
            <ul className="reader-rows" aria-label="Changes, newest first">
              {changes.map((change, index) => {
                const href = changeHref(change);
                return (
                  <li className="reader-row" key={`${change.at}-${index}`}>
                    <div>
                      <div className="reader-row-title">
                        {href ? <Link href={href}>{change.text}</Link> : change.text}
                      </div>
                      <div className="reader-row-sub">{evidenceDay(change.at)}</div>
                    </div>
                    <span className="reader-pill reader-unknown">{CHANGE_KINDS[change.kind]}</span>
                  </li>
                );
              })}
            </ul>
          )
        }
      </Load>
    </section>
  );
}
