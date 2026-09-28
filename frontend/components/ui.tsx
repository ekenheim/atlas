import type { ReactNode } from "react";

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

/** A timestamp exactly as the API recorded it (ISO 8601, UTC); absent ones say so. */
export function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">not recorded</span>;
  return <time dateTime={value}>{value}</time>;
}

/** A hash or other identifier, set in monospace so it can be compared by eye. */
export function Code({ children }: { children: ReactNode }) {
  return <code className="ident">{children}</code>;
}

export function Missing({ children = "none" }: { children?: ReactNode }) {
  return <span className="muted">{children}</span>;
}
