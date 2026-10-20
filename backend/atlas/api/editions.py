"""`/api/v1/editions`: the scheduled tasks' editions, kept insert-only (atlas-record ticket 01).

- `POST /editions?theme=&source=&commit_sha=`: import one page. The body is the page itself
  (its bytes, any content type: a file upload without the multipart envelope), so the drop-box
  pull and a `curl --data-binary @page.html` use the same call. 201 `imported` with the stored
  edition, or 200 `unchanged` when Atlas already holds those bytes (nothing is written). A
  page with no readable ledger is stored with its `parse_error`. 422 `theme_mismatch` when the
  ledger is another theme's, `invalid_source`, `invalid_theme`, `empty_page`; 413
  `page_too_large`. Audited `edition.imported`.
- `GET /editions?theme=`: newest first, without the ledger.
- `GET /editions/{id}`: the parsed ledger, the parse error, `same_as_of_differs` and the page's
  archive URI.
- `GET /editions/{id}/rewrites`: what the edition rewrote of the theme's previous parsed edition
  (the rewrite check, ticket 02; `GET /rewrites` lists them across editions).
- `GET /editions/{id}/page`: the page as stored, as a download under a sandboxing
  Content-Security-Policy (it is another party's HTML: never rendered on this origin).

Errors use the envelope.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine

from atlas.api.common import (
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    error_responses,
    not_found,
    pagination,
)
from atlas.archive import Archive
from atlas.audit import Actor
from atlas.jobs.pacing import Clock, utc_now
from atlas.record.editions import (
    Edition,
    EditionError,
    EditionImported,
    Editions,
    EditionSource,
    EditionSummary,
    get_edition,
    list_editions,
    read_page,
)
from atlas.record.rewrite_store import RewriteRecord, list_rewrites

Paged = Annotated[Pagination, Depends(pagination)]

_CHUNK = 64 * 1024
_UNTRUSTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}


def _chunks(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), _CHUNK):
        yield data[start : start + _CHUNK]


def editions_router(
    engine: Engine, archive: Archive, actor: Actor, clock: Clock = utc_now
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/editions", tags=["editions"])
    service = Editions(engine, archive, actor, clock)

    @router.post(
        "",
        response_model=EditionImported,
        status_code=201,
        responses={
            200: {"model": EditionImported, "description": "Atlas already holds these bytes"},
            **INVALID,
            **error_responses(413),
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/octet-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    async def import_edition(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        response: Response,
        theme: Annotated[str, Query(description="the theme's slug; `council` for the council's")],
        source: Annotated[EditionSource, Query()] = "manual",
        commit_sha: Annotated[
            str | None, Query(description="the drop box commit; required with `drop_box`")
        ] = None,
    ) -> EditionImported | JSONResponse:
        page = await request.body()
        try:
            imported = await run_in_threadpool(
                service.import_page, theme, page, source=source, commit_sha=commit_sha
            )
        except EditionError as error:
            return error_response(error.status, error.code, str(error))
        if imported.outcome == "unchanged":
            response.status_code = 200
        return imported

    @router.get("", response_model=Page[EditionSummary], responses=INVALID)
    def editions(  # pyright: ignore[reportUnusedFunction]
        page: Paged, theme: str | None = None
    ) -> Page[EditionSummary]:
        items, total = list_editions(engine, theme, page.limit, page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{edition_id}", response_model=Edition, responses=NOT_FOUND)
    def edition(edition_id: uuid.UUID) -> Edition | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        found = get_edition(engine, edition_id)
        return found if found is not None else not_found("edition")

    @router.get("/{edition_id}/rewrites", response_model=Page[RewriteRecord], responses=NOT_FOUND)
    def edition_rewrites(  # pyright: ignore[reportUnusedFunction]
        edition_id: uuid.UUID, page: Paged
    ) -> Page[RewriteRecord] | JSONResponse:
        if get_edition(engine, edition_id) is None:
            return not_found("edition")
        items, total = list_rewrites(
            engine, edition_id=edition_id, limit=page.limit, offset=page.offset
        )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/{edition_id}/page",
        response_class=StreamingResponse,
        response_model=None,
        responses={200: {"description": "The page as stored"}, **NOT_FOUND},
    )
    def edition_page(edition_id: uuid.UUID) -> StreamingResponse | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        data = read_page(engine, archive, edition_id)
        if data is None:
            return not_found("edition")
        headers = {
            **_UNTRUSTED_HEADERS,
            "Content-Disposition": f'attachment; filename="{edition_id}.html"',
            "Content-Length": str(len(data)),
            "Content-Type": "text/html; charset=utf-8",
        }
        return StreamingResponse(_chunks(data), headers=headers)

    return router
