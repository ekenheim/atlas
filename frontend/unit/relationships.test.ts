import { expect, test } from "@playwright/test";

import {
  DEFAULT_STATE,
  LAYERS,
  LAYER_FILTERS,
  apiQuery,
  filterSummary,
  layerLabel,
  parseTableState,
  tableSearch,
  toggleSort,
} from "../lib/relationships";

test("the edge table's state round-trips through its query string", () => {
  const state = parseTableState(
    new URLSearchParams("layer=chip-laser&review_state=approved&sort=family_count&order=desc"),
  );
  expect(state).toEqual({
    layer: "chip-laser",
    reviewState: "approved",
    sort: "family_count",
    order: "desc",
  });
  expect(parseTableState(new URLSearchParams(tableSearch(state)))).toEqual(state);
  expect(apiQuery(state)).toEqual({
    layer: "chip-laser",
    review_state: "approved",
    sort: "family_count",
    order: "desc",
  });
});

test("defaults are left out of the query string, and unknown values are ignored", () => {
  expect(tableSearch(DEFAULT_STATE)).toBe("");
  expect(apiQuery(DEFAULT_STATE)).toEqual({ sort: "created_at", order: "asc" });
  expect(
    parseTableState(new URLSearchParams("layer=mantle&review_state=maybe&sort=id&order=up")),
  ).toEqual(DEFAULT_STATE);
});

test("the layer filter's \"none\" is the edges with no layer", () => {
  const state = parseTableState(new URLSearchParams("layer=none"));
  expect(state.layer).toBe("none");
  expect(tableSearch(state)).toBe("layer=none");
  expect(apiQuery(state)).toEqual({ layer: "none", sort: "created_at", order: "asc" });
  // The filter's options: no layer first (as the API sorts it), then the layers.
  expect(Object.keys(LAYER_FILTERS)).toEqual(["none", ...Object.keys(LAYERS)]);
  expect(LAYER_FILTERS.none).toBe("No layer");
  expect(filterSummary(state)).toBe(" with no layer");
  expect(filterSummary({ ...state, layer: "module", reviewState: "approved" })).toBe(
    " in layer Module, approved",
  );
  expect(filterSummary(DEFAULT_STATE)).toBe("");
});

test("an edge's layer is named, or said to be none", () => {
  expect(layerLabel("chip-laser")).toBe("Chip / laser");
  expect(layerLabel(null)).toBeNull();
});

test("a new column sorts ascending; the current one flips its order", () => {
  const bySubject = toggleSort(DEFAULT_STATE, "subject");
  expect(bySubject).toMatchObject({ sort: "subject", order: "asc" });
  expect(toggleSort(bySubject, "subject")).toMatchObject({ sort: "subject", order: "desc" });
  expect(toggleSort(toggleSort(bySubject, "subject"), "layer")).toMatchObject({
    sort: "layer",
    order: "asc",
  });
});
