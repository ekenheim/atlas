import { expect, test } from "@playwright/test";

import type { SessionSummary } from "../lib/api/client";
import { collapseRuns, outcomeText } from "../lib/sessions";

const session = (over: Partial<SessionSummary>): SessionSummary =>
  ({
    id: "s",
    question: "Q",
    started_at: "2026-10-17T10:00:00Z",
    agent: "scout",
    facts: 0,
    beliefs_proposed: 0,
    beliefs_examined: { confirmed: 0, qualified: 0, contradicted: 0, nothing_new: 0 },
    issues_opened: 0,
    ...over,
  }) as SessionSummary;

test("a run reads as what it came to", () => {
  expect(outcomeText(session({ facts: 3 }))).toBe("recorded 3 Facts");
  expect(outcomeText(session({ facts: 1, beliefs_proposed: 2, issues_opened: 1 }))).toBe(
    "recorded 1 Fact, proposed 2 Beliefs, opened 1 Issue",
  );
  expect(
    outcomeText(session({ beliefs_examined: { confirmed: 0, qualified: 0, contradicted: 0, nothing_new: 1 } })),
  ).toBe("examined 1 Belief: nothing new");
  expect(
    outcomeText(session({ beliefs_examined: { confirmed: 1, qualified: 0, contradicted: 1, nothing_new: 1 } })),
  ).toBe("examined 3 Beliefs: 1 confirmed, 1 contradicted");
  expect(outcomeText(session({}))).toBe("found nothing new");
});

test("a server that does not send the session fields yet still reads: the run is the lead's", () => {
  const old = { id: "s", question: "Q", started_at: "2026-10-17T10:00:00Z", facts: 2 } as unknown as SessionSummary;
  expect(outcomeText(old)).toBe("recorded 2 Facts");
  expect(collapseRuns([old, old]).map((group) => group.runs)).toEqual([2]);
});

test("an agent's repeats of one question collapse into the newest, with their count", () => {
  const groups = collapseRuns([
    session({ id: "a", started_at: "2026-10-10T00:00:00Z" }),
    session({ id: "b", started_at: "2026-10-12T00:00:00Z" }),
    session({ id: "c", started_at: "2026-10-11T00:00:00Z", agent: "skeptic" }),
    session({ id: "d", started_at: "2026-10-09T00:00:00Z", question: "Other" }),
  ]);
  expect(groups.map((group) => [group.session.id, group.runs])).toEqual([
    ["b", 2],
    ["c", 1],
    ["d", 1],
  ]);
});
