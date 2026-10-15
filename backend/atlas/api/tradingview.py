"""`/api/v1/tradingview/catalog` and `/api/v1/companies/{id}/price-history`: TradingView
under the owner's override (tickets 31 and 16b).

- `GET /tradingview/catalog?company_id=&category=&has_transcript=&limit=&offset=`: the
  documents TradingView listed for the universe's companies, most recently reported first:
  category, event, form, fiscal period, reported time, title, upstream provider, and each
  view's ID and type, with the Source Version recorded from a transcript view. Metadata
  only; every entry records the owner's override. The catalog tells which primary filings
  exist, e.g. for a manual import where no adapter fetches them.
- `GET /companies/{id}/price-history?start=&end=`: the company's stored daily closes from
  `start` to `end` (default: the year to today), oldest first, each marked with the override.
  A pure read of what the `tradingview_prices` job stored: it never calls TradingView. For
  settling predictions and replays; never Evidence, and no research tool returns it.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, error_response, not_found, pagination
from atlas.companies import get_company
from atlas.tradingview import CatalogEntry, list_catalog
from atlas.tradingview.prices import PriceHistory, price_history

Paged = Annotated[Pagination, Depends(pagination)]


def tradingview_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/tradingview", tags=["tradingview"])

    @router.get("/catalog", response_model=Page[CatalogEntry])
    def catalog(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        company_id: Annotated[uuid.UUID | None, Query(description="only this company")] = None,
        category: Annotated[str | None, Query(description="e.g. Earnings call")] = None,
        has_transcript: Annotated[
            bool | None, Query(description="only documents with (or without) a transcript")
        ] = None,
    ) -> Page[CatalogEntry]:
        with engine.connect() as connection:
            items, total = list_catalog(
                connection,
                company_id=company_id,
                category=category,
                has_transcript=has_transcript,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    return router


def price_history_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/companies", tags=["tradingview"])

    @router.get(
        "/{company_id}/price-history",
        response_model=PriceHistory,
        responses=NOT_FOUND,
    )
    def prices(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        start: Annotated[
            date | None, Query(description="first day; default a year before end")
        ] = None,
        end: Annotated[date | None, Query(description="last day; default today (UTC)")] = None,
    ) -> PriceHistory | JSONResponse:
        last = end or datetime.now(UTC).date()
        first = start or last - timedelta(days=365)
        if first > last:
            return error_response(422, "invalid_range", "start is after end")
        with engine.connect() as connection:
            if get_company(connection, company_id) is None:
                return not_found("company")
            return price_history(connection, company_id=company_id, start=first, end=last)

    return router
