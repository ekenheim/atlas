// The dossier's Source Documents list: type chips with counts, and the rows shown at first.
import type { SourceDocument } from "./api/client";

/** Rows shown before "Show all". */
export const SOURCE_ROWS = 25;

const TYPE_NAMES: Record<string, string> = {
  filing: "Filings",
  transcript: "Transcripts",
  xbrl_companyfacts: "XBRL facts",
};

/** A source type in the reader's words; an unknown one as written, without underscores. */
export const typeName = (type: string) => TYPE_NAMES[type] ?? type.replace(/_/g, " ");

export type TypeChip = { type: string | null; name: string; count: number };

/** "All" first, then each source type present, the most documents first. */
export function typeChips(sources: readonly SourceDocument[]): TypeChip[] {
  const counts = new Map<string, number>();
  for (const s of sources) counts.set(s.source_type, (counts.get(s.source_type) ?? 0) + 1);
  const chips = [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, count]) => ({ type, name: typeName(type), count }));
  return [{ type: null, name: "All", count: sources.length }, ...chips];
}

/** The documents of one type, or all of them for none. */
export function filterByType(sources: readonly SourceDocument[], type: string | null) {
  return type === null ? [...sources] : sources.filter((s) => s.source_type === type);
}
