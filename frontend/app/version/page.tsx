"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";

import { VersionAssertions } from "../../components/assertions";
import { SourceDocumentRows } from "../../components/source-document";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import { api, type Assertion, type SourceVersionDetail } from "../../lib/api/client";
import { domPosition, splitAtSpan, utf16Index } from "../../lib/offsets";
import { formatCount } from "../../lib/memory";
import { routes } from "../../lib/routes";
import { versionMemory } from "../../lib/version-memory";
import { useApi, useIdParam, type Loaded } from "../../lib/use-api";

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
          <Memory versionId={version.id} />
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
          <Row name="Language">
            {version.language ? <Code>{version.language}</Code> : <Missing>not recorded</Missing>}
            {version.language && version.language !== "en" && (
              <> (archived only: retention and extraction are English-only)</>
            )}
          </Row>
          <Row name="Pages">
            {version.page_anchors ? version.page_anchors.length : <Missing />}
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
            {version.recorded_available_at_basis !== version.available_at_basis ||
            version.recorded_available_at !== version.available_at ? (
              <>
                {" "}
                (a recorded correction; the version itself records{" "}
                <Timestamp value={version.recorded_available_at} />,{" "}
                <Code>{version.recorded_available_at_basis}</Code>)
              </>
            ) : null}
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

