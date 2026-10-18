import { expect, test } from "@playwright/test";

import type {
  BeliefSummary,
  Call,
  Hypothesis,
  HypothesisVersion,
  Prediction,
  SessionSummary,
  ThemeChange,
  ThemeSummary,
} from "../lib/api/client";
import {
  agentsLine,
  agentsWeek,
  buildCard,
  changeWeight,
  coverageLine,
  newestEvidence,
  leadHypothesis,
  orderChanges,
  orderThemes,
  recordLine,
  selectChanges,
  startingLine,
  startingStatus,
} from "../lib/today";

const NOW = new Date("2026-10-18T13:00:00Z");

const theme = (over: Partial<ThemeSummary> = {}): ThemeSummary => ({
  id: "photonics",
  title: "Photonics for AI data centers",
  description: "",
  universe_version: 7,
  company_count: 12,
  companies_without_sources: 1,
  empty_layers: [],
  relationship_count: 457,
  open_candidate_count: 104,
  board: { lead: 0, candidate: 0, thesis_ready: 0, killed: 0, stale: 0, needs_review: 0 },
  ...over,
});

const MEMORY = theme({
  id: "memory-packaging",
  title: "Memory and advanced packaging for AI",
  company_count: 7,
  companies_without_sources: 7,
  empty_layers: ["controller", "bond-equipment", "package-substrate", "package-materials"],
  relationship_count: 0,
  open_candidate_count: 0,
});

function belief(step: BeliefSummary["step"], confidence: number, over: Partial<BeliefSummary> = {}): BeliefSummary {
  return {
    id: `${step}-${confidence}`,
    statement: `A ${step} statement`,
    theme: "photonics",
    step,
    as_of: "2026-10-17T00:00:00Z",
    status: "active",
    companies: [],
    judgement: {
      id: "j",
      judgement: "proven",
      confidence,
      actor: "owner",
      reason: "r",
      at: "2026-10-18T10:32:00Z",
    },
    open_flags: 0,
    open_notices: 0,
    citation_count: 1,
    produced_by: null,
    created_by: "x",
    created_at: "2026-10-17T00:00:00Z",
    last_examined_at: null,
    last_examined_as_of: null,
    last_examined_outcome: null,
    newest_evidence_at: null,
    ...over,
  };
}

const THESIS =
  "Indium phosphide substrate supply may be a chokepoint: in January 2026 AXT expected revenue of $22.5 million.";

function version(n: number, over: Partial<HypothesisVersion> = {}, content: object = {}): HypothesisVersion {
  return {
    id: `v${n}`,
    version: n,
    based_on_version: null,
    origin: n === 1 ? "editor_draft" : "correction",
    content: {
      thesis_statement: THESIS,
      mechanism: {},
      measurable_predictions: [],
      catalysts: [],
      falsifiers: [],
      required_evidence: [],
      alternative_explanations: [],
      unresolved_questions: [],
      findings: [],
      unsupported_findings: [],
      steps: [{ step: "constraint", beliefs: [] }],
      thesis_judged: null,
      ...content,
    } as unknown as HypothesisVersion["content"],
    content_sha256: "x",
    provenance: {} as HypothesisVersion["provenance"],
    note: null,
    created_by: "x",
    created_at: "2026-10-18T10:00:00Z",
    published: false,
    published_at: null,
    published_by: null,
    ...over,
  };
}

function hypothesis(id: string, versions: HypothesisVersion[], over: Partial<Hypothesis> = {}): Hypothesis {
  const published = versions.some((each) => each.published);
  return {
    id,
    theme_id: "photonics",
    status: published ? "reviewed" : "draft",
    versions,
    first_published_at: published ? "2026-10-18T10:44:00Z" : null,
    updated_at: "2026-10-18T10:44:00Z",
    ...over,
  } as unknown as Hypothesis;
}

const published = hypothesis("h1", [
  version(1),
  version(2, { published: true, published_at: "2026-10-18T10:44:08Z" }),
]);
const draft = hypothesis("h2", [version(1)]);

test("a theme leads with its published Hypothesis, and counts its other drafts", () => {
  const lead = leadHypothesis([draft, published, hypothesis("h3", [version(1)])], "photonics");
  expect(lead.hypothesis?.id).toBe("h1");
  expect(lead.version?.version).toBe(2);
  expect(lead.published).toBe(true);
  expect(lead.otherDrafts).toBe(2);
});

