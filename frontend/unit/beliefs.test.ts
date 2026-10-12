import { expect, test } from "@playwright/test";

import type { Belief, BeliefSummary } from "../lib/api/client";
import {
  apiQuery,
  citationsByCompany,
  companyNames,
  confidenceText,
  direction,
  filterSummary,
  groupBySteps,
  judgedBy,
  judgementTone,
  listSearch,
  parseListState,
  valenceText,
} from "../lib/beliefs";

type Overrides = Omit<Partial<BeliefSummary>, "judgement"> & {
  judgement?: Partial<BeliefSummary["judgement"]>;
};

function belief(overrides: Overrides): BeliefSummary {
  const { judgement, ...rest } = overrides;
  return {
    id: "b",
    statement: "A statement.",
    theme: "photonics",
    step: "constraint",
    as_of: "2026-09-30T00:00:00Z",
    status: "active",
    companies: [],
    judgement: {
      id: "j",
      judgement: "unproven",
      confidence: 0,
      actor: "claude",
      reason: "proposed",
      at: "2026-10-01T00:00:00Z",
      ...judgement,
    },
    open_flags: 0,
    citation_count: 1,
    produced_by: null,
    created_by: "claude",
    created_at: "2026-10-01T00:00:00Z",
    ...rest,
  };
}

type Citation = Belief["citations"][number];
const citation = (overrides: Partial<Citation>): Citation => ({
  id: "c",
  kind: "fact",
  ref_id: "f",
  valence: 0.9,
  weight: "load_bearing",
  note: null,
  actor: "claude",
  created_at: "2026-10-01T00:00:00Z",
  company_id: "x",
  company_name: "Lumentum",
  statement: null,
  quote: "q",
  span_start: 0,
  span_end: 1,
  source_version_id: "v",
  source_title: null,
  available_at: "2026-08-11T00:00:00Z",
  review_state: "unreviewed",
  stands: true,
  ...overrides,
});

test("the filters round-trip through the query string and unknown values are ignored", () => {
  const state = parseListState(
    new URLSearchParams(
      "theme=photonics&step=relief&judgement=proven&flagged=true&company=c1",
    ),
  );

  expect(state).toEqual({
    theme: "photonics",
    step: "relief",
    judgement: "proven",
    status: null,
    flagged: true,
    companyId: "c1",
  });
  expect(listSearch(state)).toBe(
    "theme=photonics&step=relief&judgement=proven&flagged=true&company=c1",
  );
  expect(
    parseListState(
      new URLSearchParams("step=vibes&judgement=maybe&status=gone"),
    ).step,
  ).toBeNull();
  expect(listSearch(parseListState(new URLSearchParams("step=vibes")))).toBe(
    "",
  );
});

test("the API query shows active Beliefs unless a status is chosen", () => {
  expect(apiQuery(parseListState(new URLSearchParams("")))).toEqual({
    status: "active",
  });
  expect(
    apiQuery(
      parseListState(
        new URLSearchParams("status=superseded&flagged=true&theme=t"),
      ),
    ),
  ).toEqual({
    theme: "t",
    status: "superseded",
    flagged: true,
  });
  expect(
    filterSummary(
      parseListState(new URLSearchParams("step=relief&flagged=true")),
    ),
  ).toBe(" (relief, flagged)");
});

test("a theme's Beliefs are grouped by step in the argument's order, flagged and proven first", () => {
  const groups = groupBySteps([
    belief({
      id: "weak",
      step: "relief",
      judgement: { judgement: "unproven" },
    }),
    belief({
      id: "doubt",
      step: "relief",
      open_flags: 1,
      judgement: { judgement: "proven", confidence: 0.9 },
    }),
    belief({
      id: "strong",
      step: "relief",
      judgement: { judgement: "proven", confidence: 0.8 },
    }),
    belief({
      id: "fell",
      step: "relief",
      judgement: { judgement: "disproven", confidence: 1 },
    }),
    belief({ id: "first", step: "constraint" }),
  ]);

  expect(groups.map((group) => group.step)).toEqual([
    "constraint",
    "demand_vs_supply",
    "relief",
    "control",
    "capture",
    "invalidation",
  ]);
  expect(groups[0]?.beliefs.map((each) => each.id)).toEqual(["first"]);
  expect(groups[1]?.beliefs).toEqual([]);
  expect(groups[2]?.beliefs.map((each) => each.id)).toEqual([
    "doubt",
    "strong",
    "weak",
    "fell",
  ]);
});

test("words for a judgement, a confidence, companies and who judged", () => {
  expect(confidenceText(0.8)).toBe("80%");
  expect(judgementTone("proven")).toBe("reader-supported");
  expect(judgementTone("disproven")).toBe("reader-disputed");
  expect(judgementTone("undecidable")).toBe("reader-unknown");
  expect(companyNames({ companies: [] })).toBe("no one company");
  expect(
    companyNames({
      companies: [
        { id: "1", slug: "lumentum", display_name: "Lumentum" },
        { id: "2", slug: "coherent", display_name: "Coherent" },
      ],
    }),
  ).toBe("Lumentum, Coherent");
  expect(judgedBy({ actor: "owner", at: "2026-10-12T09:00:00Z" })).toBe(
    "owner, 2026-10-12",
  );
});

test("a citation reads for, against or neutral with its weight", () => {
  expect(direction(0.2)).toBe("for");
  expect(direction(-0.2)).toBe("against");
  expect(direction(0)).toBe("neutral");
  expect(valenceText({ valence: 0.9, weight: "load_bearing" })).toBe(
    "for, load-bearing",
  );
  expect(valenceText({ valence: -0.5, weight: "context" })).toBe(
    "against (-0.5), context",
  );
});

test("citations group by the company that spoke, oldest first", () => {
  const groups = citationsByCompany([
    citation({
      id: "late",
      company_name: "Lumentum",
      available_at: "2026-09-01T00:00:00Z",
    }),
    citation({
      id: "coh",
      company_name: "Coherent",
      available_at: "2026-08-20T00:00:00Z",
    }),
    citation({
      id: "early",
      company_name: "Lumentum",
      available_at: "2026-08-11T00:00:00Z",
    }),
  ]);

  expect(groups.map((group) => group.company)).toEqual([
    "Coherent",
    "Lumentum",
  ]);
  expect(groups[1]?.citations.map((each) => each.id)).toEqual([
    "early",
    "late",
  ]);
});
