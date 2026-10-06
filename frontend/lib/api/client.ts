// A thin, typed fetch wrapper over the generated OpenAPI types (./schema.ts).
// Regenerate the types with `scripts/gen_api_client.sh`; never edit schema.ts by hand.
// The API is on the same origin as this static export, so every URL is relative.
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type Company = Schemas["Company"];
export type SourceDocument = Schemas["SourceDocument"];
export type SourceVersionSummary = Schemas["SourceVersionSummary"];
export type SourceVersionDetail = Schemas["SourceVersionDetail"];
export type FetchObservation = Schemas["FetchObservation"];
export type Assertion = Schemas["Assertion"];
export type AssertionCreate = Schemas["AssertionCreate"];
export type AssertionReview = Schemas["AssertionReview"];
export type AssertionRecorded = Schemas["AssertionRecorded"];
export type ReviewState = Assertion["review_state"];
export type Layer = Schemas["Layer"];
export type Relationship = Schemas["Relationship"];
export type RelationshipDetail = Schemas["RelationshipDetail"];
export type RelationshipEvidence = Schemas["RelationshipEvidence"];
export type RelationshipState = Relationship["review_state"];
export type OwnerReview = Schemas["OwnerReview"];
export type RelationshipRecorded = Schemas["RelationshipRecorded"];
/** The edge table's filters and sort (the page is added here). */
export type RelationshipQuery = Omit<
  NonNullable<Params<"/api/v1/relationships">["query"]>,
  "limit" | "offset"
>;
export type ThemeSummary = Schemas["ThemeSummary"];
export type ThemeMap = Schemas["ThemeMapView"];
export type ThemeCompany = Schemas["ThemeCompany"];
export type Bottlenecks = Schemas["Bottlenecks"];
export type Candidate = Schemas["Candidate"];
export type CompanyDossier = Schemas["CompanyDossier"];
export type MemoryHealth = Schemas["MemoryHealth"];
export type CompanySections = Schemas["CompanySections"];
export type SectionCounts = Schemas["SectionCounts"];
export type VersionCounts = Schemas["VersionCounts"];
export type ConsolidationRun = Schemas["ConsolidationRun"];
export type SourceVersionMemory = Schemas["SourceVersionMemory"];
export type FinancialFigure = Schemas["FinancialFigure"];
export type EpistemicType = Assertion["epistemic_type"];
export type Investigation = Schemas["Investigation"];
export type InvestigationSummary = Schemas["InvestigationSummary"];
export type InvestigationEvent = Schemas["InvestigationEvent"];
export type InvestigationCreate = Schemas["InvestigationCreate"];
export type InvestigationTask = Schemas["Task"];
export type ReadingPointer = Schemas["ReadingPointer"];
export type PointedCompany = Schemas["PointedCompany"];
export type EntityHop = Schemas["EntityHop"];
export type EvidenceItem = Schemas["EvidenceItem"];
export type ResearchCard = Schemas["ResearchCard"];
export type CardSearch = Schemas["CardSearch"];
export type CardReading = Schemas["CardReading"];
export type CardSkepticCompany = Schemas["CardSkepticCompany"];
export type Counterevidence = Schemas["Counterevidence"];
export type Hypothesis = Schemas["Hypothesis"];
export type HypothesisVersion = Schemas["HypothesisVersion"];
export type HypothesisStatus = Hypothesis["status"];
export type HypothesisTransition = Schemas["HypothesisTransition"];
export type HypothesisExport = Schemas["HypothesisExport"];
export type ExportFinding = Schemas["ExportFinding"];
export type Citation = HypothesisExport["citations"][number];
export type CardContradiction = Schemas["CardContradiction"];
export type HypothesisDiff = Schemas["HypothesisDiff"];
export type DiffClaim = Schemas["DiffClaim"];
export type PublishGate = Schemas["PublishGateView"];
export type GateFailure = Schemas["GateFailureView"];
export type Scenario = Schemas["Scenario"];
export type ScenarioInput = Schemas["ScenarioInputView"];
export type ScenarioOutputs = Schemas["ScenarioOutputs"];
export type SnapshotRecord = Schemas["ResearchSnapshotRecord"];
export type ResearchSnapshot = Schemas["ResearchSnapshot"];
export type ExportFormat = NonNullable<
  NonNullable<Params<"/api/v1/hypotheses/{hypothesis_id}/export">["query"]>["format"]
