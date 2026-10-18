// The argument at a glance (Y1): four cells that argue for the thesis, a divider, a small
// "Against" label, then the two that argue against it. Which side a step is on is structure;
// every fill is neutral and warn never means "against". Each cell names its step, how many
// Beliefs are proven and the strongest one; an empty step is a dashed outline and a dash.
import { type StepArgument, STEP_LABELS, cellName, stripOrder } from "../lib/argument";
import { Confidence } from "./confidence";

function Cell({ step }: { step: StepArgument }) {
  const empty = step.strongest === null;
  return (
    <li className={`strip-cell${empty ? " strip-empty" : ""}`} aria-label={cellName(step)}>
      <span className="strip-step" aria-hidden="true">
        {STEP_LABELS[step.step]}
      </span>
      {empty ? (
        <span className="strip-dash" aria-hidden="true">
          —
        </span>
      ) : (
        <>
          <span className="strip-count" aria-hidden="true">
            {step.proven} proven
          </span>
          <span aria-hidden="true">
            <Confidence value={step.strongest?.judgement.confidence ?? 0} />
          </span>
        </>
      )}
    </li>
  );
}

export function ArgumentStrip({
  steps,
  compact = false,
}: {
  steps: readonly StepArgument[];
  compact?: boolean;
}) {
  const ordered = stripOrder(steps);
  const forCells = ordered.filter((step) => !step.against);
  const againstCells = ordered.filter((step) => step.against);
  return (
    <ul className={`strip${compact ? " strip-compact" : ""}`} aria-label="Argument">
      {forCells.map((step) => (
        <Cell key={step.step} step={step} />
      ))}
      <li className="strip-divider" role="presentation" aria-hidden="true" />
      <li className="strip-against" role="presentation" aria-hidden="true">
        Against
      </li>
      {againstCells.map((step) => (
        <Cell key={step.step} step={step} />
      ))}
    </ul>
  );
}
