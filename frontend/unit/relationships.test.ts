import { expect, test } from "@playwright/test";

import {
  COMPANY_LEVEL,
  DEFAULT_STATE,
  LAYERS,
  LAYER_FILTERS,
  apiQuery,
  edgeLabel,
  filterSummary,
  layerLabel,
  objectLabel,
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

test("an edge's object is its company, its product, or company-level when it has none", () => {
  expect(objectLabel({ object_name: "NVIDIA", object_text: null })).toBe("NVIDIA");
  expect(objectLabel({ object_name: null, object_text: "EML lasers" })).toBe("EML lasers");
  // A company's own constraint names no product: the edge has no object at all.
  expect(COMPANY_LEVEL).toBe("company-level");
  expect(objectLabel({ object_name: null, object_text: null })).toBe("(company-level)");
});

test("an edge is read in its direction, with or without an object", () => {
  const supplies = {
    subject_name: "Coherent",
    predicate: "supplies",
    object_name: "NVIDIA",
    object_text: null,
  };
  expect(edgeLabel(supplies)).toBe("Coherent supplies NVIDIA");
  const constrained = {
    subject_name: "Lumentum",
    predicate: "capacity_constrained",
    object_name: null,
    object_text: null,
  };
  expect(edgeLabel(constrained)).toBe("Lumentum capacity_constrained (company-level)");
  expect(edgeLabel({ ...constrained, object_text: "200G EML lasers" })).toBe(
    "Lumentum capacity_constrained 200G EML lasers",
  );
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
