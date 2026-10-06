// The Memory page's derivations from GET /api/v1/memory/health: pure, no React, and never
// the clock (callers pass `now`). The response is read tolerantly: a null name, a missing
// version field, an `unavailable` listing or a null reconciliation shows what is there.
import type {
  CompanySections,
  ConsolidationRun,
  MemoryHealth,
  SectionCounts,
  VersionCounts,
} from "./api/client";
import { routes } from "./routes";

/** A company is thin when its facts are under this share of the median researched company's. */
export const THIN_SHARE = 0.4;
/** A consolidation run still going after this long is worth a warning. */
export const CONSOLIDATION_WARN_HOURS = 24;

export type Severity = "gap" | "warn" | "ok";
const SEVERITY_ORDER: Record<Severity, number> = { gap: 0, warn: 1, ok: 2 };

/** Version counts with every field present (the API omits a block it has nothing for). */
export type Versions = Required<Omit<VersionCounts, "not_submitted_samples" | "triage_failed_samples">>;

export type CompanyStatus = { severity: Severity; label: string };

export type CompanyRow = {
  key: string;
  slug: string | null;
  name: string;
  /** The dossier, or null when the response named no company id. */
  href: string | null;
  versions: Versions;
  sections: SectionCounts;
  /** Parsed versions that reached no Memory: not submitted plus triage failed. */
  notInMemory: number;
  /** Sections that failed, are stuck or were cancelled. */
  failing: number;
  /** Entities Memory holds for it; null when the listing is unavailable. */
  entityCount: number | null;
  /** Facts per version in memory; null when none is. */
  factsPerVersion: number | null;
  /** Facts as a share of the largest company's, 0..1: the depth bar's scale. */
  depth: number;
  status: CompanyStatus;
};

const num = (n: number | null | undefined) => n ?? 0;

function versionsOf(v: Partial<VersionCounts> | null | undefined): Versions {
  return {
    total: num(v?.total),
    in_memory: num(v?.in_memory),
    retired: num(v?.retired),
    all_skipped: num(v?.all_skipped),
    triage_failed: num(v?.triage_failed),
    in_flight: num(v?.in_flight),
    not_submitted: num(v?.not_submitted),
  };
}

function sectionsOf(s: Partial<SectionCounts> | null | undefined): SectionCounts {
  return {
    total: num(s?.total),
    pending: num(s?.pending),
    completed: num(s?.completed),
    failed: num(s?.failed),
    cancelled: num(s?.cancelled),
    zero_fact: num(s?.zero_fact),
    linked: num(s?.linked),
    retired: num(s?.retired),
    partial: num(s?.partial),
    fact_count: num(s?.fact_count),
    at_profile: num(s?.at_profile),
    below_profile: num(s?.below_profile),
    stuck: num(s?.stuck),
  };
}

