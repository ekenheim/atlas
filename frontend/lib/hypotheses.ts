// The Hypothesis dossier's pure parts: which version the URL names, the words for its
// states, the publish gate's failures explained, the diff grouped by change, the scenario
// lines in the model's order, and a Research Snapshot's contents counted.
import type {
  DiffClaim,
  GateFailure,
  HypothesisVersion,
  PublishGate,
  ScenarioInput,
} from "./api/client";

/** The version `?version=` names if the Hypothesis has it; else the latest (null: none yet). */
export function chosenVersion(param: string | null, versions: HypothesisVersion[]): number | null {
  const numbers = versions.map((each) => each.version);
  if (numbers.length === 0) return null;
  const asked = param !== null && /^\d+$/.test(param) ? Number(param) : null;
  return asked !== null && numbers.includes(asked) ? asked : Math.max(...numbers);
}

/** "Version 2: correction, not published" (for the version selector and headings). */
export function versionLabel(version: HypothesisVersion): string {
  const origin = version.origin === "editor_draft" ? "the Editor's draft" : "correction";
  const state = version.published ? "published" : "not published";
  return `Version ${version.version}: ${origin}, ${state}`;
}

/** A snake_case name as words: "scenario_enterprise_value" → "Scenario enterprise value". */
export function words(name: string): string {
  const spaced = name.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const GATE_EXPLANATIONS: Record<string, string> = {
  no_falsifier:
    "The version names no falsifier. Write one in a correction: the evidence that would show " +
    "the thesis wrong.",
  no_unresolved_question:
    "The version lists no unresolved question. Write one in a correction: what the evidence " +
    "doesn't settle yet.",
  relationship_not_approved:
    "The owner hasn't approved every Relationship the findings depend on (machine review is " +
    "not enough, and a rejected edge never is). Open each edge below and decide it.",
  relationship_review_pending:
    "Some Assertions the findings cite haven't been machine-reviewed into Relationships yet, " +
    "so they may still form an edge the owner hasn't seen. Run the relationship review first.",
};

/** What a failed check of the publish gate means for the researcher, in words. */
export function explainFailure(failure: GateFailure): string {
  return GATE_EXPLANATIONS[failure.code] ?? failure.message;
}

const BLOCKS: Record<NonNullable<PublishGate["blocked"]>, string> = {
  no_version: "There is no version to publish yet: the Editor's draft hasn't been written.",
  already_published: "The latest version is published. A correction makes a new version.",
  status_not_publishable:
    "Only an evidence-ready Hypothesis can be published (or, for a correction, a reviewed or " +
    "paper-tracked one).",
};

/** Why the latest version can't be published whatever the checks say, or null. */
export function explainBlock(gate: PublishGate): string | null {
  return gate.blocked ? BLOCKS[gate.blocked] : null;
}

export type Change = DiffClaim["change"];

/** The diff's changes, in reading order, with what each means. */
export const CHANGES: readonly { change: Change; title: string; meaning: string }[] = [
  { change: "new", title: "New", meaning: "only in the later version" },
  {
    change: "contradicted",
    title: "Contradicted",
    meaning:
      "new counterevidence in the later version, or dropped with a cited Assertion since " +
      "disputed, rejected or superseded",
  },
  { change: "unchanged", title: "Unchanged", meaning: "in both, with no new counterevidence" },
  {
    change: "removed",
    title: "Removed",
    meaning: "dropped from the later version, uncontradicted",
  },
];

/** The diff's claims by change, in `CHANGES` order; changes with no claim are left out. */
export function groupClaims(claims: DiffClaim[]): { change: Change; claims: DiffClaim[] }[] {
  return CHANGES.map(({ change }) => ({
    change,
    claims: claims.filter((claim) => claim.change === change),
  })).filter((group) => group.claims.length > 0);
}

/** The scenario lines in the model's order (atlas.scenarios.model). */
export const LINES = [
  "component_price",
  "incremental_revenue",
  "incremental_contribution",
  "scenario_enterprise_value",
  "net_debt",
  "illustrative_equity_value",
  "equity_value_per_share",
  "revenue_exposure",
] as const;

export const CASES = ["low", "base", "high"] as const;

/** How an input's value came to be: its source, its estimate's basis, or why it's missing. */
export function inputProvenance(input: ScenarioInput): string {
  if (input.kind === "estimated") return `estimated: ${input.basis ?? "no basis given"}`;
  if (input.kind === "missing") return `missing${input.reason ? `: ${input.reason}` : ""}`;
  const source = input.source;
  if (source === null) return "sourced";
  if (source.type === "assertion") return "sourced from an Assertion";
  const observation = source.observation;
  return (
    `sourced from XBRL: ${observation.concept}, period ending ${observation.period_end}, ` +
    `${observation.form} ${observation.accession} (filed ${observation.filed})`
  );
}

export type SnapshotSummary = {
  cutoff: string | null;
  question: string | null;
  sourceVersions: number;
  assertions: number;
  relationships: number;
  scenarios: number;
  observations: number;
  runs: number;
  roleCalls: number;
  memoryUsed: boolean;
};

/** A Research Snapshot's contents, counted (atlas.snapshots `FORMAT`); absent parts count 0. */
export function summarizeSnapshot(content: Record<string, unknown>): SnapshotSummary {
  const record = (value: unknown): Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);
  const text = (value: unknown) => (typeof value === "string" ? value : null);
  const cutoff = record(content.cutoff);
  return {
    cutoff: text(cutoff.as_of),
    question: text(cutoff.question),
    sourceVersions: count(content.source_versions),
    assertions: count(content.assertions),
    relationships: count(content.relationships),
    scenarios: count(content.scenarios),
    observations: count(record(content.financial_dataset).observations),
    runs: count(content.runs),
    roleCalls: count(content.role_calls),
    memoryUsed: record(content.memory).used === true,
  };
}
