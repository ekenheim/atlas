import { expect, test } from "@playwright/test";

import {
  MARK_KEY,
  SEEN_AFTER_MS,
  isUnseen,
  readMark,
  startMarking,
  windowStart,
  writeMark,
} from "../lib/seen";

function store(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
  };
}

const throwing = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

test("the mark is read as a date, and a missing or broken one is no mark", () => {
  expect(readMark(store({ [MARK_KEY]: "2026-10-17T08:00:00.000Z" }))?.toISOString()).toBe(
    "2026-10-17T08:00:00.000Z",
  );
  expect(readMark(store())).toBeNull();
  expect(readMark(store({ [MARK_KEY]: "nonsense" }))).toBeNull();
  expect(readMark(null)).toBeNull();
});

test("storage that throws never breaks the page", () => {
  expect(readMark(throwing)).toBeNull();
  expect(() => writeMark(new Date(), throwing)).not.toThrow();
});

test("writing the mark stores the time", () => {
  const s = store();
  writeMark(new Date("2026-10-18T12:00:00Z"), s);
  expect(s.data[MARK_KEY]).toBe("2026-10-18T12:00:00.000Z");
});

test("the window starts at the mark, or seven days back with none", () => {
  const now = new Date("2026-10-18T12:00:00Z");
  expect(windowStart(new Date("2026-10-17T08:00:00Z"), now).toISOString()).toBe("2026-10-17T08:00:00.000Z");
  expect(windowStart(null, now).toISOString()).toBe("2026-10-11T12:00:00.000Z");
});

test("something is unseen when it is newer than the mark; with no mark nothing is", () => {
  const mark = new Date("2026-10-17T08:00:00Z");
  expect(isUnseen("2026-10-17T09:00:00Z", mark)).toBe(true);
  expect(isUnseen("2026-10-17T07:00:00Z", mark)).toBe(false);
  expect(isUnseen("2026-10-17T09:00:00Z", null)).toBe(false);
  expect(isUnseen("garbage", mark)).toBe(false);
});

function fakeDocument(state: "visible" | "hidden") {
  const listeners = new Set<() => void>();
  return {
    visibilityState: state as DocumentVisibilityState,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    hide() {
      this.visibilityState = "hidden";
      for (const listener of [...listeners]) listener();
    },
    count: () => listeners.size,
  };
}

test("the visit is marked when the tab is hidden, once, and the listener is removed on cleanup", () => {
  const doc = fakeDocument("visible");
  const s = store();
  const stop = startMarking(doc as unknown as Document, s);
  expect(s.data[MARK_KEY]).toBeUndefined();
  doc.hide();
  expect(s.data[MARK_KEY]).toBeDefined();
  stop();
  expect(doc.count()).toBe(0);
});

test("leaving before ten seconds have passed marks nothing", () => {
  const doc = fakeDocument("visible");
  const s = store();
  const stop = startMarking(doc as unknown as Document, s);
  expect(SEEN_AFTER_MS).toBe(10_000);
  stop();
  expect(s.data[MARK_KEY]).toBeUndefined();
});
