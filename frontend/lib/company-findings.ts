// What Atlas found about a company, for the reader: its Relationships as plain sentences,
// grouped, with the review state in the reader's words. Pure; rejected edges are left out.
import type { Relationship, RelationshipState } from "./api/client";
import { objectLabel } from "./relationships";

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
  machine_reviewed: "Machine-reviewed",
  needs_human_review: "Awaiting review",
};
const REVIEW_ORDER = Object.keys(REVIEW) as Shown[];

export type Finding = {
  id: string;
  sentence: string;
  state: Shown;
  review: string;
  evidenceCount: number;
};

export type FindingGroup = { key: string; title: string; findings: Finding[] };

export type Tally = Record<Shown, number>;

/** One edge as a sentence from its subject's side: "AXT supplies Lumentum". */
export function sentence(edge: Relationship): string {
  if (edge.predicate === "capacity_constrained" && edge.company_level) {
    return `${edge.subject_name} is short of capacity`;
  }
  const verb = VERB[edge.predicate] ?? edge.predicate.replace(/_/g, " ");
  return `${edge.subject_name} ${verb} ${objectLabel(edge)}`;
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
