"""`GET /api/v1/archive-search`: the archive's term search over some companies' parsed English
Source Versions available at an as-of time (`atlas.research.archive_search`), read-only.

`q` is the query (its content words are searched), `company_id` repeats for each company,
`as_of` defaults to now, `top` (20) bounds the hits and `per_document` (3) the hits from one
document. Each hit names its Source Version, section anchor, offsets in the named parse and
BM25 score. Refusals: 422 `unknown_company`, `invalid_request`.

`GET /api/v1/archive-documents` (the research agents' "what is new", MCP `newest_documents`):
the documents the search would search at `as_of`, newest first, with `since` and `kind` (a form,
document or source type, repeated) filters.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import INVALID, error_response
from atlas.archive import Archive
from atlas.research.archive_search import (
    ArchiveDocuments,
    ArchiveSearch,
    UnknownCompany,
    archive_documents,
    archive_search,
)


def archive_search_router(engine: Engine, archive: Archive) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["archive-search"])

    @router.get("/archive-search", response_model=ArchiveSearch, responses=INVALID)
    def search(  # pyright: ignore[reportUnusedFunction]
        q: Annotated[str, Query(min_length=1, description="the query")],
        company_id: Annotated[
            list[uuid.UUID], Query(min_length=1, description="a company to search; repeat")
        ],
        as_of: Annotated[datetime | None, Query(description="default: now")] = None,
        top: Annotated[int, Query(ge=1, le=200)] = 20,
        per_document: Annotated[int, Query(ge=1, le=50)] = 3,
        session_id: Annotated[
            uuid.UUID | None,
            Query(description="the research session asking (web pages: see the module)"),
        ] = None,
    ) -> ArchiveSearch | JSONResponse:
        try:
            return archive_search(
                engine,
                archive,
                q,
                company_id,
                as_of or datetime.now(UTC),
                top,
                per_document,
                session_id,
            )
        except UnknownCompany as refused:
            return error_response(422, "unknown_company", str(refused))

    @router.get("/archive-documents", response_model=ArchiveDocuments, responses=INVALID)
    def documents(  # pyright: ignore[reportUnusedFunction]
        company_id: Annotated[
            list[uuid.UUID], Query(min_length=1, description="a company; repeat")
        ],
        as_of: Annotated[datetime | None, Query(description="default: now")] = None,
        since: Annotated[
            datetime | None, Query(description="only documents public at or after this time")
        ] = None,
        kind: Annotated[
            list[str] | None,
            Query(description="a form, document or source type to keep (10-Q, 8-K, transcript)"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        session_id: Annotated[
            uuid.UUID | None,
            Query(description="the research session asking (web pages: see the module)"),
        ] = None,
    ) -> ArchiveDocuments | JSONResponse:
        try:
            return archive_documents(
                engine, company_id, as_of or datetime.now(UTC), since, kind or (), limit, session_id
            )
        except UnknownCompany as refused:
            return error_response(422, "unknown_company", str(refused))

    return router
