"""`/api/v1/sessions`: research sessions (beliefs ticket 08).

- `POST /sessions` (201): open a Claude session (question, theme, seeds, as_of, model, actor)
- `POST /sessions/{id}/close`: set its usage, card (the argument plan's card shape) and
  markdown; 409 `session_closed` when it is closed already or is a pipeline session
- `GET /sessions?theme=` (newest first), `GET /sessions/{id}` (with its Facts)

A Fact joins a session through `POST /facts` (`session_id`). The pipeline's argument-plan
investigations list here too (`kind` `pipeline`). Errors use the envelope.
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
from atlas.audit import Actor
from atlas.sessions import (
    ResearchSession,
    SessionAlreadyClosed,
    SessionClose,
    SessionNotFound,
    SessionOpen,
    Sessions,
    SessionSummary,
    UnknownCompany,
    get_session,
    list_sessions,
)

Paged = Annotated[Pagination, Depends(pagination)]


def sessions_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
    service = Sessions(engine, actor)

    @router.get("", response_model=Page[SessionSummary], responses=INVALID)
    def sessions(page: Paged, theme: str | None = None) -> Page[SessionSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_sessions(
                connection, theme=theme, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{session_id}", response_model=ResearchSession, responses={**NOT_FOUND, **INVALID})
    def session(session_id: uuid.UUID) -> ResearchSession | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_session(connection, session_id)
        return found if found is not None else not_found("session")

    @router.post("", status_code=201, response_model=SessionSummary, responses=INVALID)
    def open_session(request: SessionOpen) -> SessionSummary | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.open(request)
        except UnknownCompany as error:
            return error_response(422, "unknown_company", str(error))

    @router.post(
        "/{session_id}/close",
        response_model=ResearchSession,
        responses={**NOT_FOUND, **INVALID},
    )
    def close(session_id: uuid.UUID, request: SessionClose) -> ResearchSession | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.close(session_id, request)
        except SessionNotFound:
            return not_found("session")
        except SessionAlreadyClosed:
            return error_response(409, "session_closed", "the session is closed already")

    return router
