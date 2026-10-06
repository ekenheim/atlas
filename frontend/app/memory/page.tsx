"use client";

import Link from "next/link";
import { Fragment, useState } from "react";

import { VersionBar, VersionLegend } from "../../components/version-bar";
import { api, type MemoryHealth } from "../../lib/api/client";
import {
  companyRows,
  figures,
  formatAge,
  formatCount,
  openItems,
  sortRows,
} from "../../lib/memory";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

const COLUMNS = 7;

const loadHealth = () => api.memoryHealth();

export default function MemoryPage() {
  const loaded = useApi("memory-health", loadHealth);
  return (
    <>
      <h1>Memory</h1>
      {loaded.state === "error" ? (
        <p role="alert">Memory health did not load: {loaded.message}</p>
      ) : loaded.state === "loading" ? (
        <Skeleton />
      ) : (
        <Health health={loaded.data} />
      )}
    </>
  );
}

/** The final layout in muted placeholders: the call takes about 0.65 s. */
function Skeleton() {
  return (
    <div aria-busy="true" aria-label="Loading memory health">
      <div className="mem-figures">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="mem-figure">
            <span className="ph ph-label" />
            <span className="ph ph-value" />
            <span className="ph ph-sub" />
          </div>
        ))}
      </div>
      <div className="mem-scroll">
        <table>
          <tbody>
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <tr key={i}>
                {Array.from({ length: COLUMNS }, (_, c) => (
                  <td key={c}>
                    <span className="ph ph-cell" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Health({ health }: { health: MemoryHealth }) {
  // Read once when the data arrives, so ages do not shift under a re-render.
  const [now] = useState(() => Date.now());
  const [order, setOrder] = useState<"status" | "facts">("status");
  const [expanded, setExpanded] = useState<string | null>(null);
  const fig = figures(health, now);
  const items = openItems(health, now);
  const rows = sortRows(companyRows(health), order);
  const maxFacts = Math.max(1, ...rows.map((r) => r.sections.fact_count));
  const tone = (severity: string) => (severity === "ok" ? "" : severity);

  return (
    <>
      <div className="mem-figures">
        <Figure
          label="Open"
          value={String(fig.open.count)}
          tone={fig.open.gaps ? "gap" : fig.open.count ? "warn" : ""}
          sub={`${fig.open.gaps} ${fig.open.gaps === 1 ? "gap" : "gaps"}`}
        />
        <Figure
          label="Versions in memory"
          value={fig.inMemory.percent === null ? "–" : `${fig.inMemory.percent}%`}
          sub={`${formatCount(fig.inMemory.inMemory)} of ${formatCount(fig.inMemory.inWindow)} in window`}
        />
        <Figure
          label="Facts"
          value={formatCount(fig.facts.facts)}
          sub={
            fig.facts.observations === null
              ? "observations unavailable"
              : `${formatCount(fig.facts.observations)} observations`
          }
        />
        <Figure
          label="Consolidation"
          value={fig.consolidation.running ? (fig.consolidation.age ?? "") : "idle"}
          tone={tone(fig.consolidation.severity)}
          sub={fig.consolidation.rounds === null ? "" : `${fig.consolidation.rounds} rounds`}
        />
        <Figure
          label="Reconciliation"
          value={fig.reconciliation.status}
          tone={tone(fig.reconciliation.severity)}
          sub={fig.reconciliation.age ? `${fig.reconciliation.age} ago` : ""}
        />
      </div>

      {items.length > 0 && (
        <section aria-labelledby="mem-open">
          <h2 id="mem-open">Open</h2>
          <ul className="mem-open">
            {items.map((item) => (
              <li key={`${item.what}:${item.status}`}>
                <span className={`mem-dot ${item.severity}`} aria-hidden="true" />
                <span className="mem-what">
                  {item.href ? <Link href={item.href}>{item.what}</Link> : item.what}
                </span>
                <span className={`mem-tag ${item.severity}`}>{item.status}</span>
                {item.detail && <span className="mem-detail">{item.detail}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mem-head">
        <h2>Companies</h2>
        <div className="mem-sort" role="group" aria-label="Sort companies">
          <button type="button" aria-pressed={order === "status"} onClick={() => setOrder("status")}>
            Status
          </button>
          <button type="button" aria-pressed={order === "facts"} onClick={() => setOrder("facts")}>
            Facts
          </button>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="muted">No companies.</p>
      ) : (
        <div className="mem-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Versions</th>
                <th scope="col" className="num">
                  In memory
                </th>
                <th scope="col">Facts</th>
                <th scope="col" className="num">
                  Retired
                </th>
                <th scope="col" className="num">
                  Skipped
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const open = expanded === r.key;
                const detailId = `mem-detail-${r.key}`;
                return (
                  <Fragment key={r.key}>
                    <tr className="mem-row" onClick={() => setExpanded(open ? null : r.key)}>
                      <th scope="row">
                        <button
                          type="button"
                          className="mem-toggle"
                          aria-expanded={open}
                          aria-controls={open ? detailId : undefined}
                          aria-label={`Details for ${r.name}`}
                        >
                          <span aria-hidden="true">{open ? "▾" : "▸"}</span>
                        </button>
                        {r.href ? (
                          <Link href={routes.company(r.key)} onClick={(e) => e.stopPropagation()}>
                            {r.name}
                          </Link>
                        ) : (
                          r.name
                        )}
                      </th>
                      <td>
                        <VersionBar counts={r.versions} />
                      </td>
                      <td className="num">
                        {formatCount(r.versions.in_memory)}
                        <span className="mem-of"> / {formatCount(r.versions.total)}</span>
                      </td>
                      <td>
                        <span className="mem-depth">
                          <span style={{ width: `${(100 * r.sections.fact_count) / maxFacts}%` }} />
                          <span className="num">{formatCount(r.sections.fact_count)}</span>
                        </span>
                      </td>
                      <td className="num">{r.versions.retired ? formatCount(r.versions.retired) : "–"}</td>
                      <td className="num">{r.versions.all_skipped ? formatCount(r.versions.all_skipped) : "–"}</td>
                      <td>
                        <span className={`mem-tag ${r.status.severity}`}>{r.status.label}</span>
                      </td>
                    </tr>
                    {open && (
                      <tr className="mem-expand" id={detailId}>
                        <td colSpan={COLUMNS}>
                          Sections {formatCount(r.sections.total)} · zero-fact{" "}
                          {formatCount(r.sections.zero_fact)} · below profile{" "}
                          {formatCount(r.sections.below_profile)} · stuck {formatCount(r.sections.stuck)} ·
                          facts per version{" "}
                          {r.versions.in_memory
                            ? formatCount(Math.round(r.sections.fact_count / r.versions.in_memory))
                            : "–"}{" "}
                          · entities {r.entityCount === null ? "unavailable" : formatCount(r.entityCount)}
                          {r.href && (
                            <>
                              {" · "}
                              <Link href={routes.company(r.key)}>Dossier</Link>
                            </>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <VersionLegend />
      <p className="mem-foot">
        {fig.complete.complete} of {fig.complete.total} companies complete
        {health.generated_at ? ` · checked ${formatAge(health.generated_at, now)} ago` : ""}
      </p>
    </>
  );
}

function Figure({ label, value, sub, tone = "" }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="mem-figure">
      <div className="mem-label">{label}</div>
      <div className={`mem-value ${tone}`}>{value}</div>
      <div className="mem-sub">{sub || " "}</div>
    </div>
  );
}