test("with nothing published the latest draft shows, as a draft", () => {
  const lead = leadHypothesis([draft], "photonics");
  expect(lead.published).toBe(false);
  expect(lead.version?.version).toBe(1);
  expect(leadHypothesis([], "photonics").hypothesis).toBeNull();
});

test("the photonics card: proposition, lifecycle, the unchecked correction and the weakest step", () => {
  const beliefs = [
    belief("constraint", 0.85),
    belief("demand_vs_supply", 0.8),
    belief("control", 0.6),
    belief("capture", 0.75),
    belief("relief", 0.75),
  ];
  const card = buildCard(theme(), [published, draft], beliefs, NOW);
  expect(card.starting).toBe(false);
  expect(card.proposition).toBe("Indium phosphide substrate supply may be a chokepoint");
  expect(card.lifecycle).toEqual({ text: "Published 18 Oct", tone: "ok" });
  expect(card.check?.word).toBe("Not checked");
  expect(card.weakest).toEqual({ step: "control", confidence: 0.6 });
  expect(card.beliefCount).toBe(5);
  expect(card.findings).toBeNull();
  expect(card.otherDrafts).toBe(1);
});

test("a theme with no active Belief is starting, whatever else is on file", () => {
  const card = buildCard(MEMORY, [published], [belief("constraint", 0.8)], NOW);
  expect(card.starting).toBe(true);
  expect(card.lifecycle).toBeNull();
  expect(card.weakest).toBeNull();
});

test("a Belief that is not active is not counted, and a theme with Beliefs but no thesis has none", () => {
  const card = buildCard(theme(), [], [belief("constraint", 0.8), belief("control", 0.9, { status: "superseded" })], NOW);
  expect(card.beliefCount).toBe(1);
  expect(card.proposition).toBeNull();
  expect(card.provenCount).toBe(1);
});

test("an investigation-backed Hypothesis shows its findings and no check", () => {
  const legacy = hypothesis("h9", [
    version(1, {}, { steps: [], findings: [{}, {}, {}] }),
  ]);
  const card = buildCard(theme(), [legacy], [belief("constraint", 0.8)], NOW);
  expect(card.findings).toBe(3);
  expect(card.check).toBeNull();
});

test("starting themes come last in the order the API gave", () => {
  const themes = [{ id: "memory-packaging" }, { id: "photonics" }, { id: "robotics" }];
  expect(orderThemes(themes, new Set(["memory-packaging"])).map((t) => t.id)).toEqual([
    "photonics",
    "robotics",
    "memory-packaging",
  ]);
});

test("coverage lines", () => {
  expect(startingLine(MEMORY)).toBe(
    "Starting · 0 of 7 companies have documents · 4 layers without a company",
  );
  expect(startingStatus(MEMORY)).toBe(
    "Starting · 0 of 7 companies have documents in the archive · 4 layers without a company " +
      "(Controller, Bond equipment, Package substrate, Package materials)",
  );
  expect(coverageLine(theme())).toBe("12 companies · 11 with documents · 0 layers empty");
});

const change = (kind: ThemeChange["kind"], text: string, at: string): ThemeChange => ({
  kind,
  text,
  at,
  belief_id: null,
  fact_id: null,
  source_version_id: null,
});

test("disproven, superseded and flagged changes are met first", () => {
  expect(changeWeight(change("judged", "disproven 80%: x", "2026-10-18T00:00:00Z"))).toBe(0);
  expect(changeWeight(change("judged", "superseded: x", "2026-10-18T00:00:00Z"))).toBe(0);
  expect(changeWeight(change("flagged", "A cited document was revised", "2026-10-18T00:00:00Z"))).toBe(0);
  expect(changeWeight(change("judged", "proven 85%: x", "2026-10-18T00:00:00Z"))).toBe(1);
});

test("since last visit: only the window, the important first, then the newest, with the rest counted", () => {
  const mark = new Date("2026-10-17T08:00:00Z");
  const changes = [
    change("judged", "proven 1", "2026-10-18T10:00:00Z"),
    change("judged", "proven 2", "2026-10-18T11:00:00Z"),
    change("judged", "disproven 3", "2026-10-17T09:00:00Z"),
    change("fact", "fact 4", "2026-10-18T09:00:00Z"),
    change("fact", "old", "2026-10-10T09:00:00Z"),
  ];
  const view = selectChanges(changes, mark, NOW, 3);
  expect(view.label).toBe("Since last visit");
  expect(view.shown.map((each) => each.text)).toEqual(["disproven 3", "proven 2", "proven 1"]);
  expect(view.more).toBe(1);
  expect(view.unseen).toBe(4);
});