>;
export type ContentKind =
  Params<"/api/v1/source-versions/{version_id}/content">["query"]["kind"];

type GetPath = {
  [P in keyof paths]: paths[P]["get"] extends never | undefined ? never : P;
}[keyof paths];
type GetOperation<P extends GetPath> = NonNullable<paths[P]["get"]>;
/** `{ path, query }` exactly as the schema declares them for this route. */
type Params<P extends GetPath> = Pick<GetOperation<P>["parameters"], "path" | "query">;
type Ok<P extends GetPath> = GetOperation<P>["responses"] extends {
  200: { content: { "application/json": infer T } };
}
  ? T
  : never;

type PostPath = {
  [P in keyof paths]: paths[P]["post"] extends never | undefined ? never : P;
}[keyof paths];
type PostOperation<P extends PostPath> = NonNullable<paths[P]["post"]>;
type Body<P extends PostPath> = PostOperation<P> extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : never;
/** The route's success body: 200, 201 for a create, or 202 for work accepted. */
type Posted<P extends PostPath> = PostOperation<P>["responses"] extends
  | { 200: { content: { "application/json": infer T } } }
  | { 201: { content: { "application/json": infer T } } }
  | { 202: { content: { "application/json": infer T } } }
  ? T
  : never;

/** A non-2xx answer, carrying the API's error envelope when it sent one (and the publish
 * gate's failed checks when it refused a publication). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly failures: GateFailure[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Lists in this viewer are small (one company's filings); take the API's largest page.
const PAGE = { limit: 500, offset: 0 };

function url(route: string, params: { path?: object; query?: object }): string {
  const { path = {}, query = {} } = params as {
    path?: Record<string, string>;
    query?: Record<string, string | number>;
  };
  const filled = route.replace(/\{(\w+)\}/g, (_, name: string) =>
    encodeURIComponent(path[name] ?? ""),
  );
  const search = new URLSearchParams(
    Object.entries(query).map(([key, value]) => [key, String(value)]),
  ).toString();
  return search ? `${filled}?${search}` : filled;
}

type Init = { method?: "POST"; headers?: Record<string, string>; body?: string };

async function send(target: string, init: Init = {}): Promise<Response> {
  const response = await fetch(target, {
    ...init,
    headers: { Accept: "application/json, text/plain", ...init.headers },
  });
  if (response.ok) return response;
  let code = "http_error";
  let message = `${response.status} ${response.statusText}`.trim();
  let failures: GateFailure[] = [];
  try {
    const body = (await response.json()) as Partial<Schemas["PublishRefusalEnvelope"]>;
    if (body.error) ({ code, message, failures = [] } = body.error);
  } catch {
    // Not the error envelope: keep the status line.
  }
  throw new ApiError(response.status, code, message, failures);
}

async function get<P extends GetPath>(route: P, params: Params<P>): Promise<Ok<P>> {
  const response = await send(url(route, params));
  return (await response.json()) as Ok<P>;
}

async function post<P extends PostPath>(
  route: P,
  params: { path?: Record<string, string> },
  body: Body<P>,
): Promise<Posted<P>> {
  const response = await send(url(route, params), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await response.json()) as Posted<P>;
}

export const api = {
  companies: () => get("/api/v1/companies", { query: PAGE }),
  company: (id: string) => get("/api/v1/companies/{company_id}", { path: { company_id: id } }),
  /** A company's dossier: identity, reviews, themes, sources, edges, financials as of now. */
  dossier: (id: string) =>
    get("/api/v1/companies/{company_id}/dossier", { path: { company_id: id }, query: {} }),
  /** What the research bank holds and lacks; with a company, its own counts (the bank-wide blocks stay whole). */
  memoryHealth: (companyId?: string) =>
    get("/api/v1/memory/health", { query: companyId ? { company_id: companyId } : {} }),
  /** Every theme with its coverage. */
  themes: () => get("/api/v1/themes", {}),
  /** One theme's map: companies by layer, Relationships between them, Candidates, gaps. */
  themeMap: (id: string) =>
    get("/api/v1/themes/{theme_id}/map", { path: { theme_id: id } }),
  companySources: (id: string) =>
    get("/api/v1/companies/{company_id}/sources", { path: { company_id: id }, query: PAGE }),
  source: (id: string) => get("/api/v1/sources/{document_id}", { path: { document_id: id } }),
  sourceVersions: (id: string) =>
    get("/api/v1/sources/{document_id}/versions", { path: { document_id: id }, query: PAGE }),
  sourceVersion: (id: string) =>
    get("/api/v1/source-versions/{version_id}", { path: { version_id: id } }),
  /** The content URL: `raw` downloads the original bytes, `parsed` is the UTF-8 text. */
  contentUrl: (id: string, kind: ContentKind) =>
    url("/api/v1/source-versions/{version_id}/content", {
      path: { version_id: id },
      query: { kind },
    }),
  parsedText: async (id: string) => (await send(api.contentUrl(id, "parsed"))).text(),
  /** One parse's text, keyed `"<version id> <parser version>"` (a re-parse, for `useApi`). */
  parseText: async (key: string) => {
    const [id = "", parserVersion = ""] = key.split(" ");
    const parsed = url("/api/v1/source-versions/{version_id}/content", {
      path: { version_id: id },
      query: { kind: "parsed", parser_version: parserVersion },
    });
    return (await send(parsed)).text();
  },
  /** What a Source Version holds in Memory: sections by retain state, facts, profile. */
  sourceVersionMemory: (id: string) =>
    get("/api/v1/source-versions/{version_id}/memory", { path: { version_id: id } }),
  /** The Assertions citing one Source Version, oldest first. */
  versionAssertions: (id: string) =>
    get("/api/v1/assertions", { query: { source_version_id: id, ...PAGE } }),
  /** Record an Assertion; a quote not exactly at its offsets is refused (`quote_mismatch`). */
  createAssertion: (body: AssertionCreate) => post("/api/v1/assertions", {}, body),
  assertion: (id: string) =>
    get("/api/v1/assertions/{assertion_id}", { path: { assertion_id: id } }),
  /** The edge table, filtered and sorted as `query` says (its first 500 edges). */
  relationships: (query: RelationshipQuery) =>
    get("/api/v1/relationships", { query: { ...query, ...PAGE } }),
  /** The exceptions queue: edges needing human review, oldest first. */
  relationshipExceptions: () => get("/api/v1/relationships/exceptions", { query: PAGE }),
  /** One edge with its Evidence (each supporting Assertion and its machine review). */
  relationship: (id: string) =>
    get("/api/v1/relationships/{relationship_id}", { path: { relationship_id: id } }),
  /** The owner approves or rejects an edge; repeating its decision is `invalid_transition`. */
  reviewRelationship: (id: string, body: OwnerReview) =>
    post(
      "/api/v1/relationships/{relationship_id}/review",
      { path: { relationship_id: id } },
      body,
    ),
  /** Investigations, newest first (the workbench's first 500). */
  investigations: () => get("/api/v1/investigations", { query: PAGE }),
  /** Start an investigation: its fixed plan is queued at once. */
  startInvestigation: (body: InvestigationCreate) => post("/api/v1/investigations", {}, body),
  investigation: (id: string) =>
    get("/api/v1/investigations/{investigation_id}", { path: { investigation_id: id } }),
  /** What happened, in order (the first 500 events). */
  investigationEvents: (id: string) =>
    get("/api/v1/investigations/{investigation_id}/events", {
      path: { investigation_id: id },
      query: PAGE,
    }),
  /** Continue a budget-exhausted investigation with a larger token budget. */
  resumeInvestigation: (id: string, tokenBudget: number) =>
    post(
      "/api/v1/investigations/{investigation_id}/resume",
      { path: { investigation_id: id } },
      { token_budget: tokenBudget },
    ),
  /** Mark a premise disproven: only the unstarted tasks that depend on it are cancelled. */
  disprovePremise: (id: string, premiseKey: string, reason: string) =>
    post(
      "/api/v1/investigations/{investigation_id}/premises/{premise_key}/disprove",
      { path: { investigation_id: id, premise_key: premiseKey } },
      { reason },
    ),
  /** The one bounded follow-up round, on one of the research card's open questions. */
  followUp: (id: string, question: string) =>
    post(
      "/api/v1/investigations/{investigation_id}/follow-up",
      { path: { investigation_id: id } },
      { question },
    ),
  /** Save a stopped investigation's research card as a draft Hypothesis. */
  saveHypothesis: (investigationId: string) =>
    post("/api/v1/hypotheses", {}, { investigation_id: investigationId }),
  /** Every Hypothesis, newest first, each with its versions and transitions. */
  hypotheses: () => get("/api/v1/hypotheses", { query: PAGE }),
  hypothesis: (id: string) =>
    get("/api/v1/hypotheses/{hypothesis_id}", { path: { hypothesis_id: id } }),
  /** A version's dossier: its findings with numbered citations, and the run metadata. */
  hypothesisExport: (id: string, version: number) =>
    get("/api/v1/hypotheses/{hypothesis_id}/export", {
      path: { hypothesis_id: id },
      query: { format: "json", version },
    }),
  /** The export's download URL, as JSON or Markdown. */
  exportUrl: (id: string, format: ExportFormat, version: number) =>
    url("/api/v1/hypotheses/{hypothesis_id}/export", {
      path: { hypothesis_id: id },
      query: { format, version },
    }),
  /** The claims new, contradicted, unchanged or removed between two versions. */
  hypothesisDiff: (id: string, fromVersion: number, toVersion: number) =>
    get("/api/v1/hypotheses/{hypothesis_id}/diff", {
      path: { hypothesis_id: id },
      query: { from_version: fromVersion, to_version: toVersion },
    }),
  /** The scenarios attached to one version, oldest first. */
  scenarios: (id: string, version: number) =>
    get("/api/v1/hypotheses/{hypothesis_id}/scenarios", {
      path: { hypothesis_id: id },
      query: { version },
    }),
  /** What publishing the latest version would meet now (nothing is published). */
  publishGate: (id: string) =>
    get("/api/v1/hypotheses/{hypothesis_id}/publish-gate", { path: { hypothesis_id: id } }),
  /** Publish the latest version; a refusal is an `ApiError` listing the gate's `failures`. */
  publishVersion: (id: string, version: number) =>
    post(
      "/api/v1/hypotheses/{hypothesis_id}/publish-version",
      { path: { hypothesis_id: id } },
      { version },
    ),
  /** A lifecycle change (`reviewed` only by publishing). */
  transitionHypothesis: (id: string, to: HypothesisStatus) =>
    post("/api/v1/hypotheses/{hypothesis_id}/transitions", { path: { hypothesis_id: id } }, { to }),
  /** A Hypothesis's Research Snapshots, oldest first. */
  snapshots: (hypothesisId: string) =>
    get("/api/v1/snapshots", { query: { hypothesis_id: hypothesisId, ...PAGE } }),
  /** One snapshot, verified on read; an altered or missing one is `snapshot_integrity_failed`. */
  snapshot: (id: string) => get("/api/v1/snapshots/{snapshot_id}", { path: { snapshot_id: id } }),
  /** Review an Assertion; a transition not allowed is refused (`invalid_transition`). */
  reviewAssertion: (id: string, body: AssertionReview) =>
    post("/api/v1/assertions/{assertion_id}/review", { path: { assertion_id: id } }, body),
};
