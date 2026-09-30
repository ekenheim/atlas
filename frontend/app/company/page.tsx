"use client";

import Link from "next/link";
import { Suspense } from "react";

import { EdgeList } from "../../components/edge-list";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import { api, type CompanyDossier, type FinancialFigure } from "../../lib/api/client";
import { groupDigits, period } from "../../lib/format";
import { LAYERS } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function CompanyPage() {
  return (
    <Suspense>
      <Company />
    </Suspense>
  );
}

function Company() {
  const id = useIdParam();
  const dossier = useApi(id, api.dossier);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.companies}>Companies</Link>
        <span aria-hidden="true"> · </span>
        <Link href={routes.themes}>Themes</Link>
      </p>
      <Load loaded={dossier} what="the company dossier">
        {(dossier) => <Dossier dossier={dossier} />}
      </Load>
    </>
  );
}

function Dossier({ dossier }: { dossier: CompanyDossier }) {
  const { company } = dossier;
  return (
    <>
      <h1>{company.display_name}</h1>

      <h2>Identity</h2>
      <table>
        <caption>Identity</caption>
        <tbody>
          <Row name="Legal name">{company.legal_name}</Row>
          <Row name="Role">
            {company.role === "counterparty"
              ? "Counterparty: known only as the other end of Relationships, not researched"
              : "Researched"}
          </Row>
          <Row name="CIK">{company.cik ? <Code>{company.cik}</Code> : <Missing />}</Row>
          <Row name="LEI">{company.lei ? <Code>{company.lei}</Code> : <Missing />}</Row>
          <Row name="Country">{company.country ?? <Missing />}</Row>
          <Row name="Website">
            {company.website ? (
              <a href={company.website} rel="noreferrer noopener">
                {company.website}
              </a>
            ) : (
              <Missing />
            )}
          </Row>
          <Row name="Layer">{company.layer ? LAYERS[company.layer] : <Missing />}</Row>
          <Row name="Source path">
            {company.source_path ? <Code>{company.source_path}</Code> : <Missing />}
          </Row>
          <Row name="Themes">
            {dossier.themes.length === 0 ? (
              <Missing />
            ) : (
              dossier.themes.map((theme, index) => (
                <span key={theme.id}>
                  {index > 0 && ", "}
                  <Link href={routes.theme(theme.id)}>{theme.title}</Link>
                </span>
              ))
            )}
          </Row>
        </tbody>
      </table>

      <h2>Listings</h2>
      {company.securities.length === 0 ? (
        <p>No listings recorded.</p>
      ) : (
        <table>
          <caption>Listings (securities)</caption>
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Exchange (MIC)</th>
              <th scope="col">Instrument</th>
              <th scope="col">Currency</th>
              <th scope="col">ISIN</th>
              <th scope="col">FIGI</th>
              <th scope="col">Review state</th>
              <th scope="col">Valid</th>
            </tr>
          </thead>
          <tbody>
            {company.securities.map((security) => (
              <tr key={security.id}>
                <th scope="row">{security.ticker}</th>
                <td>
                  <Code>{security.exchange_mic}</Code>
                  {security.segment_mic && (
                    <>
                      {" "}
                      (segment <Code>{security.segment_mic}</Code>)
                    </>
                  )}
                </td>
                <td>{security.instrument_type}</td>
                <td>{security.currency}</td>
                <td>{security.isin ? <Code>{security.isin}</Code> : <Missing />}</td>
                <td>{security.figi ? <Code>{security.figi}</Code> : <Missing />}</td>
                <td>{security.review_state}</td>
                <td>
                  from {security.valid_from}
                  {security.valid_to && <> to {security.valid_to}</>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Pending identity reviews</h2>
      {dossier.pending_identity_reviews.length === 0 ? (
        <p>No identity mapping awaits review.</p>
      ) : (
        <table>
          <caption>Identity mappings awaiting the owner</caption>
          <thead>
            <tr>
              <th scope="col">Kind</th>
              <th scope="col">Value</th>
              <th scope="col">Tier</th>
              <th scope="col">Source</th>
              <th scope="col">Observed</th>
              <th scope="col">Reasons</th>
            </tr>
          </thead>
          <tbody>
            {dossier.pending_identity_reviews.map((mapping) => (
              <tr key={mapping.id}>
                <th scope="row">{mapping.kind}</th>
                <td>
                  <Code>{mapping.value}</Code>
                </td>
                <td>{mapping.tier}</td>
                <td>
                  <a href={mapping.source_url} rel="noreferrer noopener">
                    {mapping.source}
                  </a>
                </td>
                <td>
                  <Timestamp value={mapping.observed_at} />
                </td>
                <td>{mapping.reasons.length === 0 ? <Missing /> : mapping.reasons.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Relationships</h2>
      {dossier.relationships_out.length === 0 ? (
        <p>No Relationships with {company.display_name} as subject.</p>
      ) : (
        <EdgeList
          edges={dossier.relationships_out}
          caption={`Relationships out (${company.display_name} as subject)`}
        />
      )}
      {dossier.relationships_in.length === 0 ? (
        <p>No Relationships with {company.display_name} as object.</p>
      ) : (
        <EdgeList
          edges={dossier.relationships_in}
          caption={`Relationships in (${company.display_name} as object)`}
        />
      )}

      <h2>Financials</h2>
      <Financials figures={dossier.financials.figures} asOf={dossier.financials.as_of} />

      <h2>Source Documents</h2>
      {dossier.sources.length === 0 ? (
        <p>No Source Documents collected yet.</p>
      ) : (
        <table>
          <caption>
            Source Documents ({dossier.source_total}
            {dossier.source_total > dossier.sources.length &&
              `, showing the first ${dossier.sources.length}`}
            )
          </caption>
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Form</th>
              <th scope="col">Accession</th>
              <th scope="col">Source type</th>
              <th scope="col">First seen</th>
              <th scope="col">Versions</th>
            </tr>
          </thead>
          <tbody>
            {dossier.sources.map((sourceDocument) => (
              <tr key={sourceDocument.id}>
                <td>
                  <Link href={routes.source(sourceDocument.id)}>{sourceDocument.title}</Link>
                </td>
                <td>{sourceDocument.form_type ?? <Missing />}</td>
                <td>
                  {sourceDocument.accession ? (
                    <Code>{sourceDocument.accession}</Code>
                  ) : (
                    <Missing />
                  )}
                </td>
                <td>{sourceDocument.source_type}</td>
                <td>
                  <Timestamp value={sourceDocument.first_seen_at} />
                </td>
                <td>{sourceDocument.version_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Fetch-gate blocks</h2>
      {dossier.fetch_gate_blocks.length === 0 ? (
        <p>No request for this company was blocked by the fetch gate.</p>
      ) : (
        <table>
          <caption>Requests the fetch gate blocked ({dossier.fetch_gate_block_total})</caption>
          <thead>
            <tr>
              <th scope="col">Decided</th>
              <th scope="col">Provider</th>
              <th scope="col">URL</th>
              <th scope="col">Blocked by</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {dossier.fetch_gate_blocks.map((block) => (
              <tr key={block.id}>
                <td>
                  <Timestamp value={block.decided_at} />
                </td>
                <td>{block.provider}</td>
                <td>
                  <Code>{block.url}</Code>
                </td>
                <td>{block.blocked_by}</td>
                <td>{block.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/** Each figure with its period, unit and currency, FX basis, availability and filings. */
function Financials({ figures, asOf }: { figures: FinancialFigure[]; asOf: string }) {
  if (figures.length === 0) {
    return (
      <p>
        No financial figures available as of <Timestamp value={asOf} />.
      </p>
    );
  }
  return (
    <table>
      <caption>
        Financials as of <Timestamp value={asOf} /> (XBRL, each value from the latest filing
        available then)
      </caption>
      <thead>
        <tr>
          <th scope="col">Metric</th>
          <th scope="col">Period</th>
          <th scope="col">Value</th>
          <th scope="col">Unit</th>
          <th scope="col">FX basis</th>
          <th scope="col">Available at</th>
          <th scope="col">Source</th>
          <th scope="col">Flags</th>
        </tr>
      </thead>
      <tbody>
        {figures.map((figure) => (
          <tr
            key={`${figure.metric}-${figure.unit}-${figure.period_start ?? ""}-${figure.period_end}`}
          >
            <th scope="row">{figure.label}</th>
            <td>
              {period(figure.period_start, figure.period_end)}
              <br />
              <span className="muted-small">{figure.period_type.replace("_", " ")}</span>
            </td>
            <td>{groupDigits(figure.value)}</td>
            <td>{figure.unit}</td>
            <td>
              {figure.fx_basis ? (
                `${figure.fx_basis.from_currency} at ${figure.fx_basis.rate_date} (${figure.fx_basis.rate_source})`
              ) : (
                <Missing>as filed</Missing>
              )}
            </td>
            <td>
              <Timestamp value={figure.available_at} />
            </td>
            <td>
              {figure.derived && <>derived from </>}
              {figure.sources.map((source, index) => (
                <span key={source.id}>
                  {index > 0 && " and "}
                  {source.form} <Code>{source.accession}</Code> (<Code>{source.concept}</Code>)
                </span>
              ))}
            </td>
            <td>{figure.flags.length === 0 ? <Missing /> : figure.flags.join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
