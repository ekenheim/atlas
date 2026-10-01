import { expect, test } from "@playwright/test";

import type {
  CardReading,
  Counterevidence,
  Investigation,
  InvestigationTask,
  PointedCompany,
  ReadingPointer,
  ResearchCard,
} from "../lib/api/client";
import {
  type PointerGroup,
  addedInvestigator,
  canSaveHypothesis,
  checklistLabel,
  counterevidenceSummary,
  figureLabel,
  followUpBlocked,
  foundBy,
  openQuestions,
  outputParts,
  pointedOutcome,
  pointerGroups,
  pointerQueryLabel,
  pointerSummary,
  pointerWeight,
  readerName,
  readingOutcome,
  selectionSummary,
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
    usage: { rounds: 1, leads: 0, documents: 0, companies: 2, tokens_in: 0, tokens_out: 0 },
    budgets: {
      max_rounds: 2,
      max_leads: 10,
      max_documents: 25,
      max_companies: 6,
      token_budget: 1000,
    },
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
      investigation({
        usage: { rounds: 2, leads: 0, documents: 0, companies: 2, tokens_in: 0, tokens_out: 0 },
      }),
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

test("a document's passages and a Claim's passage say which selections chose them", () => {
  // Memory's pointers first, then the search, the entity tags and the lead windows.
  expect(selectionSummary({ search: 5, entity: 1, pointer: 2 })).toBe(
    "pointer 2, search 5, entity 1",
  );
  expect(selectionSummary({ lead: 3 })).toBe("lead 3");
  // A card drawn before the pointers: its recall selection is shown as it was recorded.
  expect(selectionSummary({ recall: 4, entity: 2 })).toBe("entity 2, recall 4");
  expect(selectionSummary({})).toBeNull();
  expect(selectionSummary(undefined)).toBeNull();
  expect(
    foundBy(["pointer:0", "pointer:3", "search", "entity:6aed559f-3bc4-5b32-8640-69835afa9d40"]),
  ).toBe("pointer, search, entity");
  expect(foundBy(["lead"])).toBe("lead");
  expect(foundBy([])).toBeNull();
  expect(foundBy(undefined)).toBeNull();
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

function pointer(overrides: Partial<ReadingPointer>): ReadingPointer {
  return {
    id: `${overrides.round ?? 1}-${overrides.query_index}-${overrides.rank}-${overrides.section_anchor}`,
    round: 1,
    task_key: "scout",
    memory_type: "world",
    memory_text: "AXT signed a supply agreement with Coherent for 6-inch InP substrates.",
    source_version_id: "v-axt-10q",
    source_title: "AXT 10-Q",
    section_anchor: "part-i-item-2",
    section_char_start: 4000,
    section_char_end: 9000,
    company_id: "c-axt",
    company_name: "AXT",
    citation_state: "resolved",
    ...overrides,
  } as ReadingPointer;
}

test("reading pointers are grouped by the query asked of Memory, best rank first", () => {
  const question = "Who supplies the laser chips, and what feedstock limits them?";
  const substrates = "InP wafer substrate 6-inch capacity expansion";
  const groups = pointerGroups([
    // The order the API returns them in is not relied on: the groups sort themselves.
    pointer({ query_index: 1, query: substrates, rank: 3, company_name: "Coherent" }),
    pointer({
      query_index: 1,
      query: substrates,
      rank: 1,
      section_anchor: "part-ii-item-1a",
      section_char_start: 52000,
    }),
    pointer({ query_index: 1, query: substrates, rank: 1 }),
    pointer({ round: 2, query_index: 0, query: "Is capacity tight?", rank: 1, company_name: null }),
    pointer({ query_index: 0, query: question, rank: 2, company_name: "Lumentum" }),
  ]);

  expect(groups.map((group) => [group.round, group.queryIndex, group.query])).toEqual([
    [1, 0, question],
    [1, 1, substrates],
    [2, 0, "Is capacity tight?"],
  ]);
  const [asked, scouted, followUp] = groups as [PointerGroup, PointerGroup, PointerGroup];
  expect(scouted.pointers.map((each) => [each.rank, each.section_anchor])).toEqual([
    [1, "part-i-item-2"],
    [1, "part-ii-item-1a"],
    [3, "part-i-item-2"],
  ]);
  // The companies pointed at, most pointers first.
  expect(scouted.companies).toEqual([
    { name: "AXT", pointers: 2 },
    { name: "Coherent", pointers: 1 },
  ]);
  expect(pointerSummary(scouted)).toBe("3 pointers: AXT 2, Coherent 1");
  expect(pointerSummary(asked)).toBe("1 pointer: Lumentum 1");
  expect(pointerSummary(followUp)).toBe("1 pointer: no company 1");
  // The question is query 0; a later round says so (never "Round 1", a plan table's name).
  expect(pointerQueryLabel(asked)).toBe("The question");
  expect(pointerQueryLabel(scouted)).toBe("Query 1");
  expect(pointerQueryLabel(followUp)).toBe("The question (follow-up round 2)");
  expect(pointerGroups([])).toEqual([]);
});

function pointed(overrides: Partial<PointedCompany>): PointedCompany {
  return {
    round: 1,
    company_id: "c-axt",
    company_name: "AXT",
    slug: "axt",
    pointers: 4,
    score: 4,
    best_rank: 1,
    outcome: "added",
    task_key: "investigator:axt",
    ...overrides,
  };
}

test("a company the pointers name says what became of it, and an added Investigator why", () => {
  const axt = pointed({});
  const coherent = pointed({
    company_name: "Coherent",
    slug: "coherent",
    outcome: "seed",
    task_key: "investigator:coherent",
  });
  const macom = pointed({
    company_name: "MACOM",
    slug: "macom",
    pointers: 1,
    score: 0.0833,
    best_rank: 12,
    outcome: "no_room",
    task_key: null,
  });
  expect(pointerWeight(axt)).toBe("4 pointers, best rank 1, weight 4");
  expect(pointerWeight(macom)).toBe("1 pointer, best rank 12, weight 0.08");
  expect(pointedOutcome(coherent, 6)).toBe("a seed: read whatever its rank");
  expect(pointedOutcome(axt, 6)).toBe("Investigator added");
  expect(pointedOutcome(macom, 2)).toBe(
    "not read: the company budget (2 Investigators a round) had no room",
  );
  expect(pointedOutcome(pointed({ outcome: "premise_disproven", task_key: null }), 6)).toBe(
    "not read: its premise was disproven",
  );
  // The plan says which Investigators were added, and why; a seed's says nothing.
  const task = (round: number, key: string) => ({ round, key }) as InvestigationTask;
  expect(addedInvestigator(task(1, "investigator:axt"), [coherent, axt, macom])).toBe(
    "Added after the Scout: Memory points to AXT (4 pointers, best rank 1, weight 4).",
  );
  expect(addedInvestigator(task(1, "investigator:coherent"), [coherent, axt])).toBeNull();
  expect(addedInvestigator(task(2, "investigator:axt"), [coherent, axt])).toBeNull(); // round 1's
  expect(addedInvestigator(task(1, "scout"), [])).toBeNull();
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
