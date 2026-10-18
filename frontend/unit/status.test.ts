import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import type { HypothesisVersion, Prediction } from "../lib/api/client";
import {
  BELIEF_STATE_WORDS,
  BELOW_THE_BAR,
  BOARD_FILTER_WORDS,
  CALL_WORDS,
  CHOKEPOINT_WORDS,
  CROWDING_WORDS,
  GATE_CODES,
  JUDGEMENT_WORDS,
  LIFECYCLE_WORDS,
  NEEDS_QUESTION,
  OWNER_TOKENS,
  PREDICTION_WORDS,
  STEP_MARKS,
  STEP_STATUS_WORDS,
  UNPRICED_REASONS,
  WATCH_MODE_WORDS,
  beliefWords,
  callText,
  gateFailureText,
  gateMissingText,
  lifecycleWord,
  predictionWord,
  thesisCheckWord,
} from "../lib/status";

// The enum-coverage test (Y3): a value the backend adds to an enum has no word until it is
// given one here, and this fails. The schema is read from the checked-in OpenAPI document,
// because `schema.ts` holds types only.
type Schema = { enum?: string[]; properties?: Record<string, Schema>; anyOf?: Schema[] };
const openapi = JSON.parse(
  readFileSync(join(__dirname, "..", "lib", "api", "openapi.json"), "utf-8"),
) as { components: { schemas: Record<string, Schema> } };
const schemas = openapi.components.schemas;

function enumOf(name: string): string[] {
  const found = schemas[name]?.enum;
  if (!found) throw new Error(`${name} is not an enum in the OpenAPI schema`);
  return found;
}

function propertyEnum(schema: string, property: string): string[] {
  const one = schemas[schema]?.properties?.[property];
  const found = one?.enum ?? one?.anyOf?.find((each) => each.enum)?.enum;
  if (!found) throw new Error(`${schema}.${property} is not an enum`);
  return found;
}

const sorted = (values: readonly string[]) => [...values].sort();

test("every Belief judgement has a word", () => {
  expect(sorted(Object.keys(JUDGEMENT_WORDS))).toEqual(sorted(enumOf("Judgement")));
});

test("every Belief status has a word or is the default", () => {
  expect(sorted(Object.keys(BELIEF_STATE_WORDS))).toEqual(sorted(enumOf("Status")));
  expect(BELIEF_STATE_WORDS.active).toBeNull();
});

test("every Hypothesis status maps to a lifecycle word", () => {
  expect(sorted(Object.keys(LIFECYCLE_WORDS))).toEqual(
    sorted(propertyEnum("Hypothesis", "status")),
  );
  for (const status of propertyEnum("Hypothesis", "status")) {
    expect(["Draft", "Published", "Needs decision", "Retired"]).toContain(
      lifecycleWord(status as keyof typeof LIFECYCLE_WORDS).word,
    );
  }
});

test("every call state, unpriced reason and prediction state has a word", () => {
  expect(sorted(Object.keys(CALL_WORDS))).toEqual(sorted(enumOf("CallState")));
  expect(sorted(Object.keys(UNPRICED_REASONS))).toEqual(sorted(enumOf("UnpricedReason")));
  // A prediction is open, met, missed, late or lapsed; the state and the outcome give all five.
  for (const state of enumOf("PredictionState")) {
    const word = predictionWord({
      state: state as Prediction["state"],
      settlement: null,
    });
    expect(Object.values(PREDICTION_WORDS).map((each) => each.word)).toContain(word.word);
  }
  for (const outcome of enumOf("Outcome")) {
    const word = predictionWord({
      state: "settled",
      settlement: { outcome, late: false } as NonNullable<Prediction["settlement"]>,
    });
    expect(Object.values(PREDICTION_WORDS).map((each) => each.word)).toContain(word.word);
  }
});

