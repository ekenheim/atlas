import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import type { MemoryHealth } from "../lib/api/client";
import {
  THIN_SHARE,
  companyRows,
  figures,
  formatAge,
  openItems,
  sortRows,
  versionSegments,
} from "../lib/memory";

const NOW = Date.parse("2026-10-06T13:12:40Z");

// Production's memory/health of 2026-10-06 (twelve researched companies).
const sample = JSON.parse(
  readFileSync(path.join(__dirname, "fixtures", "memory-health.json"), "utf8"),
) as MemoryHealth;

/** The sample with its companies replaced. */
function withCompanies(companies: unknown[]): MemoryHealth {
  return { ...sample, companies } as MemoryHealth;
}

const sections = (fact_count: number, extra: Record<string, number> = {}) => ({
  total: 10,
  fact_count,
  ...extra,
});
const company = (slug: string, fact_count: number, versions: object, extra: object = {}) => ({
  company_id: `id-${slug}`,
  slug,
  display_name: slug.toUpperCase(),
  role: "researched",
  sections: sections(fact_count),
  versions,
  ...extra,
});

test("the thin line is 40% of the median", () => {
  expect(THIN_SHARE).toBe(0.4);
});

test("production's twelve companies: Innolight has nothing, IQE and Soitec are thin, nine are complete", () => {
  const rows = companyRows(sample);
  expect(rows).toHaveLength(12);
  const by = (slug: string) => rows.find((r) => r.slug === slug)!;
  expect(by("innolight").status).toMatchObject({ severity: "gap", label: "Nothing ingested" });
  expect(by("iqe").status).toMatchObject({ severity: "warn", label: "Thin" });
  expect(by("soitec").status).toMatchObject({ severity: "warn", label: "Thin" });
  expect(rows.filter((r) => r.status.severity === "ok")).toHaveLength(9);
  expect(by("coherent").entityCount).toBe(48);
  expect(by("coherent").mentionCount).toBe(15388);
});

test("a counterparty is not a row", () => {
  const rows = companyRows(
    withCompanies([company("a", 100, { total: 1, in_memory: 1 }), company("b", 100, {}, { role: "counterparty" })]),
  );
  expect(rows.map((r) => r.slug)).toEqual(["a"]);
});

test("versions nothing submitted or triage failed are a gap that outranks failing sections", () => {
  const [row] = companyRows(
    withCompanies([
      company("a", 100, { total: 5, in_memory: 2, not_submitted: 2, triage_failed: 1 }, { sections: sections(100, { failed: 4 }) }),
    ]),
  );
  expect(row!.notInMemory).toBe(3);
  expect(row!.status).toMatchObject({ severity: "gap", label: "3 not in memory" });
});

test("failed, stuck and cancelled sections are a gap", () => {
  const [row] = companyRows(
    withCompanies([
      company("a", 100, { total: 5, in_memory: 5 }, { sections: sections(100, { failed: 1, stuck: 2, cancelled: 3 }) }),
    ]),
  );
  expect(row!.failing).toBe(6);
  expect(row!.status).toMatchObject({ severity: "gap", label: "6 sections failing" });
});

test("a company with versions but zero facts is thin", () => {
  const rows = companyRows(
    withCompanies([
      company("big", 1000, { total: 5, in_memory: 5 }),
      company("mid", 1000, { total: 5, in_memory: 5 }),
      company("none", 0, { total: 3, all_skipped: 3 }),
    ]),
  );
  // The median is of companies with facts (1000), so "none" at 0 is under 40% of it.
  expect(rows.find((r) => r.slug === "none")!.status.severity).toBe("warn");
  expect(rows.find((r) => r.slug === "big")!.status.severity).toBe("ok");
});

test("a company exactly at the thin line is not thin", () => {
  const rows = companyRows(
    withCompanies([
      company("a", 1000, { total: 1, in_memory: 1 }),
      company("b", 1000, { total: 1, in_memory: 1 }),
      company("c", 1000 * THIN_SHARE, { total: 1, in_memory: 1 }),
    ]),
  );
  expect(rows.find((r) => r.slug === "c")!.status.severity).toBe("ok");
});

