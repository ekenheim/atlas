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
  const shown = segments.filter((s) => s.count > 0);
  const label = shown.length
    ? shown.map((s) => `${VERSION_STATE_NAMES[s.state]} ${formatCount(s.count)}`).join(", ")
    : "No versions";
  // No versions at all is a gap of its own, unless the bar is drawn to someone else's scale.
  if (!shown.length && scale === undefined) return <span className="vbar vbar-none" role="img" aria-label={label} />;
  const rest = 1 - segments.reduce((n, s) => n + s.share, 0);
  // Flex, not width, so a rare segment keeps its minimum and the larger ones give way.
  return (
    <span className="vbar" role="img" aria-label={label}>
      {shown.map((s) => (
        <span key={s.state} className={`vseg-${s.state}`} style={{ flex: `${s.share} 0 0` }} />
      ))}
      {scale !== undefined && rest > 0 && <span style={{ flex: `${rest} 0 0` }} />}
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
