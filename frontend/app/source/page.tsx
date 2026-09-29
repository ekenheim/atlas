"use client";

import Link from "next/link";
import { Suspense } from "react";

import { SourceDocumentRows } from "../../components/source-document";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
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
        {(sourceDocument) => (
          <>
            <p className="crumbs">
              <Link href={routes.companies}>Companies</Link>
              {sourceDocument.company_id && (
                <>
                  {" / "}
                  <Link href={routes.company(sourceDocument.company_id)}>Company</Link>
                </>
              )}
            </p>
            <h1>{sourceDocument.title}</h1>
            <table>
              <caption>Source Document</caption>
              <tbody>
                <Row name="URL">
                  <Code>{sourceDocument.canonical_url}</Code>
                </Row>
                <SourceDocumentRows sourceDocument={sourceDocument} />
                <Row name="first_seen_at">
                  <Timestamp value={sourceDocument.first_seen_at} />
                </Row>
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
