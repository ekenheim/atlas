import { expect, test } from "@playwright/test";

import { ApiError } from "../lib/api/client";
import { plainError } from "../lib/plain-error";

test("a known code reads as its own sentence, never the code", () => {
  const text = plainError(new ApiError(409, "invalid_transition", "x"), "Could not.");
  expect(text).toBe("That was already decided, so there is nothing to change.");
  expect(text).not.toContain("invalid_transition");
  expect(plainError(new ApiError(503, "judge_unavailable", "x"), "Could not.")).toContain("Try again later");
});

test("an unknown code falls back to the page's sentence, and never shows the raw message", () => {
  const text = plainError(new ApiError(422, "weird_code", "body.reason: Field required"), "Could not judge it.");
  expect(text).toBe("Could not judge it.");
  expect(plainError(new ApiError(500, "http_error", "500"), "Could not judge it.")).toContain("try again later");
  expect(plainError(new Error("boom"), "Could not judge it.")).toBe("Could not judge it.");
});
