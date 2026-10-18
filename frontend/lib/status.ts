// One vocabulary per object, each value with a tone (spec §4, item 1). A colour means one thing:
// ok is verified or met, warn needs attention, gap is wrong, muted is neutral and the default.
// `unit/status.test.ts` fails when a value of a backend enum has no word here.
import type {
  BearCheck,
  BeliefSummary,
  BoardFilter,
  Call,
  Chokepoint,
  GateFailure,
  Hypothesis,
  HypothesisStatus,
  HypothesisVersion,
  Prediction,
  StepState,
  WatchRun,
} from "./api/client";
import { plainDay } from "./format";

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

// --- the Chokepoint Watch (round 3, §10.2) ------------------------------------------------

export type ChokepointStatusName = Chokepoint["status"];
export type StepStatusName = StepState["status"];
export type CrowdingName = NonNullable<Chokepoint["crowding"]>;
export type WatchModeName = WatchRun["mode"];

/** A chokepoint's status, as last set. "Lead" is a record (a lead), never a chokepoint's state. */
export const CHOKEPOINT_WORDS: Record<ChokepointStatusName, Word> = {
  lead: { word: "Spotted", tone: "muted" },
  candidate: { word: "Candidate", tone: "muted" },
  thesis_ready: { word: "Thesis-ready", tone: "ok" },
  killed: { word: "Ruled out", tone: "gap" },
};

/** A thesis-ready chokepoint whose gate lapsed: a thesis step lost its quote, or the
 * falsifiers were cleared. */
export const BELOW_THE_BAR: Word = { word: "Below the bar", tone: "warn" };

/** A thesis-ready chokepoint whose gate lapsed only because its last open question was
 * answered: it needs the next one. */
export const NEEDS_QUESTION: Word = { word: "Needs a new open question", tone: "warn" };

/** No evidence-bearing change for eight weeks (the API's `stale`), read from the last one. */
export function quietWord(lastEvidenceAt: string, now: Date = new Date()): Word {
  return { word: `Quiet since ${plainDay(lastEvidenceAt, now)}`, tone: "muted" };
}

/** A step's status. The label's brightness and the mark carry it (`STEP_MARKS`). */
export const STEP_STATUS_WORDS: Record<StepStatusName, Word> = {
  primary: { word: "Quoted", tone: "muted" },
  lead: { word: "Unquoted", tone: "muted" },
  unexamined: { word: "Not examined", tone: "muted" },
  contradicted: { word: "Contradicted", tone: "gap" },
};

export const STEP_MARKS: Record<StepStatusName, string> = {
  primary: "●",
  lead: "○",
  unexamined: "",
  contradicted: "✕",
};

export const CROWDING_TITLE = "Atlas's guess at how widely it is known";

export const CROWDING_WORDS: Record<CrowdingName, Word> = {
  early: { word: "Early", tone: "muted" },
  emerging: { word: "Emerging", tone: "muted" },
  consensus: { word: "Crowded", tone: "muted" },
};

export const CROWDING_NONE = "Crowding not judged";

/** Only the first survey is named; a weekly run is the default and has no word. */
export const WATCH_MODE_WORDS: Record<WatchModeName, string | null> = {
  architect: "First survey",
  delta: null,
};

/** What the thesis gate finds missing, in words that follow "Still needs:". */
export const GATE_MISSING: Record<string, string> = {
  step_a_primary: "a quote for the constraint",
  step_b_primary: "a quote for demand against supply",
  step_d_primary: "a quote for control",
  kill_criteria: "a falsifier",
  open_issue: "an open question",
};

/** One missing item in words; an unknown code is "something else, needs review", with a
 * console warning so a new backend code is noticed. */
export function gateMissingText(code: string): string {
  const known = GATE_MISSING[code];
  if (known !== undefined) return known;
  console.warn(`Unknown thesis gate code: ${code}`);
  return "something else, needs review";
}

/** The board's route filter. The UI does not filter by these; they are named for coverage. */
export const BOARD_FILTER_WORDS: Record<BoardFilter, string> = {
  lead: CHOKEPOINT_WORDS.lead.word,
  candidate: CHOKEPOINT_WORDS.candidate.word,
  thesis_ready: CHOKEPOINT_WORDS.thesis_ready.word,
  killed: CHOKEPOINT_WORDS.killed.word,
  stale: "Quiet",
  needs_review: BELOW_THE_BAR.word,
};

/**
 * The codes a memo may still carry, each with the owner's word (the memo's owner-words pass,
 * `lib/markdown.ts`, reads this). Only tokens that are never ordinary English: "lead", "early"
 * or "candidate" in a memo's prose mean what they say, so they are left alone.
 */
export const OWNER_TOKENS: Record<string, string> = {
  thesis_ready: "thesis-ready",
  needs_review: "below the bar",
  unexamined: "not examined",
  demand_vs_supply: "demand against supply",
  kill_criteria: "falsifiers",
  open_issue: "open question",
  step_a_primary: GATE_MISSING.step_a_primary ?? "",
  step_b_primary: GATE_MISSING.step_b_primary ?? "",
  step_d_primary: GATE_MISSING.step_d_primary ?? "",
  shelf_or_atm: "shelf or offering filings",
  gaap_gross_margin: "gross margin",
  customer_concentration: "largest customer",
  going_concern: "going-concern warning",
  net_cash: "net cash",
};

// --- a company's bear checks (round 3, §10.6) ---------------------------------------------

export type CheckKeyName = BearCheck["key"];
export type CheckStatusName = BearCheck["status"];

/** A check's word beside its value: only a flag or an unknown says anything. */
export const BEAR_STATUS_WORDS: Record<CheckStatusName, Word | null> = {
  flag: { word: "Flag", tone: "warn" },
  clear: null,
  unknown: { word: "Unknown", tone: "muted" },
};

/** The six checks, in the one order the page shows them (Y7). */
export const BEAR_LABELS: Record<CheckKeyName, string> = {
  dilution: "Share count growth",
  shelf_or_atm: "Shelf or offering filings",
  gaap_gross_margin: "Gross margin, last four quarters",
  customer_concentration: "Largest customer",
  going_concern: "Going-concern warning",
  net_cash: "Net cash or debt",
};

/** Why a check is unknown, written here until W8's `unknown_reason`. */
export const BEAR_UNKNOWN_REASONS: Record<CheckKeyName, string> = {
  dilution: "no comparable share counts",
  shelf_or_atm: "not in the filings Atlas collects",
  gaap_gross_margin: "no usable quarterly figures",
  customer_concentration: "no customer share stated",
  going_concern: "no report fully read",
  net_cash: "no complete balance sheet",
};
