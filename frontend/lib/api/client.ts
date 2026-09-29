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
export type EpistemicType = Assertion["epistemic_type"];
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
/** The route's success body: 200, or 201 for a create. */
type Posted<P extends PostPath> = PostOperation<P>["responses"] extends
  | { 200: { content: { "application/json": infer T } } }
  | { 201: { content: { "application/json": infer T } } }
  ? T
  : never;

/** A non-2xx answer, carrying the API's error envelope when it sent one. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
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
  try {
    const body = (await response.json()) as Partial<Schemas["ErrorEnvelope"]>;
    if (body.error) ({ code, message } = body.error);
  } catch {
    // Not the error envelope: keep the status line.
  }
  throw new ApiError(response.status, code, message);
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
  /** The Assertions citing one Source Version, oldest first. */
  versionAssertions: (id: string) =>
    get("/api/v1/assertions", { query: { source_version_id: id, ...PAGE } }),
  /** Record an Assertion; a quote not exactly at its offsets is refused (`quote_mismatch`). */
  createAssertion: (body: AssertionCreate) => post("/api/v1/assertions", {}, body),
  /** Review an Assertion; a transition not allowed is refused (`invalid_transition`). */
  reviewAssertion: (id: string, body: AssertionReview) =>
    post("/api/v1/assertions/{assertion_id}/review", { path: { assertion_id: id } }, body),
};
