// The Theme explorer's pure parts: where a theme map's edges are listed. An edge whose
// Evidence names a layer is listed by layer; one with no layer is listed under the theme
// companies it names, never under a layer.
import type { Hypothesis, Relationship, ThemeChange } from "./api/client";
import { routes } from "./routes";

// --- the theme page's Hypotheses and what changed (atlas-beliefs ticket 21) ----------------

/** A theme's Hypotheses, the published first (newest publication first), then the rest by when
 * they last changed. Closed and rejected ones come last of all. */
export function themeHypotheses(
  hypotheses: readonly Hypothesis[],
  theme: string,
): Hypothesis[] {
  const done = (each: Hypothesis) =>
    each.status === "closed" || each.status === "rejected";
  return hypotheses
    .filter((each) => each.theme_id === theme)
    .sort(
      (a, b) =>
        Number(done(a)) - Number(done(b)) ||
        (b.first_published_at ?? "").localeCompare(a.first_published_at ?? "") ||
        b.updated_at.localeCompare(a.updated_at),
    );
}

/** A Hypothesis's thesis as its latest version states it. */
export function hypothesisThesis(hypothesis: Hypothesis): string {
  const latest = hypothesis.versions.at(-1);
  return latest ? latest.content.thesis_statement : "A Hypothesis being drafted";
}

export const CHANGE_KINDS: Record<ThemeChange["kind"], string> = {
  judged: "Judged",
  flagged: "Flagged",
  notice: "Supported",
  fact: "New fact",
};

/** What a change row says. A judgement and a new Fact read as the feed gives them; a flag or a
 * notice carries the backend's detail (it names offsets and valences, and ends with the Belief's
 * statement in parentheses), so the row says only what happened to which Belief, the statement
 * taken from the page's own Beliefs: "Flagged: <statement>", "Confirmed: <statement>". */
export function changeLabel(
  change: ThemeChange,
  statementOf: (beliefId: string) => string | undefined = () => undefined,
): string {
  if (change.kind !== "flagged" && change.kind !== "notice") return change.text;
  const word = change.kind === "flagged" ? "Flagged" : "Confirmed";
  const statement = change.belief_id ? statementOf(change.belief_id) : undefined;
  return statement ? `${word}: ${statement}` : word;
}

/** Where a change opens: a Belief's page, or a new Fact at its span in the source. */
export function changeHref(change: ThemeChange): string | null {
  if (change.kind === "fact") {
    return change.fact_id && change.source_version_id
      ? routes.span(change.source_version_id, change.fact_id)
      : null;
  }
  return change.belief_id ? routes.belief(change.belief_id) : null;
}

// --- the Theme explorer's edges -------------------------------------------------------------

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
