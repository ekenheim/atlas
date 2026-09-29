"use client";

import Link from "next/link";
import { Suspense, useState, type ReactNode } from "react";

import { VersionAssertions } from "../../components/assertions";
import { SourceDocumentRows } from "../../components/source-document";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import { api, type SourceVersionDetail } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function VersionPage() {
  return (
    <Suspense>
      <SourceVersion />
    </Suspense>
  );
}

function SourceVersion() {
  const id = useIdParam();
  const version = useApi(id, api.sourceVersion);
  return (
    <Load loaded={version} what="the Source Version">
      {(version) => (
        <>
          <p className="crumbs">
            <Link href={routes.companies}>Companies</Link>
            {version.source_document.company_id && (
              <>
                {" / "}
                <Link href={routes.company(version.source_document.company_id)}>Company</Link>
              </>
            )}
            {" / "}
            <Link href={routes.source(version.source_document_id)}>Source Document</Link>
          </p>
          <h1>
            {version.source_document.title}, version {version.version_number}
          </h1>
          <Provenance version={version} />
          <Fetches version={version} />
          <Content version={version} />
        </>
      )}
    </Load>
  );
}

function VersionLink({ id, label }: { id: string | null; label: string }) {
  return id ? <Link href={routes.version(id)}>{label}</Link> : <Missing />;
}

function Provenance({ version }: { version: SourceVersionDetail }) {
  const sourceDocument = version.source_document;
  return (
    <section aria-labelledby="provenance">
      <h2 id="provenance">Provenance</h2>
      <table>
        <caption>Source and content</caption>
        <tbody>
          <Row name="URL">
            <Code>{sourceDocument.canonical_url}</Code>
          </Row>
          {sourceDocument.origin_url !== sourceDocument.canonical_url && (
            <Row name="Origin URL">
              <Code>{sourceDocument.origin_url}</Code>
            </Row>
          )}
          <SourceDocumentRows sourceDocument={sourceDocument} />
          <Row name="Raw SHA-256">
            <Code>{version.raw_sha256}</Code>
          </Row>
          <Row name="Content SHA-256">
            {version.content_sha256 ? <Code>{version.content_sha256}</Code> : <Missing />}
          </Row>
          <Row name="Comparison SHA-256">
            <Code>{version.comparison_sha256}</Code> (rule <Code>{version.comparison_rule}</Code>)
          </Row>
          <Row name="Bytes">
            {version.byte_size.toLocaleString("en-US")} bytes, <Code>{version.media_type}</Code>
          </Row>
          <Row name="Archive object">
            <Code>{version.object_uri}</Code>
          </Row>
          <Row name="Parsed object">
            {version.parsed_object_uri ? <Code>{version.parsed_object_uri}</Code> : <Missing />}
          </Row>
          <Row name="Parser version">
            {version.parser_version ? <Code>{version.parser_version}</Code> : <Missing />}
          </Row>
          <Row name="Parse status">
            {version.parse_status}
            {version.parse_error && `: ${version.parse_error}`}
          </Row>
          <Row name="Fetch status">{version.fetch_status}</Row>
          <Row name="Supersedes">
            <VersionLink
              id={version.supersedes_version_id}
              label={`Version ${version.version_number - 1}`}
            />
          </Row>
          <Row name="Superseded by">
            <VersionLink
              id={version.superseded_by_version_id}
              label={`Version ${version.version_number + 1}`}
            />
          </Row>
        </tbody>
      </table>
      <table>
        <caption>Timestamps (never interchangeable)</caption>
        <thead>
          <tr>
            <th scope="col">Clock</th>
            <th scope="col">Value (UTC)</th>
            <th scope="col">Basis</th>
          </tr>
        </thead>
        <tbody>
          <Clock name="available_at" value={version.available_at}>
            <Code>{version.available_at_basis}</Code>: earliest public availability
          </Clock>
          <Clock name="published_at" value={version.published_at}>
            the publisher&apos;s own release time, when it gives one distinct from availability
          </Clock>
          <Clock name="event_at" value={version.event_at}>
            when the underlying development happened, if known
          </Clock>
          <Clock name="fetched_at" value={version.fetched_at}>
            when Atlas fetched these bytes
          </Clock>
          <Clock name="first_seen_at" value={sourceDocument.first_seen_at}>
            when Atlas first saw the Source Document (the adapter&apos;s discovery time)
          </Clock>
          <Clock name="ingested_at" value={version.ingested_at}>
            when the ledger committed this Source Version
          </Clock>
        </tbody>
      </table>
      <details>
        <summary>Source metadata</summary>
        <pre>{JSON.stringify(version.metadata, null, 2)}</pre>
      </details>
    </section>
  );
}

