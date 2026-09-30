import { expect, test } from "@playwright/test";

import type { DiffClaim, HypothesisVersion, PublishGate } from "../lib/api/client";
import {
  chosenVersion,
  explainBlock,
  explainFailure,
  groupClaims,
  summarizeSnapshot,
  versionLabel,
  words,
} from "../lib/hypotheses";

function version(number: number, published = false): HypothesisVersion {
  return {
    version: number,
    origin: number === 1 ? "editor_draft" : "correction",
    published,
  } as HypothesisVersion;
}

test("the URL's version is used when the Hypothesis has it, else the latest", () => {
  const versions = [version(1, true), version(2)];
  expect(chosenVersion("1", versions)).toBe(1);
  expect(chosenVersion(null, versions)).toBe(2);
  expect(chosenVersion("7", versions)).toBe(2);
  expect(chosenVersion("1.5", versions)).toBe(2);
  expect(chosenVersion("x", versions)).toBe(2);
  expect(chosenVersion("1", [])).toBeNull();
});

test("versions and names read as words", () => {
  expect(versionLabel(version(1, true))).toBe("Version 1: the Editor's draft, published");
  expect(versionLabel(version(2))).toBe("Version 2: correction, not published");
  expect(words("scenario_enterprise_value")).toBe("Scenario enterprise value");
});

test("each gate failure is explained, and an unknown one keeps the API's message", () => {
  const failure = (code: string) => ({
    code,
    message: `the API says ${code}`,
    relationship_ids: [],
    assertion_ids: [],
  });
  expect(explainFailure(failure("relationship_not_approved"))).toMatch(
    /^The owner hasn't approved every Relationship/,
  );
  expect(explainFailure(failure("no_falsifier"))).toMatch(/names no falsifier/);
  expect(explainFailure(failure("no_unresolved_question"))).toMatch(/no unresolved question/);
  expect(explainFailure(failure("relationship_review_pending"))).toMatch(/machine-reviewed/);
  expect(explainFailure(failure("a_new_check"))).toBe("the API says a_new_check");
  const gate = { blocked: "already_published" } as PublishGate;
  expect(explainBlock(gate)).toMatch(/^The latest version is published/);
  expect(explainBlock({ ...gate, blocked: null })).toBeNull();
});

test("the diff's claims are grouped new, contradicted, unchanged, removed", () => {
  const claim = (change: DiffClaim["change"], text: string) =>
    ({ change, claim_text: text }) as DiffClaim;
  const groups = groupClaims([
    claim("unchanged", "a"),
    claim("new", "b"),
    claim("removed", "c"),
    claim("new", "d"),
  ]);
  expect(groups.map((g) => [g.change, g.claims.map((c) => c.claim_text)])).toEqual([
    ["new", ["b", "d"]],
    ["unchanged", ["a"]],
    ["removed", ["c"]],
  ]);
});

test("a snapshot's contents are counted, and a malformed part counts nothing", () => {
  expect(
    summarizeSnapshot({
      cutoff: { as_of: "2026-09-01T00:00:00Z", question: "Who supplies?" },
      source_versions: [{}, {}, {}],
      assertions: [{}, {}],
      relationships: [{}],
      scenarios: [{}],
      financial_dataset: { sha256: "ab", observations: [{}, {}] },
      runs: [{}],
      role_calls: [{}, {}, {}, {}],
      memory: { used: true, items: [] },
    }),
  ).toEqual({
    cutoff: "2026-09-01T00:00:00Z",
    question: "Who supplies?",
    sourceVersions: 3,
    assertions: 2,
    relationships: 1,
    scenarios: 1,
    observations: 2,
    runs: 1,
    roleCalls: 4,
    memoryUsed: true,
  });
  expect(summarizeSnapshot({ cutoff: "x", assertions: 3, memory: [] })).toMatchObject({
    cutoff: null,
    assertions: 0,
    memoryUsed: false,
  });
});