test("on a theme's page the window's important changes lead and older ones follow, newest first", () => {
  const changes = [
    change("judged", "old", "2026-10-01T09:00:00Z"),
    change("judged", "proven", "2026-10-18T10:00:00Z"),
    change("flagged", "flagged", "2026-10-16T10:00:00Z"),
    change("judged", "older", "2026-09-01T09:00:00Z"),
  ];
  expect(orderChanges(changes, null, NOW).map((each) => each.text)).toEqual([
    "flagged",
    "proven",
    "old",
    "older",
  ]);
});

test("the theme's newest evidence is the latest document any active Belief cites", () => {
  const b = (day: string | null, status: "active" | "superseded" = "active") =>
    belief("constraint", 0.5, { newest_evidence_at: day, status });
  expect(newestEvidence([b("2026-08-14T00:00:00Z"), b("2026-09-02T00:00:00Z"), b(null)])).toBe(
    "2026-09-02T00:00:00Z",
  );
  expect(newestEvidence([b("2026-10-01T00:00:00Z", "superseded"), b("2026-08-14T00:00:00Z")])).toBe(
    "2026-08-14T00:00:00Z",
  );
  expect(newestEvidence([b(null)])).toBeNull();
  expect(newestEvidence([])).toBeNull();
});

test("with no mark the window is the week and nothing is called new", () => {
  const changes = [
    change("judged", "recent", "2026-10-15T10:00:00Z"),
    change("judged", "old", "2026-10-01T10:00:00Z"),
  ];
  const view = selectChanges(changes, null, NOW, 3);
  expect(view.label).toBe("This week");
  expect(view.shown.map((each) => each.text)).toEqual(["recent"]);
  expect(view.unseen).toBe(0);
});

const session = (over: Partial<SessionSummary>): SessionSummary =>
  ({
    started_at: "2026-10-17T10:00:00Z",
    agent: "scout",
    facts: 0,
    beliefs_proposed: 0,
    beliefs_examined: { confirmed: 0, qualified: 0, contradicted: 0, nothing_new: 0 },
    issues_opened: 0,
    isolated: false,
    ...over,
  }) as SessionSummary;

test("the agents line reads each agent's week: runs, what they added and the runs that found nothing", () => {
  const week = agentsWeek(
    [
      session({ facts: 3 }),
      session({ facts: 4 }),
      session({ facts: 0 }),
      session({ facts: 9, isolated: true }),
      session({ facts: 5, started_at: "2026-09-01T00:00:00Z" }),
      session({ agent: "skeptic", beliefs_examined: { confirmed: 0, qualified: 0, contradicted: 0, nothing_new: 2 } }),
      session({ agent: "skeptic", beliefs_examined: { confirmed: 1, qualified: 0, contradicted: 0, nothing_new: 0 } }),
      session({ agent: "researcher", facts: 2, beliefs_proposed: 3, issues_opened: 1 }),
    ],
    NOW,
  );
  expect(week.map((each) => each.agent)).toEqual(["scout", "researcher", "skeptic"]);
  expect(week[0]).toMatchObject({ runs: 3, facts: 7, nothingNew: 1 });
  expect(week[2]).toMatchObject({ runs: 2, examined: 3, nothingNew: 1 });
  expect(agentsLine(week)).toBe(
    "This week: Scout 3 runs · 7 Facts · 1 found nothing new · " +
      "Researcher 1 run · 2 Facts · 3 Beliefs proposed · 1 Issue opened · " +
      "Skeptic 2 runs · examined 3 Beliefs · 1 found nothing new",
  );
  expect(agentsWeek([session({ agent: "lead", facts: 1 })], NOW).map((each) => each.agent)).toEqual(["lead"]);
  expect(agentsWeek([], NOW)).toEqual([]);
});

test("the record line names the open calls, the first checkpoint and the predictions due", () => {
  const call = {
    state: "open",
    next_due: { horizon_months: 1, due_on: "2026-11-18" },
  } as unknown as Call;
  const prediction = { state: "open", deadline: "2026-11-30", measure: "m", hypothesis_id: "h", unit: null, expected_low: null, expected_high: null } as unknown as Prediction;
  expect(recordLine([call, call], [prediction, prediction], NOW)).toBe(
    "2 calls open · first checkpoint 18 Nov · 2 predictions due 30 Nov",
  );
  expect(recordLine([], [], NOW)).toBeNull();
});
