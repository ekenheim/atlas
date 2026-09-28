"use client";

import Link from "next/link";
import { Suspense } from "react";

import { Code, Load, Missing, Timestamp } from "../../components/ui";
import { api } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function SourcePage() {
  return (
    <Suspense>
      <SourceDocument />
    </Suspense>
  );
}

function SourceDocument() {
  const id = useIdParam();
  const source = useApi(id, api.source);
  const versions = useApi(id, api.sourceVersions);
  return (
    <>
      <Load loaded={source} what="the Source Document">
        {(document) => (
          <>
            <p className="crumbs">
              <Link href={routes.companies}>Companies</Link>
              {document.company_id && (
                <>
                  {" / "}
                  <Link href={routes.company(document.company_id)}>Company</Link>
                </>
              )}
            </p>
            <h1>{document.title}</h1>
            <table>
              <caption>Source Document</caption>
              <tbody>
                <tr>
                  <th scope="row">URL</th>
                  <td>
                    <Code>{document.canonical_url}</Code>
                  </td>
                </tr>
                <tr>
                  <th scope="row">Accession</th>
                  <td>{document.accession ? <Code>{document.accession}</Code> : <Missing />}</td>
                </tr>
                <tr>
                  <th scope="row">Form</th>
                  <td>
                    {document.form_type ?? <Missing />}
                    {document.document_type &&
                      document.document_type !== document.form_type &&
                      ` (${document.document_type})`}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Publisher</th>
                  <td>
                    {document.publisher} via {document.provider}; tier {document.source_tier},
                    licence {document.license_class}
                  </td>
                </tr>
                <tr>
                  <th scope="row">first_seen_at</th>
                  <td>
                    <Timestamp value={document.first_seen_at} />
                  </td>
                </tr>
              </tbody>
            </table>
          </>
        )}
      </Load>
      <h2>Version history</h2>
      <Load loaded={versions} what="the version history">
        {(page) => (
          <table>
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">available_at (basis)</th>
                <th scope="col">fetched_at</th>
                <th scope="col">Raw SHA-256</th>
                <th scope="col">Parse</th>
                <th scope="col">Supersedes</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((version) => (
                <tr key={version.id}>
                  <td>
                    <Link href={routes.version(version.id)}>Version {version.version_number}</Link>
                  </td>
                  <td>
                    <Timestamp value={version.available_at} /> ({version.available_at_basis})
                  </td>
                  <td>
                    <Timestamp value={version.fetched_at} />
                  </td>
                  <td>
                    <Code>{version.raw_sha256}</Code>
                  </td>
                  <td>
                    {version.parse_status}
                    {version.parser_version && ` (${version.parser_version})`}
                  </td>
                  <td>
                    {version.supersedes_version_id ? (
                      <Link href={routes.version(version.supersedes_version_id)}>
                        Version {version.version_number - 1}
                      </Link>
                    ) : (
                      <Missing />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Load>
    </>
  );
}
