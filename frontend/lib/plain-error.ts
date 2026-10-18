// An action that fails says why in a sentence, never a code. The API's error envelope has a
// machine code and a message written for developers; a page shows neither, only the plain line
// for the codes it knows and the page's own fallback for the rest.
import { ApiError } from "./api/client";

const KNOWN: Record<string, string> = {
  not_found: "That is no longer there: reload the page.",
  invalid_transition: "That was already decided, so there is nothing to change.",
  publish_gate_failed: "The publish gate still has checks to pass.",
  judge_unavailable: "The judge is not available now. Try again later.",
  invalid_request: "That could not be saved: check what was typed.",
  belief_not_in_session: "That Belief cannot be changed from here.",
};

/** A sentence for a failed action: the known code's line, else the page's own `fallback`. */
export function plainError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (KNOWN[error.code]) return KNOWN[error.code] as string;
    if (error.status >= 500) return `${fallback} The server had a problem: try again later.`;
  }
  return fallback;
}
