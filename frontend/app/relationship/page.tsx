"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import {
  EdgeObject,
  LayerName,
  OwnerReviewControls,
  ReviewState,
  edgeLabel,
} from "../../components/relationships";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  api,
  type Relationship,
  type RelationshipDetail,
  type RelationshipEvidence,
} from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function RelationshipPage() {
  return (
    <Suspense>
      <Edge />
    </Suspense>
  );
}

function Edge() {
  const id = useIdParam();
  const loaded = useApi(id, api.relationship);
  // The edge as the owner's last decision on this page left it.
  const [decided, setDecided] = useState<Relationship | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.relationships()}>Relationships</Link>
        {" / "}
        <Link href={routes.exceptions}>Exceptions queue</Link>
      </p>
      <Load loaded={loaded} what="the relationship">
        {(detail) => {
          const edge: Relationship = decided?.id === detail.id ? decided : detail;
          return (
            <>
              <h1>{edgeLabel(edge)}</h1>
              <Summary edge={edge} />
              <section aria-labelledby="owner-review">
                <h2 id="owner-review">Owner review</h2>
                {notice && (
                  <p role="status" aria-live="polite">
                    {notice}
                  </p>
                )}
                <p id="owner-review-hint">
                  Approve the edge to let published work depend on it, or reject it. The
                  decision is audited, and later Evidence never overrides it.
                </p>
                <OwnerReviewControls
                  key={edge.review_state}
                  relationship={edge}
                  describedBy="owner-review-hint"
                  onRecorded={(recorded) => {
                    setDecided(recorded.relationship);
                    setNotice(
                      `Recorded: ${recorded.relationship.review_state} (audit event ` +
                        `${recorded.audit_event_id}).`,
                    );
                  }}
                />
              </section>
              <Evidence detail={detail} />
            </>
          );
        }}
      </Load>
    </>
  );
}

function Summary({ edge }: { edge: Relationship }) {
  return (
    <table>
      <caption>The edge</caption>
      <tbody>
        <Row name="Subject">
          <Link href={routes.company(edge.subject_company_id)}>{edge.subject_name}</Link>
        </Row>
        <Row name="Predicate">
          <Code>{edge.predicate}</Code>
        </Row>
        <Row name="Object">
          {edge.object_company_id ? (
            <Link href={routes.company(edge.object_company_id)}>
              <EdgeObject relationship={edge} />
            </Link>
          ) : (
            <EdgeObject relationship={edge} />
          )}
        </Row>
        <Row name="Layer">
          <LayerName layer={edge.layer} />
        </Row>
        <Row name="Products">
          {edge.products.length > 0 ? edge.products.join(", ") : <Missing />}
        </Row>
        <Row name="Review state">
          <ReviewState relationship={edge} />
        </Row>
        <Row name="Evidence">
          {edge.evidence_count} open Assertion{edge.evidence_count === 1 ? "" : "s"} from{" "}
          {edge.family_count} Evidence Famil{edge.family_count === 1 ? "y" : "ies"} (independent
          witnesses)
        </Row>
        <Row name="Created">
          <Timestamp value={edge.created_at} />
        </Row>
        <Row name="Updated">
          <Timestamp value={edge.updated_at} />
        </Row>
      </tbody>
    </table>
  );
}

function Evidence({ detail }: { detail: RelationshipDetail }) {
  return (
    <section aria-labelledby="evidence">
      <h2 id="evidence">Evidence</h2>
      {detail.evidence.length === 0 ? (
        <p>No supporting Assertions.</p>
      ) : (
        <table>
          <caption>Supporting Assertions, oldest first; each opens its source span</caption>
          <thead>
            <tr>
              <th scope="col">Quote</th>
              <th scope="col">Source</th>
              <th scope="col">Assertion</th>
              <th scope="col">Machine review</th>
            </tr>
          </thead>
          <tbody>
            {detail.evidence.map((evidence) => (
              <EvidenceRow key={evidence.assertion.id} evidence={evidence} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function EvidenceRow({ evidence }: { evidence: RelationshipEvidence }) {
  const assertion = evidence.assertion;
  const review = evidence.review;
  const quoteId = `evidence-${assertion.id}-quote`;
  return (
    <tr>
      <td>
        <blockquote id={quoteId} className="quote">
          {assertion.quote}
        </blockquote>
        <Link
          href={routes.span(assertion.source_version_id, assertion.id)}
          aria-describedby={quoteId}
        >
          Open source span
        </Link>{" "}
        <span className="muted-small">
          characters {assertion.span_start}–{assertion.span_end}
          {assertion.page_or_anchor && <> ({assertion.page_or_anchor})</>}
        </span>
      </td>
      <td>
        <Link href={routes.source(evidence.source_document_id)}>{evidence.source_title}</Link>
        <br />
        <span className="muted-small">
          {evidence.publisher}, Tier {evidence.source_tier}
          <br />
          Evidence Family{" "}
          {evidence.evidence_family_id ? (
            <Code>{evidence.evidence_family_id.slice(0, 8)}</Code>
          ) : (
            <Missing>none (its own witness)</Missing>
          )}
        </span>
      </td>
      <td>
        <strong>{assertion.review_state}</strong> <Code>{assertion.epistemic_type}</Code>
        <br />
        <span className="muted-small">
          by {assertion.created_by} ({assertion.extractor_version}), added{" "}
          <Timestamp value={evidence.added_at} />
        </span>
      </td>
      <td>
        {review ? (
          <>
            <strong>{review.outcome}</strong>
            {review.reasons.length > 0 && <>: {review.reasons.join(", ")}</>}
            <br />
            <span className="muted-small">
              verbatim span {String(review.verbatim_span)}, Tier A {String(review.tier_a)},
              language {review.directional_language ?? "unknown"}
              {review.directional_cue && <> (cue “{review.directional_cue}”)</>}
              {review.hedge && <> (hedge “{review.hedge}”)</>}; Reviewer {review.reviewer_status}
              {review.reviewer_verdict && <>: {review.reviewer_verdict}</>}
              {review.reviewer_direction && (
                <>
                  : direction {review.reviewer_direction}
                  {review.reviewer_hedge && <>, hedge {review.reviewer_hedge}</>}, layer{" "}
                  {review.reviewer_layer}
                  {review.reviewer_suggested_layer && (
                    <> (suggests {review.reviewer_suggested_layer})</>
                  )}
                </>
              )}
              ; layer its quote supports: {review.supported_layer ?? "none"}
            </span>
            {review.reviewer_reasoning && (
              <>
                <br />
                <span className="muted-small">{review.reviewer_reasoning}</span>
              </>
            )}
          </>
        ) : (
          <Missing>not machine-reviewed</Missing>
        )}
      </td>
    </tr>
  );
}
