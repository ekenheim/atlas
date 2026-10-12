import { expect, test } from "@playwright/test";

import type { SessionSummary } from "../lib/api/client";
import {
  cardView,
  costText,
  factsById,
  newestFirst,
  statusLabel,
  tokensSpent,
  usageParts,
} from "../lib/sessions";

const FACT = {
  fact_id: "f-1",
  statement: "Coherent is expanding InP laser capacity.",
  period: "FY2026",
  status: "in_effect",
  evidence_available_at: "2025-08-14T12:00:00Z",
};

test("a card's steps read with their statements, Facts and counterevidence", () => {
  const view = cardView({
    steps: [
      {
        step: "demand_vs_supply",
        status: "disputed",
        statements: [
          { statement: "Supply trails demand.", facts: [FACT], counterevidence: [{ ...FACT, fact_id: "f-2" }] },
        ],
        unchecked: ["pricing"],
      },
      { step: "relief", status: "unknown", statements: [] },
    ],
    question_parts: [{ key: "who", text: "Who gains?", status: "answered" }],
    open_questions: ["Who else makes InP lasers?"],
  });

  expect(view.steps.map((step) => [step.key, step.title, step.status])).toEqual([
    ["demand_vs_supply", "demand vs supply", "disputed"],
    ["relief", "relief", "unknown"],
  ]);
  const [statement] = view.steps[0]?.statements ?? [];
  expect(statement?.facts[0]).toEqual({
    id: "f-1",
    statement: FACT.statement,
    detail: "FY2026; 2025-08-14; in effect",
  });
  expect(statement?.counterevidence.map((each) => each.id)).toEqual(["f-2"]);
  expect(view.steps[0]?.unchecked).toEqual(["pricing"]);
  expect(view.parts).toEqual([{ key: "who", text: "Who gains?", status: "answered" }]);
  expect(view.openQuestions).toEqual(["Who else makes InP lasers?"]);
});

test("a step with one statement and the step's Facts beside it is read the same way", () => {
  const view = cardView({ steps: [{ step: "constraint", statement: "A single point.", facts: [FACT] }] });

  expect(view.steps[0]?.statements).toHaveLength(1);
  expect(view.steps[0]?.statements[0]?.facts[0]?.id).toBe("f-1");
});

test("a card that is missing or not understood is empty, never an error", () => {
  const empty = { steps: [], parts: [], openQuestions: [] };
  expect(cardView(null)).toEqual(empty);
  expect(cardView({ steps: "none", open_questions: [3, "ok", ""] })).toEqual({
    ...empty,
    openQuestions: ["ok"],
  });
});

test("cost is the recorded tokens, whichever way the usage gives them", () => {
  expect(tokensSpent({ tokens: 3456 })).toBe(3456);
  expect(tokensSpent({ tokens_in: 1000, tokens_out: 250 })).toBe(1250);
  expect(tokensSpent({ calls: 4 })).toBeNull();
  expect(costText({ tokens: 1234567 })).toBe("1,234,567 tokens");
  expect(costText({})).toBe("none recorded");
  expect(usageParts({ calls: 12, tokens: 5, records_refused: 2, note: "x" })).toEqual([
    "calls: 12",
    "records refused: 2",
  ]);
});

test("statuses read in words, and the list is newest first", () => {
  expect(statusLabel("nothing_found")).toBe("nothing found");
  expect(statusLabel("")).toBe("unknown");
  const sessions = [
    { started_at: "2026-10-01T00:00:00Z", question: "b" },
    { started_at: "2026-10-02T00:00:00Z", question: "z" },
    { started_at: "2026-10-02T00:00:00Z", question: "a" },
  ] as SessionSummary[];

  expect(newestFirst(sessions).map((each) => each.question)).toEqual(["a", "z", "b"]);
  expect(factsById([{ id: "x" }, { id: "y" }]).get("y")).toEqual({ id: "y" });
});
