"use client";

// The site navigation (spec §2): Today, Themes, Record, Decide with its count, and System pushed
// right. A client component because `aria-current` needs the current path. The Decide badge is
// read in the background (two list calls, cached for the tab); a failed read shows no badge and
// never an error, and the label is always there so nothing reshuffles.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { cacheCount, cachedCount, loadDecideCount } from "../lib/decide";
import { NAV_ITEMS, sectionOf } from "../lib/nav";

export function SiteNav() {
  const pathname = usePathname();
  const current = sectionOf(pathname);
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    const read = async () => {
      const cached = cachedCount();
      if (cached !== null) return cached;
      const found = await loadDecideCount();
      cacheCount(found);
      return found;
    };
    read().then(
      (found) => live && setCount(found),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);

  return (
    <nav aria-label="Site">
      <ul>
        {NAV_ITEMS.map((item) => (
          <li key={item.section} className={item.section === "system" ? "nav-system" : undefined}>
            <Link
              href={item.href}
              aria-current={item.section === current ? "page" : undefined}
              aria-describedby={item.section === "decide" && count ? "decide-count" : undefined}
            >
              {item.label}
              {item.section === "decide" && count ? (
                <span className="nav-badge" aria-hidden="true">
                  <span className="nav-dot" />
                  {count}
                </span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
      {count ? (
        <span id="decide-count" className="sr-only">
          {count} waiting on you
        </span>
      ) : null}
    </nav>
  );
}
