"""`/api/v1/candidates`: companies outside the universe that leads named (spec §8.3).

- `GET /candidates?state=&theme=`: Candidates, newest first, each with its resolution (tier,
  identifiers, evidence), proposed source path, the leads that named it and, once decided,
  who decided, when, and the company, ingest job or reject reason.
- `GET /candidates/{id}` reads one.
- `POST /candidates/{id}/commit` (`{slug?, display_name?, country?, layer?, cik?, note?}`):
  the company joins the universe (in the database, in the Candidate's theme) and its ingest
  is enqueued for its source path, or the Candidate records that no automated source
  exists yet; the Candidate becomes `investigating`. 409 `already_in_universe`,
  `slug_taken`, `country_required` or `cik_not_offered`.
- `POST /candidates/{id}/reject` (`{reason}`): the Candidate is kept, `rejected`, with the
  reason.

Both are audited; 409 `invalid_transition` for a Candidate that isn't a `lead`.
"""

import uuid
from collections.abc import Callable
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
from atlas.candidates import (
    Candidate,
    CandidateCommit,
    CandidateDecided,
    CandidateRefused,
    CandidateReject,
    Candidates,
    CandidateState,
    get_candidate,
    list_candidates,
)
from atlas.companies import Universe

Paged = Annotated[Pagination, Depends(pagination)]


def candidates_router(
    engine: Engine, actor: Actor, universe: Callable[[], Universe], *, ingest_lookback_days: int
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/candidates", tags=["candidates"])

    def service() -> Candidates:
        return Candidates(engine, actor, universe(), ingest_lookback_days=ingest_lookback_days)

    @router.get("", response_model=Page[Candidate], responses=INVALID)
    def candidates(  # pyright: ignore[reportUnusedFunction]
        page: Paged, state: CandidateState | None = None, theme: str | None = None
    ) -> Page[Candidate]:
        with engine.connect() as connection:
            items, total = list_candidates(
                connection, state=state, theme=theme, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{candidate_id}", response_model=Candidate, responses={**NOT_FOUND, **INVALID})
    def candidate(candidate_id: uuid.UUID) -> Candidate | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_candidate(connection, candidate_id)
        return found if found is not None else not_found("candidate")

    @router.post(
        "/{candidate_id}/commit",
        response_model=CandidateDecided,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def commit(  # pyright: ignore[reportUnusedFunction]
        candidate_id: uuid.UUID, request: CandidateCommit
    ) -> CandidateDecided | JSONResponse:
        try:
            return service().commit(candidate_id, request)
        except CandidateRefused as refused:
            return error_response(refused.status, refused.code, refused.message)

    @router.post(
        "/{candidate_id}/reject",
        response_model=CandidateDecided,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def reject(  # pyright: ignore[reportUnusedFunction]
        candidate_id: uuid.UUID, request: CandidateReject
    ) -> CandidateDecided | JSONResponse:
        try:
            return service().reject(candidate_id, request)
        except CandidateRefused as refused:
            return error_response(refused.status, refused.code, refused.message)

    return router
