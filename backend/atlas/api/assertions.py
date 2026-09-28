"""`/api/v1/assertions`: record, list and review Assertions (spec Part A, stories 37-42).

- `POST /assertions` (201): record an Assertion; its quote must occur exactly at its
  offsets in the cited Source Version's parsed text (422 `quote_mismatch` otherwise)
- `POST /assertions/{id}/review`: move it to a new review state, or supersede it
  (409 `invalid_transition` for a transition build plan §5.4 does not allow)
- `GET /assertions?company_id=&review_state=&source_version_id=` (oldest first), and
  `GET /assertions/{id}`

Mutations return the Assertion and the ID of the audit event that recorded the change.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import (
    NOT_FOUND,
    ErrorEnvelope,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.archive import Archive
from atlas.assertions import (
    Assertion,
    AssertionCreate,
    AssertionNotFound,
    AssertionRecorded,
    AssertionRefused,
    AssertionReview,
    Assertions,
    InvalidTransition,
    ReviewState,
    get_assertion,
    list_assertions,
)
from atlas.audit import Actor

Paged = Annotated[Pagination, Depends(pagination)]

_INVALID: dict[int | str, dict[str, Any]] = {422: {"model": ErrorEnvelope}}
_CONFLICT: dict[int | str, dict[str, Any]] = {409: {"model": ErrorEnvelope}}


def _refused(refusal: AssertionRefused) -> JSONResponse:
    if isinstance(refusal, AssertionNotFound):
        status = 404
    elif isinstance(refusal, InvalidTransition):
        status = 409
    else:
        status = 422
    return error_response(status, refusal.code, refusal.message)


def assertions_router(engine: Engine, archive: Archive, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/assertions", tags=["assertions"])
    service = Assertions(engine, archive, actor)

    @router.get("", response_model=Page[Assertion], responses=_INVALID)
    def assertions(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        company_id: Annotated[
            uuid.UUID | None, Query(description="the company as subject or object")
        ] = None,
        review_state: ReviewState | None = None,
        source_version_id: uuid.UUID | None = None,
    ) -> Page[Assertion]:
        with engine.connect() as connection:
            items, total = list_assertions(
                connection,
                company_id=company_id,
                review_state=review_state,
                source_version_id=source_version_id,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{assertion_id}", response_model=Assertion, responses={**NOT_FOUND, **_INVALID})
    def assertion(assertion_id: uuid.UUID) -> Assertion | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_assertion(connection, assertion_id)
        return found if found is not None else not_found("assertion")

    @router.post("", status_code=201, response_model=AssertionRecorded, responses=_INVALID)
    def create(request: AssertionCreate) -> AssertionRecorded | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.create(request)
        except AssertionRefused as refusal:
            return _refused(refusal)

    @router.post(
        "/{assertion_id}/review",
        response_model=AssertionRecorded,
        responses={**NOT_FOUND, **_CONFLICT, **_INVALID},
    )
    def review(  # pyright: ignore[reportUnusedFunction]
        assertion_id: uuid.UUID, request: AssertionReview
    ) -> AssertionRecorded | JSONResponse:
        try:
            return service.review(assertion_id, request)
        except AssertionRefused as refusal:
            return _refused(refusal)

    return router
