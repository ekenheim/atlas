// The Theme explorer's pure parts: where a theme map's edges are listed. An edge whose
// Evidence names a layer is listed by layer; one with no layer is listed under the theme
// companies it names, never under a layer.
import type { Relationship } from "./api/client";

/** A theme company, as far as listing edges under it needs. */
export type EdgeCompany = { id: string; display_name: string };

/** A theme company and the layerless edges that name it (as subject or object). */
export type CompanyEdges<C extends EdgeCompany = EdgeCompany> = {
  company: C;
  edges: Relationship[];
};

/** The edges that have a layer, in the order given (the API sorts them by layer). */
export function layeredEdges(edges: readonly Relationship[]): Relationship[] {
  return edges.filter((edge) => edge.layer !== null);
}

/**
 * The edges with no layer, under each of `companies` they name, in the companies' order. An
 * edge between two theme companies is listed under both; a company with none is left out.
 */
export function layerlessByCompany<C extends EdgeCompany>(
  edges: readonly Relationship[],
  companies: readonly C[],
): CompanyEdges<C>[] {
  const layerless = edges.filter((edge) => edge.layer === null);
  return companies
    .map((company) => ({
      company,
      edges: layerless.filter(
        (edge) => edge.subject_company_id === company.id || edge.object_company_id === company.id,
      ),
    }))
    .filter((group) => group.edges.length > 0);
}
