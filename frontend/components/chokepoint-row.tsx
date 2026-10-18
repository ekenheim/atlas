// One row of the board (spec §10.3.3): the constraint, the row's link to its page, then the
// badges only (a group's word is its heading, so a row carries no status word). The second line
// is who holds it, the layer, how crowded, when relief could come, and the step strip. Holder
// names are text here: the row has one target.
import Link from "next/link";

import type { Chokepoint } from "../lib/api/client";
import { badges, rowSecondary } from "../lib/chokepoints";
import { routes } from "../lib/routes";
import { CROWDING_TITLE } from "../lib/status";
import { Status } from "./status";
import { StepPips } from "./step-pips";

export function ChokepointRow({ chokepoint, now }: { chokepoint: Chokepoint; now: Date }) {
  const marks = badges(chokepoint, now);
  const secondary = rowSecondary(chokepoint);
  return (
    <li className="reader-row board-row">
      <div className="row-title board-title">
        <Link href={routes.chokepoint(chokepoint.id)}>{chokepoint.constraint}</Link>
      </div>
      <span className="row-verdict board-badges">
        {marks.map((mark) => (
          <Status key={mark.kind} word={mark.word} />
        ))}
      </span>
      <div className="row-secondary board-secondary" title={chokepoint.crowding ? CROWDING_TITLE : undefined}>
        {secondary.join(" · ")}
      </div>
      <StepPips steps={chokepoint.steps} />
    </li>
  );
}
