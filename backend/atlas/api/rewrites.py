"""`/api/v1/rewrites`: what later editions rewrote of earlier ones (atlas-record ticket 02).

- `GET /rewrites?theme=&since=`: the rewrite check's findings across editions, newest edition
  first. `since` is an as-of day (`2026-10-26`): the editions of that day or later. Each finding
  has its kind, the ID it is about, the field, the values before and after, and the two editions
  compared. One edition's findings are also at `GET /editions/{id}/rewrites`.

Errors use the envelope.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from atlas.api.common import INVALID, Page, Pagination, pagination
from atlas.record.rewrite_store import RewriteRecord, list_rewrites

Paged = Annotated[Pagination, Depends(pagination)]


def rewrites_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/rewrites", tags=["editions"])

    @router.get("", response_model=Page[RewriteRecord], responses=INVALID)
    def rewrites(  # pyright: ignore[reportUnusedFunction]
        page: Paged, theme: str | None = None, since: date | None = None
    ) -> Page[RewriteRecord]:
        items, total = list_rewrites(
            engine, theme=theme, since=since, limit=page.limit, offset=page.offset
        )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    return router
