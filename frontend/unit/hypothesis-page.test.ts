import { expect, test } from "@playwright/test";

import type { Belief, Call, HypothesisVersion } from "../lib/api/client";
import {
  callsFor,
  counterevidenceOf,
  stepBeliefIds,
  thesisCheck,
} from "../lib/hypothesis-steps";

function version(content: Record<string, unknown>): HypothesisVersion {
  return { content } as unknown as HypothesisVersion;
}

const step = (name: string, ...ids: string[]) => ({
  step: name,
  beliefs: ids.map((id) => ({ belief_id: id, confidence: 0.5 })),
});

test("a thesis is checked, overreaches, or is not checked; an investigation's has no check", () => {
  // Only the effective verdict (`thesis_judgement`) is read: the backend resolves it.
  const judged = (verdict: string | null, reason: string | null = null) =>
    ({
      content: { steps: [step("control", "a")], thesis_judged: "supported" },
      thesis_judgement:
        verdict === null ? null : { verdict, reason, at: "", by: "owner", source: "rejudge" },
    }) as unknown as HypothesisVersion;

  expect(thesisCheck(judged("supported"))?.state).toBe("supported");
  expect(thesisCheck(judged("misstated", "it says merchant"))).toEqual({
    state: "misstated",
    text: "Says more than its quotes: it says merchant",
  });
  expect(thesisCheck(judged("unjudged", "no Fact"))?.state).toBe("unchecked");
  // No effective verdict is not a check, whatever its content records.
  expect(thesisCheck(judged(null))).toEqual({
    state: "unchecked",
    text: "Not checked against its quotes yet.",
  });
  // A version of an investigation has no steps, so no check to report.
  expect(thesisCheck(version({ thesis_judged: "supported" }))).toBeNull();
  expect(thesisCheck(version({ steps: [] }))).toBeNull();
});

test("the Beliefs a version rests on are listed once, in the argument's order", () => {
  const ids = stepBeliefIds(
    version({
      steps: [step("control", "b"), step("constraint", "a", "b"), step("capture", "c")],
    }),
  );
  expect(ids).toEqual(["a", "b", "c"]);
  expect(stepBeliefIds(version({}))).toEqual([]);
});

test("counterevidence keeps only the Beliefs that have some, the heaviest against first", () => {
  const against = (ref: string, valence: number) => ({ ref_id: ref, valence });
  const beliefs = [
    { id: "quiet", statement: "Nothing against.", counterevidence: [] },
    {
      id: "doubted",
      statement: "Doubted.",
      counterevidence: [against("x", -0.25), against("y", -1), against("z", -0.5)],
    },
  ] as unknown as Belief[];

  const found = counterevidenceOf(beliefs);

  expect(found.map((each) => each.id)).toEqual(["doubted"]);
  expect(found[0]?.against.map((each) => each.ref_id)).toEqual(["y", "z", "x"]);
  expect(counterevidenceOf([])).toEqual([]);
});

test("a Hypothesis's calls are those of its versions and of its Beliefs, newest first", () => {
  const call = (id: string, origin: Call["origin"], originId: string, madeAt: string) =>
    ({ id, origin, origin_id: originId, made_at: madeAt }) as Call;
  const calls = [
    call("old-belief", "belief", "b1", "2026-09-01T00:00:00Z"),
    call("other-version", "hypothesis", "v9", "2026-10-02T00:00:00Z"),
    call("version", "hypothesis", "v1", "2026-10-01T00:00:00Z"),
    call("other-belief", "belief", "b9", "2026-10-03T00:00:00Z"),
    // An ID of the wrong kind is no match: a Belief's ID is not a version's.
    call("wrong-kind", "signal", "v1", "2026-10-04T00:00:00Z"),
    call("belief", "belief", "b2", "2026-10-05T00:00:00Z"),
  ];

  expect(callsFor(calls, ["v1"], ["b1", "b2"]).map((each) => each.id)).toEqual([
    "belief",
    "version",
    "old-belief",
  ]);
  expect(callsFor(calls, [], [])).toEqual([]);
});
