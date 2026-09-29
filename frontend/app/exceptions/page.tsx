"use client";

import Link from "next/link";
import { useState } from "react";

import {
  EdgeLink,
  EdgeObject,
  LayerName,
  OwnerReviewControls,
  ReviewState,
  edgeLabel,
} from "../../components/relationships";
import { Code, Load } from "../../components/ui";
import { api, type Relationship } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

const loadExceptions = () => api.relationshipExceptions();

/**
 * The exceptions queue: edges the machine review sent to a human, oldest first, each with
 * the reasons. The owner approves or rejects each here; a decided edge leaves the queue.
 */
export default function ExceptionsPage() {
  const loaded = useApi("exceptions", loadExceptions);
  // Edges decided on this page, as the API answered each decision.
  const [decided, setDecided] = useState<Relationship[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <>
      <p className="crumbs">
        <Link href={routes.companies}>Companies</Link>
        {" / "}
        <Link href={routes.relationships()}>Relationships</Link>
      </p>
      <h1>Exceptions queue</h1>
      <p>
        Relationships that need human review: a deterministic check failed (a hedge, a
        non-Tier A source, a span that isn&apos;t verbatim) or the Reviewer didn&apos;t
        confirm them. Open an edge to read its Evidence before deciding.
      </p>
      {notice && (
        <p role="status" aria-live="polite">
          {notice}
        </p>
      )}
      <Load loaded={loaded} what="the exceptions queue">
        {(page) => {
          const done = new Set(decided.map((edge) => edge.id));
          const open = page.items.filter((edge) => !done.has(edge.id));
          return open.length === 0 ? (
            <p>No relationships need review.</p>
          ) : (
            <table>
              <caption>
                {open.length === 1 ? "1 relationship" : `${open.length} relationships`} waiting
                for the owner, oldest first
              </caption>
              <thead>
                <tr>
                  <th scope="col">Relationship</th>
                  <th scope="col">Layer</th>
                  <th scope="col">Why</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {open.map((edge) => {
                  const labelId = `exception-${edge.id}-edge`;
                  return (
                    <tr key={edge.id} aria-label={edgeLabel(edge)}>
                      <td id={labelId}>
                        {edge.subject_name} <Code>{edge.predicate}</Code>{" "}
                        <EdgeObject relationship={edge} />
                        <br />
                        <EdgeLink relationship={edge} />
                      </td>
                      <td>
                        <LayerName layer={edge.layer} />
                      </td>
                      <td>
                        <ReviewState relationship={edge} />
                      </td>
                      <td>
                        {edge.evidence_count} Assertion{edge.evidence_count === 1 ? "" : "s"},{" "}
                        {edge.family_count} famil{edge.family_count === 1 ? "y" : "ies"}
                      </td>
                      <td>
                        <OwnerReviewControls
                          relationship={edge}
                          describedBy={labelId}
                          onRecorded={(recorded) => {
                            setDecided((current) => [...current, recorded.relationship]);
                            setNotice(
                              `${edgeLabel(recorded.relationship)}: ` +
                                `${recorded.relationship.review_state} (audit event ` +
                                `${recorded.audit_event_id}).`,
                            );
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          );
        }}
      </Load>
    </>
  );
}
