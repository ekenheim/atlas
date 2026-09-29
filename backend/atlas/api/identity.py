"""`/api/v1/identity-mappings`: the entity-resolution review queue.

- `GET /identity-mappings?review_state=&company_id=&kind=`: each identifier entity resolution
  proposed for a company (CIK, LEI, or a TICKER@MIC listing) with its tier, source, when it
  was observed, the reasons it needs review, and the evidence chain; `review_state=pending`
  is the owner's queue. `GET /identity-mappings/{id}` reads one.
- `POST /identity-mappings/{id}/confirm` applies a pending mapping (sets the company's CIK or
  LEI, or the listing's security) and answers the company's other pending CIKs or LEIs;
  409 `identity_conflict` if it contradicts what is stored.
- `POST /identity-mappings/{id}/reject` rejects it with a reason (kept).

Both are audited; 409 `invalid_transition` for a mapping that isn't pending.
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
from atlas.identity.service import (
    IdentityMapping,
    IdentityMappings,
    MappingConfirm,
    MappingRefused,
    MappingReject,
    MappingReviewed,
    ReviewState,
    get_mapping,
    list_mappings,
)

Paged = Annotated[Pagination, Depends(pagination)]


def identity_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/identity-mappings", tags=["identity"])
    service = IdentityMappings(engine, actor)

    @router.get("", response_model=Page[IdentityMapping], responses=INVALID)
    def mappings(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        review_state: ReviewState | None = None,
        company_id: uuid.UUID | None = None,
        kind: Annotated[str | None, Query(pattern="^(cik|lei|listing)$")] = None,
    ) -> Page[IdentityMapping]:
        with engine.connect() as connection:
            items, total = list_mappings(
                connection,
                review_state=review_state,
                company_id=company_id,
                kind=kind,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{mapping_id}", response_model=IdentityMapping, responses={**NOT_FOUND, **INVALID})
    def mapping(mapping_id: uuid.UUID) -> IdentityMapping | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_mapping(connection, mapping_id)
        return found if found is not None else not_found("identity mapping")

    @router.post(
        "/{mapping_id}/confirm",
        response_model=MappingReviewed,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def confirm(  # pyright: ignore[reportUnusedFunction]
        mapping_id: uuid.UUID, request: MappingConfirm
    ) -> MappingReviewed | JSONResponse:
        try:
            return service.confirm(mapping_id, request)
        except MappingRefused as refused:
            return error_response(refused.status, refused.code, refused.message)

    @router.post(
        "/{mapping_id}/reject",
        response_model=MappingReviewed,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def reject(  # pyright: ignore[reportUnusedFunction]
        mapping_id: uuid.UUID, request: MappingReject
    ) -> MappingReviewed | JSONResponse:
        try:
            return service.reject(mapping_id, request)
        except MappingRefused as refused:
            return error_response(refused.status, refused.code, refused.message)

    return router
