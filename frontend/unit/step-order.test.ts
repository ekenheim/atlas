import { expect, test } from "@playwright/test";

import type { HypothesisVersion } from "../lib/api/client";
import { ARGUMENT_ORDER, FOR_STEPS, AGAINST_STEPS, stripOrder, argumentOf } from "../lib/argument";
import { stepViews } from "../lib/hypothesis-steps";

test("one ordering: the steps for the thesis, then the two against it", () => {
  expect(ARGUMENT_ORDER).toEqual([...FOR_STEPS, ...AGAINST_STEPS]);
  expect(ARGUMENT_ORDER).toEqual([
    "constraint",
    "demand_vs_supply",
    "control",
    "capture",
    "relief",
    "invalidation",
  ]);
  const steps = argumentOf([]);
  expect(stripOrder(steps).map((each) => each.step)).toEqual(steps.map((each) => each.step));
});

test("a version's step rows follow the same order", () => {
  const version = {
    content: {
      steps: ["invalidation", "relief", "capture", "control", "demand_vs_supply", "constraint"].map(
        (step) => ({ step, beliefs: [] }),
      ),
    },
  } as unknown as HypothesisVersion;
  expect(stepViews(version).map((each) => each.step)).toEqual([...ARGUMENT_ORDER]);
});
