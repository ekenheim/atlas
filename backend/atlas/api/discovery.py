"""`/api/v1/leads` and `/api/v1/discoveries` reads.

- `GET /leads?theme=&limit=&offset=`: Tier C leads, newest first, one per canonical URL: URL,
  title, snippet, published date, engines, the query that first found it and how often
  queries have returned it. `theme` keeps the leads a discovery for that theme returned.
  Leads are never Evidence.
- `GET /discoveries`, `GET /discoveries/{id}`: each discovery (a `discover` job): its theme
  and question, run, engines, where its open gaps came from, and each query with its
  outcome (results, new leads, the engines SearXNG reported unresponsive, or the error).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.discovery import Discovery, Lead, get_discovery, list_discoveries, list_leads

Paged = Annotated[Pagination, Depends(pagination)]


def discovery_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["discovery"])

    @router.get("/leads", response_model=Page[Lead])
    def leads(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: Annotated[str | None, Query(description="only leads found for this theme")] = None,
    ) -> Page[Lead]:
        with engine.connect() as connection:
            items, total = list_leads(connection, theme=theme, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/discoveries", response_model=Page[Discovery])
    def discoveries(page: Paged) -> Page[Discovery]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_discoveries(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/discoveries/{discovery_id}", response_model=Discovery, responses=NOT_FOUND)
    def discovery(  # pyright: ignore[reportUnusedFunction]
        discovery_id: uuid.UUID,
    ) -> Discovery | JSONResponse:
        with engine.connect() as connection:
            found = get_discovery(connection, discovery_id)
        return found if found is not None else not_found("discovery")

    return router
