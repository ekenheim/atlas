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

function url<P extends GetPath>(route: P, params: Params<P>): string {
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

async function send(target: string): Promise<Response> {
  const response = await fetch(target, { headers: { Accept: "application/json, text/plain" } });
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
};
