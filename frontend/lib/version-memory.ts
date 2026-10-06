// The version page's Memory line, from GET /api/v1/source-versions/{id}/memory. Pure.
import type { Severity } from "./memory";
import type { SourceVersionMemory } from "./api/client";

export type VersionMemory = {
  label: string;
  severity: Severity;
  sections: number;
  facts: number;
  /** Sections retained under an older retain profile than the current one. */
  below: number;
  profile: string | null;
};

/** The state of one version in memory; null (no record, or an error) is "Not in memory". */
export function versionMemory(memory: SourceVersionMemory | null): VersionMemory {
  if (!memory) {
    return { label: "Not in memory", severity: "gap", sections: 0, facts: 0, below: 0, profile: null };
  }
  const n = (key: string) => (memory.counts as Record<string, number | undefined>)[key] ?? 0;
  const sections = memory.documents.length;
  const stored = n("completed") + n("zero_fact") + n("linked");
  const below = memory.documents.filter(
    (d) => d.retain_profile && d.retain_profile !== memory.current_retain_profile,
  ).length;
  let state: { label: string; severity: Severity };
  if (sections > 0 && n("retired") === sections) state = { label: "Retired", severity: "ok" };
  else if (sections > 0 && stored === sections) state = { label: "In memory", severity: "ok" };
  else if (n("failed") + n("cancelled") > 0) state = { label: "Partly in memory", severity: "gap" };
  else if (n("pending") > 0) state = { label: "In flight", severity: "warn" };
  else state = { label: "Not in memory", severity: "gap" };
  return {
    ...state,
    sections,
    facts: memory.fact_count,
    below,
    profile: memory.current_retain_profile,
  };
}
