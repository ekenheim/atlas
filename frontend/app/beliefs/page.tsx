"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { BeliefRow } from "../../components/beliefs";
import { Load } from "../../components/ui";
import { api } from "../../lib/api/client";
import {
  DEFAULT_STATE,
  JUDGEMENTS,
  STEPS,
  apiQuery,
  filterSummary,
  groupBySteps,
  listSearch,
  parseListState,
  type BeliefStatus,
  type JudgementName,
  type ListState,
  type Step,
} from "../../lib/beliefs";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

export default function BeliefsPage() {
  return (
    <Suspense>
      <Beliefs />
    </Suspense>
  );
}

// The load key is the filters' query string, so `useApi` re-loads when it changes.
const loadBeliefs = (search: string) =>
  api.beliefs(apiQuery(parseListState(new URLSearchParams(search))));
const loadThemes = () => api.themes();

function Beliefs() {
  const router = useRouter();
  const state = parseListState(useSearchParams());
  const search = listSearch(state);
  const beliefs = useApi(search, loadBeliefs);
  const themes = useApi("themes", loadThemes);
  // The checkbox follows the click at once; the URL catches up after the router replaces it.
  const [clicked, setClicked] = useState({ from: state.flagged, value: state.flagged });
  const flagged = clicked.from === state.flagged ? clicked.value : state.flagged;
  const show = (next: ListState) =>
    router.replace(routes.beliefs(listSearch(next)));

  return (
    <>
      <h1>Beliefs</h1>
      <p>
        What Atlas holds to be true, step by step, with the verdict on each and
        the evidence behind it.
      </p>
      <form
        className="filters"
        aria-label="Filter beliefs"
        onSubmit={(event) => event.preventDefault()}
      >
        <div className="field">
          <label htmlFor="filter-theme">Theme</label>
          <select
            id="filter-theme"
            value={state.theme ?? ""}
            onChange={(event) =>
              show({ ...state, theme: event.target.value || null })
            }
          >
            <option value="">All themes</option>
            {themes.state === "ready" &&
              themes.data.map((theme) => (
                <option key={theme.id} value={theme.id}>
                  {theme.title}
                </option>
              ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-step">Step</label>
          <select
            id="filter-step"
            value={state.step ?? ""}
            onChange={(event) =>
              show({
                ...state,
                step: (event.target.value || null) as Step | null,
              })
            }
          >
            <option value="">All steps</option>
            {Object.entries(STEPS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-judgement">Judgement</label>
          <select
            id="filter-judgement"
            value={state.judgement ?? ""}
            onChange={(event) =>
              show({
                ...state,
                judgement: (event.target.value || null) as JudgementName | null,
              })
            }
          >
            <option value="">All judgements</option>
            {Object.entries(JUDGEMENTS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-status">Status</label>
          <select
            id="filter-status"
            value={state.status ?? ""}
            onChange={(event) =>
              show({
                ...state,
                status: (event.target.value || null) as BeliefStatus | null,
              })
            }
          >
            <option value="">Active</option>
            <option value="superseded">Superseded</option>
            <option value="withdrawn">Withdrawn</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-flagged">
            <input
              id="filter-flagged"
              type="checkbox"
              checked={state.flagged}
              onChange={(event) =>
                show({ ...state, flagged: event.target.checked })
              }
            />{" "}
            Flagged only
          </label>
        </div>
        {search !== "" && (
          <button type="button" onClick={() => show(DEFAULT_STATE)}>
            Clear filters
          </button>
        )}
      </form>
      <Load loaded={beliefs} what="beliefs">
        {(page) => (
          <>
            <p role="status" aria-live="polite">
              {page.total === 1 ? "1 belief" : `${page.total} beliefs`}
              {filterSummary(state)}.
            </p>
            {groupBySteps(page.items).map((group) => (
              <section key={group.step} aria-label={group.title}>
                <h2>{group.title}</h2>
                {group.beliefs.length === 0 ? (
                  <p className="muted">Nothing believed yet.</p>
                ) : (
                  <ul
                    className="reader-rows"
                    aria-label={`${group.title} beliefs`}
                  >
                    {group.beliefs.map((belief) => (
                      <BeliefRow key={belief.id} belief={belief} />
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </>
        )}
      </Load>
    </>
  );
}
