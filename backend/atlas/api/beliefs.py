"""`/api/v1/beliefs`: Beliefs (beliefs ticket 02).

- `POST /beliefs` (201): propose; refused 422 `no_load_bearing_citation` without a load-bearing
  citation of positive valence; born `unproven`
- `POST /beliefs/{id}/cite`, `/judge` (an author's judgement; clears open flags), `/supersede`
- `GET /beliefs?theme=&step=&company_id=&judgement=&status=&flagged=&as_of=`,
  `GET /beliefs/{id}[?as_of=]` (citations with their quotes, spans and dates)

Errors use the envelope: 404 `not_found`, 409 `belief_not_active` / `already_cited`, 422.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
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
from atlas.beliefs.service import (
    Belief,
    BeliefJudge,
    BeliefNotActive,
    BeliefNotFound,
    BeliefPropose,
    BeliefRefused,
    Beliefs,
    BeliefSummary,
    BeliefSupersede,
    CitationIn,
    get_belief,
    list_beliefs,
)

Paged = Annotated[Pagination, Depends(pagination)]


def _refused(refusal: BeliefRefused) -> JSONResponse:
    status = 409 if refusal.code == "already_cited" else 422
    return error_response(status, refusal.code, refusal.message)


def beliefs_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/beliefs", tags=["beliefs"])
    service = Beliefs(engine, actor)

    @router.get("", response_model=Page[BeliefSummary], responses=INVALID)
    def beliefs(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: str | None = None,
        step: str | None = None,
        company_id: uuid.UUID | None = None,
        judgement: str | None = None,
        status: str | None = None,
        flagged: bool | None = None,
        as_of: datetime | None = None,
    ) -> Page[BeliefSummary]:
        with engine.connect() as connection:
            items, total = list_beliefs(
                connection,
                theme=theme,
                step=step,
                company_id=company_id,
                judgement=judgement,
                status=status,
                flagged=flagged,
                as_of=as_of,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{belief_id}", response_model=Belief, responses={**NOT_FOUND, **INVALID})
    def belief(belief_id: uuid.UUID, as_of: datetime | None = None) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_belief(connection, belief_id, as_of=as_of)
        return found if found is not None else not_found("belief")

    @router.post("", status_code=201, response_model=Belief, responses=INVALID)
    def propose(request: BeliefPropose) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.propose(request)
        except BeliefRefused as refusal:
            return _refused(refusal)

    @router.post(
        "/{belief_id}/cite", response_model=Belief, responses={**NOT_FOUND, **CONFLICT, **INVALID}
    )
    def cite(belief_id: uuid.UUID, request: CitationIn) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.cite(belief_id, request))

    @router.post(
        "/{belief_id}/judge", response_model=Belief, responses={**NOT_FOUND, **CONFLICT, **INVALID}
    )
    def judge(belief_id: uuid.UUID, request: BeliefJudge) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.judge(belief_id, request))

    @router.post(
        "/{belief_id}/supersede",
        response_model=Belief,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def supersede(belief_id: uuid.UUID, request: BeliefSupersede) -> Belief | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _run(lambda: service.supersede(belief_id, request))

    return router


def _run(action: Callable[[], Belief]) -> Belief | JSONResponse:
    try:
        return action()
    except BeliefNotFound:
        return not_found("belief")
    except BeliefNotActive:
        return error_response(409, "belief_not_active", "the Belief is superseded or withdrawn")
    except BeliefRefused as refusal:
        return _refused(refusal)
