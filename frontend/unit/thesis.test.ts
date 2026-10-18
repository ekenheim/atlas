import { expect, test } from "@playwright/test";

import { draftedProposition, proposition, rest } from "../lib/thesis";

// The production v2 thesis of the photonics Hypothesis (18 October 2026).
const V2 =
  "Indium phosphide substrate supply may be a chokepoint: in January 2026 AXT expected revenue " +
  "of $22.5 to $23.5 million primarily because China's Ministry of Commerce issued fewer " +
  "indium phosphide export permits than expected, and in August 2026 Lumentum said the " +
  "substrate problem had become very significant and that another deal with AXT might not be enough.";

test("the production thesis leads with its first clause, within 160 characters", () => {
  const lead = proposition(V2);
  expect(lead).toBe("Indium phosphide substrate supply may be a chokepoint");
  expect(lead.length).toBeLessThanOrEqual(160);
  expect(rest(V2).startsWith("in January 2026 AXT expected revenue")).toBe(true);
});

test("a single sentence with no colon is its own proposition", () => {
  const sentence = "Lumentum's laser demand is outrunning its capacity.";
  expect(proposition(sentence)).toBe(sentence);
  expect(rest(sentence)).toBe("");
});

test("a colon beyond 160 characters ends nothing; the whole statement stays", () => {
  const long = `${"word ".repeat(40)}end: and then the facts.`;
  expect(proposition(long)).toBe(long.trim());
  expect(rest(long)).toBe("");
});

test("a time of day is not a colon that ends a proposition", () => {
  const text = "The call began at 10:30 and ran long.";
  expect(proposition(text)).toBe(text);
});

test("an 80-word statement with no colon comes back whole for the layout to clamp", () => {
  const eighty = Array.from({ length: 80 }, (_, i) => `word${i}`).join(" ") + ".";
  expect(proposition(eighty)).toBe(eighty);
});

test("it never cuts at the first sentence", () => {
  const two = "Supply is tight. Demand is rising.";
  expect(proposition(two)).toBe(two);
});

test("a drafted proposition wins when the backend gives one", () => {
  expect(proposition(V2, "InP supply is a chokepoint")).toBe("InP supply is a chokepoint");
  expect(rest("InP supply is a chokepoint: the facts", "InP supply is a chokepoint")).toBe("the facts");
  expect(rest("InP supply is a chokepoint", "InP supply is a chokepoint")).toBe("");
  expect(draftedProposition({ thesis_proposition: " X " })).toBe(" X ");
  expect(draftedProposition({ thesis_proposition: "" })).toBeNull();
  expect(draftedProposition({})).toBeNull();
});
