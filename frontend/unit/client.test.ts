import { expect, test } from "@playwright/test";

import { api, forgetHypotheses } from "../lib/api/client";

function stubFetch(answers: Array<"ok" | "fail">) {
  const calls: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    const answer = answers.shift() ?? "ok";
    if (answer === "fail") return new Response("{}", { status: 500 });
    return new Response(JSON.stringify({ items: [], total: 0, limit: 500, offset: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  return { calls, restore: () => (globalThis.fetch = original) };
}

test("the Hypotheses list is read once and shared until it is forgotten", async () => {
  forgetHypotheses();
  const stub = stubFetch(["ok", "ok"]);
  try {
    await Promise.all([api.hypotheses(), api.hypotheses()]);
    await api.hypotheses();
    expect(stub.calls).toHaveLength(1);
    forgetHypotheses();
    await api.hypotheses();
    expect(stub.calls).toHaveLength(2);
  } finally {
    stub.restore();
    forgetHypotheses();
  }
});

test("a failed Hypotheses read is not remembered", async () => {
  forgetHypotheses();
  const stub = stubFetch(["fail", "ok"]);
  try {
    await expect(api.hypotheses()).rejects.toThrow();
    await api.hypotheses();
    expect(stub.calls).toHaveLength(2);
  } finally {
    stub.restore();
    forgetHypotheses();
  }
});

test("the totals come from one-row pages", async () => {
  const stub = stubFetch(["ok", "ok", "ok"]);
  try {
    expect(await api.exceptionsTotal()).toBe(0);
    expect(await api.candidatesTotal()).toBe(0);
    expect(await api.identityPendingTotal()).toBe(0);
    expect(stub.calls[0]).toContain("/api/v1/relationships/exceptions?limit=1");
    expect(stub.calls[1]).toContain("state=lead");
    expect(stub.calls[2]).toContain("review_state=pending");
  } finally {
    stub.restore();
  }
});
