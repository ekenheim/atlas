"""`/api/v1/leads` and `/api/v1/discoveries` reads.

- `GET /leads?theme=&origin=&known_by=&event_from=&event_to=&limit=&offset=`: Tier C leads,
  newest first, one per canonical URL: URL, title, snippet, published date, engines, the query
  that first found it and how often queries have returned it. `theme` keeps the leads a
  discovery for that theme returned (or a headline or calendar date listed for a company in
  it). `origin` keeps one origin; `known_by` keeps what Atlas had stored by that time (a
  calendar lead then shows the date it knew by then); `event_from`/`event_to` keep the calendar
  leads whose date falls inside, soonest first (ticket 16b). `origin=archive_signal` (ticket 18)
  lists the sentences the nightly scan found in archived documents that read like a bottleneck,
  ranked by score, each with its quote, span, company and why it scored; `company_id` keeps one
  company's; for them `known_by` bounds the document's availability. Leads are never Evidence.
- `GET /discoveries`, `GET /discoveries/{id}`: each discovery (a `discover` job): its theme
  and question, run, engines, where its open gaps came from, and each query with its
  outcome (results, new leads, the engines SearXNG reported unresponsive, or the error).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
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
        origin: Annotated[
            Literal[
                "searxng", "tradingview_news", "edgar_fts", "tradingview_calendar", "archive_signal"
            ]
            | None,
            Query(description="only leads of this origin"),
        ] = None,
        company_id: Annotated[
            uuid.UUID | None, Query(description="only leads about this company")
        ] = None,
        known_by: Annotated[
            AwareDatetime | None,
            Query(
                description="only leads Atlas had stored by this time; a calendar lead shows"
                " the date it knew by then. For an archive signal: only those whose document"
                " was public by this time (when Atlas scanned it does not matter)"
            ),
        ] = None,
        available_from: Annotated[
            AwareDatetime | None,
            Query(
                description="archive signals whose document became public at or after this"
                " time (other origins are left out)"
            ),
        ] = None,
        event_from: Annotated[
            AwareDatetime | None,
            Query(description="calendar leads whose date is at or after this time (soonest first)"),
        ] = None,
        event_to: Annotated[
            AwareDatetime | None,
            Query(description="calendar leads whose date is at or before this time"),
        ] = None,
    ) -> Page[Lead]:
        with engine.connect() as connection:
            items, total = list_leads(
                connection,
                theme=theme,
                limit=page.limit,
                offset=page.offset,
                origin=origin,
                known_by=known_by,
                event_from=event_from,
                event_to=event_to,
                company_id=company_id,
                available_from=available_from,
            )
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
