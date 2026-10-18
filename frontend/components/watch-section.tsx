// Today's Watch (spec §10.3.1): one row per watched theme, below the theme cards. Line 1 is the
// theme, its last watch and its board in a line; line 2 names what changed on the board since the
// run before, each a link to its chokepoint; line 3 is the memo's opening line and `Memo →`. With
// no watched theme (the shipping state), while loading, or on a failed read it renders nothing.
import Link from "next/link";
import { Fragment } from "react";

import { boardParts } from "../lib/chokepoints";
import { plainDay } from "../lib/format";
import { routes } from "../lib/routes";
import { WATCH_MODE_WORDS } from "../lib/status";
import type { WatchRow } from "../lib/watch";

function Named({ row }: { row: WatchRow }) {
  const { parts, more } = row.named;
  if (parts.length === 0) return null;
  return (
    <p className="watch-named">
      {parts.map((part, index) => (
        <Fragment key={part.label}>
          {index > 0 ? " · " : null}
          <span className="watch-label">{part.label}:</span>{" "}
          {part.chokepoints.map((each, at) => (
            <Fragment key={each.id}>
              {at > 0 ? " · " : null}
              <Link href={routes.chokepoint(each.id)}>{each.constraint}</Link>
            </Fragment>
          ))}
        </Fragment>
      ))}
      {more > 0 ? <span className="watch-more"> +{more}</span> : null}
    </p>
  );
}

function Row({ row, now }: { row: WatchRow; now: Date }) {
  const latest = row.runs?.latest ?? null;
  const mode = latest ? WATCH_MODE_WORDS[latest.mode] : null;
  const parts = boardParts(row.counts);
  return (
    <li className="watch-row">
      <div className="watch-line">
        <p className="watch-theme">
          {row.unseen ? <span className="unseen-dot" aria-label="new" /> : null}
          <Link href={routes.theme(row.slug)}>{row.title}</Link>
          {latest ? (
            <span className={row.stopped ? "watch-date status-warn" : "watch-date"}>
              {" · "}
              {row.stopped ? `last watch ${plainDay(latest.run_date, now)}` : plainDay(latest.run_date, now)}
            </span>
          ) : null}
          {mode ? <span className="watch-date"> · {mode}</span> : null}
        </p>
        {parts.length > 0 ? (
          <Link className="watch-board" href={routes.board(row.slug)}>
            {parts.map((part, index) => (
              <Fragment key={part.text}>
                {index > 0 ? " · " : null}
                <span className={part.tone === "warn" ? "status-warn" : undefined}>{part.text}</span>
              </Fragment>
            ))}
          </Link>
        ) : null}
      </div>
      <Named row={row} />
      {latest ? (
        <p className="watch-memo">
          {row.excerpt ? <span className="watch-excerpt">{row.excerpt}</span> : null}
          <Link href={routes.watchRun(latest.id)}>
            Memo <span aria-hidden="true">→</span>
          </Link>
        </p>
      ) : null}
    </li>
  );
}

export function WatchSection({ rows, now = new Date() }: { rows: readonly WatchRow[]; now?: Date }) {
  if (rows.length === 0) return null;
  return (
    <section className="watch" aria-labelledby="watch">
      <h2 className="reader-label" id="watch">
        Watch
      </h2>
      <ul className="watch-rows" aria-label="Watched themes">
        {rows.map((row) => (
          <Row key={row.slug} row={row} now={now} />
        ))}
      </ul>
    </section>
  );
}
