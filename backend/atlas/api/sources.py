"""`/api/v1` reads of the company universe and the source ledger.

- `GET /companies`, `GET /companies/{id}`, `GET /companies/{id}/sources`
- `GET /sources/{id}`, `GET /sources/{id}/versions` (version history, oldest first)
- `GET /source-versions/{id}` (metadata, provenance and fetch observations)
- `GET /source-versions/{id}/content?kind=raw|parsed` (streamed from the archive)

Source content is untrusted data: raw bytes are served as a download under a sandboxing
Content-Security-Policy, never rendered on the application's origin.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.archive import Archive
from atlas.companies import Company, get_company, list_companies
from atlas.ledger import (
    ContentKind,
    SourceDocument,
    SourceVersionDetail,
    SourceVersionSummary,
    get_content,
    get_document,
    get_version,
    list_documents,
    list_versions,
)

_CHUNK = 64 * 1024
_UNTRUSTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}

Paged = Annotated[Pagination, Depends(pagination)]


def _chunks(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), _CHUNK):
        yield data[start : start + _CHUNK]


def sources_router(engine: Engine, archive: Archive) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["sources"])

    @router.get("/companies", response_model=Page[Company])
    def companies(page: Paged) -> Page[Company]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_companies(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/companies/{company_id}", response_model=Company, responses=NOT_FOUND)
    def company(company_id: uuid.UUID) -> Company | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_company(connection, company_id)
        return found if found is not None else not_found("company")

    @router.get(
        "/companies/{company_id}/sources",
        response_model=Page[SourceDocument],
        responses=NOT_FOUND,
    )
    def company_sources(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID, page: Paged
    ) -> Page[SourceDocument] | JSONResponse:
        with engine.connect() as connection:
            if get_company(connection, company_id) is None:
                return not_found("company")
            items, total = list_documents(
                connection, company_id, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/sources/{document_id}", response_model=SourceDocument, responses=NOT_FOUND)
    def source(document_id: uuid.UUID) -> SourceDocument | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_document(connection, document_id)
        return found if found is not None else not_found("source document")

    @router.get(
        "/sources/{document_id}/versions",
        response_model=Page[SourceVersionSummary],
        responses=NOT_FOUND,
    )
    def source_versions(  # pyright: ignore[reportUnusedFunction]
        document_id: uuid.UUID, page: Paged
    ) -> Page[SourceVersionSummary] | JSONResponse:
        with engine.connect() as connection:
            if get_document(connection, document_id) is None:
                return not_found("source document")
            items, total = list_versions(
                connection, document_id, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/source-versions/{version_id}", response_model=SourceVersionDetail, responses=NOT_FOUND
    )
    def source_version(version_id: uuid.UUID) -> SourceVersionDetail | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_version(connection, version_id)
        return found if found is not None else not_found("source version")

    @router.get(
        "/source-versions/{version_id}/content",
        response_class=StreamingResponse,
        response_model=None,
        responses={
            200: {"description": "The archived bytes (raw) or UTF-8 text (parsed)"},
            **NOT_FOUND,
        },
    )
    def source_version_content(  # pyright: ignore[reportUnusedFunction]
        version_id: uuid.UUID,
        kind: Annotated[ContentKind, Query(description="raw bytes or the parsed text")],
    ) -> StreamingResponse | JSONResponse:
        with engine.connect() as connection:
            content = get_content(connection, archive, version_id, kind)
        if content is None:
            return not_found("source version" if kind == "raw" else "parsed content")
        disposition = "attachment" if kind == "raw" else "inline"
        headers = {
            **_UNTRUSTED_HEADERS,
            "Content-Disposition": f'{disposition}; filename="{content.filename}"',
            "Content-Length": str(len(content.data)),
            "ETag": f'"{content.sha256}"',
            "X-Content-SHA256": content.sha256,
            # Set as stored: Starlette would otherwise add a charset the source never declared.
            "Content-Type": content.media_type,
        }
        return StreamingResponse(_chunks(content.data), headers=headers)

    return router
