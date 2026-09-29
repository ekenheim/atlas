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
};
