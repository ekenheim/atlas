"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import {
  EdgeLink,
  EdgeObject,
  LayerName,
  ReviewState,
  edgeLabel,
} from "../../components/relationships";
import { Code, Load } from "../../components/ui";
import { api, type RelationshipState } from "../../lib/api/client";
import {
  COLUMNS,
  DEFAULT_STATE,
  LAYER_FILTERS,
  STATES,
  apiQuery,
  filterSummary,
  parseTableState,
  tableSearch,
  toggleSort,
  type LayerFilter,
  type SortKey,
  type TableState,
} from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

export default function RelationshipsPage() {
  return (
    <Suspense>
      <EdgeTable />
    </Suspense>
  );
}

// The load key is the table's query string, so `useApi` re-loads when it changes.
const loadEdges = (search: string) =>
  api.relationships(apiQuery(parseTableState(new URLSearchParams(search))));

function EdgeTable() {
  const router = useRouter();
  const state = parseTableState(useSearchParams());
  const search = tableSearch(state);
  const edges = useApi(search, loadEdges);
  const show = (next: TableState) => router.replace(routes.relationships(tableSearch(next)));
  const sorted = (key: SortKey) =>
    state.sort === key ? (state.order === "asc" ? "ascending" : "descending") : undefined;

  return (
    <>
      <p className="crumbs">
        <Link href={routes.companies}>Companies</Link>
      </p>
      <h1>Relationships</h1>
      <p>
        Every edge the graph holds: who does what to whom, in which supply-chain layer (when its
        Evidence names one), how it
        was reviewed and how much independent Evidence backs it. Open an edge to see each
        supporting Assertion and its source span. Edges waiting for the owner are in the{" "}
        <Link href={routes.exceptions}>exceptions queue</Link>.
      </p>
      <form
        className="filters"
        aria-label="Filter relationships"
        onSubmit={(event) => event.preventDefault()}
      >
        <div className="field">
          <label htmlFor="filter-layer">Layer</label>
          <select
            id="filter-layer"
            value={state.layer ?? ""}
            onChange={(event) =>
              show({ ...state, layer: (event.target.value || null) as LayerFilter | null })
            }
          >
            <option value="">All layers</option>
            {Object.entries(LAYER_FILTERS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-state">Review state</label>
          <select
            id="filter-state"
            value={state.reviewState ?? ""}
            onChange={(event) =>
              show({
                ...state,
                reviewState: (event.target.value || null) as RelationshipState | null,
              })
            }
          >
            <option value="">All review states</option>
            {Object.entries(STATES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {(state.layer || state.reviewState) && (
          <button
            type="button"
            onClick={() =>
              show({ ...state, layer: DEFAULT_STATE.layer, reviewState: DEFAULT_STATE.reviewState })
            }
          >
            Clear filters
          </button>
        )}
      </form>
      <Load loaded={edges} what="relationships">
        {(page) => (
          <>
            <p role="status" aria-live="polite">
              {page.total === 1 ? "1 relationship" : `${page.total} relationships`}
              {page.total > page.items.length && `, showing the first ${page.items.length}`}
              {filterSummary(state)}.
            </p>
            {page.items.length > 0 && (
              <table>
                <caption>
                  Relationships (activate a column header to sort by it; again to reverse)
                </caption>
                <thead>
                  <tr>
                    {COLUMNS.map((column) => (
                      <th key={column.key} scope="col" aria-sort={sorted(column.key)}>
                        <button
                          type="button"
                          className="sort"
                          onClick={() => show(toggleSort(state, column.key))}
                        >
                          {column.label}
                          <span aria-hidden="true">
                            {state.sort === column.key ? (state.order === "asc" ? " ▲" : " ▼") : ""}
                          </span>
                        </button>
                      </th>
                    ))}
                    <th scope="col">Edge</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((edge) => (
                    <tr key={edge.id} aria-label={edgeLabel(edge)}>
                      <td>{edge.subject_name}</td>
                      <td>
                        <Code>{edge.predicate}</Code>
                      </td>
                      <td>
                        <EdgeObject relationship={edge} />
                        {edge.products.length > 0 && (
                          <>
                            <br />
                            <span className="muted-small">
                              products: {edge.products.join(", ")}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        <LayerName layer={edge.layer} />
                      </td>
                      <td>
                        <ReviewState relationship={edge} />
                      </td>
                      <td>{edge.evidence_count}</td>
                      <td>{edge.family_count}</td>
                      <td>
                        <EdgeLink relationship={edge} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Load>
    </>
  );
}