test("every verdict the backend resolves has a check word; only the effective verdict is read", () => {
  const verdicts = schemas["ThesisJudgement"]?.properties?.verdict?.enum ?? [];
  expect(sorted(verdicts)).toEqual(["misstated", "supported", "unjudged"]);
  const words = (verdict: string | null) => thesisCheckWord(version(verdict))?.word;
  expect(words("supported")).toBe("Checked");
  expect(words("misstated")).toBe("Overreaches");
  expect(words("unjudged")).toBe("Not checked");
  expect(words(null)).toBe("Not checked");
});

function version(verdict: string | null): Pick<HypothesisVersion, "content" | "thesis_judgement"> {
  return {
    // The content still says "supported": it is not read.
    content: {
      steps: [{ step: "constraint", beliefs: [] }],
      thesis_judged: "supported",
    } as unknown as HypothesisVersion["content"],
    thesis_judgement:
      verdict === null
        ? null
        : ({ verdict, reason: null, at: "", by: "x", source: "draft" } as HypothesisVersion["thesis_judgement"]),
  };
}

test("a version of an investigation has no thesis check", () => {
  expect(
    thesisCheckWord({
      content: { findings: [] } as unknown as HypothesisVersion["content"],
    }),
  ).toBeNull();
});

test("a thesis that was never checked is a warning, not a pass", () => {
  expect(thesisCheckWord(version(null))?.tone).toBe("warn");
  expect(thesisCheckWord(version("supported"))?.tone).toBe("ok");
  expect(thesisCheckWord(version("misstated"))?.tone).toBe("gap");
});

const failure = (code: string, ids: Partial<Record<"relationship_ids" | "assertion_ids" | "belief_ids", string[]>> = {}) => ({
  code,
  relationship_ids: ids.relationship_ids ?? [],
  assertion_ids: ids.assertion_ids ?? [],
  belief_ids: ids.belief_ids ?? [],
});

test("each gate failure code reads in plain words with its count", () => {
  expect(gateFailureText(failure("relationship_not_approved", { relationship_ids: ["a", "b", "c"] }))).toBe(
    "3 links not yet approved",
  );
  expect(gateFailureText(failure("relationship_not_approved", { relationship_ids: ["a"] }))).toBe(
    "1 link not yet approved",
  );
  expect(gateFailureText(failure("belief_not_proven", { belief_ids: ["a", "b"] }))).toBe(
    "2 Beliefs not proven",
  );
  expect(gateFailureText(failure("belief_flagged", { belief_ids: ["a"] }))).toBe("1 Belief flagged");
  expect(gateFailureText(failure("thesis_misstated"))).toBe("Thesis overreaches its quotes");
  expect(gateFailureText(failure("thesis_unchecked"))).toBe("Thesis not checked");
  expect(gateFailureText(failure("no_falsifier"))).toBe("No falsifier");
  expect(gateFailureText(failure("no_unresolved_question"))).toBe("No open question");
  // None of the known codes falls through to the generic words.
  for (const code of GATE_CODES) {
    expect(gateFailureText(failure(code))).not.toBe("Blocked: needs review");
  }
});

test("an unknown gate code is blocked for review, and warns in the console", () => {
  const warnings: unknown[] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]) => warnings.push(args);
  try {
    expect(gateFailureText(failure("something_new"))).toBe("Blocked: needs review");
  } finally {
    console.warn = original;
  }
  expect(warnings).toHaveLength(1);
});

test("a call is open, checkpointed or not priced with its reason", () => {
  expect(callText({ state: "open", unpriced_reason: null })).toBe("Open");
  expect(callText({ state: "settled", unpriced_reason: null })).toBe("Checkpointed");
  expect(callText({ state: "unpriced", unpriced_reason: "no_symbol" })).toBe(
    "Not priced: no price symbol",
  );
  expect(callText({ state: "unpriced", unpriced_reason: "tradingview_disabled" })).toBe(
    "Not priced: price source off",
  );
});

