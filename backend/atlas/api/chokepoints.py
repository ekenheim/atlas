"""`/api/v1/chokepoints` and `/api/v1/watch-runs`: the Chokepoint Watch's board and run record
(ticket W1).

- `GET /chokepoints?theme=&status=&session_id=`: the board, the latest event first. Each
  chokepoint is the fold of its events: constraint, layer, holders, `status` (`lead`,
  `candidate`, `thesis_ready` or `killed`, as last set), the six steps' statuses and evidence
  (**a constraint, b demand_vs_supply, c relief, d control, e capture, f invalidation**; a
  payload names a step by letter or name), kill criteria, relief horizon, crowding (context,
  never evidence) and the linked Issues. `stale` is derived (no `field_set` or `step_set` event
  for 56 days; a note or a status change does not count), never stored. `thesis_gate` says
  whether `thesis_ready` would be allowed now (`holds`, `missing`); a `thesis_ready` chokepoint
  whose gate no longer holds has `needs_review`. `?status=stale` and `?status=needs_review` list
  those, any other value filters the stored status. A `session_id` read is refused like a write
  (below).
- `POST /chokepoints` (201): create one (`theme`, `constraint`, `layer`, `holders`, and the
  `session_id` or `run_id` that made it); answers the chokepoint with its history.
- `GET /chokepoints/{id}`: the state and the history of every event.
- `POST /chokepoints/{id}/events`: append an event (`kind` `field_set`, `step_set`,
  `status_set` or `note`, its `payload`, a `reason`, the `session_id`). A list given in a payload
  (`holders`, `kill_criteria`, `issue_ids`, a step's `evidence`) **replaces the whole list**;
  `add_issue_ids` and `add_evidence` append. One event is one change: to change step a, b or d
  of a `thesis_ready` chokepoint to anything but `primary`, first move the status down (a
  `status_set`), then the step (`thesis_ready_step_locked`). With a `session_id` the session
  must be open, not isolated, of now (`not_prospective`: as-of more than 36 hours before now),
  of the chokepoint's theme (`other_theme`, as is an Issue's); a Fact, lead or Issue it cites
  must have been public or opened by its as-of time (an Issue its own session opened is fine;
  `created_after_as_of`), and a Fact of an isolated session is refused (`fact_not_in_session`);
  its actor is the event's actor unless one is given. Refusals (422): a
  `primary` or `contradicted` step without a Fact (`step_needs_fact`), a `lead` without a lead or
  an Issue (`step_needs_lead`), `killed` without a reason (`reason_required`), `thesis_ready`
  without steps a, b and d primary, a kill criterion and an open linked Issue
  (`thesis_not_ready`, with `missing`), a Fact public after the session's as-of time
  (`fact_available_after_as_of`), an unknown Fact, lead, Issue, session or run, an isolated
  session (`isolated_session`) and a payload that does not fit its kind (`invalid_payload`).
- `POST /watch-runs` (201), `GET /watch-runs?theme=`, `GET /watch-runs/{id}`: one run of the
  Watch with its memo (markdown), counts and tool calls, insert-only, the newest first.

Every write is audited. Errors use the envelope.
"""

import uuid
from datetime import UTC
from typing import Annotated, Literal

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
from atlas.chokepoints import (
    Chokepoint,
    ChokepointCreate,
    ChokepointDetail,
    ChokepointError,
    Chokepoints,
    EventCreate,
    WatchRun,
    WatchRunCreate,
    WatchRuns,
    check_read_session,
    get_chokepoint,
    get_watch_run,
    list_chokepoints,
    list_watch_runs,
)
from atlas.jobs.pacing import Clock, utc_now

Paged = Annotated[Pagination, Depends(pagination)]
type BoardFilter = Literal["lead", "candidate", "thesis_ready", "killed", "stale", "needs_review"]


def failed(error: ChokepointError) -> JSONResponse:
    return error_response(error.status, error.code, str(error), error.detail or None)


def chokepoints_router(engine: Engine, actor: Actor, clock: Clock = utc_now) -> APIRouter:
    router = APIRouter(prefix="/api/v1/chokepoints", tags=["chokepoints"])
    service = Chokepoints(engine, actor, clock)

    @router.get("", response_model=Page[Chokepoint], responses=INVALID)
    def board(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: str | None = None,
        status: BoardFilter | None = None,
        session_id: uuid.UUID | None = None,
    ) -> Page[Chokepoint] | JSONResponse:
        try:
            check_read_session(engine, session_id, clock().astimezone(UTC))
        except ChokepointError as error:
            return failed(error)
        with engine.connect() as connection:
            items, total = list_chokepoints(
                connection,
                clock().astimezone(UTC),
                theme=theme,
                status=status,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/{chokepoint_id}", response_model=ChokepointDetail, responses={**NOT_FOUND, **INVALID}
    )
    def read(  # pyright: ignore[reportUnusedFunction]
        chokepoint_id: uuid.UUID, session_id: uuid.UUID | None = None
    ) -> ChokepointDetail | JSONResponse:
        try:
            check_read_session(engine, session_id, clock().astimezone(UTC))
        except ChokepointError as error:
            return failed(error)
        with engine.connect() as connection:
            found = get_chokepoint(connection, chokepoint_id, clock().astimezone(UTC))
        return found if found is not None else not_found("chokepoint")

    @router.post("", status_code=201, response_model=ChokepointDetail, responses=INVALID)
    def create(request: ChokepointCreate) -> ChokepointDetail | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.create(request)
        except ChokepointError as error:
            return failed(error)

    @router.post(
        "/{chokepoint_id}/events",
        status_code=201,
        response_model=ChokepointDetail,
        responses={**NOT_FOUND, **INVALID},
    )
    def append(chokepoint_id: uuid.UUID, request: EventCreate) -> ChokepointDetail | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            state = service.append(chokepoint_id, request)
        except ChokepointError as error:
            return failed(error)
        return state if state is not None else not_found("chokepoint")

    return router


def watch_runs_router(engine: Engine, actor: Actor, clock: Clock = utc_now) -> APIRouter:
    router = APIRouter(prefix="/api/v1/watch-runs", tags=["chokepoints"])
    service = WatchRuns(engine, actor, clock)

    @router.get("", response_model=Page[WatchRun], responses=INVALID)
    def runs(  # pyright: ignore[reportUnusedFunction]
        page: Paged, theme: str | None = None, session_id: uuid.UUID | None = None
    ) -> Page[WatchRun] | JSONResponse:
        try:
            check_read_session(engine, session_id, clock().astimezone(UTC))
        except ChokepointError as error:
            return failed(error)
        with engine.connect() as connection:
            items, total = list_watch_runs(
                connection, theme=theme, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{run_id}", response_model=WatchRun, responses=NOT_FOUND)
    def read(run_id: uuid.UUID) -> WatchRun | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_watch_run(connection, run_id)
        return found if found is not None else not_found("watch run")

    @router.post("", status_code=201, response_model=WatchRun, responses=INVALID)
    def create(request: WatchRunCreate) -> WatchRun | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.create(request)
        except ChokepointError as error:
            return failed(error)

    return router
