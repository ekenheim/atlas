"""The read side of Relationships: the edge table (sortable, filterable), one edge with its
Evidence and their machine reviews, and the exceptions queue.

**Counts.** `evidence_count` is the number of supporting Assertions that are not rejected or
superseded; `family_count` the number of distinct Evidence Families among their Source
Versions (a version in no family counts as its own). A family is one witness, so
`family_count` is the number of independent witnesses.

**Reasons.** `review_reasons` are the reason codes of the edge's machine reviews that didn't
pass, first occurrence first: why it is (or was) an exception.

**Layers** (memory-directed reading ticket 08). An edge may have no layer (`layer` null): the
`layer` filter takes `none` for those, and they sort before the layers. `layer_duplicates`
is the read-only report of the edges recorded before migration 0055 that share a subject,
predicate and object and differ only by layer: they are left as they are, and no new one can
be made.

**Company-level edges** (memory-directed reading ticket 09). An edge may have no object:
a company's own `capacity_constrained` statement that names no product (`company_level`
true; object company, name and text null; no layer). There is at most one per company; it
is among the company's edges like any other, and sorted by object it comes first.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import Connection, text

from atlas.assertions import EpistemicType, ReviewState
from atlas.claims.predicates import LAYERS
from atlas.companies import Layer

RelationshipState = Literal["machine_reviewed", "needs_human_review", "approved", "rejected"]
ReviewerStatus = Literal["answered", "skipped", "quarantined", "no_answer"]
MachineOutcome = Literal["machine_reviewed", "needs_human_review", "not_eligible"]
SortKey = Literal[
    "subject",
    "predicate",
    "object",
    "layer",
    "review_state",
    "evidence_count",
    "family_count",
    "created_at",
    "updated_at",
]
SortOrder = Literal["asc", "desc"]
# The edge table's layer filter: a layer, or `none` for the edges that have no layer.
LayerFilter = Layer | Literal["none"]

# Layers sort upstream to downstream (the taxonomy's order), not alphabetically.
_LAYER_ORDER = ", ".join(f"'{layer.name}'" for layer in LAYERS)
_SORT_COLUMNS: dict[str, str] = {
    "subject": "subject_name",
    "predicate": "predicate",
    "object": "object_sort",
    "layer": "layer_rank",
    "review_state": "review_state",
    "evidence_count": "evidence_count",
    "family_count": "family_count",
    "created_at": "created_at",
    "updated_at": "updated_at",
}


class Relationship(BaseModel):
    id: uuid.UUID
    subject_company_id: uuid.UUID
    subject_name: str
    predicate: str
    object_company_id: uuid.UUID | None
    object_name: str | None  # the object company's display name
    object_text: str | None  # the object product, material or technology
    # True for the subject's company-level edge: it has no object at all (`object_company_id`,
    # `object_name` and `object_text` are null) and no layer. Only `capacity_constrained`.
    company_level: bool
    layer: Layer | None  # null: no Evidence of the edge names a layer
    products: list[str]
    review_state: RelationshipState
    review_reasons: list[str]
    evidence_count: int
    family_count: int
    reviewed_by: str | None  # the owner's decision: who, when, and why
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceAssertion(BaseModel):
    """The supporting Assertion and the span it quotes (open it in the source viewer)."""

    id: uuid.UUID
    source_version_id: uuid.UUID
    quote: str
    span_start: int
    span_end: int
    page_or_anchor: str | None
    epistemic_type: EpistemicType
    review_state: ReviewState
    extractor_version: str
    created_by: str


class MachineReview(BaseModel):
    id: uuid.UUID
    verbatim_span: bool | None
    tier_a: bool | None
    directional_language: Literal["explicit", "hedged", "absent"] | None
    directional_cue: str | None
    hedge: str | None
    reviewer_status: ReviewerStatus
    # The overall verdict of reviews under `reviewer.v3` and earlier; null from `reviewer.v4`
    # on, where each check is answered on its own (`reviewer_direction`, `reviewer_hedge`,
    # `reviewer_layer`).
    reviewer_verdict: Literal["confirmed", "rejected", "uncertain"] | None
    reviewer_direction: Literal["as_proposed", "reversed", "undirected", "not_stated"] | None
    reviewer_hedge: Literal["none", "hedged"] | None
    reviewer_layer: Literal["correct", "wrong", "unclear", "not_proposed"] | None
    reviewer_suggested_layer: str | None
    # The layer the Assertion's quote supports (null: none): what it would bring to the edge.
    supported_layer: str | None
    reviewer_reasoning: str | None
    outcome: MachineOutcome
    reasons: list[str]
    job_id: uuid.UUID | None
    run_id: uuid.UUID | None
    role_call_id: uuid.UUID | None
    created_at: datetime


class RelationshipEvidence(BaseModel):
    assertion: EvidenceAssertion
    source_document_id: uuid.UUID
    source_title: str
    publisher: str
    source_tier: str
    evidence_family_id: uuid.UUID | None
    added_at: datetime
    review: MachineReview | None


class RelationshipDetail(Relationship):
    evidence: list[RelationshipEvidence]


_BASE = f"""
    SELECT r.id, r.subject_company_id, s.display_name AS subject_name, r.predicate,
           r.object_company_id, o.display_name AS object_name, r.object_text,
           (r.object_company_id IS NULL AND r.object_text IS NULL) AS company_level, r.layer,
           coalesce(ev.products, '{{}}') AS products, r.review_state,
           coalesce(ev.evidence_count, 0) AS evidence_count,
           coalesce(ev.family_count, 0) AS family_count,
           r.reviewed_by, r.reviewed_at, r.review_note, r.created_at, r.updated_at,
           coalesce(o.display_name, r.object_text, '') AS object_sort,
           coalesce(array_position(ARRAY[{_LAYER_ORDER}], r.layer), 0) AS layer_rank
    FROM relationship r
    JOIN company s ON s.id = r.subject_company_id
    LEFT JOIN company o ON o.id = r.object_company_id
    LEFT JOIN LATERAL (
        SELECT count(*) AS evidence_count,
               count(DISTINCT coalesce(m.evidence_family_id, a.source_version_id))
                   AS family_count,
               array_agg(DISTINCT a.value_json ->> 'product')
                   FILTER (WHERE a.value_json ->> 'product' IS NOT NULL) AS products
        FROM relationship_assertion ra
        JOIN assertion a ON a.id = ra.assertion_id
        LEFT JOIN evidence_family_member m ON m.source_version_id = a.source_version_id
        WHERE ra.relationship_id = r.id
          AND a.verification_status NOT IN ('rejected', 'superseded')
    ) ev ON true
