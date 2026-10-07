// What Atlas found about a company, for the reader: its Relationships as plain sentences,
// grouped, with the review state in the reader's words. Pure; rejected edges are left out.
import type { Relationship, RelationshipEvidence, RelationshipState } from "./api/client";

/** How each predicate reads between its subject and object. */
const VERB: Record<string, string> = {
  capacity_constrained: "is short of capacity for",
  expands_capacity_for: "is adding capacity for",
  manufactures: "makes",
  sole_sources: "relies on a single supplier for",
  supplies: "supplies",
  vertically_integrates: "makes in-house",
};

const GROUPS: { key: string; title: string; predicates: string[] }[] = [
  { key: "constraint", title: "Constraint and demand", predicates: ["capacity_constrained"] },
  { key: "capacity", title: "Capacity", predicates: ["expands_capacity_for"] },
  { key: "supply", title: "Supply chain", predicates: ["supplies", "sole_sources"] },
  { key: "makes", title: "What it makes", predicates: ["manufactures", "vertically_integrates"] },
];

type Shown = Exclude<RelationshipState, "rejected">;

/** The review states a reader sees, best first (also the order within a group). */
const REVIEW: Record<Shown, string> = {
  approved: "Approved",
  // Machine review is right about 57% of the time (the pilot verdict, 2026-10-07): it is no
  // verification, and a reader isn't told which queue an edge waits in (the spec's "review
  // state for a reader").
  machine_reviewed: "Machine-checked only",
  needs_human_review: "Not yet verified",
};
const REVIEW_ORDER = Object.keys(REVIEW) as Shown[];

/** A review state's pill colour: only an edge awaiting a person is amber. */
const TONE: Record<Shown, "reader-supported" | "reader-unknown" | "reader-review"> = {
  approved: "reader-supported",
  machine_reviewed: "reader-unknown",
  needs_human_review: "reader-review",
};

export type Finding = {
  id: string;
  sentence: string;
  state: Shown;
  review: string;
  tone: (typeof TONE)[Shown];
  evidenceCount: number;
};

export type FindingGroup = { key: string; title: string; findings: Finding[] };

export type Tally = Record<Shown, number>;

/** One edge as a sentence from its subject's side: "AXT supplies Lumentum". */
export function sentence(edge: Relationship): string {
  const object = edge.object_name ?? edge.object_text;
  if (edge.predicate === "capacity_constrained" && (edge.company_level || !object)) {
    return `${edge.subject_name} is short of capacity`;
  }
  const verb = VERB[edge.predicate] ?? edge.predicate.replace(/_/g, " ");
  return object ? `${edge.subject_name} ${verb} ${object}` : `${edge.subject_name} ${verb}`;
}

/** The company's edges (out, then in) as grouped sentences, and the tally of their review states. */
export function companyFindings(
  out: readonly Relationship[],
  incoming: readonly Relationship[],
): { groups: FindingGroup[]; tally: Tally } {
  const seen = new Set<string>();
  const shown: { edge: Relationship; finding: Finding }[] = [];
  for (const edge of [...out, ...incoming]) {
    if (edge.review_state === "rejected" || seen.has(edge.id)) continue;
    seen.add(edge.id);
    shown.push({
      edge,
      finding: {
        id: edge.id,
        sentence: sentence(edge),
        state: edge.review_state,
        review: REVIEW[edge.review_state],
        tone: TONE[edge.review_state],
        evidenceCount: edge.evidence_count,
      },
    });
  }
  const tally: Tally = { approved: 0, machine_reviewed: 0, needs_human_review: 0 };
  for (const { finding } of shown) tally[finding.state] += 1;
  const known = new Set(GROUPS.flatMap((g) => g.predicates));
  const defs = [
    ...GROUPS,
    { key: "other", title: "Other", predicates: [] as string[] },
  ];
  const groups = defs
    .map((def) => ({
      key: def.key,
      title: def.title,
      findings: shown
        .filter(({ edge }) =>
          def.key === "other" ? !known.has(edge.predicate) : def.predicates.includes(edge.predicate),
        )
        .map(({ finding }) => finding)
        .sort(
          (a, b) =>
            REVIEW_ORDER.indexOf(a.state) - REVIEW_ORDER.indexOf(b.state) ||
            a.sentence.localeCompare(b.sentence),
        ),
    }))
    .filter((g) => g.findings.length > 0);
  return { groups, tally };
}

/** The first quote worth showing: not one the owner or a later Assertion has set aside. */
export function firstQuote(
  evidence: readonly RelationshipEvidence[],
): RelationshipEvidence | null {
  return (
    evidence.find(
      (item) =>
        item.assertion.review_state !== "rejected" && item.assertion.review_state !== "superseded",
    ) ?? null
  );
}
