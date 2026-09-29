// The edge table's vocabulary and its URL state: filters and sort live in the page's
// query string, so a filtered, sorted table can be reloaded, bookmarked and linked.
import type { Layer, RelationshipQuery, RelationshipState } from "./api/client";

/** The photonics layers, upstream to downstream, as the API sorts them. */
export const LAYERS: Record<Layer, string> = {
  substrate: "Substrate",
  epi: "Epi",
  "chip-laser": "Chip / laser",
  dsp: "DSP",
  module: "Module",
  "contract-manufacturing": "Contract manufacturing",
  system: "System",
};

/** A Relationship's review states (spec "Review"). */
export const STATES: Record<RelationshipState, string> = {
  machine_reviewed: "Machine-reviewed",
  needs_human_review: "Needs human review",
  approved: "Approved",
  rejected: "Rejected",
};

export type SortKey = NonNullable<RelationshipQuery["sort"]>;
export type SortOrder = NonNullable<RelationshipQuery["order"]>;

/** The table's sortable columns, in column order, with their headers. */
export const COLUMNS: readonly { key: SortKey; label: string }[] = [
  { key: "subject", label: "Subject" },
  { key: "predicate", label: "Predicate" },
  { key: "object", label: "Object" },
  { key: "layer", label: "Layer" },
  { key: "review_state", label: "Review state" },
  { key: "evidence_count", label: "Evidence" },
  { key: "family_count", label: "Families" },
];

const SORT_KEYS: readonly SortKey[] = [
  ...COLUMNS.map((column) => column.key),
  "created_at",
  "updated_at",
];

/** What the edge table shows: its filters and its sort. */
export type TableState = {
  layer: Layer | null;
  reviewState: RelationshipState | null;
  sort: SortKey;
  order: SortOrder;
};

export const DEFAULT_STATE: TableState = {
  layer: null,
  reviewState: null,
  sort: "created_at",
  order: "asc",
};

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

/** The table state a query string names; unknown or missing values take the defaults. */
export function parseTableState(search: URLSearchParams): TableState {
  return {
    layer: oneOf(search.get("layer"), Object.keys(LAYERS) as Layer[]),
    reviewState: oneOf(search.get("review_state"), Object.keys(STATES) as RelationshipState[]),
    sort: oneOf(search.get("sort"), SORT_KEYS) ?? DEFAULT_STATE.sort,
    order: oneOf(search.get("order"), ["asc", "desc"] as const) ?? DEFAULT_STATE.order,
  };
}

/** The query string for `state`, leaving out what is the default. */
export function tableSearch(state: TableState): string {
  const search = new URLSearchParams();
  if (state.layer) search.set("layer", state.layer);
  if (state.reviewState) search.set("review_state", state.reviewState);
  if (state.sort !== DEFAULT_STATE.sort) search.set("sort", state.sort);
  if (state.order !== DEFAULT_STATE.order) search.set("order", state.order);
  return search.toString();
}

/** The API query for `state`. */
export function apiQuery(state: TableState): RelationshipQuery {
  return {
    ...(state.layer ? { layer: state.layer } : {}),
    ...(state.reviewState ? { review_state: state.reviewState } : {}),
    sort: state.sort,
    order: state.order,
  };
}

/**
 * The state after activating `key`'s column header: a new column sorts ascending; the
 * current one flips its order.
 */
export function toggleSort(state: TableState, key: SortKey): TableState {
  if (state.sort !== key) return { ...state, sort: key, order: "asc" };
  return { ...state, order: state.order === "asc" ? "desc" : "asc" };
}
