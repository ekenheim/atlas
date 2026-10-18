"use client";

// The Watch's board for one theme (spec §10.3.3): the chokepoints by group, Thesis-ready first,
// then Candidates, then Spotted (five, then all of them in place), and the ruled-out ones in a
// closed fold of their own whose rows render only once it is opened. Nothing for an empty board:
// the page says so in one line when it has to.
import Link from "next/link";
import { useState } from "react";

import type { Chokepoint, WatchRun } from "../lib/api/client";
import { boardGroups, clampWords } from "../lib/chokepoints";
import { plainDay } from "../lib/format";
import { routes } from "../lib/routes";
import { ChokepointRow } from "./chokepoint-row";
import { PipLegend } from "./step-pips";

/** Spotted rows shown before `All N spotted`. */
export const SPOTTED_SHOWN = 5;

function Group({
  id,
  title,
  rows,
  now,
  limit,
}: {
  id: string;
  title: string;
  rows: Chokepoint[];
  now: Date;
  limit?: number;
}) {
  const [all, setAll] = useState(false);
  if (rows.length === 0) return null;
  const clipped = limit !== undefined && rows.length > limit && !all;
  const shown = clipped ? rows.slice(0, limit) : rows;
  return (
    <section className="board-group" aria-labelledby={id}>
      <h3 className="reader-label" id={id}>
        {title} ({rows.length})
      </h3>
      <ul className="reader-rows" aria-label={title}>
        {shown.map((each) => (
          <ChokepointRow key={each.id} chokepoint={each} now={now} />
        ))}
      </ul>
      {clipped ? (
        <button type="button" className="show-all show-all-flush" onClick={() => setAll(true)}>
          All {rows.length} spotted
        </button>
      ) : null}
    </section>
  );
}

function RuledOut({ rows, now }: { rows: Chokepoint[]; now: Date }) {
  const [opened, setOpened] = useState(false);
  if (rows.length === 0) return null;
  return (
    <details
      className="board-killed"
      onToggle={(event) => {
        if (event.currentTarget.open) setOpened(true);
      }}
    >
      <summary>Ruled out ({rows.length})</summary>
      {opened ? (
        <ul className="reader-rows" aria-label="Ruled out">
          {rows.map((each) => (
            <li className="reader-row" key={each.id}>
              <div className="row-title one-line">
                <Link href={routes.chokepoint(each.id)}>{each.constraint}</Link>
                <span className="board-killed-meta">
                  {" "}
                  · ruled out {plainDay(each.last_event_at, now)}
                  {each.status_reason ? ` · ${clampWords(each.status_reason, 90)}` : ""}
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </details>
  );
}

export function Board({
  items,
  run,
  now = new Date(),
}: {
  items: readonly Chokepoint[];
  /** The theme's latest run: the header links its memo. */
  run?: WatchRun | null;
  now?: Date;
}) {
  if (items.length === 0) return null;
  const groups = boardGroups(items);
  return (
    <section id="board" className="board" aria-labelledby="board-title">
      <div className="board-head">
        <h2 className="reader-label" id="board-title">
          Chokepoints
        </h2>
        {run ? (
          <Link className="board-memo" href={routes.watchRun(run.id)}>
            Memo · {plainDay(run.run_date, now)} <span aria-hidden="true">→</span>
          </Link>
        ) : null}
      </div>
      <PipLegend />
      <Group id="board-ready" title="Thesis-ready" rows={groups.ready} now={now} />
      <Group id="board-candidates" title="Candidates" rows={groups.candidates} now={now} />
      <Group id="board-spotted" title="Spotted" rows={groups.spotted} now={now} limit={SPOTTED_SHOWN} />
      <RuledOut rows={groups.killed} now={now} />
    </section>
  );
}
