// The Memory page's figures, generalised: three to five cells, each a label, a value at 1.5rem
// and a sub-line. Used on Record, Decide and System.
import type { ReactNode } from "react";

import type { Tone } from "../lib/status";

export interface Stat {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
}

export function StatStrip({ stats, label }: { stats: readonly Stat[]; label?: string }) {
  return (
    <dl className="stat-strip" aria-label={label}>
      {stats.map((stat) => (
        <div className="stat" key={stat.label}>
          <dt className="stat-label">{stat.label}</dt>
          <dd className={`stat-value${stat.tone && stat.tone !== "muted" ? ` stat-${stat.tone}` : ""}`}>
            {stat.value}
          </dd>
          {stat.sub ? <dd className="stat-sub">{stat.sub}</dd> : null}
        </div>
      ))}
    </dl>
  );
}
