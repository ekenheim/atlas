"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ApiError,
  api,
  type OwnerReview,
  type Relationship,
  type RelationshipRecorded,
} from "../lib/api/client";
import { STATES, layerLabel } from "../lib/relationships";
import { routes } from "../lib/routes";
import { Code, Missing, Timestamp } from "./ui";

function describe(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

/** The edge's object: its company, or the product, material or technology it names. */
export function EdgeObject({ relationship }: { relationship: Relationship }) {
  if (relationship.object_name) return <>{relationship.object_name}</>;
  if (relationship.object_text) return <em>{relationship.object_text}</em>;
  return <Missing />;
}

/** "Subject predicate Object", the edge read in its direction. */
export function edgeLabel(relationship: Relationship): string {
  const object = relationship.object_name ?? relationship.object_text ?? "?";
  return `${relationship.subject_name} ${relationship.predicate} ${object}`;
}

/** The edge's layer, or "none" when its Evidence names no layer. */
export function LayerName({ layer }: { layer: Relationship["layer"] }) {
  return <>{layerLabel(layer) ?? <Missing />}</>;
}

/** The review state, the reasons its machine reviews didn't pass, and the owner's decision. */
export function ReviewState({ relationship }: { relationship: Relationship }) {
  return (
    <>
      <strong>{STATES[relationship.review_state]}</strong>
      {relationship.review_reasons.length > 0 && (
        <>
          <br />
          <span className="muted-small">
            reasons:{" "}
            {relationship.review_reasons.map((reason, index) => (
              <span key={reason}>
                {index > 0 && ", "}
                <Code>{reason}</Code>
              </span>
            ))}
          </span>
        </>
      )}
      {relationship.reviewed_by && (
        <>
          <br />
          <span className="muted-small">
            {relationship.review_state} by {relationship.reviewed_by} at{" "}
            <Timestamp value={relationship.reviewed_at} />
            {relationship.review_note && <>: {relationship.review_note}</>}
          </span>
        </>
      )}
    </>
  );
}

const DECISIONS: readonly { state: OwnerReview["review_state"]; label: string }[] = [
  { state: "approved", label: "Approve" },
  { state: "rejected", label: "Reject" },
];

/**
 * The owner's approve and reject buttons for one edge, with an optional note. A decision
 * the edge already has is not offered (the API refuses it as `invalid_transition`).
 * `describedBy` names the element that says which edge the buttons act on.
 */
export function OwnerReviewControls({
  relationship,
  describedBy,
  onRecorded,
}: {
  relationship: Relationship;
  describedBy: string;
  onRecorded: (recorded: RelationshipRecorded) => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const noteId = `relationship-${relationship.id}-note`;

  const decide = async (state: OwnerReview["review_state"]) => {
    setBusy(true);
    setRefusal(null);
    try {
      const recorded = await api.reviewRelationship(relationship.id, {
        review_state: state,
        note: note.trim() ? note : null,
      });
      setNote("");
      onRecorded(recorded);
    } catch (error) {
      setRefusal(describe(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="field">
        <label htmlFor={noteId}>Note (optional)</label>
        <input
          id={noteId}
          type="text"
          value={note}
          maxLength={4000}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      {DECISIONS.filter((decision) => decision.state !== relationship.review_state).map(
        (decision) => (
          <button
            key={decision.state}
            type="button"
            disabled={busy}
            aria-describedby={describedBy}
            onClick={() => void decide(decision.state)}
          >
            {decision.label}
          </button>
        ),
      )}
      {refusal && <p role="alert">{refusal}</p>}
    </>
  );
}

/** A link to the edge's page, named by the edge itself. */
export function EdgeLink({ relationship }: { relationship: Relationship }) {
  return (
    <Link
      href={routes.relationship(relationship.id)}
      aria-label={`Open ${edgeLabel(relationship)}`}
    >
      Open
    </Link>
  );
}
