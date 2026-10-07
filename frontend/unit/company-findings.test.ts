import { expect, test } from "@playwright/test";

import type { Relationship, RelationshipEvidence } from "../lib/api/client";
import { companyFindings, firstQuote } from "../lib/company-findings";

function edge(over: Partial<Relationship> & Pick<Relationship, "id" | "predicate">): Relationship {
  return {
    subject_company_id: "c-lite",
    subject_name: "Lumentum",
    object_company_id: null,
    object_name: null,
    object_text: null,
    company_level: false,
    layer: null,
    products: [],
    review_state: "machine_reviewed",
    review_reasons: [],
    evidence_count: 1,
    family_count: 1,
    reviewed_by: null,
    reviewed_at: null,
    review_note: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...over,
  } as Relationship;
}

test("a company-level constraint reads as being short of capacity", () => {
  const result = companyFindings(
    [edge({ id: "1", predicate: "capacity_constrained", company_level: true })],
    [],
  );
  expect(result.groups[0]?.title).toBe("Constraint and demand");
  expect(result.groups[0]?.findings[0]?.sentence).toBe("Lumentum is short of capacity");
});

test("a constraint with an object reads with it", () => {
  const result = companyFindings(
    [edge({ id: "1", predicate: "capacity_constrained", object_text: "pump lasers" })],
    [],
  );
  expect(result.groups[0]?.findings[0]?.sentence).toBe(
    "Lumentum is short of capacity for pump lasers",
  );
});

test("an inbound edge reads from its subject's side", () => {
  const result = companyFindings(
    [],
    [
      edge({
        id: "2",
        predicate: "supplies",
        subject_name: "AXT",
        object_name: "Lumentum",
        object_company_id: "c-lite",
      }),
    ],
  );
  expect(result.groups[0]?.title).toBe("Supply chain");
  expect(result.groups[0]?.findings[0]?.sentence).toBe("AXT supplies Lumentum");
});

test("rejected edges are hidden and the tally counts the rest", () => {
  const result = companyFindings(
    [
      edge({ id: "1", predicate: "manufactures", object_text: "lasers", review_state: "approved" }),
      edge({ id: "2", predicate: "manufactures", object_text: "modules", review_state: "rejected" }),
      edge({
        id: "3",
        predicate: "supplies",
        object_text: "chips",
        review_state: "needs_human_review",
      }),
      edge({ id: "4", predicate: "supplies", object_text: "wafers" }),
    ],
    [],
  );
  expect(result.tally).toEqual({ approved: 1, machine_reviewed: 1, needs_human_review: 1 });
  expect(result.groups.flatMap((g) => g.findings.map((f) => f.id))).not.toContain("2");
});

test("groups come in fixed order, empty ones are left out, unknown predicates go to Other", () => {
  const result = companyFindings(
    [
      edge({ id: "1", predicate: "depends_on", object_name: "Fabrinet" }),
      edge({ id: "2", predicate: "manufactures", object_text: "lasers" }),
      edge({ id: "3", predicate: "expands_capacity_for", object_text: "EML" }),
    ],
    [],
  );
  expect(result.groups.map((g) => g.title)).toEqual(["Capacity", "What it makes", "Other"]);
  expect(result.groups[2]?.findings[0]?.sentence).toBe("Lumentum depends on Fabrinet");
});

test("within a group reviewed findings come first, in the reader's words", () => {
  const result = companyFindings(
    [
      edge({ id: "1", predicate: "supplies", object_text: "a", review_state: "needs_human_review" }),
      edge({ id: "2", predicate: "supplies", object_text: "b", review_state: "approved" }),
      edge({ id: "3", predicate: "supplies", object_text: "c" }),
    ],
    [],
  );
  const findings = result.groups[0]?.findings ?? [];
  expect(findings.map((f) => f.id)).toEqual(["2", "3", "1"]);
  expect(findings.map((f) => f.review)).toEqual(["Approved", "Machine-checked only", "Not yet verified"]);
  expect(findings.map((f) => f.tone)).toEqual(["reader-supported", "reader-unknown", "reader-review"]);
});

test("an edge in both lists appears once", () => {
  const e = edge({ id: "1", predicate: "supplies", object_text: "x" });
  expect(companyFindings([e], [e]).groups[0]?.findings).toHaveLength(1);
});

test("nothing, or only rejected edges, is no groups and a zero tally", () => {
  const none = { groups: [], tally: { approved: 0, machine_reviewed: 0, needs_human_review: 0 } };
  expect(companyFindings([], [])).toEqual(none);
  expect(
    companyFindings([edge({ id: "1", predicate: "supplies", review_state: "rejected" })], []),
  ).toEqual(none);
});

test("an edge with no object never reads as a made-up object", () => {
  const sentences = companyFindings(
    [edge({ id: "1", predicate: "capacity_constrained" }), edge({ id: "2", predicate: "manufactures" })],
    [],
  ).groups.flatMap((g) => g.findings.map((f) => f.sentence));
  expect(sentences).toContain("Lumentum is short of capacity");
  expect(sentences).toContain("Lumentum makes");
});

test("an unknown predicate on an incoming edge reads from its subject's side", () => {
  const result = companyFindings(
    [],
    [edge({ id: "1", predicate: "licenses_to", subject_name: "AXT", object_name: "Lumentum" })],
  );
  expect(result.groups[0]?.title).toBe("Other");
  expect(result.groups[0]?.findings[0]?.sentence).toBe("AXT licenses to Lumentum");
});

test("a long subject name comes through whole", () => {
  const name = "A".repeat(40);
  const result = companyFindings(
    [edge({ id: "1", predicate: "supplies", subject_name: name, object_text: "x" })],
    [],
  );
  expect(result.groups[0]?.findings[0]?.sentence).toBe(`${name} supplies x`);
});

function evidence(id: string, review_state: string): RelationshipEvidence {
  return { assertion: { id, review_state } } as unknown as RelationshipEvidence;
}

test("the first quote skips rejected and superseded ones", () => {
  expect(firstQuote([evidence("a", "rejected"), evidence("b", "accepted")])?.assertion.id).toBe("b");
  expect(firstQuote([evidence("a", "superseded"), evidence("b", "disputed")])?.assertion.id).toBe("b");
  expect(firstQuote([evidence("a", "rejected")])).toBeNull();
  expect(firstQuote([])).toBeNull();
});
