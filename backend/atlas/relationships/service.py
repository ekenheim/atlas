"""The write side of Relationships: machine review links an Assertion to its edge; the owner
approves or rejects an edge. Every change is audited in its own transaction.

**Machine review** (`record_machine_review`, called by the `review_relationships` job, one
Assertion per transaction): the Assertion's review row is recorded (`relationship_review.
recorded`). An eligible Assertion then joins the edge its (subject, predicate, object)
names: a new edge is created in the review's outcome (`relationship.created`); an
existing one gains the Evidence (`relationship.evidence_added`) and, if it was an exception
and this Assertion passed, becomes machine-reviewed (`relationship.machine_reviewed`).
Machine review never changes an owner's decision, and a failing witness doesn't undo a
passing one; its reasons stay visible on the edge.

**The layer** (memory-directed reading ticket 08) is not part of an edge's identity. `Edge.
layer` is the layer the Assertion brings (`atlas.relationships.checks.brings_layer`), if any:

- A new edge takes it (or has none).
- An edge with no layer takes it (`relationship.layer_set`) when the edge is still an
  exception, or when this Assertion passed its review: a machine-reviewed or owner-decided
  edge never gets a layer from a witness that failed.
- An edge that has **another** layer is not duplicated: the Assertion joins it, its review
  gets the reason `layer_conflict` (and so is `needs_human_review`), and a machine-reviewed
  edge goes to the exceptions queue (`relationship.layer_conflict`). An owner's decision
  stands; the reason shows on the edge. A conflicted edge is not lifted by a later passing
  witness: only the owner settles it.
- Edges recorded before migration 0055 that share an identity and differ by layer are left
  as they are (`legacy_layer_duplicate`). New Evidence joins the one with its layer, else
  the oldest (with `layer_conflict` when it brings another layer).

**Owner review** (`Relationships.review`): the owner may approve or reject any Relationship,
whatever its state (`relationship.approved`, `relationship.rejected`), with an optional note.
Repeating the current decision is not a transition (409 `invalid_transition`).
"""

import uuid
from dataclasses import dataclass, replace
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


LAYER_CONFLICT = "layer_conflict"


@dataclass(frozen=True)
class Edge:
    """What an eligible Assertion claims: the edge's identity (subject, predicate, object),
    and the layer the Assertion brings to it (None: none)."""

    subject_company_id: uuid.UUID
    predicate: str
    object_company_id: uuid.UUID | None
    object_text: str | None
    layer: str | None

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
    reviewer_direction: str | None = None
    reviewer_hedge: str | None = None
    reviewer_layer: str | None = None
    reviewer_suggested_layer: str | None = None
    reviewer_reasoning: str | None = None
    # The layer the Assertion's quote supports (None: none), whether or not it brings it.
    supported_layer: str | None = None


