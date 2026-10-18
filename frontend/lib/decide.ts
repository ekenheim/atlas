// What waits on the owner (spec §5.8), kept to what he decides himself: a version at the publish
// gate, an open proposed update, a Belief to judge. Edge exceptions, Candidates and identity
// mappings are the lead's delegated work: they are counts, and an edge becomes an item only when
// it blocks a gate.
import { api, type BeliefSummary } from "./api/client";

/** Beliefs that need his judgement: active, unproven or undecidable, flagged, or with a newer
 * document that supports them. */
export function beliefsToJudge<T extends Pick<BeliefSummary, "status" | "open_flags" | "open_notices"> & {
  judgement: Pick<BeliefSummary["judgement"], "judgement">;
}>(beliefs: readonly T[]): T[] {
  return beliefs.filter(
    (belief) =>
      belief.status === "active" &&
      (belief.judgement.judgement === "unproven" ||
        belief.judgement.judgement === "undecidable" ||
        belief.open_flags > 0 ||
        belief.open_notices > 0),
  );
}

/** Why a Belief is on the list, in a few words. */
export function whyToJudge(
  belief: Pick<BeliefSummary, "open_flags" | "open_notices"> & {
    judgement: Pick<BeliefSummary["judgement"], "judgement">;
  },
): string {
  if (belief.open_flags > 0) return belief.open_flags === 1 ? "1 flag" : `${belief.open_flags} flags`;
  if (belief.judgement.judgement === "unproven") return "unproven";
  if (belief.judgement.judgement === "undecidable") return "undecidable";
  return belief.open_notices === 1 ? "1 confirmation" : `${belief.open_notices} confirmations`;
}

// --- the nav badge ---------------------------------------------------------------------------

export const COUNT_KEY = "atlas.decideCount";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function tabStore(): Store | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

/** The count cached for this tab, or null. */
export function cachedCount(store: Store | null = tabStore()): number | null {
  try {
    const raw = store?.getItem(COUNT_KEY);
    if (raw === null || raw === undefined) return null;
    const count = Number(raw);
    return Number.isInteger(count) && count >= 0 ? count : null;
  } catch {
    return null;
  }
}

export function cacheCount(count: number, store: Store | null = tabStore()): void {
  try {
    store?.setItem(COUNT_KEY, String(count));
  } catch {
    // A convenience: the badge is read again without it.
  }
}

/** Dropped after any successful action, so the badge is read again. */
export function forgetDecideCount(store: Store | null = tabStore()): void {
  try {
    store?.removeItem(COUNT_KEY);
  } catch {
    // Nothing cached, or storage is blocked.
  }
}

/** The badge's count: Beliefs to judge and open proposed updates (two list calls). The gate
 * blocks are counted on the Decide page itself, which makes a call for each draft. */
export async function loadDecideCount(): Promise<number> {
  const [beliefs, updates] = await Promise.all([
    api.beliefs({ status: "active" }),
    api.proposedUpdates("open"),
  ]);
  return beliefsToJudge(beliefs.items).length + updates.total;
}
