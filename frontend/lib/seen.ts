// The last-visit mark (Y9). Each device keeps its own: there is no server-side "seen". Today
// reads the previous mark into memory when it mounts (the mark drives the "new" dots), and
// writes `now` when the tab is hidden or after ten seconds visible. Storage can be missing or
// throw (a private window, blocked site data), so every read and write is in a try/catch and
// the page renders without it.

export const MARK_KEY = "atlas.lastVisit";
/** How long a tab stays visible before the visit counts as seen. */
export const SEEN_AFTER_MS = 10_000;
/** With no mark the window is a week. */
export const FALLBACK_DAYS = 7;

type Store = Pick<Storage, "getItem" | "setItem">;

function browserStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The previous visit's mark, or null when there is none (or it cannot be read). */
export function readMark(store: Store | null = browserStore()): Date | null {
  try {
    const raw = store?.getItem(MARK_KEY);
    if (!raw) return null;
    const at = new Date(raw);
    return Number.isNaN(at.getTime()) ? null : at;
  } catch {
    return null;
  }
}

/** Records `now` as the mark; a failure is swallowed. */
export function writeMark(now: Date = new Date(), store: Store | null = browserStore()): void {
  try {
    store?.setItem(MARK_KEY, now.toISOString());
  } catch {
    // Storage is a convenience: the page works without it.
  }
}

/** Where "since you last looked" starts: the mark, or seven days ago when there is none. */
export function windowStart(mark: Date | null, now: Date = new Date()): Date {
  return mark ?? new Date(now.getTime() - FALLBACK_DAYS * 86_400_000);
}

/** Whether something at `at` is newer than the mark (unseen). With no mark, nothing is. */
export function isUnseen(at: string, mark: Date | null): boolean {
  if (mark === null) return false;
  const time = new Date(at).getTime();
  return !Number.isNaN(time) && time > mark.getTime();
}

/**
 * Starts marking this visit: writes `now` when the tab becomes hidden, or after ten seconds
 * visible, once. Returns the cleanup. Call it from an effect.
 */
export function startMarking(
  doc: Pick<Document, "addEventListener" | "removeEventListener" | "visibilityState"> | null =
    typeof document === "undefined" ? null : document,
  store: Store | null = browserStore(),
): () => void {
  if (doc === null) return () => undefined;
  let done = false;
  const mark = () => {
    if (done) return;
    done = true;
    writeMark(new Date(), store);
  };
  const onChange = () => {
    if (doc.visibilityState === "hidden") mark();
  };
  doc.addEventListener("visibilitychange", onChange);
  const timer = setTimeout(() => {
    if (doc.visibilityState === "visible") mark();
  }, SEEN_AFTER_MS);
  return () => {
    clearTimeout(timer);
    doc.removeEventListener("visibilitychange", onChange);
  };
}
