import type { ReactNode } from "react";

import { activity, due, evidenceDay, exactTime } from "../lib/format";
import type { Loaded } from "../lib/use-api";

/** Renders a load's loading and error states, and `children(data)` once it is ready. */
export function Load<T>({
  loaded,
  what,
  children,
}: {
  loaded: Loaded<T>;
  what: string;
  children: (data: T) => ReactNode;
}) {
  if (loaded.state === "loading") {
    return (
      <p role="status" aria-live="polite">
        Loading {what}…
      </p>
    );
  }
  if (loaded.state === "error") {
    return (
      <p role="alert">
        Could not load {what}: {loaded.message}
      </p>
    );
  }
  return <>{children(loaded.data)}</>;
}

export type TimestampMode = "activity" | "evidence" | "due" | "exact";

/**
 * A date or time in the mode it is read in: `evidence` (the default) is the absolute day with
 * its year, `activity` is relative within a week, `due` says how far off a date is, and `exact`
 * is the ISO time to the minute, for the Records only. Absent ones say so.
 */
export function Timestamp({
  value,
  mode = "evidence",
}: {
  value: string | null | undefined;
  mode?: TimestampMode;
}) {
  if (!value) return <span className="muted">not recorded</span>;
  const text =
    mode === "activity"
      ? activity(value)
      : mode === "due"
        ? due(value)
        : mode === "exact"
          ? exactTime(value)
          : evidenceDay(value);
  return <time dateTime={value}>{text}</time>;
}

/** A hash or other identifier, set in monospace so it can be compared by eye. */
export function Code({ children }: { children: ReactNode }) {
  return <code className="ident">{children}</code>;
}

export function Missing({ children = "none" }: { children?: ReactNode }) {
  return <span className="muted">{children}</span>;
}

/** A table row: a header cell naming the value, then the value. */
export function Row({ name, children }: { name: string; children: ReactNode }) {
  return (
    <tr>
      <th scope="row">{name}</th>
      <td>{children}</td>
    </tr>
  );
}