/** The median of the positive values (the upper one of two); 0 for none. */
function medianOf(values: number[]): number {
  const sorted = values.filter((n) => n > 0).sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

/** The median fact count of the researched companies that have facts. */
export function medianFacts(health: MemoryHealth): number {
  return medianOf(researched(health).map((c) => num(c.sections?.fact_count)));
}

function researched(health: MemoryHealth): CompanySections[] {
  return (health.companies ?? []).filter((c) => c.role !== "counterparty");
}

function statusOf(v: Versions, s: SectionCounts, notInMemory: number, failing: number, median: number): CompanyStatus {
  if (v.total === 0)
    return s.fact_count > 0
      ? { severity: "warn", label: "No version in window" }
      : { severity: "gap", label: "Nothing ingested" };
  if (notInMemory > 0) return { severity: "gap", label: `${notInMemory} not in memory` };
  if (failing > 0) return { severity: "gap", label: `${plural(failing, "section")} failing` };
  if (s.fact_count < THIN_SHARE * median) return { severity: "warn", label: "Thin" };
  return { severity: "ok", label: "Complete" };
}

/** The researched companies as table rows, in the response's order. */
export function companyRows(health: MemoryHealth): CompanyRow[] {
  const median = medianFacts(health);
  const maxFacts = Math.max(1, ...researched(health).map((c) => num(c.sections?.fact_count)));
  const listing = health.entities?.status === "ok" ? (health.entities.companies ?? []) : null;
  return researched(health).map((c, index) => {
    const versions = versionsOf(c.versions);
    const sections = sectionsOf(c.sections);
    const name = c.display_name ?? c.slug ?? "Unnamed company";
    const notInMemory = versions.not_submitted + versions.triage_failed;
    const failing = sections.failed + sections.stuck + sections.cancelled;
    const found = listing?.find((e) => (c.company_id ? e.company_id === c.company_id : e.slug === c.slug));
    const entities = found?.entities ?? [];
    return {
      key: c.company_id ?? c.slug ?? `row-${index}`,
      slug: c.slug,
      name,
      href: c.company_id ? routes.company(c.company_id) : null,
      versions,
      sections,
      notInMemory,
      failing,
      entityCount: listing ? entities.length : null,
      factsPerVersion: versions.in_memory ? Math.round(sections.fact_count / versions.in_memory) : null,
      depth: sections.fact_count / maxFacts,
      status: statusOf(versions, sections, notInMemory, failing, median),
    };
  });
}

/** A count with its digits grouped, as the page writes every figure. */
export function formatCount(n: number): string {
  return n.toLocaleString("en-GB");
}

/** "1 section", "2 sections". */
export const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

/** How long before `now` (epoch ms) an ISO time was: "5 min", "38 h", "3 days". */
export function formatAge(iso: string, now: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "unknown";
  const hours = Math.max(0, now - then) / 3_600_000;
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

/** Companies in the order the table shows them: by status then facts, or by facts alone. */
export function sortRows(rows: CompanyRow[], order: "status" | "facts"): CompanyRow[] {
  const byFacts = (a: CompanyRow, b: CompanyRow) => b.sections.fact_count - a.sections.fact_count;
  const byStatus = (a: CompanyRow, b: CompanyRow) =>
    SEVERITY_ORDER[a.status.severity] - SEVERITY_ORDER[b.status.severity];
  return [...rows].sort(order === "facts" ? byFacts : (a, b) => byStatus(a, b) || byFacts(a, b));
}

export type OpenItem = {
  severity: Exclude<Severity, "ok">;
  what: string;
  status: string;
  detail: string;
  /** Where to look: a company's dossier; null for the bank's own items. */
  href: string | null;
};

/** The running consolidation, if any: requested, not completed, still submitted. */
function runningConsolidation(health: MemoryHealth): ConsolidationRun | null {
  const run = health.consolidation?.last_requested;
  return run && !run.completed_at && run.status === "submitted" ? run : null;
}

/** What needs a look, gaps before warnings: companies, then consolidation, reconciliation, entities. */
export function openItems(health: MemoryHealth, now: number): OpenItem[] {
  const rows = companyRows(health);
  const median = medianFacts(health);
  const items: OpenItem[] = [];
  for (const r of rows) {
    if (r.status.severity === "ok") continue;
    // The status shows the first condition; the failing sections it hid go in the detail.
    const hidden =
      r.notInMemory > 0 && r.failing > 0 && r.versions.total > 0 ? `${plural(r.failing, "section")} failing` : "";
    items.push({
      severity: r.status.severity,
      what: r.name,
      status: r.status.label,
      detail:
        r.status.label === "Thin"
          ? `${formatCount(r.sections.fact_count)} facts · median ${formatCount(median)}`
          : hidden,
      href: r.href,
    });
  }
  const run = runningConsolidation(health);
  if (run && now - Date.parse(run.requested_at) > CONSOLIDATION_WARN_HOURS * 3_600_000)
    items.push({
      severity: "warn",
      what: "Consolidation",
      status: `Running ${formatAge(run.requested_at, now)}`,
      detail: plural(run.rounds, "round"),
      href: null,
    });
  const rec = health.reconciliation;
  if (!rec) items.push({ severity: "warn", what: "Reconciliation", status: "Never reconciled", detail: "", href: null });
  else if (rec.status !== "clean")
    items.push({
      severity: "gap",
      what: "Reconciliation",
      status: rec.status === "drift" ? "Drift" : rec.status === "failed" ? "Failed" : rec.status,
      detail:
        rec.status === "drift"
          ? `${plural(Object.values(rec.counts).reduce((n, c) => n + c, 0), "difference")} · ${formatAge(rec.started_at, now)} ago`
          : `${formatAge(rec.started_at, now)} ago`,
      href: null,
    });
  const split = rows
    .filter((r) => (r.entityCount ?? 0) > 1)
    .sort((a, b) => (b.entityCount ?? 0) - (a.entityCount ?? 0));
  if (split[0])
    items.push({
      severity: "warn",
      what: "Entities",
      status: `${split.length} of ${rows.length} split`,
      detail: `most: ${split[0].name} (${split[0].entityCount})`,
      href: null,
    });
  return items.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

export type Figures = {
  open: { count: number; gaps: number };
  /** Versions in memory as a share of those inside the intake window (total minus retired). */
  inMemory: { percent: number | null; inMemory: number; inWindow: number };
  /** Observations are null when the scope listing is unavailable. */
  facts: { facts: number; observations: number | null };
  consolidation: { running: boolean; severity: "warn" | "ok"; age: string | null; rounds: number | null };
  reconciliation: { status: string; severity: Severity; age: string | null };
  /** The footer's verdict: companies with nothing open, of those researched. */
  complete: { complete: number; total: number };
};

/** The five figures of the strip, and the footer's count. */
export function figures(health: MemoryHealth, now: number): Figures {
  const items = openItems(health, now);
  const rows = companyRows(health);
  const v = versionsOf(health.versions);
  const inWindow = Math.max(0, v.total - v.retired);
  const scopes = health.observation_scopes;
  const run = runningConsolidation(health);
  const rec = health.reconciliation;
  return {
    open: { count: items.length, gaps: items.filter((i) => i.severity === "gap").length },
    inMemory: {
      percent: inWindow === 0 ? null : Math.floor((100 * v.in_memory) / inWindow),
      inMemory: v.in_memory,
      inWindow,
    },
    facts: {
      facts: num(health.sections?.fact_count),
      observations: scopes?.status === "ok" ? (scopes.scopes ?? []).reduce((n, s) => n + s.count, 0) : null,
    },
    consolidation: run
      ? {
          running: true,
          severity: now - Date.parse(run.requested_at) > CONSOLIDATION_WARN_HOURS * 3_600_000 ? "warn" : "ok",
          age: formatAge(run.requested_at, now),
          rounds: run.rounds,
        }
      : { running: false, severity: "ok", age: null, rounds: null },
    reconciliation: rec
      ? { status: rec.status, severity: rec.status === "clean" ? "ok" : "gap", age: formatAge(rec.started_at, now) }
      : { status: "never", severity: "warn", age: null },
    complete: { complete: rows.filter((r) => r.status.severity === "ok").length, total: rows.length },
  };
}

export const VERSION_STATES = ["in_memory", "in_flight", "retired", "all_skipped", "gap"] as const;
export type VersionState = (typeof VERSION_STATES)[number];
export const VERSION_STATE_NAMES: Record<VersionState, string> = {
  in_memory: "In memory",
  in_flight: "In flight",
  retired: "Retired",
  all_skipped: "Skipped by triage",
  gap: "Not in memory",
};

/** The bar's segments in order. `share` is of the versions' total, or of `scale` to draw bars to one scale. */
export function versionSegments(
  counts: Partial<VersionCounts> | null | undefined,
  scale?: number,
): { state: VersionState; count: number; share: number }[] {
  const v = versionsOf(counts);
  const whole = scale ?? v.total;
  return VERSION_STATES.map((state) => {
    const count = state === "gap" ? v.not_submitted + v.triage_failed : v[state];
    return { state, count, share: whole > 0 ? count / whole : 0 };
  });
}
