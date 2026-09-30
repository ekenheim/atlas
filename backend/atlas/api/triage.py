"""`/api/v1` retention triage (ticket 30): what was retained and skipped, and retain on demand.

- `GET /triage?source_version_id=&company_id=&decision=&category=&method=&effective=`: triage
  decisions, newest first; each says whether it is its section's effective (latest) one.
- `POST /source-versions/{id}/sections/{anchor}/retain` (`{reason, investigation_id?}`), 202:
  retain a section now (typically one triage skipped). The decision is recorded with who
  asked (the actor, and the investigation when one asked) and why, and a `retain` job is
  enqueued. 404 for an unknown version, section or investigation; 409 `not_retainable`,
  `linked` or `already_retained`.
- `GET /triage/audits?limit=&offset=`: triage audits (`atlas triage audit`, ticket 33), newest
  first: what was asked, the reader settings audited, status and progress.
- `GET /triage/audits/{id}`: one audit with its strata, every judged sample (the section, the
  triage decision, the full-section judge's decision and reason, agreement) and its summary
  (miss rate with a Wilson 95% interval, by length band, category, method and form, example
  misses).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
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
from atlas.archive import Archive
from atlas.audit import Actor
from atlas.retention import (
    RetainOnDemand,
    RetainRefused,
    RetainRequested,
    TriageAudit,
    TriageAuditRun,
    TriageDecision,
    get_audit,
    list_audits,
    list_decisions,
    request_retain,
)
from atlas.retention.decisions import Method, Verdict

Paged = Annotated[Pagination, Depends(pagination)]


def triage_router(engine: Engine, archive: Archive, actor: Actor, bank_id: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["triage"])

    @router.get("/triage", response_model=Page[TriageDecision], responses=INVALID)
    def triage_decisions(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        source_version_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        decision: Verdict | None = None,
        category: str | None = None,
        method: Method | None = None,
        effective: bool = Query(False, description="only each section's latest decision"),
    ) -> Page[TriageDecision]:
        with engine.connect() as connection:
            items, total = list_decisions(
                connection,
                source_version_id=source_version_id,
                company_id=company_id,
                decision=decision,
                category=category,
                method=method,
                effective_only=effective,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.post(
        "/source-versions/{version_id}/sections/{anchor}/retain",
        response_model=RetainRequested,
        status_code=202,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def retain_section(  # pyright: ignore[reportUnusedFunction]
        version_id: uuid.UUID, anchor: str, request: RetainOnDemand
    ) -> RetainRequested | JSONResponse:
        try:
            return request_retain(
                engine, archive, actor, version_id, anchor, request, bank_id=bank_id
            )
        except RetainRefused as refused:
            return error_response(refused.status, refused.code, refused.message)

    @router.get("/triage/audits", response_model=Page[TriageAuditRun])
    def triage_audits(page: Paged) -> Page[TriageAuditRun]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_audits(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/triage/audits/{audit_id}", response_model=TriageAudit, responses=NOT_FOUND)
    def triage_audit(audit_id: uuid.UUID) -> TriageAudit | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_audit(connection, audit_id)
        return found if found is not None else not_found("triage audit")

    return router
