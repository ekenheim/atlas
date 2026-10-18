"use client";

// "Check the thesis": where the publish gate holds a version for a thesis nobody has checked, the
// owner asks the judge to read it against its Beliefs' quotes. A refusal says why and what to do
// instead (a thesis the judge found overreaching changes only by a correction).
import { useState } from "react";

import { ApiError, api } from "../lib/api/client";
import { thesisJudgeRefusal, thesisJudgedMessage } from "../lib/hypotheses";

export function CheckThesisButton({
  hypothesisId,
  version,
  onChecked,
}: {
  hypothesisId: string;
  version: number;
  /** Told what the check found, to show a line and read the page again. */
  onChecked: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  return (
    <span className="check-thesis">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setRefusal(null);
          api.judgeThesis(hypothesisId, version).then(
            (hypothesis) => {
              setBusy(false);
              const judged = hypothesis.versions.find((each) => each.version === version);
              onChecked(thesisJudgedMessage(version, judged?.thesis_judgement?.verdict));
            },
            (error: unknown) => {
              setBusy(false);
              setRefusal(
                error instanceof ApiError
                  ? thesisJudgeRefusal(error.code)
                  : thesisJudgeRefusal("judge_unavailable"),
              );
            },
          );
        }}
      >
        Check the thesis
      </button>
      {refusal ? <span role="alert"> {refusal}</span> : null}
    </span>
  );
}
