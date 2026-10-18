import { expect, test } from "@playwright/test";

import type { HypothesisVersion } from "../lib/api/client";
import { firstSentence, mechanismText, versionArgument } from "../lib/hypothesis-page";

test("a statement's first sentence stops at a full stop before a capital, not at a figure", () => {
  expect(
    firstSentence(
      "In January 2026, AXT expected revenue of $22.5 to $23.5 million. In AXT's May 2025 filing, it said more.",
    ),
  ).toBe("In January 2026, AXT expected revenue of $22.5 to $23.5 million.");
  expect(firstSentence("One sentence only")).toBe("One sentence only");
  expect(firstSentence("Is it? Yes.")).toBe("Is it?");
});

test("the mechanism reads as one paragraph of what the draft established", () => {
  expect(
    mechanismText({
      demand_driver: "Demand is strong.",
      possible_constraint: null,
      economic_capture_question: "Who captures it?",
    }),
  ).toBe("Demand is strong. Who captures it?");
  expect(mechanismText(undefined)).toBe("");
});

test("a version's argument is read from the Beliefs it recorded", () => {
  const version = {
    content: {
      steps: [
        {
          step: "control",
          beliefs: [
            { belief_id: "a", statement: "A", judgement: "proven", confidence: 0.6, as_of: "2026-10-01T00:00:00Z", judged_by: "x", companies: [], citations: [] },
            { belief_id: "b", statement: "B", judgement: "proven", confidence: 0.8, as_of: "2026-10-01T00:00:00Z", judged_by: "x", companies: [], citations: [] },
          ],
        },
      ],
    },
  } as unknown as HypothesisVersion;
  const control = versionArgument(version).find((each) => each.step === "control");
  expect(control?.proven).toBe(2);
  expect(control?.strongest?.judgement.confidence).toBe(0.8);
});
