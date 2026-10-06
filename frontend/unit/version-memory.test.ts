import { expect, test } from "@playwright/test";

import type { SourceVersionMemory } from "../lib/api/client";
import { versionMemory } from "../lib/version-memory";

function memory(counts: Record<string, number>, profiles: (string | null)[]): SourceVersionMemory {
  return {
    current_retain_profile: "retain-v2",
    fact_count: 12,
    counts,
    documents: profiles.map((p, i) => ({ section_anchor: `s${i}`, retain_profile: p })),
  } as unknown as SourceVersionMemory;
}

test("every section stored is in memory", () => {
  const v = versionMemory(
    memory({ completed: 2, zero_fact: 1 }, ["retain-v2", "retain-v2", "retain-v2"]),
  );
  expect(v).toMatchObject({ label: "In memory", severity: "ok", sections: 3, facts: 12, below: 0 });
});

test("no memory, or an error, reads Not in memory", () => {
  expect(versionMemory(null)).toMatchObject({ label: "Not in memory", severity: "gap", sections: 0 });
  expect(versionMemory(memory({}, []))).toMatchObject({ label: "Not in memory" });
});

test("failed sections make it partly in memory; pending ones in flight", () => {
  expect(versionMemory(memory({ completed: 1, failed: 1 }, ["retain-v2", null])).label).toBe(
    "Partly in memory",
  );
  expect(versionMemory(memory({ completed: 1, pending: 1 }, ["retain-v2", null])).label).toBe(
    "In flight",
  );
});

test("all retired reads Retired", () => {
  expect(versionMemory(memory({ retired: 2 }, [null, null])).label).toBe("Retired");
});

test("sections under an older retain profile are counted below", () => {
  const v = versionMemory(memory({ completed: 2 }, ["retain-v1", "retain-v2"]));
  expect(v.below).toBe(1);
  expect(v.profile).toBe("retain-v2");
});
