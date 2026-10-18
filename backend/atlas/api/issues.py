"""`/api/v1/issues`: the research frontier (beliefs ticket 04).

- `POST /issues` (201): open an Issue (`kind`, `theme`, `priority`, `company_ids`, optional
  `narrows` and `requires`, and for a `question` the archive-signal `lead_id` it escalates: that
  makes a call, 422 `unknown_lead` for any other lead)
- `POST /issues/{id}/edges`: add `narrows` or `requires` to a parent; 409 `issue_cycle`
- `POST /issues/{id}/complete|abandon`: close an active Issue (409 `issue_not_active`)
- `POST /issues/{id}/produced`: record a Belief or a Fact it produced
- `GET /issues?theme=&status=`, `GET /issues/{id}` (also its `edges`, from both ends: kind,
  direction `parent`|`child`, the other Issue's id, title and status; ticket 32)
- `GET /issues/next?theme=`: the next action by rule (`atlas.issues.next_issue`)

An **isolated** session (ticket 29a, the early-call scorecard) has no Issues: `POST /issues` with
its `produced_by`, and `GET /issues` and `GET /issues/next` with its `session_id`, are 422
`isolated_session` (its question and open questions would be the next run's frontier, and a
question with a `lead_id` makes a call), and closing it creates none.

Every write is audited. Errors use the envelope.
"""

import uuid
from pathlib import Path
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
from atlas.issues import (
    Issue,
    IssueCreate,
    IssueCycle,
    IssueDetail,
    IssueEdgeCreate,
    IssueNotFound,
    IssueNotOpen,
    IssueProductCreate,
    Issues,
    NextIssue,
    UnknownCompany,
    UnknownLead,
    UnknownProduct,
    get_issue_detail,
    list_issues,
    next_issue,
)
from atlas.issues.service import IssueStatus
from atlas.sessions import session_is_isolated

Paged = Annotated[Pagination, Depends(pagination)]


def issues_router(engine: Engine, actor: Actor, themes_config: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/issues", tags=["issues"])
    service = Issues(engine, actor, themes_config)

    def isolated_refusal(session_id: uuid.UUID | None) -> JSONResponse | None:
        with engine.connect() as connection:
            isolated = session_is_isolated(connection, session_id)
        if not isolated:
            return None
        return error_response(
            422,
            "isolated_session",
            "an isolated session (the early-call scorecard) has no Issues: it starts from"
            " nothing and leaves nothing for others",
        )

    @router.get("", response_model=Page[Issue], responses=INVALID)
    def issues(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: str | None = None,
        status: IssueStatus | None = None,
        session_id: uuid.UUID | None = None,
    ) -> Page[Issue] | JSONResponse:
        if (refused := isolated_refusal(session_id)) is not None:
            return refused
        with engine.connect() as connection:
            items, total = list_issues(
                connection, theme=theme, status=status, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/next", response_model=NextIssue, responses=INVALID)
    def next_action(theme: str, session_id: uuid.UUID | None = None) -> NextIssue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if (refused := isolated_refusal(session_id)) is not None:
            return refused
        with engine.connect() as connection:
            return next_issue(connection, theme)

    @router.get("/{issue_id}", response_model=IssueDetail, responses={**NOT_FOUND, **INVALID})
    def issue(issue_id: uuid.UUID) -> IssueDetail | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_issue_detail(connection, issue_id)
        return found if found is not None else not_found("issue")

    @router.post(
        "", status_code=201, response_model=Issue, responses={**NOT_FOUND, **INVALID, **CONFLICT}
    )
    def create(request: IssueCreate) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if (refused := isolated_refusal(request.produced_by)) is not None:
            return refused
        try:
            return service.create(request)
        except IssueNotFound:
            return error_response(422, "unknown_issue", "narrows or requires names no Issue")
        except UnknownCompany as error:
            return error_response(422, "unknown_company", str(error))
        except UnknownLead as error:
            return error_response(422, "unknown_lead", str(error))
        except IssueCycle as error:
            return error_response(409, "issue_cycle", str(error))

    @router.post(
        "/{issue_id}/edges", response_model=Issue, responses={**NOT_FOUND, **INVALID, **CONFLICT}
    )
    def add_edge(issue_id: uuid.UUID, request: IssueEdgeCreate) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.add_edge(issue_id, request)
        except IssueNotFound:
            return not_found("issue")
        except IssueCycle as error:
            return error_response(409, "issue_cycle", str(error))

    def closer(issue_id: uuid.UUID, abandon: bool) -> Issue | JSONResponse:
        try:
            return service.abandon(issue_id) if abandon else service.complete(issue_id)
        except IssueNotFound:
            return not_found("issue")
        except IssueNotOpen as error:
            return error_response(409, "issue_not_active", str(error))

    @router.post("/{issue_id}/complete", response_model=Issue, responses={**NOT_FOUND, **CONFLICT})
    def complete(issue_id: uuid.UUID) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return closer(issue_id, False)

    @router.post("/{issue_id}/abandon", response_model=Issue, responses={**NOT_FOUND, **CONFLICT})
    def abandon(issue_id: uuid.UUID) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return closer(issue_id, True)

    @router.post("/{issue_id}/produced", response_model=Issue, responses={**NOT_FOUND, **INVALID})
    def produced(issue_id: uuid.UUID, request: IssueProductCreate) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.produced(issue_id, request)
        except IssueNotFound:
            return not_found("issue")
        except UnknownProduct as error:
            return error_response(422, "unknown_product", str(error))

    return router