/** What Memory holds of this version: one line, and the sections behind a toggle. */
function Memory({ versionId }: { versionId: string }) {
  const memory = useApi(versionId, api.sourceVersionMemory);
  const [open, setOpen] = useState(false);
  if (memory.state === "loading") {
    return (
      <section aria-labelledby="memory">
        <h2 id="memory">Memory</h2>
        <p className="muted" role="status">
          Loading memory…
        </p>
      </section>
    );
  }
  // A 404 or any error: nothing of this version is in memory.
  const held = memory.state === "ready" ? memory.data : null;
  const state = versionMemory(held);
  return (
    <section aria-labelledby="memory">
      <h2 id="memory">Memory</h2>
      <p className="mem-line">
        <span className={`mem-tag ${state.severity}`}>{state.label}</span>
        {held && (
          <>
            <span>{state.sections} sections</span>
            <span>{formatCount(state.facts)} facts</span>
            <span className={state.below ? "mem-tag warn" : "muted"}>
              {state.below ? `${state.below} below ${state.profile}` : state.profile}
            </span>
            {state.sections > 0 && (
              <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
                {open ? "Hide sections" : "Sections"}
              </button>
            )}
          </>
        )}
      </p>
      {held && open && (
        <table>
          <caption>Sections in memory</caption>
          <thead>
            <tr>
              <th scope="col">Section</th>
              <th scope="col">State</th>
              <th scope="col">Facts</th>
              <th scope="col">Profile</th>
            </tr>
          </thead>
          <tbody>
            {held.documents.map((d) => (
              <tr key={d.section_anchor}>
                <th scope="row">{d.section_heading ?? d.section_anchor}</th>
                <td>{d.retain_state.replace("_", " ")}</td>
                <td>{d.fact_count == null ? <Missing /> : formatCount(d.fact_count)}</td>
                <td>{d.retain_profile ?? <Missing />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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

type PageAnchor = NonNullable<SourceVersionDetail["page_anchors"]>[number];

/** A PDF page's name: its label, and its number too when the label differs. */
function pageName(anchor: PageAnchor): string {
  const name = `Page ${anchor.label}`;
  return anchor.label === String(anchor.page) ? name : `${name} (PDF page ${anchor.page})`;
}

/** The PDF's page anchors: each jumps to where its page's text begins. */
function PageAnchors({
  anchors,
  text,
  textElement,
}: {
  anchors: PageAnchor[];
  text: string;
  textElement: HTMLPreElement | null;
}) {
  const jump = (anchor: PageAnchor) => {
    if (!textElement) return;
    const position = domPosition(textElement, utf16Index(text, anchor.start));
    if (!position) return;
    const range = document.createRange();
    range.setStart(position.node, position.offset);
    range.collapse(true);
    const top = range.getBoundingClientRect().top - textElement.getBoundingClientRect().top;
    textElement.scrollBy({ top });
    textElement.scrollIntoView({ block: "nearest" });
  };
  return (
    <nav aria-label="Pages">
      <p>
        Pages ({anchors.length}): each starts at a character offset of the parsed text, which
        Assertions on this version name as their page.
      </p>
      <ol className="pages">
        {anchors.map((anchor) => (
          <li key={anchor.page}>
            <button type="button" onClick={() => jump(anchor)}>
              {pageName(anchor)}
            </button>{" "}
            {anchor.start === anchor.end ? (
              <Missing>no text</Missing>
            ) : (
              <span className="muted">
                characters {anchor.start}–{anchor.end}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * The Assertion named by `?assertion=`, whose span the parsed text highlights (an edge's
 * Evidence links here), or null when none is named.
 */
function useHighlightedAssertion(): Loaded<Assertion> | null {
  const id = useSearchParams().get("assertion");
  const loaded = useApi(id, api.assertion);
  return id ? loaded : null;
}

/** Where the highlighted span is, or why it can't be shown. */
function HighlightNote({
  assertion,
  version,
  inside,
}: {
  assertion: Loaded<Assertion>;
  version: SourceVersionDetail;
  inside: string | null;
}) {
  if (assertion.state === "loading") return null;
  if (assertion.state === "error") {
    return <p role="alert">Could not load the Assertion to highlight: {assertion.message}</p>;
  }
  const { data } = assertion;
  if (data.source_version_id !== version.id) {
    return (
      <p role="alert">
        The Assertion to highlight quotes another Source Version:{" "}
        <Link href={routes.span(data.source_version_id, data.id)}>open it there</Link>.
      </p>
    );
  }
  if (inside !== data.quote) {
    return (
      <p role="alert">
        The Assertion&apos;s quote is not at characters {data.span_start}–{data.span_end} of this
        text, so no span is highlighted.
      </p>
    );
  }
  return (
    <p id="highlighted-span-hint">
      Highlighted: the span of the <Code>{data.predicate}</Code> Assertion, characters{" "}
      {data.span_start}–{data.span_end}
      {data.page_or_anchor && <> ({data.page_or_anchor})</>}.
    </p>
  );
}

function Content({ version }: { version: SourceVersionDetail }) {
  const parsed = version.content_sha256 !== null;
  const highlighted = useHighlightedAssertion();
  // An Assertion is checked against the parse it was made on: highlighting one made on a
  // re-parse shows that parse's text; otherwise the text is the recorded parse.
  const reparse =
    highlighted?.state === "ready" &&
    highlighted.data.source_version_id === version.id &&
    highlighted.data.parser_version !== version.parser_version
      ? highlighted.data.parser_version
      : null;
  const recordedText = useApi(parsed && !reparse ? version.id : null, api.parsedText);
  const reparseText = useApi(reparse ? `${version.id} ${reparse}` : null, api.parseText);
  const text = reparse ? reparseText : recordedText;
  // The rendered text, where a selection makes a new Assertion's quote span.
  const [textElement, setTextElement] = useState<HTMLPreElement | null>(null);
  const [mark, setMark] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!mark || !textElement) return;
    // Scroll the span to the middle of the text box, and the box into view.
    const offset = mark.getBoundingClientRect().top - textElement.getBoundingClientRect().top;
    textElement.scrollBy({ top: offset - textElement.clientHeight / 3 });
    textElement.scrollIntoView({ block: "start" });
  }, [mark, textElement]);
  const split = (whole: string) => {
    if (highlighted?.state !== "ready") return null;
    const assertion = highlighted.data;
    if (assertion.source_version_id !== version.id) return null;
    return splitAtSpan(whole, assertion.span_start, assertion.span_end);
  };
  return (
    <>
      <section aria-labelledby="parsed-text">
        <h2 id="parsed-text">Parsed text</h2>
        <p>
          Parse <Code>{reparse ?? version.parser_version}</Code>
          {reparse
            ? ", a re-parse of the original bytes (the Assertion highlighted quotes it)."
            : version.parses.length > 1
              ? ", as recorded; this version also has a re-parse (see its API record)."
              : "."}
        </p>
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
            {(text) => {
              const parts = split(text);
              const quote = highlighted?.state === "ready" ? highlighted.data.quote : null;
              const shown = parts && parts[1] === quote ? parts : null;
              return (
                <>
                  <p id="parsed-text-hint">
                    Select a passage to quote it in a new Assertion (below).
                  </p>
                  {highlighted && (
                    <HighlightNote
                      assertion={highlighted}
                      version={version}
                      inside={parts ? parts[1] : null}
                    />
                  )}
                  {version.page_anchors && (
                    <PageAnchors
                      anchors={version.page_anchors}
                      text={text}
                      textElement={textElement}
                    />
                  )}
                  {/* The text verbatim: one text node, or three around a highlighted span.
                      Selection offsets index the parsed text either way. */}
                  <pre
                    ref={setTextElement}
                    className="document"
                    tabIndex={0}
                    aria-label="Parsed text of this Source Version"
                    aria-describedby={
                      shown ? "parsed-text-hint highlighted-span-hint" : "parsed-text-hint"
                    }
                  >
                    {shown ? (
                      <>
                        {shown[0]}
                        <mark ref={setMark} className="span">
                          {shown[1]}
                        </mark>
                        {shown[2]}
                      </>
                    ) : (
                      text
                    )}
                  </pre>
                </>
              );
            }}
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
        parserVersion={reparse}
      />
    </>
  );
}
