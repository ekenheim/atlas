import { expect, test } from "@playwright/test";

import { explainFailure, needsThesisCheck, thesisJudgeRefusal, thesisJudgedMessage } from "../lib/hypotheses";

const failure = (code: string) => ({
  code,
  message: "m",
  relationship_ids: [],
  assertion_ids: [],
});

test("the check button is offered where the gate holds a version for an unchecked thesis", () => {
  expect(needsThesisCheck({ failures: [failure("thesis_unchecked")] })).toBe(true);
  expect(needsThesisCheck({ failures: [failure("thesis_misstated"), failure("no_falsifier")] })).toBe(false);
  expect(needsThesisCheck({ failures: [] })).toBe(false);
});

test("the gate's explanation of an unchecked thesis names the button", () => {
  expect(explainFailure(failure("thesis_unchecked"))).toContain("Check the thesis");
});

test("each refusal says why and what to do instead", () => {
  expect(thesisJudgeRefusal("not_belief_backed")).toContain("drafted from Beliefs");
  const stands = thesisJudgeRefusal("thesis_misstated_stands");
  expect(stands).toContain("Only a correction changes it");
  expect(thesisJudgeRefusal("judge_unavailable")).toContain("Try again later");
  expect(thesisJudgeRefusal("anything_else")).toBe("The thesis could not be checked.");
});

test("what a check found is told in a line", () => {
  expect(thesisJudgedMessage(2, "supported")).toBe("Checked the thesis of version 2: it holds.");
  expect(thesisJudgedMessage(2, "misstated")).toContain("A correction changes it");
  expect(thesisJudgedMessage(2, "unjudged")).toContain("could not be judged");
  expect(thesisJudgedMessage(2, undefined)).toContain("could not be judged");
});
