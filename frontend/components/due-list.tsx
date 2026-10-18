// What falls due next, soonest first (spec §3.5): calls grouped by the day of their next
// checkpoint, predictions by deadline, and reporting dates when the calendar gave any. Each row
// reads "18 Nov · in 31 d · first checkpoint · 22 calls" and is a row-link where it has a page.
import Link from "next/link";
import type { ReactNode } from "react";

import type { Call, Lead, Prediction } from "../lib/api/client";
import { dueRows } from "../lib/due";
import { dueState } from "../lib/format";

export function DueList({
  calls,
  predictions,
  leads,
  theme,
  limit = 4,
  label = "Due",
  empty = "Nothing falls due yet.",
  now = new Date(),
}: {
  calls?: readonly Call[];
  predictions?: readonly Prediction[];
  leads?: readonly Lead[];
  theme?: string | null;
  /** At most this many rows; 0 for all. */
  limit?: number;
  label?: string;
  empty?: ReactNode;
  now?: Date;
}) {
  const rows = dueRows({ calls, predictions, leads, theme, today: now.toISOString().slice(0, 10) });
  const shown = limit > 0 ? rows.slice(0, limit) : rows;
  if (shown.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="due-list" aria-label={label}>
      {shown.map((row) => {
        const state = dueState(row.date, now);
        const text = (
          <>
            <span className={state.overdue ? "due-when due-overdue" : "due-when"}>{state.text}</span>
            {" · "}
            <span title={row.title}>{row.label}</span>
          </>
        );
        return (
          <li className="reader-row due-row" key={row.key}>
            <div className="row-title">
              {row.href ? <Link href={row.href}>{text}</Link> : <span>{text}</span>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
