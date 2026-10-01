import { expect, test } from "@playwright/test";

import type {
  CardReading,
  Counterevidence,
  Investigation,
  ResearchCard,
} from "../lib/api/client";
import {
  canSaveHypothesis,
  checklistLabel,
  counterevidenceSummary,
  figureLabel,
  followUpBlocked,
  openQuestions,
  outputParts,
  readerName,
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

test("the Skeptic's reading says what code chose for it, its counterevidence, or why it read nothing", () => {
  const reading = {
    round: 1,
    task_key: "skeptic",
    role: "skeptic",
    company_name: null,
    documents: [
      { source_version_id: "a", title: "10-K", sections: ["item-1a"], selected_by: "plan" },
      { source_version_id: "b", title: "10-Q", sections: ["item-2"], selected_by: "fallback" },
      { source_version_id: "c", title: "10-K", sections: [], selected_by: "fallback" },
    ],
    documents_fallback: true,
    documents_dropped: 0,
    passages: 6,
    claims_proposed: 2,
    claims_accepted: 1,
    rejected: { quote_mismatch: 1 },
    detail: null,
  } as unknown as CardReading;
  expect(readerName(reading)).toBe("Skeptic");
  expect(readingOutcome(reading)).toBe(
    "3 documents read; 2 chosen by code (its plan chose none for a seed company); 6 passages;" +
      " 2 counterevidence items proposed, 1 accepted; rejected: quote mismatch ×1.",
  );
  const noPassage = {
    ...reading,
    documents: [reading.documents[0]],
    passages: 0,
    claims_proposed: 0,
    claims_accepted: 0,
    rejected: {},
    detail: "the Skeptic read no passage: no passage of the 1 document it chose matches a checklist item",
  } as unknown as CardReading;
  expect(readingOutcome(noPassage)).toBe(
    "1 document read; 0 passages; 0 counterevidence items proposed, 0 accepted;" +
      " the Skeptic read no passage: no passage of the 1 document it chose matches a checklist item.",
  );
  const skipped = {
    ...reading,
    documents: [],
    detail: "nothing to challenge: the Investigators accepted no Claim",
  } as unknown as CardReading;
  expect(readingOutcome(skipped)).toBe("nothing to challenge: the Investigators accepted no Claim");
  const investigator = { ...reading, role: "investigator", company_name: "Coherent" };
  expect(readerName(investigator as unknown as CardReading)).toBe("Coherent");
});

test("the Skeptic's items are counted by kind: contradictions, bear context, rejected", () => {
  const item = (outcome: string, kind: string) => ({ outcome, kind }) as unknown as Counterevidence;
  expect(counterevidenceSummary([])).toBe("No accepted counterevidence.");
  expect(
    counterevidenceSummary([
      item("accepted", "contradiction"),
      item("accepted", "bear_context"),
      item("accepted", "bear_context"),
      item("accepted", "bear_context"),
      item("rejected", "contradiction"),
    ]),
  ).toBe("1 contradiction of a Claim and 3 bear-context items accepted; 1 proposed item rejected.");
  expect(counterevidenceSummary([item("accepted", "bear_context")])).toBe(
    "0 contradictions of a Claim and 1 bear-context item accepted.",
  );
  expect(
    counterevidenceSummary([item("rejected", "bear_context"), item("rejected", "contradiction")]),
  ).toBe("No accepted counterevidence. 2 proposed items rejected.");
});

test("a bear-checklist item and a table row's figure are shown in words", () => {
  expect(checklistLabel("customer_concentration")).toBe("Customer concentration");
  expect(checklistLabel("dilution_financing")).toBe("Dilution and financing");
  expect(checklistLabel("some_later_item")).toBe("some later item");
  expect(
    figureLabel({ figure_name: "Inventories", figure_period: "March 31, 2026 and June 30, 2025" }),
  ).toBe("Inventories, March 31, 2026 and June 30, 2025");
  expect(figureLabel({ figure_name: null, figure_period: null })).toBeNull();
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
