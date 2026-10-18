"use client";

// The one place raw records live (spec §1.3, item 4). A closed `<details>` whose children are
// not rendered until it is first opened, and stay mounted afterwards. It never opens on its own;
// only a `#records` hash (a deep link from System or a quiet "3 drafts") may open it. Closed, it
// costs the page nothing: the record tables behind it make no request and add no rows.
import { type ReactNode, useEffect, useRef, useState } from "react";

export function RecordsFold({
  counts,
  children,
}: {
  /** "457 relationships, 104 candidates", when the counts are known. */
  counts?: string | null;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    const openFromHash = () => {
      if (window.location.hash === "#records" && ref.current) ref.current.open = true;
    };
    openFromHash();
    window.addEventListener("hashchange", openFromHash);
    return () => window.removeEventListener("hashchange", openFromHash);
  }, []);

  return (
    <details
      id="records"
      className="reader-records"
      ref={ref}
      onToggle={(event) => {
        if (event.currentTarget.open) setOpened(true);
      }}
    >
      <summary>{counts ? `Records · ${counts}` : "Records"}</summary>
      {opened ? <div className="records-body">{children}</div> : null}
    </details>
  );
}