def record_machine_review(
    connection: Connection, actor: Actor, review: MachineReviewRecord, edge: Edge | None
) -> uuid.UUID | None:
    """Record `review` (and, for an eligible Assertion, link it to `edge`) in the caller's
    transaction. Returns the Relationship's ID (None: not eligible). An Assertion already
    reviewed is left as it is (returns its Relationship). An Assertion bringing another layer
    than its edge has is recorded `needs_human_review` with `layer_conflict`."""
    existing = connection.execute(
        text("SELECT relationship_id FROM relationship_review WHERE assertion_id = :id"),
        {"id": review.assertion_id},
    ).one_or_none()
    if existing is not None:
        return existing.relationship_id
    if (edge is None) != (review.outcome == "not_eligible"):
        raise ValueError("an eligible Assertion (and only one) has an edge")
    relationship_id: uuid.UUID | None = None
    if edge is not None:
        relationship_id, review = _link(connection, actor, review, edge)
    row = (
        connection.execute(
            text(
                "INSERT INTO relationship_review (id, assertion_id, relationship_id, job_id,"
                " run_id, role_call_id, verbatim_span, tier_a, directional_language,"
                " directional_cue, hedge, reviewer_status, reviewer_direction, reviewer_hedge,"
                " reviewer_layer, reviewer_suggested_layer, reviewer_reasoning, supported_layer,"
                " outcome, reasons)"
                " VALUES (:id, :assertion_id, :relationship_id, :job_id, :run_id, :role_call_id,"
                " :verbatim_span, :tier_a, :directional_language, :directional_cue, :hedge,"
                " :reviewer_status, :reviewer_direction, :reviewer_hedge, :reviewer_layer,"
                " :reviewer_suggested_layer, :reviewer_reasoning, :supported_layer, :outcome,"
                " :reasons) RETURNING *"
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
) -> tuple[uuid.UUID, MachineReviewRecord]:
    """Link the Assertion to the edge it names, creating it if there is none. Returns the
    edge and the review as it is to be recorded (with `layer_conflict` when the Assertion
    brings another layer than the edge has)."""
    identity = {
        "subject": edge.subject_company_id,
        "predicate": edge.predicate,
        "object_key": edge.object_key,
    }
    created = connection.execute(
        text(
            "INSERT INTO relationship (id, subject_company_id, predicate, object_company_id,"
            " object_text, object_key, layer, review_state) VALUES (:id, :subject, :predicate,"
            " :object, :object_text, :object_key, :layer, :state)"
            " ON CONFLICT (subject_company_id, predicate, object_key)"
            " WHERE NOT legacy_layer_duplicate DO NOTHING RETURNING id"
        ),
        {
            **identity,
            "id": uuid.uuid4(),
            "object": edge.object_company_id,
            "object_text": edge.object_text,
            "layer": edge.layer,
            "state": review.outcome,
        },
    ).scalar_one_or_none()
    if created is not None:
        _add_evidence(connection, created, review.assertion_id)
        _audit(connection, actor, "created", created, None)
        return created, review
    # The edge of this identity: the oldest, or, among edges recorded before 0055 that differ
    # only by layer, the one with the layer this Assertion brings.
    edges = connection.execute(
        text(
            "SELECT id, layer, review_state FROM relationship WHERE subject_company_id = :subject"
            " AND predicate = :predicate AND object_key = :object_key"
            " ORDER BY legacy_layer_duplicate, created_at, id FOR UPDATE"
        ),
        identity,
    ).all()
    found = next((row for row in edges if edge.layer is not None and row.layer == edge.layer), None)
    found = found or edges[0]
    conflict = edge.layer is not None and found.layer is not None and found.layer != edge.layer
    if conflict:
        review = replace(
            review, outcome="needs_human_review", reasons=[*review.reasons, LAYER_CONFLICT]
        )
    passed = review.outcome == "machine_reviewed"
    before = _snapshot(connection, found.id)
    _add_evidence(connection, found.id, review.assertion_id)
    connection.execute(
        text("UPDATE relationship SET updated_at = now() WHERE id = :id"), {"id": found.id}
    )
    current = _audit(connection, actor, "evidence_added", found.id, before)
    exception = found.review_state == "needs_human_review"
    if found.layer is None and edge.layer is not None and (passed or exception):
        connection.execute(
            text("UPDATE relationship SET layer = :layer WHERE id = :id"),
            {"id": found.id, "layer": edge.layer},
        )
        current = _audit(connection, actor, "layer_set", found.id, current)
    if conflict and found.review_state == "machine_reviewed":
        connection.execute(
            text("UPDATE relationship SET review_state = 'needs_human_review' WHERE id = :id"),
            {"id": found.id},
        )
        _audit(connection, actor, "layer_conflict", found.id, current)
    elif exception and passed and not _conflicted(connection, found.id):
        connection.execute(
            text("UPDATE relationship SET review_state = 'machine_reviewed' WHERE id = :id"),
            {"id": found.id},
        )
        _audit(connection, actor, "machine_reviewed", found.id, current)
    return found.id, review


def _conflicted(connection: Connection, relationship_id: uuid.UUID) -> bool:
    """Whether Evidence of the edge brought another layer than it has: only the owner settles
    that, so a later passing witness doesn't lift it."""
    return connection.execute(
        text(
            "SELECT EXISTS (SELECT FROM relationship_review WHERE relationship_id = :id"
            " AND :conflict = ANY(reasons))"
        ),
        {"id": relationship_id, "conflict": LAYER_CONFLICT},
    ).scalar_one()


def _audit(
    connection: Connection,
    actor: Actor,
    change: str,
    relationship_id: uuid.UUID,
    before: str | None,
) -> str:
    """Record `relationship.<change>` and return the edge's hash after it."""
    after = _snapshot(connection, relationship_id)
    record(
        connection,
        actor,
        f"relationship.{change}",
        entity_type="relationship",
        entity_id=str(relationship_id),
        old_hash=before,
        new_hash=after,
    )
    return after


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
