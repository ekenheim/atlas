"""`/api/v1/facts`: record and read Facts (bottleneck-argument ticket 02).

- `POST /facts` (201): record a Fact; its quote must occur exactly at its offsets (422
  `quote_mismatch`) and a quantity's number must occur in the quote (422
  `quantity_not_in_quote`); an unknown step or status is 422 `invalid_request`
- `GET /facts?company_id=&step=&investigation_id=` (oldest first), `GET /facts/{id}`
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import (
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.archive import Archive
from atlas.assertions import AssertionNotFound, AssertionRefused
from atlas.audit import Actor
from atlas.facts import Fact, FactCreate, FactRecorded, Facts, FactStep, get_fact, list_facts

Paged = Annotated[Pagination, Depends(pagination)]


def facts_router(engine: Engine, archive: Archive, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/facts", tags=["facts"])
    service = Facts(engine, archive, actor)

    @router.get("", response_model=Page[Fact], responses=INVALID)
    def facts(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        company_id: uuid.UUID | None = None,
        step: FactStep | None = None,
        investigation_id: uuid.UUID | None = None,
    ) -> Page[Fact]:
        with engine.connect() as connection:
            items, total = list_facts(
                connection,
                company_id=company_id,
                step=step,
                investigation_id=investigation_id,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{fact_id}", response_model=Fact, responses={**NOT_FOUND, **INVALID})
    def fact(fact_id: uuid.UUID) -> Fact | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_fact(connection, fact_id)
        return found if found is not None else not_found("fact")

    @router.post("", status_code=201, response_model=FactRecorded, responses=INVALID)
    def create(request: FactCreate) -> FactRecorded | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.create(request)
        except AssertionNotFound:
            return not_found("fact")
        except AssertionRefused as refusal:
            return error_response(422, refusal.code, refusal.message)

    return router
