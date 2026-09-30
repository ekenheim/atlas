"""`/api/v1/replay-jobs`: replay the pipeline as of a cutoff in an isolated bank (§9.2;
ticket 22).

- `POST /replay-jobs` (202; `{cutoff, company_ids?, question_set?, max_source_versions?}`):
  records the replay with the Source Versions it may see (available at the cutoff; at most
  `ATLAS_REPLAY_MAX_SOURCE_VERSIONS`, the latest) and enqueues its `replay` job, which
  creates `atlas-replay-<id>` on the local Hindsight, retains them in order, waits for
  consolidation, asks the fixed question set and deletes the bank. 503 without
  `ATLAS_REPLAY_HINDSIGHT_URL`; 422 for a cutoff in the future, an unknown company or question
  set, or nothing available at the cutoff.
- `GET /replay-jobs`: replays, newest first.
- `GET /replay-jobs/{id}`: one replay: its stage and status, the Source Versions it saw, each
  question's recall and answer with resolved citations, its leakage counts (all 0 when
  nothing from after the cutoff was accepted) and when its bank was deleted.
- `POST /replay-jobs/{id}/cancel` (202): stop it; its next step deletes the bank (audited).
  409 once it is finishing or finished.
"""

import uuid
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
    error_responses,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.companies import UniverseConfigError, load_universe
from atlas.jobs import JobQueue
from atlas.replay import (
    QuestionSetError,
    ReplayJob,
    ReplayJobSummary,
    ReplayRefused,
    ReplayRequest,
    get_replay,
    list_replays,
    load_question_sets,
    request_cancel,
    request_replay,
)
from atlas.settings import Settings

Paged = Annotated[Pagination, Depends(pagination)]
NOT_CONFIGURED = error_responses(503)


def replay_router(engine: Engine, queue: JobQueue, actor: Actor, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/replay-jobs", tags=["replay"])

    def found(replay_id: uuid.UUID) -> ReplayJob | JSONResponse:
        with engine.connect() as connection:
            replay = get_replay(connection, replay_id)
        return replay if replay is not None else not_found("replay job")

    @router.post(
        "",
        status_code=202,
        response_model=ReplayJob,
        responses={**INVALID, **NOT_CONFIGURED},
    )
    def create(request: ReplayRequest) -> ReplayJob | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if not settings.replay_hindsight_url:
            return error_response(
                503,
                "replay_not_configured",
                "a replay needs ATLAS_REPLAY_HINDSIGHT_URL (the local Hindsight)",
            )
        try:
            replay_id = request_replay(
                engine,
                queue,
                actor,
                request,
                question_sets=load_question_sets(settings.replay_question_sets_config),
                universe=load_universe(settings.themes_config),
                max_source_versions=settings.replay_max_source_versions,
            )
        except ReplayRefused as error:
            return error_response(error.status, error.code, error.message)
        except (QuestionSetError, UniverseConfigError) as error:
            return error_response(503, "replay_misconfigured", str(error))
        return found(replay_id)

    @router.get("", response_model=Page[ReplayJobSummary])
    def listing(page: Paged) -> Page[ReplayJobSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_replays(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{replay_id}", response_model=ReplayJob, responses=NOT_FOUND)
    def replay(replay_id: uuid.UUID) -> ReplayJob | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return found(replay_id)

    @router.post(
        "/{replay_id}/cancel",
        status_code=202,
        response_model=ReplayJob,
        responses={**NOT_FOUND, **CONFLICT},
    )
    def cancel(replay_id: uuid.UUID) -> ReplayJob | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        asked = request_cancel(engine, actor, replay_id)
        if asked is None:
            return not_found("replay job")
        if not asked:
            return error_response(409, "replay_finished", "the replay is finishing or finished")
        return found(replay_id)

    return router
