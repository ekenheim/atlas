"""The write side of Relationships: machine review links an Assertion to its edge; the owner
approves or rejects an edge. Every change is audited in its own transaction.

**Machine review** (`record_machine_review`, called by the `review_relationships` job, one
Assertion per transaction): the Assertion's review row is recorded (`relationship_review.
recorded`). An eligible Assertion then joins the edge its (subject, predicate, object,
layer) names: a new edge is created in the review's outcome (`relationship.created`); an
existing one gains the Evidence (`relationship.evidence_added`) and, if it was an exception
and this Assertion passed, becomes machine-reviewed (`relationship.machine_reviewed`).
Machine review never changes an owner's decision, and never demotes an edge: a failing
witness doesn't undo a passing one; its reasons stay visible on the edge.

**Owner review** (`Relationships.review`): the owner may approve or reject any Relationship,
whatever its state (`relationship.approved`, `relationship.rejected`), with an optional note.
Repeating the current decision is not a transition (409 `invalid_transition`).
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.proposed_updates.triggers import on_relationship_rejected
from atlas.relationships.reads import (
    MachineOutcome,
    Relationship,
    ReviewerStatus,
    get_relationship,
    supporting_assertion_ids,
)

OwnerDecision = Literal["approved", "rejected"]


class OwnerReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_state: OwnerDecision
    note: str | None = Field(default=None, max_length=4000, description="why, for the record")

    @field_validator("note")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class RelationshipRecorded(BaseModel):
    """A mutation's result: the Relationship as it now is, and the audit event recording it."""

    relationship: Relationship
    audit_event_id: int


class RelationshipRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RelationshipNotFound(RelationshipRefused):
    def __init__(self) -> None:
        super().__init__("not_found", "relationship not found")


class InvalidTransition(RelationshipRefused):
    pass


class Relationships:
    def __init__(self, engine: Engine, actor: Actor) -> None:
        self._engine = engine
        self._actor = actor

    def review(self, relationship_id: uuid.UUID, request: OwnerReview) -> RelationshipRecorded:
        with self._engine.begin() as connection:
            current = connection.execute(
                text("SELECT review_state FROM relationship WHERE id = :id FOR UPDATE"),
                {"id": relationship_id},
            ).scalar_one_or_none()
            if current is None:
                raise RelationshipNotFound
            if current == request.review_state:
                raise InvalidTransition(
                    "invalid_transition", f"the relationship is already {current}"
                )
            before = _snapshot(connection, relationship_id)
            connection.execute(
                text(
                    "UPDATE relationship SET review_state = :state, reviewed_by = :actor,"
                    " reviewed_at = now(), review_note = :note, updated_at = now()"
                    " WHERE id = :id"
                ),
                {
                    "state": request.review_state,
                    "actor": self._actor.name,
                    "note": request.note,
                    "id": relationship_id,
                },
            )
            event = record(
                connection,
                self._actor,
                f"relationship.{request.review_state}",
                entity_type="relationship",
                entity_id=str(relationship_id),
                old_hash=before,
                new_hash=_snapshot(connection, relationship_id),
            )
            if request.review_state == "rejected":
                # A published Hypothesis version depending on it gets a proposed update.
                on_relationship_rejected(connection, relationship_id)
            after = get_relationship(connection, relationship_id)
        assert after is not None
        return RelationshipRecorded(relationship=after, audit_event_id=event.id)


@dataclass(frozen=True)
class Edge:
    """What an eligible Assertion claims: the edge's identity."""

    subject_company_id: uuid.UUID
    predicate: str
    object_company_id: uuid.UUID | None
    object_text: str | None
    layer: str

    @property
    def object_key(self) -> str:
        if self.object_company_id is not None:
            return str(self.object_company_id)
        assert self.object_text is not None
        return " ".join(self.object_text.split()).casefold()


@dataclass(frozen=True)
class MachineReviewRecord:
    """One Assertion's machine review, as recorded."""

    assertion_id: uuid.UUID
    outcome: MachineOutcome
    reasons: list[str]
    reviewer_status: ReviewerStatus
    job_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    role_call_id: uuid.UUID | None = None
    verbatim_span: bool | None = None
    tier_a: bool | None = None
    directional_language: str | None = None
    directional_cue: str | None = None
    hedge: str | None = None
    reviewer_verdict: str | None = None
    reviewer_direction: str | None = None
    reviewer_layer: str | None = None
    reviewer_suggested_layer: str | None = None
    reviewer_reasoning: str | None = None


