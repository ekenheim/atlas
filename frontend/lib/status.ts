// One vocabulary per object, each value with a tone (spec §4, item 1). A colour means one thing:
// ok is verified or met, warn needs attention, gap is wrong, muted is neutral and the default.
// `unit/status.test.ts` fails when a value of a backend enum has no word here.
import type {
  BeliefSummary,
  Call,
  GateFailure,
  Hypothesis,
  HypothesisStatus,
  HypothesisVersion,
  Prediction,
} from "./api/client";

export type Tone = "ok" | "warn" | "gap" | "muted";

export interface Word {
  word: string;
  tone: Tone;
  /** What the word is shown as when it counts something: "Flagged" reads "1 flag" on a row. */
  detail?: string;
}

// --- a Belief ------------------------------------------------------------------------------

export type JudgementName = BeliefSummary["judgement"]["judgement"];
export type BeliefState = BeliefSummary["status"];

export const JUDGEMENT_WORDS: Record<JudgementName, Word> = {
  proven: { word: "Proven", tone: "muted" },
  unproven: { word: "Unproven", tone: "warn" },
  disproven: { word: "Disproven", tone: "gap" },
  undecidable: { word: "Undecidable", tone: "warn" },
};

/** A Belief that is no longer active is read by that, not by its last judgement. */
export const BELIEF_STATE_WORDS: Record<BeliefState, Word | null> = {
  active: null,
  superseded: { word: "Superseded", tone: "muted" },
  withdrawn: { word: "Withdrawn", tone: "muted" },
};

export interface BeliefWords {
  /** The main word: the judgement, or Superseded or Withdrawn once the Belief is not active. */
  main: Word;
  /** Whether the Belief's own meta reads struck through (superseded). */
  struck: boolean;
  /** Flags and notices are modifiers beside the main word, never states of their own. */
  modifiers: Word[];
}

export function beliefWords(
  belief: Pick<BeliefSummary, "status" | "open_flags" | "open_notices"> & {
    judgement: Pick<BeliefSummary["judgement"], "judgement">;
  },
): BeliefWords {
  const state = BELIEF_STATE_WORDS[belief.status];
  const modifiers: Word[] = [];
  if (belief.open_flags > 0) {
    modifiers.push({
      word: "Flagged",
      tone: "gap",
      detail: `${belief.open_flags} ${belief.open_flags === 1 ? "flag" : "flags"}`,
    });
  }
  if (belief.open_notices > 0) {
    modifiers.push({
      word: "Confirmed",
      tone: "ok",
      detail: `${belief.open_notices} ${belief.open_notices === 1 ? "confirmation" : "confirmations"}`,
    });
  }
  return {
    main: state ?? JUDGEMENT_WORDS[belief.judgement.judgement],
    struck: belief.status === "superseded",
    modifiers,
  };
}

// --- a Hypothesis --------------------------------------------------------------------------

export const LIFECYCLE_WORDS: Record<HypothesisStatus, Word> = {
  draft: { word: "Draft", tone: "muted" },
  researching: { word: "Draft", tone: "muted" },
  needs_more_evidence: { word: "Draft", tone: "muted" },
  evidence_ready: { word: "Needs decision", tone: "warn" },
  reviewed: { word: "Published", tone: "ok" },
  paper_tracking: { word: "Published", tone: "ok" },
  closed: { word: "Retired", tone: "muted" },
  rejected: { word: "Retired", tone: "muted" },
};

export function lifecycleWord(status: HypothesisStatus): Word {
  return LIFECYCLE_WORDS[status];
}

export type ThesisCheckKind = "checked" | "overreaches" | "not_checked";

export interface ThesisCheckWord extends Word {
  kind: ThesisCheckKind;
}

const CHECK_WORDS: Record<ThesisCheckKind, Word> = {
  checked: { word: "Checked", tone: "ok" },
  overreaches: { word: "Overreaches", tone: "gap" },
  not_checked: { word: "Not checked", tone: "warn" },
};

/** Whether the thesis was checked against its quotes. Only the version's effective verdict
 * (`thesis_judgement`, resolved by the backend) is read: supported is Checked, misstated is
 * Overreaches, unjudged or none is Not checked. A version of an investigation (no steps) has no
 * such check: null. */