test("missing version fields count as 0 and a missing versions block as no versions", () => {
  const [row] = companyRows(
    withCompanies([{ ...company("a", 10, {}), versions: undefined }]),
  );
  expect(row!.versions).toMatchObject({ total: 0, in_memory: 0, not_submitted: 0 });
  expect(row!.status.label).toBe("Nothing ingested");
});

test("null names fall back to the slug, then to a placeholder, and the key to the name", () => {
  const rows = companyRows(
    withCompanies([
      company("a", 10, { total: 1, in_memory: 1 }, { display_name: null }),
      { ...company("b", 10, { total: 1, in_memory: 1 }), slug: null, display_name: null, company_id: null },
    ]),
  );
  expect(rows[0]!.name).toBe("a");
  expect(rows[1]!.name).toBe("Unnamed company");
  expect(rows[1]!.href).toBeNull();
  expect(rows[0]!.href).toBe("/company/?id=id-a");
});

test("no companies gives no rows", () => {
  expect(companyRows(withCompanies([]))).toEqual([]);
});

test("entity counts are unknown when the listing is unavailable", () => {
  const health = {
    ...sample,
    entities: { status: "unavailable", reason: "down", scanned: 0, complete: false },
  } as MemoryHealth;
  expect(companyRows(health).every((r) => r.entityCount === null)).toBe(true);
});

const HOUR = 3_600_000;
const unavailable = { status: "unavailable", reason: "down", scanned: 0, complete: false };
/** A bank whose only content is what the test sets; every listing answers. */
const bank = (over: object = {}): MemoryHealth =>
  ({
    ...sample,
    companies: [company("a", 100, { total: 1, in_memory: 1 })],
    consolidation: { last_requested: null, last_completed: null, sections_retained_since: 0 },
    reconciliation: { ...sample.reconciliation!, status: "clean" },
    entities: { status: "ok", scanned: 0, complete: true, companies: [] },
    ...over,
  }) as unknown as MemoryHealth;

test("an age is minutes under an hour, hours under two days, then days", () => {
  const ago = (ms: number) => formatAge(new Date(NOW - ms).toISOString(), NOW);
  expect(ago(5 * 60_000)).toBe("5 min");
  expect(ago(90 * 60_000)).toBe("2 h");
  expect(ago(47 * HOUR)).toBe("47 h");
  expect(ago(72 * HOUR)).toBe("3 days");
  expect(ago(-HOUR)).toBe("0 min");
  expect(formatAge("not a time", NOW)).toBe("unknown");
});

test("the sample's open items: Innolight first, then the warnings in the order the page reads", () => {
  const items = openItems(sample, NOW);
  expect(items.map((i) => [i.severity, i.what, i.status])).toEqual([
    ["gap", "Zhongji Innolight", "Nothing ingested"],
    ["warn", "IQE", "Thin"],
    ["warn", "Soitec", "Thin"],
    ["warn", "Consolidation", "Running 38 h"],
    ["warn", "Entities", "11 of 12 split"],
  ]);
  expect(items[1]!.detail).toBe("1,322 facts · median 4,130");
  expect(items[3]!.detail).toBe("337 rounds");
  expect(items[4]!.detail).toBe("most: Coherent (48)");
  expect(items[0]!.href).toMatch(/^\/company\/\?id=/);
  expect(items[3]!.href).toBeNull();
});

test("a consolidation under 24 hours is not an item, and a finished one never is", () => {
  const run = (hours: number, done: boolean) =>
    ({
      status: done ? "completed" : "submitted",
      rounds: 3,
      requested_at: new Date(NOW - hours * HOUR).toISOString(),
      completed_at: done ? new Date(NOW).toISOString() : null,
    }) as unknown as MemoryHealth["consolidation"]["last_requested"];
  const consolidation = (last_requested: unknown) =>
    bank({ consolidation: { last_requested, last_completed: null, sections_retained_since: 0 } });
  expect(openItems(consolidation(run(23, false)), NOW)).toEqual([]);
  expect(openItems(consolidation(run(25, false)), NOW)).toHaveLength(1);
  expect(openItems(consolidation(run(100, true)), NOW)).toEqual([]);
});

