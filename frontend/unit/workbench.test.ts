import { expect, test } from "@playwright/test";

import type { Investigation, ResearchCard } from "../lib/api/client";
import { followUpBlocked, openQuestions, outputParts } from "../lib/workbench";

const card = {
  status: "draft",
  question: "Who supplies the lasers?",
  findings: [
    { open_questions: ["Does NVIDIA qualify a second laser source?", "Is capacity tight?"] },
  ],
  open_questions: ["Is capacity tight?", "Who makes the DSPs?"],
} as unknown as ResearchCard;

function investigation(overrides: Partial<Investigation>): Investigation {
  return {
    status: "stopped",
    stop_reason: "answered",
    research_card: card,
    usage: { rounds: 1, leads: 0, documents: 0, tokens_in: 0, tokens_out: 0 },
    budgets: { max_rounds: 2, max_leads: 10, max_documents: 25, token_budget: 1000 },
    request: { hypothesis_id: null },
    ...overrides,
  } as unknown as Investigation;
}

test("a research card's open questions: the card's, then its findings', each once", () => {
  expect(openQuestions(card)).toEqual([
    "Is capacity tight?",
    "Who makes the DSPs?",
    "Does NVIDIA qualify a second laser source?",
  ]);
  expect(openQuestions(null)).toEqual([]);
});

test("a follow-up is offered only when the API would take it", () => {
  expect(followUpBlocked(investigation({}))).toBeNull();
  expect(followUpBlocked(investigation({ status: "running", stop_reason: null }))).toMatch(
    /still running/,
  );
  expect(followUpBlocked(investigation({ stop_reason: "budget_exhausted" }))).toMatch(/resume/);
  expect(
    followUpBlocked(
      investigation({ usage: { rounds: 2, leads: 0, documents: 0, tokens_in: 0, tokens_out: 0 } }),
    ),
  ).toMatch(/2 rounds are spent/);
  expect(
    followUpBlocked(
      investigation({ request: { hypothesis_id: "h-1" } as Investigation["request"] }),
    ),
  ).toMatch(/Hypothesis/);
  expect(followUpBlocked(investigation({ research_card: null }))).toMatch(/no open question/);
});

test("a task's output is shown from whatever its role recorded", () => {
  expect(
    outputParts({
      documents: 2,
      extraction_status: "completed",
      queries: ["a", "b"],
      scenario: { low: 1, base: 2 },
      error: null,
    }),
  ).toEqual([
    "documents: 2",
    "extraction status: completed",
    "queries: 2",
    "scenario: 2 entries",
    "error: none",
  ]);
});