def record_machine_review(
    connection: Connection, actor: Actor, review: MachineReviewRecord, edge: Edge | None
) -> uuid.UUID | None:
    """Record `review` (and, for an eligible Assertion, link it to `edge`) in the caller's
    transaction. Returns the Relationship's ID (None: not eligible). An Assertion already
    reviewed is left as it is (returns its Relationship)."""
    existing = connection.execute(
        text("SELECT relationship_id FROM relationship_review WHERE assertion_id = :id"),
        {"id": review.assertion_id},
    ).one_or_none()
    if existing is not None:
        return existing.relationship_id
    if (edge is None) != (review.outcome == "not_eligible"):
        raise ValueError("an eligible Assertion (and only one) has an edge")
    relationship_id = None if edge is None else _link(connection, actor, review, edge)
    row = (
        connection.execute(
            text(
                "INSERT INTO relationship_review (id, assertion_id, relationship_id, job_id,"
                " run_id, role_call_id, verbatim_span, tier_a, directional_language,"
                " directional_cue, hedge, reviewer_status, reviewer_verdict, reviewer_direction,"
                " reviewer_layer, reviewer_suggested_layer, reviewer_reasoning, outcome, reasons)"
                " VALUES (:id, :assertion_id, :relationship_id, :job_id, :run_id, :role_call_id,"
                " :verbatim_span, :tier_a, :directional_language, :directional_cue, :hedge,"
                " :reviewer_status, :reviewer_verdict, :reviewer_direction, :reviewer_layer,"
                " :reviewer_suggested_layer, :reviewer_reasoning, :outcome, :reasons)"
                " RETURNING *"
            ),
            {
                **review.__dict__,
                "id": uuid.uuid4(),
                "relationship_id": relationship_id,
            },
        )
        .mappings()
        .one()
    )
    record(
        connection,
        actor,
        "relationship_review.recorded",
        entity_type="relationship_review",
        entity_id=str(row["id"]),
        new_hash=content_hash(dict(row)),
    )
    return relationship_id


def _link(
    connection: Connection, actor: Actor, review: MachineReviewRecord, edge: Edge
) -> uuid.UUID:
    state = review.outcome
    created = connection.execute(
        text(
            "INSERT INTO relationship (id, subject_company_id, predicate, object_company_id,"
            " object_text, object_key, layer, review_state) VALUES (:id, :subject, :predicate,"
            " :object, :object_text, :object_key, :layer, :state)"
            " ON CONFLICT (subject_company_id, predicate, object_key, layer) DO NOTHING"
            " RETURNING id"
        ),
        {
            "id": uuid.uuid4(),
            "subject": edge.subject_company_id,
            "predicate": edge.predicate,
            "object": edge.object_company_id,
            "object_text": edge.object_text,
            "object_key": edge.object_key,
            "layer": edge.layer,
            "state": state,
        },
    ).scalar_one_or_none()
    if created is not None:
        _add_evidence(connection, created, review.assertion_id)
        record(
            connection,
            actor,
            "relationship.created",
            entity_type="relationship",
            entity_id=str(created),
            new_hash=_snapshot(connection, created),
        )
        return created
    found = connection.execute(
        text(
            "SELECT id, review_state FROM relationship WHERE subject_company_id = :subject"
            " AND predicate = :predicate AND object_key = :object_key AND layer = :layer"
            " FOR UPDATE"
        ),
        {
            "subject": edge.subject_company_id,
            "predicate": edge.predicate,
            "object_key": edge.object_key,
            "layer": edge.layer,
        },
    ).one()
    before = _snapshot(connection, found.id)
    _add_evidence(connection, found.id, review.assertion_id)
    connection.execute(
        text("UPDATE relationship SET updated_at = now() WHERE id = :id"), {"id": found.id}
    )
    with_evidence = _snapshot(connection, found.id)
    record(
        connection,
        actor,
        "relationship.evidence_added",
        entity_type="relationship",
        entity_id=str(found.id),
        old_hash=before,
        new_hash=with_evidence,
    )
    if found.review_state == "needs_human_review" and state == "machine_reviewed":
        connection.execute(
            text("UPDATE relationship SET review_state = 'machine_reviewed' WHERE id = :id"),
            {"id": found.id},
        )
        record(
            connection,
            actor,
            "relationship.machine_reviewed",
            entity_type="relationship",
            entity_id=str(found.id),
            old_hash=with_evidence,
            new_hash=_snapshot(connection, found.id),
        )
    return found.id


def _add_evidence(
    connection: Connection, relationship_id: uuid.UUID, assertion_id: uuid.UUID
) -> None:
    connection.execute(
        text(
            "INSERT INTO relationship_assertion (assertion_id, relationship_id)"
            " VALUES (:assertion, :relationship)"
        ),
        {"assertion": assertion_id, "relationship": relationship_id},
    )


def _snapshot(connection: Connection, relationship_id: uuid.UUID) -> str:
    """The content hash of the edge's row and its supporting Assertions."""
    row: dict[str, Any] = dict(
        connection.execute(
            text("SELECT * FROM relationship WHERE id = :id"), {"id": relationship_id}
        )
        .mappings()
        .one()
    )
    row["supporting_assertion_ids"] = supporting_assertion_ids(connection, relationship_id)
    return content_hash(row)
