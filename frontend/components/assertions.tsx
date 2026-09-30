"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  api,
  type Assertion,
  type AssertionRecorded,
  type Company,
  type EpistemicType,
  type SourceVersionDetail,
} from "../lib/api/client";
import { EPISTEMIC_TYPES, canSucceed, reviewActions, type ReviewAction } from "../lib/assertions";
import { selectedSpan, type Span } from "../lib/offsets";
import { useApi } from "../lib/use-api";
import { Code, Load, Missing, Timestamp } from "./ui";

type Notice = { kind: "ok" | "error"; text: string };

const loadCompanies = () => api.companies();

function describe(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

function sameSpan(a: Span | null, b: Span): boolean {
  return a !== null && a.span_start === b.span_start && a.span_end === b.span_end;
}

/** `list` with `changed` in place of the Assertion it updates, or appended if new. */
function merge(list: Assertion[], changed: Assertion[]): Assertion[] {
  let merged = list;
  for (const assertion of changed) {
    merged = merged.some((item) => item.id === assertion.id)
      ? merged.map((item) => (item.id === assertion.id ? assertion : item))
      : [...merged, assertion];
  }
  return merged;
}

function shorten(quote: string, length = 80): string {
  return quote.length > length ? `${quote.slice(0, length - 1)}…` : quote;
}

/**
 * Creating Assertions from a selection in the parsed text (`textElement`, which renders
 * `text` verbatim), and listing and reviewing this Source Version's Assertions. `parserVersion`
 * names the parse `text` is when it is not the recorded one (a re-parse): a new Assertion
 * quotes that parse.
 */
export function VersionAssertions({
  version,
  text,
  textElement,
  parserVersion = null,
}: {
  version: SourceVersionDetail;
  text: string | null;
  textElement: HTMLElement | null;
  parserVersion?: string | null;
}) {
  const loaded = useApi(version.id, api.versionAssertions);
  const companies = useApi("all", loadCompanies);
  // Assertions created or reviewed on this page, as the API answered each mutation.
  const [changed, setChanged] = useState<Assertion[]>([]);
  const [span, setSpan] = useState<Span | null>(null);
  const [created, setCreated] = useState<Notice | null>(null);

  useEffect(() => {
    if (text === null || textElement === null) return;
    const capture = () => {
      const selection = document.getSelection();
      const next = selection && selectedSpan(textElement, text, selection);
      if (next) setSpan((current) => (sameSpan(current, next) ? current : next));
    };
    document.addEventListener("selectionchange", capture);
    return () => document.removeEventListener("selectionchange", capture);
  }, [text, textElement]);

  const record = (recorded: AssertionRecorded) =>
    setChanged((current) => [...current, recorded.assertion]);
  const companyList = companies.state === "ready" ? companies.data.items : [];
  const subject = companyList.find((company) => company.id === version.source_document.company_id);

  const clearSelection = () => {
    setSpan(null);
    document.getSelection()?.removeAllRanges();
  };

  return (
    <>
      <section aria-labelledby="new-assertion">
        <h2 id="new-assertion">New Assertion</h2>
        {created && (
          <p role={created.kind === "ok" ? "status" : "alert"} aria-live="polite">
            {created.text}
          </p>
        )}
        {text === null ? (
          <p>An Assertion quotes the parsed text, and this Source Version has none to quote.</p>
        ) : !version.source_document.company_id ? (
          <p>This Source Document names no company, so it has no subject for an Assertion.</p>
        ) : span === null ? (
          <p>Select a passage in the parsed text above to quote it in a new Assertion.</p>
        ) : (
          <AssertionForm
            version={version}
            parserVersion={parserVersion}
            span={span}
            subject={subject}
            companies={companyList}
            onCancel={clearSelection}
            onRecorded={(recorded) => {
              record(recorded);
              clearSelection();
              setCreated({
                kind: "ok",
                text:
                  `Recorded Assertion ${recorded.assertion.id} (audit event ` +
                  `${recorded.audit_event_id}); it is listed below.`,
              });
            }}
          />
        )}
      </section>
      <section aria-labelledby="assertions">
        <h2 id="assertions">Assertions</h2>
        <Load loaded={loaded} what="the Assertions">
          {(page) => (
            <AssertionTable
              assertions={merge(page.items, changed)}
              companies={companyList}
              onRecorded={record}
            />
          )}
        </Load>
      </section>
    </>
  );
}

function AssertionForm({
  version,
  parserVersion,
  span,
  subject,
  companies,
  onCancel,
  onRecorded,
}: {
  version: SourceVersionDetail;
  parserVersion: string | null;
  span: Span;
  subject: Company | undefined;
  companies: Company[];
  onCancel: () => void;
  onRecorded: (recorded: AssertionRecorded) => void;
}) {
  const [predicate, setPredicate] = useState("");
  const [objectCompany, setObjectCompany] = useState("");
  const [value, setValue] = useState("");
  const [anchor, setAnchor] = useState("");
  const [epistemicType, setEpistemicType] = useState<EpistemicType | "">("");
  const [busy, setBusy] = useState(false);
  // A refusal belongs to the span it was for; selecting another passage clears it.
  const [refusal, setRefusal] = useState<{ span: Span; text: string } | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const subjectId = version.source_document.company_id;
    if (!subjectId || !epistemicType) return;
    let valueJson: unknown = null;
    if (value.trim()) {
      try {
        valueJson = JSON.parse(value);
      } catch {
        setRefusal({ span, text: "The value is not valid JSON; nothing was sent." });
        return;
      }
    }
    setBusy(true);
    setRefusal(null);
    try {
      onRecorded(
        await api.createAssertion({
          subject_company_id: subjectId,
          predicate: predicate.trim(),
          object_company_id: objectCompany || null,
          value_json: valueJson,
          source_version_id: version.id,
          quote: span.quote,
          span_start: span.span_start,
          span_end: span.span_end,
          page_or_anchor: anchor.trim() || null,
          epistemic_type: epistemicType,
          parser_version: parserVersion,
        }),
      );
    } catch (error) {
      setRefusal({ span, text: `The API refused this Assertion (${describe(error)}).` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} aria-describedby="new-assertion-quote">
      <figure>
        <blockquote id="new-assertion-quote" className="quote">
          {span.quote}
        </blockquote>
        <figcaption aria-live="polite">
          Characters {span.span_start}–{span.span_end} of the parsed text (code points; the
          end is exclusive).
        </figcaption>
      </figure>
      <p>Subject: {subject ? subject.display_name : <Code>{version.source_document.company_id}</Code>}</p>
      <div className="field">
        <label htmlFor="assertion-predicate">Predicate</label>
        <input
          id="assertion-predicate"
          required
          value={predicate}
          onChange={(event) => setPredicate(event.target.value)}
          placeholder="e.g. reported_net_revenue"
        />
      </div>
      <div className="field">
        <label htmlFor="assertion-object">Object company (optional)</label>
        <select
          id="assertion-object"
          value={objectCompany}
          onChange={(event) => setObjectCompany(event.target.value)}
        >
          <option value="">None</option>
          {companies.map((company) => (
            <option key={company.id} value={company.id}>
              {company.display_name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="assertion-value">Value (JSON, optional)</label>
        <input
          id="assertion-value"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder='e.g. {"amount": 1010000000, "currency": "USD"}'
        />
      </div>
      <div className="field">
        <label htmlFor="assertion-anchor">Page or anchor (optional)</label>
        <input
          id="assertion-anchor"
          value={anchor}
          onChange={(event) => setAnchor(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="assertion-epistemic-type">Epistemic type</label>
        <select
          id="assertion-epistemic-type"
          required
          value={epistemicType}
          onChange={(event) => setEpistemicType(event.target.value as EpistemicType | "")}
        >
          <option value="">Choose…</option>
          {EPISTEMIC_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </select>
      </div>
      {refusal && sameSpan(refusal.span, span) && <p role="alert">{refusal.text}</p>}
      <p>
        <button type="submit" disabled={busy} aria-busy={busy}>
          Create Assertion
        </button>{" "}
        <button type="button" onClick={onCancel}>
          Clear selection
        </button>
      </p>
    </form>
  );
}

function AssertionTable({
  assertions,
  companies,
  onRecorded,
}: {
  assertions: Assertion[];
  companies: Company[];
  onRecorded: (recorded: AssertionRecorded) => void;
}) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  if (assertions.length === 0) return <p>No Assertions cite this Source Version yet.</p>;

  const companyName = (id: string | null) =>
    companies.find((company) => company.id === id)?.display_name ?? id;
  const byId = new Map(assertions.map((assertion) => [assertion.id, assertion]));

  const review = async (assertion: Assertion, action: ReviewAction, successor?: string) => {
    setBusy(assertion.id);
    try {
      const recorded = await api.reviewAssertion(assertion.id, {
        review_state: action.state,
        superseded_by: successor ?? null,
      });
      onRecorded(recorded);
      setNotice({
        kind: "ok",
        text:
          `Assertion ${assertion.predicate} is now ${recorded.assertion.review_state} ` +
          `(audit event ${recorded.audit_event_id}).`,
      });
      // The button pressed may be gone; keep focus on the row's new state.
      requestAnimationFrame(() => document.getElementById(`assertion-${assertion.id}-state`)?.focus());
    } catch (error) {
      setNotice({ kind: "error", text: `The review was refused (${describe(error)}).` });
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      {notice && <p role={notice.kind === "ok" ? "status" : "alert"}>{notice.text}</p>}
      <table>
        <caption>Assertions citing this Source Version, oldest first</caption>
        <thead>
          <tr>
            <th scope="col">Quote</th>
            <th scope="col">Characters</th>
            <th scope="col">Statement</th>
            <th scope="col">Epistemic type</th>
            <th scope="col">Review state</th>
            <th scope="col">Review</th>
          </tr>
        </thead>
        <tbody>
          {assertions.map((assertion) => {
            const successor = assertion.superseded_by ? byId.get(assertion.superseded_by) : null;
            return (
              <tr key={assertion.id}>
                <td id={`assertion-${assertion.id}-quote`} className="quote">
                  {assertion.quote}
                </td>
                <td>
                  {assertion.span_start}–{assertion.span_end}
                  {assertion.page_or_anchor && <> ({assertion.page_or_anchor})</>}
                  <br />
                  <span className="muted-small">
                    of the <Code>{assertion.parser_version}</Code> parse
                  </span>
                </td>
                <td>
                  <Code>{assertion.predicate}</Code>
                  {assertion.object_company_id && (
                    <> about {companyName(assertion.object_company_id)}</>
                  )}
                  {assertion.value_json !== null && (
                    <>
                      {": "}
                      <Code>{JSON.stringify(assertion.value_json)}</Code>
                    </>
                  )}
                  <br />
                  <span className="muted-small">
                    recorded <Timestamp value={assertion.extracted_at} /> by {assertion.created_by}
                  </span>
                </td>
                <td>
                  {EPISTEMIC_TYPES.find((type) => type.value === assertion.epistemic_type)?.label}
                </td>
                <td id={`assertion-${assertion.id}-state`} tabIndex={-1}>
                  <strong>{assertion.review_state}</strong>
                  {assertion.reviewer_id && (
                    <>
                      <br />
                      <span className="muted-small">
                        reviewed by {assertion.reviewer_id} at{" "}
                        <Timestamp value={assertion.reviewed_at} />
                      </span>
                    </>
                  )}
                  {assertion.superseded_by && (
                    <>
                      <br />
                      {successor ? (
                        <>
                          Superseded by <Code>{successor.predicate}</Code>, characters{" "}
                          {successor.span_start}–{successor.span_end}
                        </>
                      ) : (
                        <>
                          Superseded by Assertion <Code>{assertion.superseded_by}</Code>
                        </>
                      )}
                    </>
                  )}
                </td>
                <td>
                  <ReviewControls
                    assertion={assertion}
                    candidates={assertions.filter(
                      (other) => other.id !== assertion.id && canSucceed(other.review_state),
                    )}
                    busy={busy !== null}
                    onReview={review}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

function ReviewControls({
  assertion,
  candidates,
  busy,
  onReview,
}: {
  assertion: Assertion;
  candidates: Assertion[];
  busy: boolean;
  onReview: (assertion: Assertion, action: ReviewAction, successor?: string) => void;
}) {
  const [successor, setSuccessor] = useState("");
  const actions = reviewActions(assertion.review_state);
  if (actions.length === 0) return <Missing>final</Missing>;
  const describedBy = `assertion-${assertion.id}-quote`;
  const chosen = candidates.some((candidate) => candidate.id === successor)
    ? successor
    : (candidates[0]?.id ?? "");
  return (
    <>
      {actions
        .filter((action) => action.state !== "superseded")
        .map((action) => (
          <button
            key={action.state}
            type="button"
            disabled={busy}
            aria-describedby={describedBy}
            onClick={() => onReview(assertion, action)}
          >
            {action.label}
          </button>
        ))}
      {actions
        .filter((action) => action.state === "superseded" && candidates.length > 0)
        .map((action) => (
          <div key={action.state} className="field">
            <label htmlFor={`assertion-${assertion.id}-successor`}>Successor</label>
            <select
              id={`assertion-${assertion.id}-successor`}
              value={chosen}
              onChange={(event) => setSuccessor(event.target.value)}
            >
              {candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {`${candidate.predicate}: ${shorten(candidate.quote)}`}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy || !chosen}
              aria-describedby={describedBy}
              onClick={() => onReview(assertion, action, chosen)}
            >
              {action.label}
            </button>
          </div>
        ))}
    </>
  );
}