"""  # noqa: S608 (constant fragments)

# Each filter applies only when its parameter is set.
_FILTER = """
    WHERE (CAST(:layer AS text) IS NULL OR layer = :layer
           OR (:layer = 'none' AND layer IS NULL))
      AND (CAST(:state AS text) IS NULL OR review_state = :state)
      AND (CAST(:predicate AS text) IS NULL OR predicate = :predicate)
      AND (CAST(:company AS uuid) IS NULL
           OR subject_company_id = :company OR object_company_id = :company)
"""


def list_relationships(
    connection: Connection,
    *,
    layer: LayerFilter | None = None,
    review_state: RelationshipState | None = None,
    predicate: str | None = None,
    company_id: uuid.UUID | None = None,
    sort: SortKey = "created_at",
    order: SortOrder = "asc",
    limit: int,
    offset: int,
) -> tuple[list[Relationship], int]:
    """The edge table, sorted by `sort` (`order`), then oldest first. A company's edges are
    those naming it as subject or object. `layer` `none` is the edges with no layer; sorted by
    layer, those come before the layers (after them when descending)."""
    params: dict[str, Any] = {
        "layer": layer,
        "state": review_state,
        "predicate": predicate,
        "company": company_id,
        "limit": limit,
        "offset": offset,
    }
    direction = "DESC" if order == "desc" else "ASC"
    query = (
        f"SELECT * FROM ({_BASE}) q {_FILTER}"  # noqa: S608 (constant fragments)
        f" ORDER BY {_SORT_COLUMNS[sort]} {direction}, created_at, id LIMIT :limit OFFSET :offset"
    )
    total = connection.execute(
        text(f"SELECT count(*) FROM ({_BASE}) q {_FILTER}"),  # noqa: S608
        params,
    ).scalar_one()
    rows = [dict(row) for row in connection.execute(text(query), params).mappings()]
    return _with_reasons(connection, rows), total


class LayerDuplicates(BaseModel):
    """Edges recorded before migration 0055 that are one edge by today's identity (subject,
    predicate, object) and differ only by layer. The first is the one new Evidence joins
    unless it brings another of the group's layers."""

    subject_company_id: uuid.UUID
    subject_name: str
    predicate: str
    object_company_id: uuid.UUID | None
    object_name: str | None
    object_text: str | None
    layers: list[Layer | None]
    relationships: list[Relationship]  # oldest first


