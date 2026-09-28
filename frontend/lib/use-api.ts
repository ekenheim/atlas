"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

/**
 * Loads `load(key)` on the client and re-loads when `key` changes. `load` must be a
 * stable (module-level) function, such as a method of `api`. A null key is an error:
 * the page was opened without the id it needs.
 */
export function useApi<T>(key: string | null, load: (key: string) => Promise<T>): Loaded<T> {
  const [result, setResult] = useState<{ key: string; loaded: Loaded<T> } | null>(null);
  useEffect(() => {
    if (key === null) return;
    let current = true;
    load(key).then(
      (data) => current && setResult({ key, loaded: { state: "ready", data } }),
      (error: unknown) =>
        current &&
        setResult({
          key,
          loaded: { state: "error", message: error instanceof Error ? error.message : String(error) },
        }),
    );
    return () => {
      current = false;
    };
  }, [key, load]);
  if (key === null) return { state: "error", message: "No id given: open this page from a link." };
  return result?.key === key ? result.loaded : { state: "loading" };
}

/** The `?id=` of the current page: static export has no dynamic routes. */
export function useIdParam(): string | null {
  return useSearchParams().get("id");
}
