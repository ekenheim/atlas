// The version-state bar and its legend: one shape for "where a company's Source Versions
// are", shared by the Memory page, the dossier and the landing page.
import type { VersionCounts } from "../lib/api/client";
import {
  VERSION_STATES,
  VERSION_STATE_NAMES,
  formatCount,
  versionSegments,
} from "../lib/memory";

/** The stacked bar for one company's versions; `scale` draws several bars to one scale. */
export function VersionBar({
  counts,
  scale,
}: {
  counts: Partial<VersionCounts> | null | undefined;
  scale?: number;
}) {
  const segments = versionSegments(counts, scale);
  const label = segments.map((s) => `${VERSION_STATE_NAMES[s.state]} ${formatCount(s.count)}`).join(", ");
  return (
    <span className="vbar" role="img" aria-label={label}>
      {segments.map((s) =>
        s.count > 0 ? (
          <span key={s.state} className={`vseg-${s.state}`} style={{ width: `${100 * s.share}%` }} />
        ) : null,
      )}
    </span>
  );
}

/** What each segment colour means. */
export function VersionLegend() {
  return (
    <ul className="vlegend" aria-label="Version states">
      {VERSION_STATES.map((state) => (
        <li key={state}>
          <span className={`vswatch vseg-${state}`} aria-hidden="true" />
          {VERSION_STATE_NAMES[state]}
        </li>
      ))}
    </ul>
  );
}
