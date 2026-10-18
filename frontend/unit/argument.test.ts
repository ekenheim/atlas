import { expect, test } from "@playwright/test";

import {
  type ArgBelief,
  argumentOf,
  cellName,
  stripOrder,
  weakestStep,
  weakestText,
} from "../lib/argument";

let counter = 0;
function belief(
  step: ArgBelief["step"],
  judgement: ArgBelief["judgement"]["judgement"],
  confidence: number,
  over: Partial<ArgBelief> = {},
): ArgBelief {
  counter += 1;
  return {
    id: `b${String(counter).padStart(3, "0")}`,
    step,
    statement: `${step} ${judgement} ${confidence}`,
    as_of: "2026-10-17T00:00:00Z",
    status: "active",
    open_flags: 0,
    last_examined_at: null,
    judgement: { judgement, confidence },
    ...over,
  };
}

const at = (steps: ReturnType<typeof argumentOf>, name: string) => {
  const found = steps.find((each) => each.step === name);
  if (!found) throw new Error(`no step ${name}`);
  return found;
};

test("each step counts what is proven and names the strongest", () => {
  const steps = argumentOf([
    belief("relief", "proven", 0.6),
    belief("relief", "proven", 0.75),
    belief("relief", "proven", 0.5),
    belief("relief", "unproven", 0.9),
    belief("control", "proven", 0.6),
  ]);
  expect(steps.map((each) => each.step)).toEqual([
    "constraint",
    "demand_vs_supply",
    "relief",
    "control",
    "capture",
    "invalidation",
  ]);
  const relief = at(steps, "relief");
  expect(relief.proven).toBe(3);
  expect(relief.strongest?.judgement.confidence).toBe(0.75);
  expect(relief.against).toBe(true);
  expect(at(steps, "control").against).toBe(false);
  expect(at(steps, "capture").strongest).toBeNull();
  expect(at(steps, "capture").proven).toBe(0);
});

test("a Belief that is not active is not part of the argument", () => {
  const steps = argumentOf([
    belief("control", "proven", 0.9, { status: "superseded" }),
    belief("control", "proven", 0.6),
  ]);
  expect(at(steps, "control").proven).toBe(1);
  expect(at(steps, "control").strongest?.judgement.confidence).toBe(0.6);
});

test("disproven and flagged Beliefs are met first, then proven by confidence", () => {
  const steps = argumentOf([
    belief("constraint", "unproven", 0.5),
    belief("constraint", "proven", 0.6),
    belief("constraint", "proven", 0.8),
    belief("constraint", "proven", 0.7, { open_flags: 1 }),
    belief("constraint", "disproven", 0.9),
  ]);
  expect(at(steps, "constraint").beliefs.map((each) => each.judgement.judgement + each.judgement.confidence)).toEqual([
    "disproven0.9",
    "proven0.7",
    "proven0.8",
    "proven0.6",
    "unproven0.5",
  ]);
});

test("the latest examination of a step is the newest of its Beliefs", () => {
  const steps = argumentOf([
    belief("control", "proven", 0.6, { last_examined_at: "2026-10-12T00:00:00Z" }),
    belief("control", "proven", 0.7, { last_examined_at: "2026-10-16T00:00:00Z" }),
    belief("control", "proven", 0.7),
  ]);
  expect(at(steps, "control").examinedAt).toBe("2026-10-16T00:00:00Z");
  expect(at(steps, "capture").examinedAt).toBeNull();
});

test("the strip puts four for-steps before the two against", () => {
  expect(stripOrder(argumentOf([])).map((each) => each.step)).toEqual([
    "constraint",
    "demand_vs_supply",
    "control",
    "capture",
    "relief",
    "invalidation",
  ]);
});

test("the weakest step is an empty one first, else the lowest strongest confidence", () => {
  const all = [
    belief("constraint", "proven", 0.85),
    belief("demand_vs_supply", "proven", 0.8),
    belief("control", "proven", 0.6),
    belief("capture", "proven", 0.75),
    belief("relief", "proven", 0.3),
  ];
  expect(weakestStep(argumentOf(all))).toEqual({ step: "control", confidence: 0.6 });
  expect(weakestText(weakestStep(argumentOf(all)))).toBe("Weakest step: Control · 60%");
  // Relief argues against the thesis: it is never the weakest step for it.
  const withoutCapture = all.filter((each) => each.step !== "capture");
  expect(weakestStep(argumentOf(withoutCapture))).toEqual({ step: "capture", confidence: null });
  expect(weakestText({ step: "capture", confidence: null })).toBe(
    "Weakest step: Capture · nothing proven",
  );
  // Several empty steps: the first of them in the argument's order.
  expect(weakestStep(argumentOf([])).step).toBe("constraint");
});

test("a cell is named for the step, its side, its proven count and its strongest", () => {
  const steps = argumentOf([
    belief("relief", "proven", 0.75),
    belief("relief", "proven", 0.5),
    belief("relief", "proven", 0.6),
    belief("constraint", "proven", 0.85),
  ]);
  expect(cellName(at(steps, "relief"))).toBe("Relief, against the thesis: 3 proven, strongest 75%");
  expect(cellName(at(steps, "constraint"))).toBe("Constraint: 1 proven, strongest 85%");
  expect(cellName(at(steps, "control"))).toBe("Control: nothing proven");
  expect(cellName(at(steps, "invalidation"))).toBe("Invalidation, against the thesis: nothing proven");
});