function Clock({
  name,
  value,
  children,
}: {
  name: string;
  value: string | null;
  children: ReactNode;
}) {
  return (
    <tr>
      <th scope="row">{name}</th>
      <td>
        <Timestamp value={value} />
      </td>
      <td>{children}</td>
    </tr>
  );
}

function Fetches({ version }: { version: SourceVersionDetail }) {
  return (
    <section aria-labelledby="fetches">
      <h2 id="fetches">Fetch observations</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Outcome</th>
            <th scope="col">fetched_at</th>
            <th scope="col">Recorded</th>
            <th scope="col">Raw SHA-256</th>
            <th scope="col">Validators</th>
            <th scope="col">Attempts</th>
          </tr>
        </thead>
        <tbody>
          {version.fetches.map((fetch) => (
            <tr key={fetch.id}>
              <td>{fetch.outcome}</td>
              <td>
                <Timestamp value={fetch.fetched_at} />
              </td>
              <td>
                <Timestamp value={fetch.observed_at} />
              </td>
              <td>{fetch.raw_sha256 ? <Code>{fetch.raw_sha256}</Code> : <Missing />}</td>
              <td>
                {fetch.etag || fetch.last_modified ? (
                  [fetch.etag && `ETag ${fetch.etag}`, fetch.last_modified]
                    .filter(Boolean)
                    .join("; ")
                ) : (
                  <Missing />
                )}
              </td>
              <td>{fetch.attempts}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Content({ version }: { version: SourceVersionDetail }) {
  const parsed = version.content_sha256 !== null;
  const text = useApi(parsed ? version.id : null, api.parsedText);
  // The rendered text, where a selection makes a new Assertion's quote span.
  const [textElement, setTextElement] = useState<HTMLPreElement | null>(null);
  return (
    <>
      <section aria-labelledby="parsed-text">
        <h2 id="parsed-text">Parsed text</h2>
        <p>
          <a href={api.contentUrl(version.id, "raw")} download>
            Download original bytes
          </a>{" "}
          ({version.media_type}, {version.byte_size.toLocaleString("en-US")} bytes, SHA-256{" "}
          <Code>{version.raw_sha256.slice(0, 12)}</Code>…) to check the parse against the
          original.
        </p>
        {parsed ? (
          <Load loaded={text} what="the parsed text">
            {(text) => (
              <>
                <p id="parsed-text-hint">
                  Select a passage to quote it in a new Assertion (below).
                </p>
                {/* One text node, verbatim: selection offsets index the parsed text. */}
                <pre
                  ref={setTextElement}
                  className="document"
                  tabIndex={0}
                  aria-label="Parsed text of this Source Version"
                  aria-describedby="parsed-text-hint"
                >
                  {text}
                </pre>
              </>
            )}
          </Load>
        ) : (
          <p>
            No parsed text: parse status <Code>{version.parse_status}</Code>
            {version.parse_error && ` (${version.parse_error})`}.
          </p>
        )}
      </section>
      <VersionAssertions
        key={version.id}
        version={version}
        text={parsed && text.state === "ready" ? text.data : null}
        textElement={textElement}
      />
    </>
  );
}
