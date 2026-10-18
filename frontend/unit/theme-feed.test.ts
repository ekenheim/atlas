import { expect, test } from "@playwright/test";

import type { Hypothesis, ThemeChange } from "../lib/api/client";
import { changeHref, changeLabel, hypothesisThesis, themeHypotheses } from "../lib/themes";

function hypothesis(
  id: string,
  fields: Partial<Hypothesis> & { thesis?: string },
): Hypothesis {
  const { thesis, ...rest } = fields;
  return {
    id,
    theme_id: "photonics",
    status: "draft",
    first_published_at: null,
    updated_at: "2026-10-01T00:00:00Z",
    versions: thesis ? [{ content: { thesis_statement: thesis } }] : [],
    ...rest,
  } as unknown as Hypothesis;
}

test("a theme's Hypotheses: the published first, newest publication first, then the rest", () => {
  const listed = themeHypotheses(
    [
      hypothesis("draft-new", { updated_at: "2026-10-09T00:00:00Z" }),
      hypothesis("published-old", { first_published_at: "2026-09-01T00:00:00Z" }),
      hypothesis("elsewhere", { theme_id: "memory", first_published_at: "2026-10-10T00:00:00Z" }),
      hypothesis("published-new", { first_published_at: "2026-10-02T00:00:00Z" }),
      hypothesis("closed", { status: "closed", first_published_at: "2026-10-08T00:00:00Z" }),
      hypothesis("draft-old", { updated_at: "2026-09-20T00:00:00Z" }),
    ],
    "photonics",
  );

  expect(listed.map((each) => each.id)).toEqual([
    "published-new",
    "published-old",
    "draft-new",
    "draft-old",
    "closed",
  ]);
});

test("a Hypothesis is named by its latest version's thesis, else as being drafted", () => {
  expect(hypothesisThesis(hypothesis("a", { thesis: "Lasers are scarce." }))).toBe(
    "Lasers are scarce.",
  );
  expect(hypothesisThesis(hypothesis("b", {}))).toBe("A Hypothesis being drafted");
});

test("a change opens the Belief it is about, or a new Fact at its span", () => {
  const change = (fields: Partial<ThemeChange>) =>
    ({
      kind: "judged",
      belief_id: null,
      fact_id: null,
      source_version_id: null,
      ...fields,
    }) as ThemeChange;

  expect(changeHref(change({ kind: "judged", belief_id: "b1" }))).toBe("/belief/?id=b1");
  expect(changeHref(change({ kind: "flagged", belief_id: "b1" }))).toBe("/belief/?id=b1");
  expect(changeHref(change({ kind: "notice", belief_id: "b2" }))).toBe("/belief/?id=b2");
  expect(changeHref(change({ kind: "fact", fact_id: "f1", source_version_id: "v1" }))).toBe(
    "/version/?id=v1&assertion=f1",
  );
  expect(changeHref(change({ kind: "fact", fact_id: "f1" }))).toBeNull();
  expect(changeHref(change({ kind: "judged" }))).toBeNull();
});

test("a flag or a notice reads as what happened to which Belief, with none of the backend's detail", () => {
  const change = (fields: Partial<ThemeChange>) =>
    ({
      kind: "judged",
      at: "2026-10-18T00:00:00Z",
      text: "",
      belief_id: null,
      fact_id: null,
      source_version_id: null,
      ...fields,
    }) as ThemeChange;
  const text =
    "A load-bearing citation at valence -1 stands against it (Lumentum can add laser capacity faster than demand grows.)";
  expect(changeLabel(change({ kind: "flagged", text }))).toBe(
    "Flagged: Lumentum can add laser capacity faster than demand grows.",
  );
  expect(changeLabel(change({ kind: "notice", text: "A newer 10-Q supports it (X is true.)" }))).toBe(
    "Confirmed: X is true.",
  );
  expect(changeLabel(change({ kind: "flagged", text: "no statement here" }))).toBe("Flagged");
  // A judgement and a new Fact read as the feed gives them.
  expect(changeLabel(change({ kind: "judged", text: "proven 80%: X." }))).toBe("proven 80%: X.");
  expect(changeLabel(change({ kind: "fact", text: "Lumentum: Y." }))).toBe("Lumentum: Y.");
});
