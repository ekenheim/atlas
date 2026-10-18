"use client";

import { useEffect, useState } from "react";

import { getDecideCount } from "./decide";

/** What waits on the owner, for the nav's badge and Today's banner; null until it is known, and
 * for good when the read fails (no badge, never an error). */
export function useDecideCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    getDecideCount().then(
      (found) => live && setCount(found),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  return count;
}