test("a reconciliation that found drift is a gap, and one never run a warning", () => {
  const drift = bank({ reconciliation: { ...sample.reconciliation!, status: "drift" } });
  expect(openItems(drift, NOW).map((i) => [i.severity, i.what, i.status])).toEqual([
    ["gap", "Reconciliation", "drift"],
  ]);
  expect(openItems(bank({ reconciliation: null }), NOW).map((i) => [i.severity, i.status])).toEqual([
    ["warn", "Never reconciled"],
  ]);
});

test("gaps come before warnings whatever raised them", () => {
  const health = bank({
    companies: [company("thin", 1, { total: 1, in_memory: 1 }), company("big", 100, { total: 1, in_memory: 1 }), company("big2", 100, { total: 1, in_memory: 1 })],
    reconciliation: { ...sample.reconciliation!, status: "failed" },
  });
  expect(openItems(health, NOW).map((i) => i.severity)).toEqual(["gap", "warn"]);
});

test("every listing unavailable: no entity item, observations unknown, nothing thrown", () => {
  const health = bank({ entities: unavailable, observation_scopes: unavailable, reconciliation: null });
  expect(openItems(health, NOW).map((i) => i.what)).toEqual(["Reconciliation"]);
  expect(figures(health, NOW).facts.observations).toBeNull();
});

test("no companies: no items beyond the bank's, and the verdict counts zero of zero", () => {
  const health = bank({ companies: [], versions: { total: 0 } });
  expect(openItems(health, NOW)).toEqual([]);
  const f = figures(health, NOW);
  expect(f.open).toEqual({ count: 0, gaps: 0 });
  expect(f.complete).toEqual({ complete: 0, total: 0 });
  expect(f.inMemory.percent).toBeNull();
});

test("the sample's five figures", () => {
  expect(figures(sample, NOW)).toEqual({
    open: { count: 5, gaps: 1 },
    inMemory: { percent: 69, inMemory: 521, inWindow: 753 },
    facts: { facts: 44973, observations: 8618 },
    consolidation: { running: true, severity: "warn", age: "38 h", rounds: 337 },
    reconciliation: { status: "clean", severity: "ok", age: "28 min" },
    complete: { complete: 9, total: 12 },
  });
});

test("an idle bank and a failed reconciliation in the figures", () => {
  const f = figures(bank({ reconciliation: { ...sample.reconciliation!, status: "failed" } }), NOW);
  expect(f.consolidation).toEqual({ running: false, severity: "ok", age: null, rounds: null });
  expect(f.reconciliation).toMatchObject({ status: "failed", severity: "gap" });
  expect(figures(bank({ reconciliation: null }), NOW).reconciliation).toEqual({
    status: "never",
    severity: "warn",
    age: null,
  });
});

test("version segments follow the bar's order, count a gap as not submitted plus triage failed, and sum to the total", () => {
  const v = { total: 20, in_memory: 10, in_flight: 1, retired: 4, all_skipped: 2, not_submitted: 2, triage_failed: 1 };
  expect(versionSegments(v).map((s) => [s.state, s.count])).toEqual([
    ["in_memory", 10],
    ["in_flight", 1],
    ["retired", 4],
    ["all_skipped", 2],
    ["gap", 3],
  ]);
  expect(versionSegments(v)[0]!.share).toBe(0.5);
  expect(versionSegments(v, 40)[0]!.share).toBe(0.25);
  expect(versionSegments({ total: 0 }).every((s) => s.share === 0)).toBe(true);
});

test("rows sort by status then facts, or by facts alone, without changing the input", () => {
  const rows = companyRows(sample);
  const before = rows.map((r) => r.slug);
  expect(sortRows(rows, "status").map((r) => r.slug).slice(0, 4)).toEqual(["innolight", "iqe", "soitec", "lumentum"]);
  expect(sortRows(rows, "facts").map((r) => r.slug).slice(0, 2)).toEqual(["lumentum", "coherent"]);
  expect(rows.map((r) => r.slug)).toEqual(before);
});
