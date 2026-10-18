// Pages take their id as a query parameter, so the static export needs no dynamic routes.
const withId = (page: string) => (id: string) => `/${page}/?id=${encodeURIComponent(id)}`;

export const routes = {
  /** The reader's way in: what Atlas believes per theme, what changed, what is due. */
  home: "/",
  /** The prospective record: calls, predictions and how they came out; `search` is `theme=`. */
  record: "/record/",
  recordFor: (theme: string) => `/record/?theme=${encodeURIComponent(theme)}`,
  /** Everything that waits on the owner. */
  decide: "/decide/",
  /** The operations index: Memory, Agents, Issues, edges, the workbench. */
  system: "/system/",
  /** One Issue: what is to find out, and what it produced. */
  issue: withId("issue"),
  companies: "/companies/",
  /** What Memory holds, per company. */
  memory: "/memory/",
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
  /** A theme's Beliefs by argument step; `search` is the filters (`listSearch`). */
  beliefs: (search = "") => (search ? `/beliefs/?${search}` : "/beliefs/"),
  /** One Belief: its judgement, citations at their spans, flags and history. */
  belief: withId("belief"),
  /** Every research session, newest first. */
  sessions: "/sessions/",
  /** One research session: its card, Facts and usage. */
  session: withId("session"),
  /** The research frontier: open Issues, the next action first; `search` is the filters. */
  issues: (search = "") => (search ? `/issues/?${search}` : "/issues/"),
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