test("a prediction settled late is late whatever the outcome", () => {
  const settlement = (outcome: string, late: boolean) =>
    ({ outcome, late }) as NonNullable<Prediction["settlement"]>;
  expect(predictionWord({ state: "settled", settlement: settlement("met", true) }).word).toBe("Late");
  expect(predictionWord({ state: "settled", settlement: settlement("met", false) }).word).toBe("Met");
  expect(predictionWord({ state: "settled", settlement: settlement("missed", false) }).tone).toBe("gap");
  expect(predictionWord({ state: "lapsed", settlement: null }).word).toBe("Lapsed");
  expect(predictionWord({ state: "open", settlement: null }).word).toBe("Open");
});

test("flags and confirmations are modifiers beside the judgement", () => {
  const belief = (judgement: "proven" | "unproven" | "disproven", over = {}) => ({
    judgement: { judgement },
    status: "active" as const,
    open_flags: 0,
    open_notices: 0,
    ...over,
  });
  expect(beliefWords(belief("proven")).main).toEqual({ word: "Proven", tone: "muted" });
  expect(beliefWords(belief("unproven")).main.tone).toBe("warn");
  expect(beliefWords(belief("disproven")).main.tone).toBe("gap");
  expect(beliefWords(belief("proven", { open_flags: 2 })).modifiers).toEqual([
    { word: "Flagged", tone: "gap", detail: "2 flags" },
  ]);
  expect(beliefWords(belief("proven", { open_notices: 1 })).modifiers).toEqual([
    { word: "Confirmed", tone: "ok", detail: "1 confirmation" },
  ]);
  const superseded = beliefWords(belief("proven", { status: "superseded" }));
  expect(superseded.main.word).toBe("Superseded");
  expect(superseded.struck).toBe(true);
});

// --- the Chokepoint Watch (round 3) -----------------------------------------------------------

test("every chokepoint status, step status, crowding, watch mode and board filter has a word", () => {
  expect(sorted(Object.keys(CHOKEPOINT_WORDS))).toEqual(sorted(enumOf("ChokepointStatus")));
  expect(sorted(Object.keys(STEP_STATUS_WORDS))).toEqual(sorted(enumOf("StepStatus")));
  expect(sorted(Object.keys(STEP_MARKS))).toEqual(sorted(enumOf("StepStatus")));
  expect(sorted(Object.keys(CROWDING_WORDS))).toEqual(sorted(enumOf("Crowding")));
  expect(sorted(Object.keys(WATCH_MODE_WORDS))).toEqual(sorted(enumOf("WatchMode")));
  expect(sorted(Object.keys(BOARD_FILTER_WORDS))).toEqual(sorted(enumOf("BoardFilter")));
  expect(CHOKEPOINT_WORDS.lead.word).toBe("Spotted");
  expect(CHOKEPOINT_WORDS.killed).toEqual({ word: "Ruled out", tone: "gap" });
  expect(STEP_STATUS_WORDS.lead.word).toBe("Unquoted");
  expect(CROWDING_WORDS.consensus.word).toBe("Crowded");
  expect(WATCH_MODE_WORDS.delta).toBeNull();
});

test("the thesis gate's codes read as what is still needed", () => {
  expect(gateMissingText("step_b_primary")).toBe("a quote for demand against supply");
  expect(gateMissingText("kill_criteria")).toBe("a falsifier");
  expect(gateMissingText("open_issue")).toBe("an open question");
  expect(NEEDS_QUESTION).toEqual({ word: "Needs a new open question", tone: "warn" });
  expect(BELOW_THE_BAR.tone).toBe("warn");
  // The memo pass's tokens are codes, never plain words, and none maps to a code.
  for (const [token, word] of Object.entries(OWNER_TOKENS)) {
    expect(token).toMatch(/_|^unexamined$/);
    expect(word).not.toMatch(/_/);
  }
});
