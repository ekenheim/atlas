"""`/api/v1/proposed-updates`: later Evidence contradicting a published Hypothesis version
(spec §5.6, §5.7 "Contradiction flow"; ticket 21).

- `GET /proposed-updates[?hypothesis_id=&candidate_id=&state=]`, `GET /proposed-updates/{id}`
  and `GET /hypotheses/{id}/proposed-updates[?state=]`: each update's published version, the
  event (`trigger`), the contradicting Evidence, the findings it bears on, the Candidates it
  concerns and the owner's resolution, oldest first. `Hypothesis.open_proposed_updates`
  counts the open ones.
- `POST /proposed-updates/{id}/accept` (`{"note"?}`): start a correction: a new draft version
  from the latest one, its affected findings marked `needs_review`. 409 if the update isn't
  open or the Hypothesis is closed or rejected.
- `POST /proposed-updates/{id}/dismiss` (`{"reason"}`): keep the version as it is.

Both audited. Neither ever changes the published version or its Research Snapshot.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from atlas.api.common import (
    CONFLICT,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.hypotheses import HypothesisError
from atlas.proposed_updates.model import (
    ProposedUpdate,
    ProposedUpdateState,
    get_proposed_update,
    list_proposed_updates,
)
from atlas.proposed_updates.service import ProposedUpdates

Paged = Annotated[Pagination, Depends(pagination)]


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None, max_length=2000, description="the correction's note; default the summary"
    )


class DismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


def proposed_updates_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["proposed-updates"])
    updates = ProposedUpdates(engine)

    def found(proposed_update_id: uuid.UUID) -> ProposedUpdate | JSONResponse:
        with engine.connect() as connection:
            update = get_proposed_update(connection, proposed_update_id)
        return update if update is not None else not_found("proposed update")

    def page_of(
        page: Pagination,
        *,
        hypothesis_id: uuid.UUID | None,
        candidate_id: uuid.UUID | None,
        state: ProposedUpdateState | None,
    ) -> Page[ProposedUpdate]:
        with engine.connect() as connection:
            items, total = list_proposed_updates(
                connection,
                hypothesis_id=hypothesis_id,
                candidate_id=candidate_id,
                state=state,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/proposed-updates", response_model=Page[ProposedUpdate])
    def listing(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        hypothesis_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        state: ProposedUpdateState | None = None,
    ) -> Page[ProposedUpdate]:
        return page_of(page, hypothesis_id=hypothesis_id, candidate_id=candidate_id, state=state)

    @router.get(
        "/hypotheses/{hypothesis_id}/proposed-updates",
        response_model=Page[ProposedUpdate],
        responses=NOT_FOUND,
    )
    def of_hypothesis(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, page: Paged, state: ProposedUpdateState | None = None
    ) -> Page[ProposedUpdate] | JSONResponse:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT EXISTS (SELECT FROM hypothesis WHERE id = :id)"),
                {"id": hypothesis_id},
            ).scalar_one()
        if not exists:
            return not_found("hypothesis")
        return page_of(page, hypothesis_id=hypothesis_id, candidate_id=None, state=state)

    @router.get(
        "/proposed-updates/{proposed_update_id}",
        response_model=ProposedUpdate,
        responses=NOT_FOUND,
    )
    def proposed_update(proposed_update_id: uuid.UUID) -> ProposedUpdate | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return found(proposed_update_id)

    @router.post(
        "/proposed-updates/{proposed_update_id}/accept",
        response_model=ProposedUpdate,
        responses={**NOT_FOUND, **CONFLICT},
    )
    def accept(  # pyright: ignore[reportUnusedFunction]
        proposed_update_id: uuid.UUID, request: AcceptRequest
    ) -> ProposedUpdate | JSONResponse:
        note = request.note.strip() or None if request.note is not None else None
        try:
            updates.accept(actor, proposed_update_id, note)
        except HypothesisError as error:
            return error_response(error.status, error.code, error.message)
        return found(proposed_update_id)

    @router.post(
        "/proposed-updates/{proposed_update_id}/dismiss",
        response_model=ProposedUpdate,
        responses={**NOT_FOUND, **CONFLICT},
    )
    def dismiss(  # pyright: ignore[reportUnusedFunction]
        proposed_update_id: uuid.UUID, request: DismissRequest
    ) -> ProposedUpdate | JSONResponse:
        try:
            updates.dismiss(actor, proposed_update_id, request.reason.strip())
        except HypothesisError as error:
            return error_response(error.status, error.code, error.message)
        return found(proposed_update_id)

    return router
