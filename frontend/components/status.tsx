// A status as a 6px dot and a word at 0.8rem, coloured from `lib/status.ts` (spec §3.5). Outlined
// pills survive only for actionable items on Decide. The dot is decoration: the word carries it.
import type {
  BeliefSummary,
  Call,
  HypothesisStatus,
  HypothesisVersion,
  Prediction,
} from "../lib/api/client";
import {
  type Tone,
  type Word,
  beliefWords,
  callText,
  lifecycleWord,
  predictionWord,
  thesisCheckWord,
} from "../lib/status";
import { Confidence } from "./confidence";

/** One word with its dot, then a space (so the next text node reads on: "Proven 80%").
 * `struck` reads it struck through (a superseded Belief). */
export function Status({ word, struck = false }: { word: Word; struck?: boolean }) {
  return (
    <>
      <span className={`status status-${word.tone}${struck ? " status-struck" : ""}`}>
        <span className="status-dot" aria-hidden="true" />
        {word.word}
      </span>{" "}
    </>
  );
}

type Verdict = Pick<BeliefSummary, "status" | "open_flags" | "open_notices"> & {
  judgement: Pick<BeliefSummary["judgement"], "judgement" | "confidence">;
};

/** A Belief's standing: its judgement word, its confidence once one was formed ("Proven 80%"),
 * then the modifiers beside it (a flag is "1 flag", a newer supporting document "1 confirmation"). */
export function BeliefVerdict({ belief }: { belief: Verdict }) {
  const words = beliefWords(belief);
  const formed = belief.judgement.judgement === "proven" || belief.judgement.judgement === "disproven";
  return (
    <>
      <Status word={words.main} struck={words.struck} />
      {formed && belief.status === "active" && <Confidence value={belief.judgement.confidence} />}
      {words.modifiers.map((modifier) => (
        <span key={modifier.word} className={`status status-${modifier.tone} status-modifier`}>
          {" · "}
          {modifier.detail ?? modifier.word}
        </span>
      ))}
    </>
  );
}

export function LifecycleStatus({ status }: { status: HypothesisStatus }) {
  return <Status word={lifecycleWord(status)} />;
}

/** The thesis check word; nothing for a version of an investigation. */
export function ThesisCheck({ version }: { version: Pick<HypothesisVersion, "origin" | "content"> }) {
  const word = thesisCheckWord(version);
  return word === null ? null : <Status word={word} />;
}

export function PredictionStatus({ prediction }: { prediction: Pick<Prediction, "state" | "settlement"> }) {
  return <Status word={predictionWord(prediction)} />;
}

export function CallStatus({ call }: { call: Pick<Call, "state" | "unpriced_reason"> }) {
  const tone: Tone = call.state === "unpriced" ? "warn" : call.state === "settled" ? "ok" : "muted";
  return <Status word={{ word: callText(call), tone }} />;
}