def layer_duplicates(connection: Connection) -> list[LayerDuplicates]:
    """The report of edges that differ only by layer, by subject, predicate and object; each
    group's edges oldest first. Read-only: they are never merged or deleted."""
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                f"SELECT q.*, r.object_key FROM ({_BASE}) q"  # noqa: S608 (constant fragments)
                " JOIN relationship r ON r.id = q.id"
                " WHERE (SELECT count(*) FROM relationship d"
                "   WHERE d.subject_company_id = r.subject_company_id"
                "   AND d.predicate = r.predicate AND d.object_key = r.object_key) > 1"
                " ORDER BY q.subject_name, q.predicate, r.object_key, q.created_at, q.id"
            )
        ).mappings()
    ]
    keys = {
        row["id"]: (row["subject_company_id"], row["predicate"], row["object_key"]) for row in rows
    }
    groups: dict[tuple[uuid.UUID, str, str], list[Relationship]] = {}
    for edge in _with_reasons(connection, rows):
        groups.setdefault(keys[edge.id], []).append(edge)
    return [
        LayerDuplicates(
            subject_company_id=edges[0].subject_company_id,
            subject_name=edges[0].subject_name,
            predicate=edges[0].predicate,
            object_company_id=edges[0].object_company_id,
            object_name=edges[0].object_name,
            object_text=edges[0].object_text,
            layers=[edge.layer for edge in edges],
            relationships=edges,
        )
        for edges in groups.values()
    ]


def get_relationship(connection: Connection, relationship_id: uuid.UUID) -> Relationship | None:
    row = (
        connection.execute(
            text(f"SELECT * FROM ({_BASE}) q WHERE id = :id"),  # noqa: S608
            {"id": relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _with_reasons(connection, [dict(row)])[0]


def get_relationship_detail(
    connection: Connection, relationship_id: uuid.UUID
) -> RelationshipDetail | None:
    found = get_relationship(connection, relationship_id)
    if found is None:
        return None
    reviews = {
        row["assertion_id"]: MachineReview.model_validate(dict(row))
        for row in connection.execute(
            text("SELECT * FROM relationship_review WHERE relationship_id = :id"),
            {"id": relationship_id},
        ).mappings()
    }
    evidence: list[RelationshipEvidence] = []
    for row in connection.execute(
        text(
            "SELECT a.id, a.source_version_id, a.quote, a.span_start, a.span_end,"
            " a.page_or_anchor, a.epistemic_type, a.verification_status AS review_state,"
            " a.extractor_version, a.created_by, d.id AS source_document_id,"
            " d.title AS source_title, d.publisher, d.source_tier, m.evidence_family_id,"
            " ra.added_at"
            " FROM relationship_assertion ra JOIN assertion a ON a.id = ra.assertion_id"
            " JOIN source_version v ON v.id = a.source_version_id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " LEFT JOIN evidence_family_member m ON m.source_version_id = v.id"
            " WHERE ra.relationship_id = :id ORDER BY ra.added_at, a.id"
        ),
        {"id": relationship_id},
    ).mappings():
        values = dict(row)
        evidence.append(
            RelationshipEvidence(
                assertion=EvidenceAssertion.model_validate(values),
                source_document_id=values["source_document_id"],
                source_title=values["source_title"],
                publisher=values["publisher"],
                source_tier=values["source_tier"],
                evidence_family_id=values["evidence_family_id"],
                added_at=values["added_at"],
                review=reviews.get(values["id"]),
            )
        )
    return RelationshipDetail(**found.model_dump(), evidence=evidence)


def supporting_assertion_ids(connection: Connection, relationship_id: uuid.UUID) -> list[str]:
    return [
        str(each)
        for each in connection.execute(
            text(
                "SELECT assertion_id FROM relationship_assertion WHERE relationship_id = :id"
                " ORDER BY added_at, assertion_id"
            ),
            {"id": relationship_id},
        ).scalars()
    ]


def _with_reasons(connection: Connection, rows: list[dict[str, Any]]) -> list[Relationship]:
    reasons: dict[uuid.UUID, list[str]] = {row["id"]: [] for row in rows}
    if rows:
        for relationship_id, codes in connection.execute(
            text(
                "SELECT relationship_id, reasons FROM relationship_review"
                " WHERE relationship_id = ANY(:ids) ORDER BY created_at, id"
            ),
            {"ids": list(reasons)},
        ).all():
            seen = reasons[relationship_id]
            seen.extend(code for code in codes if code not in seen)
    return [
        Relationship.model_validate(row | {"review_reasons": reasons[row["id"]]}) for row in rows
    ]
