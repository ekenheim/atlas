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

/** The edge table's layer filter: a layer, or `none` for the edges that have no layer. */
export type LayerFilter = NonNullable<RelationshipQuery["layer"]>;

/** The layer filter's options: no layer first (as the API sorts it), then the layers. */
export const LAYER_FILTERS: Record<LayerFilter, string> = { none: "No layer", ...LAYERS };

/** An edge's layer by name, or null when it has none (its Evidence names no layer). */
export function layerLabel(layer: Layer | null): string | null {
  return layer === null ? null : LAYERS[layer];
}

/**
 * What an edge with no object is called: a company's own `capacity_constrained` statement
 * that names no product (the API's `company_level`). It has no object company, no object
 * text and no layer.
 */
export const COMPANY_LEVEL = "company-level";

/** The object of an edge or of a Claim, as far as naming it needs. */
export type EdgeObjectNames = { object_name: string | null; object_text: string | null };

/** An object as text: the company, else the product, else "(company-level)" for none. */
export function objectLabel(edge: EdgeObjectNames): string {
  return edge.object_name ?? edge.object_text ?? `(${COMPANY_LEVEL})`;
}

/** "Subject predicate Object", the edge read in its direction. */
export function edgeLabel(
  edge: EdgeObjectNames & { subject_name: string; predicate: string },
): string {
  return `${edge.subject_name} ${edge.predicate} ${objectLabel(edge)}`;
}

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
  layer: LayerFilter | null;
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
    layer: oneOf(search.get("layer"), Object.keys(LAYER_FILTERS) as LayerFilter[]),
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

/** What the table's filters say, for its status line: " in layer Module, approved". */
export function filterSummary(state: TableState): string {
  const layer =
    state.layer === null
      ? ""
      : state.layer === "none"
        ? " with no layer"
        : ` in layer ${LAYERS[state.layer]}`;
  return layer + (state.reviewState ? `, ${STATES[state.reviewState].toLowerCase()}` : "");
}

/**
 * The state after activating `key`'s column header: a new column sorts ascending; the
 * current one flips its order.
 */
export function toggleSort(state: TableState, key: SortKey): TableState {
  if (state.sort !== key) return { ...state, sort: key, order: "asc" };
  return { ...state, order: state.order === "asc" ? "desc" : "asc" };
}
