// Pages take their id as a query parameter, so the static export needs no dynamic routes.
const withId = (page: string) => (id: string) => `/${page}/?id=${encodeURIComponent(id)}`;

export const routes = {
  companies: "/",
  company: withId("company"),
  source: withId("source"),
  version: withId("version"),
  /** A Source Version with one Assertion's span highlighted and scrolled into view. */
  span: (versionId: string, assertionId: string) =>
    `${withId("version")(versionId)}&assertion=${encodeURIComponent(assertionId)}`,
  /** The edge table; `search` is its filters and sort (`tableSearch`). */
  relationships: (search = "") => (search ? `/relationships/?${search}` : "/relationships/"),
  relationship: withId("relationship"),
  exceptions: "/exceptions/",
  /** The Theme explorer: every theme with its coverage. */
  themes: "/themes/",
  /** One theme's map: companies by layer, Relationships, Candidates, open gaps. */
  theme: withId("theme"),
  /** The research workbench: start an investigation, and every investigation so far. */
  workbench: "/workbench/",
  /** One investigation: its plan, events, Evidence tray, contradictions and actions. */
  investigation: withId("investigation"),
  /** Every Hypothesis, newest first. */
  hypotheses: "/hypotheses/",
  /** A Hypothesis dossier, at one version (default: the latest). */
  hypothesis: (id: string, version?: number) =>
    version === undefined
      ? withId("hypothesis")(id)
      : `${withId("hypothesis")(id)}&version=${version}`,
};
