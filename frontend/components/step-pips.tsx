// A chokepoint's six steps as a strip (spec §10.3.3, Z8): the mark first, then the step's short
// name, its brightness carrying the state (quoted bright, unquoted dimmer, not examined muted,
// contradicted red). Four steps argue for the chokepoint, then `Against` and the two against it.
// Each item is named for a screen reader: "Control: unquoted".
import type { Chokepoint } from "../lib/api/client";
import { type Pip, pipsOf } from "../lib/chokepoints";

const CLASS: Record<Pip["status"], string> = {
  primary: "pip-q",
  lead: "pip-u",
  unexamined: "pip-n",
  contradicted: "pip-x",
};

function PipItem({ pip }: { pip: Pip }) {
  return (
    <li className={`pip ${CLASS[pip.status]}`} aria-label={pip.accessible}>
      {pip.mark ? (
        <span className="pip-mark" aria-hidden="true">
          {pip.mark}
        </span>
      ) : null}
      <span aria-hidden="true">{pip.label}</span>
    </li>
  );
}

export function StepPips({ steps }: { steps: Chokepoint["steps"] }) {
  const pips = pipsOf({ steps });
  return (
    <ul className="pips" aria-label="Steps">
      {pips
        .filter((pip) => !pip.against)
        .map((pip) => (
          <PipItem key={pip.name} pip={pip} />
        ))}
      <li className="pips-break" aria-hidden="true" />
      <li className="pips-against" aria-hidden="true">
        <span className="pips-dot">· </span>Against
      </li>
      {pips
        .filter((pip) => pip.against)
        .map((pip) => (
          <PipItem key={pip.name} pip={pip} />
        ))}
    </ul>
  );
}

/** The board's one legend line (decoration: each pip is named on its own). */
export function PipLegend() {
  return (
    <p className="pip-legend" aria-hidden="true">
      <span className="pip-q">● quoted</span> <span className="pip-u">○ unquoted</span>{" "}
      <span className="pip-x">✕ contradicted</span> <span className="pip-n">· dim: not examined</span>
    </p>
  );
}