export function thesisCheckWord(
  version: Pick<HypothesisVersion, "content" | "thesis_judgement">,
): ThesisCheckWord | null {
  if ((version.content.steps ?? []).length === 0) return null;
  const verdict = version.thesis_judgement?.verdict;
  const kind: ThesisCheckKind =
    verdict === "supported" ? "checked" : verdict === "misstated" ? "overreaches" : "not_checked";
  return { kind, ...CHECK_WORDS[kind] };
}

/** The latest published version, or null. */
export function publishedVersion(
  hypothesis: Pick<Hypothesis, "versions">,
): HypothesisVersion | null {
  return [...hypothesis.versions].reverse().find((each) => each.published) ?? null;
}

// --- the publish gate, in plain words ------------------------------------------------------

export const GATE_CODES = [
  "relationship_not_approved",
  "belief_not_proven",
  "belief_flagged",
  "thesis_misstated",
  "thesis_unchecked",
  "no_falsifier",
  "no_unresolved_question",
  "relationship_review_pending",
] as const;

const plural = (count: number, one: string, many: string) =>
  `${count} ${count === 1 ? one : many}`;

/** A failed check of the publish gate in plain words. An unknown code is "Blocked: needs
 * review", with a console warning so a new backend code is noticed. */
export function gateFailureText(
  failure: Pick<GateFailure, "code" | "relationship_ids" | "assertion_ids" | "belief_ids">,
): string {
  switch (failure.code) {
    case "relationship_not_approved":
      return `${plural(failure.relationship_ids.length, "link", "links")} not yet approved`;
    case "belief_not_proven":
      return `${plural((failure.belief_ids ?? []).length, "Belief", "Beliefs")} not proven`;
    case "belief_flagged":
      return `${plural((failure.belief_ids ?? []).length, "Belief", "Beliefs")} flagged`;
    case "thesis_misstated":
      return "Thesis overreaches its quotes";
    case "thesis_unchecked":
      return "Thesis not checked";
    case "no_falsifier":
      return "No falsifier";
    case "no_unresolved_question":
      return "No open question";
    case "relationship_review_pending":
      return `${plural(failure.assertion_ids.length, "quote", "quotes")} awaiting link review`;
    default:
      console.warn(`Unknown publish gate code: ${failure.code}`);
      return "Blocked: needs review";
  }
}

// --- a call and a prediction ---------------------------------------------------------------

export const CALL_WORDS: Record<Call["state"], Word> = {
  open: { word: "Open", tone: "muted" },
  settled: { word: "Checkpointed", tone: "ok" },
  unpriced: { word: "Not priced", tone: "warn" },
};

export const UNPRICED_REASONS: Record<NonNullable<Call["unpriced_reason"]>, string> = {
  no_symbol: "no price symbol",
  tradingview_disabled: "price source off",
};

/** "Not priced: no price symbol", or a call's own state word. */
export function callText(call: Pick<Call, "state" | "unpriced_reason">): string {
  if (call.state !== "unpriced") return CALL_WORDS[call.state].word;
  return call.unpriced_reason
    ? `Not priced: ${UNPRICED_REASONS[call.unpriced_reason]}`
    : CALL_WORDS.unpriced.word;
}

export type PredictionWord = "Open" | "Met" | "Missed" | "Late" | "Lapsed";

export const PREDICTION_WORDS: Record<PredictionWord, Word> = {
  Open: { word: "Open", tone: "muted" },
  Met: { word: "Met", tone: "ok" },
  Missed: { word: "Missed", tone: "gap" },
  Late: { word: "Late", tone: "warn" },
  Lapsed: { word: "Lapsed", tone: "muted" },
};

/** A prediction's word: settled late is Late whatever the outcome, else Met or Missed. */
export function predictionWord(prediction: Pick<Prediction, "state" | "settlement">): Word {
  const settlement = prediction.settlement;
  if (settlement) {
    if (settlement.late) return PREDICTION_WORDS.Late;
    return settlement.outcome === "met" ? PREDICTION_WORDS.Met : PREDICTION_WORDS.Missed;
  }
  return prediction.state === "lapsed" ? PREDICTION_WORDS.Lapsed : PREDICTION_WORDS.Open;
}
