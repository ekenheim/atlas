import { expect, test } from "@playwright/test";

import type { CardReading, Investigation, ResearchCard } from "../lib/api/client";
import {
  canSaveHypothesis,
  followUpBlocked,
  openQuestions,
  outputParts,
  readingOutcome,
} from "../lib/workbench";

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

test("only a card with a finding can be saved as a Hypothesis", () => {
  expect(canSaveHypothesis(investigation({}))).toBe(true);
  const empty = { ...card, findings: [] } as unknown as ResearchCard;
  expect(canSaveHypothesis(investigation({ research_card: empty }))).toBe(false);
  expect(canSaveHypothesis(investigation({ research_card: null }))).toBe(false);
  expect(canSaveHypothesis(investigation({ status: "running", stop_reason: null }))).toBe(false);
});

test("an Investigator's reading says what it read and why nothing was accepted", () => {
  const reading = {
    documents: [{ source_version_id: "v1", title: "10-K", sections: ["item-1", "item-1a"] }],
    documents_dropped: 2,
    passages: 24,
    claims_proposed: 3,
    claims_accepted: 0,
    rejected: { quote_mismatch: 1, no_directional_language: 2 },
    detail: null,
  } as unknown as CardReading;
  expect(readingOutcome(reading)).toBe(
    "1 document read; 2 left out by the document budget; 24 passages; 3 Claims proposed," +
      " 0 accepted; rejected: no directional language ×2, quote mismatch ×1.",
  );
  const none = {
    ...reading,
    documents: [],
    detail: "the document budget is spent",
  } as unknown as CardReading;
  expect(readingOutcome(none)).toBe("the document budget is spent");
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
