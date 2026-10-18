"use client";

// The owner's actions on Decide, in the row they belong to: judge a Belief, accept or dismiss a
// proposed update, publish a version that passes its gate. The owner is the actor. Each says in
// a sentence when it fails, and tells the page when it worked so the row can leave the queue.
import { useState, type FormEvent } from "react";

import { api } from "../lib/api/client";
import { JUDGEMENTS, type JudgementName } from "../lib/beliefs";
import { plainError } from "../lib/plain-error";

/** Runs an action, and reports its failure as a sentence. */
function useAction(onDone: (message: string) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<unknown>, done: string, fallback: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDone(done);
    } catch (failure) {
      setError(plainError(failure, fallback));
      setBusy(false);
    }
  };
  return { busy, error, run };
}

export function JudgeBelief({
  id,
  statement,
  current,
  onDone,
}: {
  id: string;
  statement: string;
  current: { judgement: JudgementName; confidence: number };
  onDone: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [judgement, setJudgement] = useState<JudgementName>(
    current.judgement === "unproven" ? "proven" : current.judgement,
  );
  const [percent, setPercent] = useState(Math.round((current.confidence || 0.6) * 100));
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction(onDone);
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Judge
      </button>
    );
  }
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () =>
        api.judgeBelief(id, {
          actor: "owner",
          judgement,
          confidence: Math.min(1, Math.max(0, percent / 100)),
          reason: reason.trim(),
        }),
      `Judged ${JUDGEMENTS[judgement].toLowerCase()}: ${statement}`,
      "Could not save the judgement.",
    );
  };
  return (
    <form className="inline-form" aria-label={`Judge: ${statement}`} onSubmit={submit}>
      <label>
        Judgement{" "}
        <select value={judgement} onChange={(event) => setJudgement(event.target.value as JudgementName)}>
          {Object.entries(JUDGEMENTS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Confidence (%){" "}
        <input
          type="number"
          min={0}
          max={100}
          step={5}
          value={percent}
          onChange={(event) => setPercent(Number(event.target.value))}
        />
      </label>
      <label>
        Reason{" "}
        <input required value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" disabled={busy || reason.trim() === ""}>
        Save judgement
      </button>
      <button type="button" disabled={busy} onClick={() => setOpen(false)}>
        Cancel
      </button>
      {error ? <span role="alert"> {error}</span> : null}
    </form>
  );
}

export function UpdateActions({
  id,
  summary,
  onDone,
}: {
  id: string;
  summary: string;
  onDone: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [needReason, setNeedReason] = useState(false);
  const { busy, error, run } = useAction(onDone);
  return (
    <div className="inline-form" role="group" aria-label={`Proposed update: ${summary}`}>
      <label>
        Note or reason{" "}
        <input
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setNeedReason(false);
          }}
        />
      </label>
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          void run(() => api.acceptUpdate(id, text.trim() || undefined), "Accepted the update: a correction is drafted.", "Could not accept the update.")
        }
      >
        Accept
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (text.trim() === "") {
            setNeedReason(true);
            return;
          }
          void run(() => api.dismissUpdate(id, text.trim()), "Dismissed the update.", "Could not dismiss the update.");
        }}
      >
        Dismiss
      </button>
      {needReason ? <span role="alert"> Say why you dismiss it.</span> : null}
      {error ? <span role="alert"> {error}</span> : null}
    </div>
  );
}

export function PublishVersion({
  hypothesisId,
  version,
  onDone,
}: {
  hypothesisId: string;
  version: number;
  onDone: (message: string) => void;
}) {
  const { busy, error, run } = useAction(onDone);
  return (
    <span className="inline-form">
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          void run(
            () => api.publishVersion(hypothesisId, version),
            `Published version ${version}.`,
            "Could not publish it.",
          )
        }
      >
        Publish version {version}
      </button>
      {error ? <span role="alert"> {error}</span> : null}
    </span>
  );
}
