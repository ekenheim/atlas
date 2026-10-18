import { expect, test } from "@playwright/test";

import { beliefsToJudge, cacheCount, cachedCount, forgetDecideCount, whyToJudge } from "../lib/decide";
import { NAV_ITEMS, sectionOf } from "../lib/nav";

test("the nav has five items in order", () => {
  expect(NAV_ITEMS.map((item) => item.label)).toEqual(["Today", "Themes", "Record", "Decide", "System"]);
  expect(NAV_ITEMS.map((item) => item.href)).toEqual(["/", "/themes/", "/record/", "/decide/", "/system/"]);
});

test("each path belongs to one section", () => {
  const cases: [string, string][] = [
    ["/", "today"],
    ["/themes/", "themes"],
    ["/theme/", "themes"],
    ["/hypothesis/", "themes"],
    ["/belief/", "themes"],
    ["/company/", "themes"],
    ["/chokepoint/", "themes"],
    ["/watch-run/", "themes"],
    ["/record/", "record"],
    ["/decide/", "decide"],
    ["/system/", "system"],
    ["/memory/", "system"],
    ["/issues/", "system"],
    ["/issue/", "system"],
    ["/relationships/", "system"],
    ["/relationship/", "system"],
    ["/exceptions/", "system"],
    ["/workbench/", "system"],
    ["/investigation/", "system"],
    ["/sessions/", "system"],
    ["/session/", "system"],
    ["/beliefs/", "system"],
    ["/hypotheses/", "system"],
    ["/companies/", "system"],
    ["/source/", "system"],
    ["/version/", "system"],
  ];
  for (const [path, section] of cases) expect(sectionOf(path), path).toBe(section);
  // Without a trailing slash, as a dev server would serve it.
  expect(sectionOf("/theme")).toBe("themes");
  expect(sectionOf("/memory")).toBe("system");
});

const belief = (judgement: "proven" | "unproven" | "undecidable" | "disproven", over = {}) => ({
  judgement: { judgement },
  status: "active" as const,
  open_flags: 0,
  open_notices: 0,
  ...over,
});

test("Beliefs to judge are the unproven, undecidable, flagged or newly supported active ones", () => {
  const list = [
    belief("proven"),
    belief("unproven"),
    belief("undecidable"),
    belief("proven", { open_flags: 1 }),
    belief("proven", { open_notices: 1 }),
    belief("unproven", { status: "superseded" }),
    belief("disproven"),
  ];
  expect(beliefsToJudge(list)).toHaveLength(4);
  expect(whyToJudge(belief("unproven"))).toBe("unproven");
  expect(whyToJudge(belief("proven", { open_flags: 2 }))).toBe("2 flags");
  expect(whyToJudge(belief("proven", { open_notices: 1 }))).toBe("1 confirmation");
});

test("the badge count is cached for the tab, and dropped after an action", () => {
  const data: Record<string, string> = {};
  const store = {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => void (data[key] = value),
    removeItem: (key: string) => void delete data[key],
  };
  expect(cachedCount(store)).toBeNull();
  cacheCount(2, store);
  expect(cachedCount(store)).toBe(2);
  forgetDecideCount(store);
  expect(cachedCount(store)).toBeNull();
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
    removeItem: () => {
      throw new Error("blocked");
    },
  };
  expect(cachedCount(broken)).toBeNull();
  expect(() => cacheCount(1, broken)).not.toThrow();
  expect(() => forgetDecideCount(broken)).not.toThrow();
});
