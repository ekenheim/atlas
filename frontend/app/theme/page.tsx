"use client";

import Link from "next/link";
import { Suspense } from "react";

import { EdgeList } from "../../components/edge-list";
import { Code, Load, Missing, Timestamp } from "../../components/ui";
import {
  api,
  type Bottlenecks,
  type Candidate,
  type ThemeCompany,
} from "../../lib/api/client";
import { LAYERS } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function ThemePage() {
  return (
    <Suspense>
      <Theme />
    </Suspense>
  );
}

const GAPS: Record<ThemeCompany["gaps"][number], string> = {
  not_seeded: "not seeded",
  no_sources: "no sources",
};

function Theme() {
  const id = useIdParam();
  const map = useApi(id, api.themeMap);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.themes}>Themes</Link>
      </p>
      <Load loaded={map} what="the theme">
        {(map) => (
          <>
            <h1>{map.theme.title}</h1>
            {map.theme.description && <p>{map.theme.description}</p>}
            <p>
              {map.theme.company_count} companies, {map.theme.companies_without_sources} without
              sources; {map.theme.relationship_count} Relationships between them;{" "}
              {map.theme.open_candidate_count} Candidates awaiting a decision. Universe config
              version {map.theme.universe_version}.
            </p>

            <h2>Companies by layer</h2>
            <p>Upstream to downstream. A layer with no company is a coverage gap.</p>
            {map.layers.map((layer) => (
              <section key={layer.layer} aria-labelledby={`layer-${layer.layer}`}>
                <h3 id={`layer-${layer.layer}`}>{LAYERS[layer.layer]}</h3>
                <p className="muted-small">{layer.covers}</p>
                {layer.companies.length === 0 ? (
                  <p>
                    <strong>Coverage gap:</strong> no company in this layer.
                  </p>
                ) : (
                  <Companies caption={`${LAYERS[layer.layer]} companies`} companies={layer.companies} />
                )}
              </section>
            ))}
            {map.unlayered.length > 0 && (
              <section aria-labelledby="layer-none">
                <h3 id="layer-none">No layer set</h3>
                <Companies caption="Companies with no layer" companies={map.unlayered} />
              </section>
            )}

            <h2>Relationships</h2>
            <p>
              Edges between the theme&apos;s companies, to a product, or to a counterparty, by
              layer. Edges to researched companies outside the theme are on each company&apos;s
              dossier; every edge is in the <Link href={routes.relationships()}>edge table</Link>.
            </p>
            {map.counterparties.length > 0 && (
              <p>
                Counterparties (known only as the other end of an edge, not researched):{" "}
                {map.counterparties.map((company, index) => (
                  <span key={company.id}>
                    {index > 0 && ", "}
                    <Link href={routes.company(company.id)}>{company.display_name}</Link>
                  </span>
                ))}
              </p>
            )}
            {map.relationships.length === 0 ? (
              <p>No Relationships between the theme&apos;s companies yet.</p>
            ) : (
              <EdgeList edges={map.relationships} caption="Relationships between the theme's companies" />
            )}

            <h2>Candidates</h2>
            {map.candidates.length === 0 ? (
              <p>No Candidates proposed for this theme.</p>
            ) : (
              <Candidates candidates={map.candidates} />
            )}

            <h2>Open gaps (Bottlenecks)</h2>
            <OpenGaps bottlenecks={map.bottlenecks} />
          </>
        )}
      </Load>
    </>
  );
}

function Companies({ caption, companies }: { caption: string; companies: ThemeCompany[] }) {
  return (
    <table>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Company</th>
          <th scope="col">Country</th>
          <th scope="col">Source path</th>
          <th scope="col">Sources</th>
          <th scope="col">Relationships</th>
          <th scope="col">Identity reviews</th>
          <th scope="col">Coverage gaps</th>
        </tr>
      </thead>
      <tbody>
        {companies.map((company) => (
          <tr key={company.id}>
            <th scope="row">
              {company.seeded ? (
                <Link href={routes.company(company.id)}>{company.display_name}</Link>
              ) : (
                company.display_name
              )}
            </th>
            <td>{company.country}</td>
            <td>
              <Code>{company.source_path}</Code>
            </td>
            <td>{company.source_count}</td>
            <td>{company.relationship_count}</td>
            <td>
              {company.pending_identity_reviews > 0 ? (
                `${company.pending_identity_reviews} pending`
              ) : (
                <Missing />
              )}
            </td>
            <td>
              {company.gaps.length === 0 ? (
                <Missing />
              ) : (
                company.gaps.map((gap) => GAPS[gap]).join(", ")
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Candidates({ candidates }: { candidates: Candidate[] }) {
  return (
    <table>
      <caption>Candidates (companies outside the universe that leads named)</caption>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">State</th>
          <th scope="col">Resolution tier</th>
          <th scope="col">Identifier</th>
          <th scope="col">Leads</th>
          <th scope="col">Proposed</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((candidate) => (
          <tr key={candidate.id}>
            <th scope="row">{candidate.name}</th>
            <td>
              {candidate.state}
              {candidate.reject_reason && (
                <>
                  <br />
                  <span className="muted-small">{candidate.reject_reason}</span>
                </>
              )}
            </td>
            <td>{candidate.tier}</td>
            <td>
              <Code>{candidate.identity_key}</Code>
            </td>
            <td>{candidate.leads.length}</td>
            <td>
              <Timestamp value={candidate.created_at} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OpenGaps({ bottlenecks }: { bottlenecks: Bottlenecks }) {
  const model = bottlenecks.model;
  if (bottlenecks.status !== "refreshed" || !model) {
    const why = {
      refreshed: "",
      not_refreshed: "Hindsight has not generated the Bottlenecks mental model yet.",
      not_in_bank: "The bank template (with the Bottlenecks mental model) is not applied yet.",
      not_configured: "Hindsight is not configured, so there is no Bottlenecks mental model.",
      unavailable: `Hindsight could not be read: ${bottlenecks.message ?? "unknown error"}.`,
    }[bottlenecks.status];
    return <p>{why}</p>;
  }
  const counts = model.counts;
  return (
    <>
      <p>
        <strong>Generated by Hindsight: Memory, not Evidence.</strong> Refreshed{" "}
        <Timestamp value={model.last_refreshed_at} />. Citations: {counts.resolved ?? 0} resolved,{" "}
        {counts.unverified ?? 0} unverified, {counts.broken ?? 0} broken.
        {model.evidence_missing && <strong> Unsupported: no citation resolves to a source.</strong>}
      </p>
      <blockquote className="quote">{model.content}</blockquote>
      {model.evidence.length > 0 && (
        <>
          <h3>Sources behind resolved citations</h3>
          <ul>
            {model.evidence.map((evidence) => (
              <li key={`${evidence.source_version_id}-${evidence.section_anchor}`}>
                <Link href={routes.version(evidence.source_version_id)}>
                  {evidence.form_type ?? "Source Version"}:{" "}
                  {evidence.section_heading ?? evidence.section_anchor}
                </Link>{" "}
                <span className="muted-small">
                  available <Timestamp value={evidence.available_at} />
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
