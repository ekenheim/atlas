"""`/api/v1/relationships`: the edge table, the exceptions queue and the owner's review.

- `GET /relationships?layer=&review_state=&predicate=&company_id=&sort=&order=`: the edge
  table (subject, predicate, object, layer, review state, Evidence and family counts),
  sorted by `sort` (`subject`, `predicate`, `object`, `layer` (edges with no layer, then
  upstream to downstream), `review_state`, `evidence_count`, `family_count`, `created_at`
  (default), `updated_at`). `layer` is a layer, or `none` for the edges that have no layer
- `GET /relationships/exceptions`: the exceptions queue: edges `needs_human_review`, oldest
  first, each with the reasons its machine reviews didn't pass
- `GET /relationships/layer-duplicates`: a read-only report for the owner: the edges
  recorded before the layer left an edge's identity (migration 0055) that share a subject,
  predicate and object and differ only by layer, grouped, oldest first. They are left as they
  are; no new one can be made
- `GET /relationships/{id}`: one edge with its Evidence: each supporting Assertion (its
  Source Version and exact span, to open in the source viewer), its source's tier and
  Evidence Family, and its machine review
- `POST /relationships/{id}/review`: the owner approves or rejects the edge
  (409 `invalid_transition` when it already is), audited

The review mutation returns the Relationship and the ID of the audit event that recorded it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import (
    CONFLICT,
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.relationships import (
    InvalidTransition,
    LayerDuplicates,
    LayerFilter,
    OwnerReview,
    Relationship,
    RelationshipDetail,
    RelationshipNotFound,
    RelationshipRecorded,
    RelationshipRefused,
    Relationships,
    RelationshipState,
    SortKey,
    SortOrder,
    get_relationship_detail,
    layer_duplicates,
    list_relationships,
)

Paged = Annotated[Pagination, Depends(pagination)]


def relationships_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/relationships", tags=["relationships"])
    service = Relationships(engine, actor)

    @router.get("", response_model=Page[Relationship], responses=INVALID)
    def relationships(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        layer: Annotated[
            LayerFilter | None,
            Query(description="a layer, or `none` for the edges that have no layer"),
        ] = None,
        review_state: RelationshipState | None = None,
        predicate: str | None = None,
        company_id: Annotated[
            uuid.UUID | None, Query(description="the company as subject or object")
        ] = None,
        sort: SortKey = "created_at",
        order: SortOrder = "asc",
    ) -> Page[Relationship]:
        with engine.connect() as connection:
            items, total = list_relationships(
                connection,
                layer=layer,
                review_state=review_state,
                predicate=predicate,
                company_id=company_id,
                sort=sort,
                order=order,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/exceptions", response_model=Page[Relationship], responses=INVALID)
    def exceptions(page: Paged) -> Page[Relationship]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_relationships(
                connection,
                review_state="needs_human_review",
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/layer-duplicates", response_model=list[LayerDuplicates])
    def duplicates() -> list[LayerDuplicates]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            return layer_duplicates(connection)

    @router.get(
        "/{relationship_id}",
        response_model=RelationshipDetail,
        responses={**NOT_FOUND, **INVALID},
    )
    def relationship(  # pyright: ignore[reportUnusedFunction]
        relationship_id: uuid.UUID,
    ) -> RelationshipDetail | JSONResponse:
        with engine.connect() as connection:
            found = get_relationship_detail(connection, relationship_id)
        return found if found is not None else not_found("relationship")

    @router.post(
        "/{relationship_id}/review",
        response_model=RelationshipRecorded,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def review(  # pyright: ignore[reportUnusedFunction]
        relationship_id: uuid.UUID, request: OwnerReview
    ) -> RelationshipRecorded | JSONResponse:
        try:
            return service.review(relationship_id, request)
        except RelationshipRefused as refusal:
            status = 404 if isinstance(refusal, RelationshipNotFound) else 422
            if isinstance(refusal, InvalidTransition):
                status = 409
            return error_response(status, refusal.code, refusal.message)

    return router
