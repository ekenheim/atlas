import { expect, test } from "@playwright/test";

import {
  DEFAULT_STATE,
  apiQuery,
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

test("a new column sorts ascending; the current one flips its order", () => {
  const bySubject = toggleSort(DEFAULT_STATE, "subject");
  expect(bySubject).toMatchObject({ sort: "subject", order: "asc" });
  expect(toggleSort(bySubject, "subject")).toMatchObject({ sort: "subject", order: "desc" });
  expect(toggleSort(toggleSort(bySubject, "subject"), "layer")).toMatchObject({
    sort: "layer",
    order: "asc",
  });
});
