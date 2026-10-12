"""`/api/v1/issues`: the research frontier (beliefs ticket 04).

- `POST /issues` (201): open an Issue (`kind`, `theme`, `priority`, `company_ids`, optional
  `narrows` and `requires`)
- `POST /issues/{id}/edges`: add `narrows` or `requires` to a parent; 409 `issue_cycle`
- `POST /issues/{id}/complete|abandon`: close an active Issue (409 `issue_not_active`)
- `POST /issues/{id}/produced`: record a Belief or a Fact it produced
- `GET /issues?theme=&status=`, `GET /issues/{id}`
- `GET /issues/next?theme=`: the next action by rule (`atlas.issues.next_issue`)

Every write is audited. Errors use the envelope.
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
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.issues import (
    Issue,
    IssueCreate,
    IssueCycle,
    IssueEdgeCreate,
    IssueNotFound,
    IssueNotOpen,
    IssueProductCreate,
    Issues,
    NextIssue,
    UnknownCompany,
    UnknownProduct,
    get_issue,
    list_issues,
    next_issue,
)
from atlas.issues.service import IssueStatus

Paged = Annotated[Pagination, Depends(pagination)]


def issues_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/issues", tags=["issues"])
    service = Issues(engine, actor)

    @router.get("", response_model=Page[Issue], responses=INVALID)
    def issues(  # pyright: ignore[reportUnusedFunction]
        page: Paged, theme: str | None = None, status: IssueStatus | None = None
    ) -> Page[Issue]:
        with engine.connect() as connection:
            items, total = list_issues(
                connection, theme=theme, status=status, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/next", response_model=NextIssue, responses=INVALID)
    def next_action(theme: str) -> NextIssue:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            return next_issue(connection, theme)

    @router.get("/{issue_id}", response_model=Issue, responses={**NOT_FOUND, **INVALID})
    def issue(issue_id: uuid.UUID) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_issue(connection, issue_id)
        return found if found is not None else not_found("issue")

    @router.post(
        "", status_code=201, response_model=Issue, responses={**NOT_FOUND, **INVALID, **CONFLICT}
    )
    def create(request: IssueCreate) -> Issue | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            return service.create(request)
        except IssueNotFound:
            return error_response(422, "unknown_issue", "narrows or requires names no Issue")
        except UnknownCompany as error:
            return error_response(422, "unknown_company", str(error))
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
