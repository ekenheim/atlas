"""`/api/v1` reads of the company universe and the source ledger.

- `GET /companies?role=researched|counterparty`, `GET /companies/{id}`,
  `GET /companies/{id}/sources`
- `GET /sources/{id}`, `GET /sources/{id}/versions` (version history, oldest first)
- `GET /source-versions/{id}` (metadata, provenance, fetch observations and its parses: the
  recorded one and any re-parse)
- `GET /source-versions/{id}/content?kind=raw|parsed[&parser_version=]` (streamed from the
  archive; the parsed text is the recorded parse unless `parser_version` names another)
- `GET /evidence-families/{id}` (an Evidence Family and its member Source Versions)
- `GET /companies/{id}/fetch-gate-decisions?status=allowed|blocked` (whether each exchange
  request was allowed, newest first: a `blocked` one names the gate that blocked it) and
  `GET /fetch-gate-decisions/{id}`

Source content is untrusted data: raw bytes are served as a download under a sandboxing
Content-Security-Policy, never rendered on the application's origin.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.archive import Archive
from atlas.companies import Company, CompanyRole, get_company, list_companies
from atlas.ledger import (
    ContentKind,
    EvidenceFamily,
    FetchGateDecision,
    SourceDocument,
    SourceVersionDetail,
    SourceVersionSummary,
    get_content,
    get_decision,
    get_evidence_family,
    get_source_document,
    get_version,
    list_decisions,
    list_source_documents,
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
    def companies(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        role: Annotated[
            CompanyRole | None,
            Query(description="only researched companies, or only counterparties"),
        ] = None,
    ) -> Page[Company]:
        with engine.connect() as connection:
            items, total = list_companies(
                connection, limit=page.limit, offset=page.offset, role=role
            )
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
            items, total = list_source_documents(
                connection, company_id, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/sources/{document_id}", response_model=SourceDocument, responses=NOT_FOUND)
    def source(document_id: uuid.UUID) -> SourceDocument | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_source_document(connection, document_id)
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
            if get_source_document(connection, document_id) is None:
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
        parser_version: Annotated[
            str | None,
            Query(
                description="with kind=parsed: the parse under this parser version (the"
                " recorded parse or a re-parse, as `parses` lists them); default the recorded"
                " parse"
            ),
        ] = None,
    ) -> StreamingResponse | JSONResponse:
        with engine.connect() as connection:
            content = get_content(connection, archive, version_id, kind, parser_version)
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

    @router.get(
        "/evidence-families/{family_id}", response_model=EvidenceFamily, responses=NOT_FOUND
    )
    def evidence_family(family_id: uuid.UUID) -> EvidenceFamily | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_evidence_family(connection, family_id)
        return found if found is not None else not_found("evidence family")

    @router.get(
        "/companies/{company_id}/fetch-gate-decisions",
        response_model=Page[FetchGateDecision],
        responses=NOT_FOUND,
    )
    def company_fetch_gate_decisions(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        page: Paged,
        status: Annotated[
            Literal["allowed", "blocked"] | None,
            Query(description="only decisions with this status"),
        ] = None,
    ) -> Page[FetchGateDecision] | JSONResponse:
        with engine.connect() as connection:
            if get_company(connection, company_id) is None:
                return not_found("company")
            items, total = list_decisions(
                connection, company_id, status=status, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/fetch-gate-decisions/{decision_id}",
        response_model=FetchGateDecision,
        responses=NOT_FOUND,
    )
    def fetch_gate_decision(decision_id: uuid.UUID) -> FetchGateDecision | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_decision(connection, decision_id)
        return found if found is not None else not_found("fetch gate decision")

    return router
